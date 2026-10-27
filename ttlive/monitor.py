"""Watch the channel list and start a Recorder when a channel goes live.

The channel list can change while running (the web UI adds, removes and
pauses channels), so all channel state sits behind one lock.
"""

import logging
import random
import threading
import time
from dataclasses import dataclass

from .http_client import CaptchaRequired, RateLimited, TikTokError
from .recorder import Recorder

log = logging.getLogger(__name__)


@dataclass
class ChannelState:
    username: str
    status: str = "waiting"  # waiting, offline, live, error
    room_id: str = ""
    last_check: float = 0.0
    next_check: float = 0.0
    error: str = ""
    paused: bool = False


class Monitor:
    def __init__(self, cfg, http, api, notifier, on_channels_changed=None):
        self.cfg, self.http, self.api, self.notifier = cfg, http, api, notifier
        self.on_channels_changed = on_channels_changed
        self.recorders = {}
        self.channels = {}
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._captcha_notified = False
        now = time.time()
        # Spread the first checks out so channels are not all checked at once
        for i, u in enumerate(cfg.channels):
            self.channels[u] = ChannelState(u, next_check=now + i * cfg.min_request_gap)

    def interval(self):
        base = random.uniform(self.cfg.check_interval_min, self.cfg.check_interval_max)
        return base * random.uniform(1 - self.cfg.jitter, 1 + self.cfg.jitter)

    # ---- control (called from the web UI thread) ---------------------

    def add_channel(self, username):
        username = username.strip().lstrip("@").strip()
        if not username or not all(c.isalnum() or c in "._" for c in username) or len(username) > 40:
            raise ValueError("ชื่อผู้ใช้ไม่ถูกต้อง")
        with self.lock:
            if username in self.channels:
                raise ValueError(f"มี @{username} อยู่แล้ว")
            # Never earlier than the last scheduled check, so adding many at once stays spaced out
            last = max([c.next_check for c in self.channels.values()] + [time.time()])
            self.channels[username] = ChannelState(username, next_check=last + self.cfg.min_request_gap)
        self._channels_changed()
        log.info("added @%s", username)
        return username

    def remove_channel(self, username):
        with self.lock:
            if self.channels.pop(username, None) is None:
                raise KeyError(username)
            rec = self.recorders.get(username)
        if rec:
            rec.stop()
        self._channels_changed()
        log.info("removed @%s", username)

    def set_paused(self, username, paused):
        with self.lock:
            st = self.channels[username]
            st.paused = paused
            if not paused:
                st.next_check = time.time()
            rec = self.recorders.get(username) if paused else None
        if rec:
            rec.stop()

    def check_now(self, username):
        with self.lock:
            st = self.channels[username]
            st.paused = False
            st.next_check = time.time()

    def _channels_changed(self):
        if self.on_channels_changed:
            with self.lock:
                names = list(self.channels)
            try:
                self.on_channels_changed(names)
            except Exception:
                log.exception("could not save channel list")

    def snapshot(self):
        with self.lock:
            out = []
            for st in self.channels.values():
                rec = self.recorders.get(st.username)
                item = {
                    "username": st.username, "status": st.status, "paused": st.paused,
                    "room_id": st.room_id, "last_check": st.last_check or None,
                    "next_check": None if st.paused or rec else st.next_check,
                    "error": st.error, "recording": None,
                }
                if rec:
                    item["recording"] = {
                        "phase": rec.phase, "started_at": rec.started_at, "quality": rec.quality,
                        "bytes": rec.bytes_recorded(), "session_dir": rec.session_dir,
                    }
                out.append(item)
            return out

    # ---- main loop --------------------------------------------------

    def stop(self):
        self._stop.set()
        with self.lock:
            recs = list(self.recorders.values())
        for r in recs:
            r.stop()

    def run(self):
        log.info("watching %d channel(s): %s", len(self.channels), ", ".join(self.channels))
        while not self._stop.is_set():
            self._reap()
            left = self.http.paused()
            if left:
                self._stop.wait(min(left, 5))
                continue
            self._captcha_notified = False

            now = time.time()
            with self.lock:
                due = [u for u, st in self.channels.items()
                       if st.next_check <= now and not st.paused and u not in self.recorders]
            for username in due:
                if self._stop.is_set():
                    break
                self._check(username)
            self._stop.wait(1)

        with self.lock:
            recs = list(self.recorders.values())
        for r in recs:
            r.join(timeout=120)

    def _check(self, username):
        try:
            result = self.api.room_status(username)
            err = ""
        except CaptchaRequired as e:
            if not self._captcha_notified:
                self.notifier.send(f"⚠️ หยุดเช็กชั่วคราว {self.cfg.captcha_pause_minutes} นาที: {e}")
                self._captcha_notified = True
            return
        except RateLimited as e:
            log.warning("%s", e)
            return
        except TikTokError as e:
            log.warning("[%s] check failed: %s", username, e)
            result, err = None, str(e)

        with self.lock:
            st = self.channels.get(username)
            if st is None or st.paused:  # removed or paused while we were checking
                return
            st.last_check = time.time()
            st.next_check = st.last_check + self.interval()
            st.error = err
            if result is None:
                st.status = "error"
                return
            st.room_id = result.room_id
            st.status = "live" if result.is_live else "offline"
            if not result.is_live:
                log.info("[%s] offline", username)
                return
            rec = Recorder(self.cfg, self.api, self.notifier, username, result.room_id)
            self.recorders[username] = rec
        rec.start()

    def _reap(self):
        with self.lock:
            for u, r in list(self.recorders.items()):
                if not r.is_alive():
                    del self.recorders[u]
                    st = self.channels.get(u)
                    if st:
                        # The room just ended; look again after a normal interval
                        st.status = "offline"
                        st.next_check = time.time() + self.interval()
