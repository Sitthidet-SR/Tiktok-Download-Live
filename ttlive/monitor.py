"""Watch the channel list and start a Recorder when a channel goes live.

The channel list can change while running (the web UI adds, removes and
pauses channels), so all channel state sits behind one lock.
"""

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field

from .http_client import CaptchaRequired, RateLimited, TikTokError
from .recorder import Recorder

log = logging.getLogger(__name__)

LOW_DISK = 5 * 1024**3       # warn below this much free space
FULL_DISK = 1 * 1024**3      # don't start new recordings below this
RECHECK_AFTER_END = 30       # a streamer who restarts gets a new room; look again soon


@dataclass
class ChannelState:
    username: str
    status: str = "waiting"  # waiting, offline, live, error
    room_id: str = ""
    last_check: float = 0.0
    next_check: float = 0.0
    error: str = ""
    paused: bool = False
    profile: dict = field(default_factory=dict)  # nickname, avatar, title, viewers


class Monitor:
    def __init__(self, cfg, http, api, notifier, on_channels_changed=None):
        self.cfg, self.http, self.api, self.notifier = cfg, http, api, notifier
        self.on_channels_changed = on_channels_changed
        self.recorders = {}
        self.channels = {}
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._captcha_notified = False
        self._profile_tried = set()
        self._disk_checked = 0.0
        self._disk_warned = False
        self.disk_free = None
        now = time.time()
        # Spread the first checks out so channels are not all checked at once
        for i, u in enumerate(cfg.channels):
            self.channels[u] = ChannelState(u, next_check=now + i * cfg.min_request_gap,
                                            paused=u in cfg.paused_channels)

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
        self._channels_changed()

    def check_now(self, username):
        with self.lock:
            st = self.channels[username]
            was_paused, st.paused = st.paused, False
            st.next_check = time.time()
        if was_paused:
            self._channels_changed()

    def _channels_changed(self):
        if self.on_channels_changed:
            with self.lock:
                names = list(self.channels)
                paused = [u for u, st in self.channels.items() if st.paused]
            try:
                self.on_channels_changed(names, paused)
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
                    "error": st.error, "recording": None, **st.profile,
                }
                if rec:
                    item["recording"] = {
                        "phase": rec.phase, "started_at": rec.started_at, "quality": rec.quality,
                        "wait_until": rec.wait_until,
                        "bytes": rec.bytes_recorded(), "session_dir": rec.session_dir,
                        "stats": rec.stats, "history": rec.history,
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
            self._check_disk()
            left = self.http.paused()
            if left:
                self._stop.wait(min(left, 5))
                continue
            self._captcha_notified = False

            now = time.time()
            with self.lock:
                due = [u for u, st in self.channels.items()
                       if st.next_check <= now and not st.paused and u not in self.recorders]
                nameless = [u for u, st in self.channels.items()
                            if st.paused and not st.profile and u not in self._profile_tried]
            for username in due:
                if self._stop.is_set():
                    break
                self._check(username)
            if nameless and not due:
                self._fetch_profile(nameless[0])
            self._stop.wait(1)

        with self.lock:
            recs = list(self.recorders.values())
        for r in recs:
            r.join(timeout=120)

    def _fetch_profile(self, username):
        """One lookup so a paused channel still shows its name and picture."""
        self._profile_tried.add(username)
        try:
            result = self.api.room_status(username)
        except TikTokError as e:  # includes captcha / rate limit; the client handles the pause
            log.debug("[%s] profile lookup failed: %s", username, e)
            return
        with self.lock:
            st = self.channels.get(username)
            if st is not None:
                st.profile = {k: v for k, v in result.profile.items()
                              if v not in ("", None) and k in ("nickname", "avatar")}

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
            # Keep the last known name/avatar if this check didn't return one
            st.profile = {**st.profile, **{k: v for k, v in result.profile.items() if v not in ("", None)}}
            if not result.is_live:
                st.profile.pop("title", None)
                st.profile.pop("viewers", None)
            st.status = "live" if result.is_live else "offline"
            if not result.is_live:
                log.info("[%s] offline", username)
                return
            if self.disk_free is not None and self.disk_free < FULL_DISK:
                st.error = "พื้นที่ดิสก์เหลือน้อยกว่า 1 GB จึงไม่เริ่มบันทึก"
                log.error("[%s] is live but the disk is almost full; not recording", username)
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
                        st.status = "offline"
                        st.next_check = time.time() + RECHECK_AFTER_END

    def _check_disk(self):
        if time.time() - self._disk_checked < 60:
            return
        self._disk_checked = time.time()
        path = self.cfg.path(self.cfg.output_dir)
        try:
            os.makedirs(path, exist_ok=True)
            st = os.statvfs(path)
        except OSError:
            return
        self.disk_free = st.f_bavail * st.f_frsize
        if self.disk_free < LOW_DISK and not self._disk_warned:
            self._disk_warned = True
            self.notifier.send(f"⚠️ พื้นที่ดิสก์เหลือ {self.disk_free / 1024**3:.1f} GB "
                               "ถ้าต่ำกว่า 1 GB จะไม่เริ่มบันทึกไลฟ์ใหม่")
        elif self.disk_free > LOW_DISK * 1.2:
            self._disk_warned = False
