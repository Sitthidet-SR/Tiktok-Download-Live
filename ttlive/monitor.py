"""Watch the channel list and start a Recorder when a channel goes live."""

import logging
import random
import threading
import time

from .http_client import CaptchaRequired, RateLimited, TikTokError
from .recorder import Recorder

log = logging.getLogger(__name__)


class Monitor:
    def __init__(self, cfg, http, api, notifier):
        self.cfg, self.http, self.api, self.notifier = cfg, http, api, notifier
        self.recorders = {}
        self._stop = threading.Event()
        now = time.time()
        # Spread the first checks out so channels are not all checked at once
        spread = max(cfg.min_request_gap * len(cfg.channels), 1)
        self.next_check = {u: now + i * spread / len(cfg.channels) for i, u in enumerate(cfg.channels)}
        self._captcha_notified = False

    def interval(self):
        base = random.uniform(self.cfg.check_interval_min, self.cfg.check_interval_max)
        return base * random.uniform(1 - self.cfg.jitter, 1 + self.cfg.jitter)

    def stop(self):
        self._stop.set()
        for r in list(self.recorders.values()):
            r.stop()

    def run(self):
        log.info("watching %d channel(s): %s", len(self.cfg.channels), ", ".join(self.cfg.channels))
        while not self._stop.is_set():
            self._reap()
            left = self.http.paused()
            if left:
                self._stop.wait(min(left, 30))
                continue
            self._captcha_notified = False

            now = time.time()
            due = [u for u, t in self.next_check.items() if t <= now and u not in self.recorders]
            for username in due:
                if self._stop.is_set():
                    break
                self._check(username)
            self._stop.wait(1)

        for r in list(self.recorders.values()):
            r.join(timeout=120)

    def _check(self, username):
        try:
            st = self.api.room_status(username)
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
            self.next_check[username] = time.time() + self.interval()
            return

        self.next_check[username] = time.time() + self.interval()
        if not st.is_live:
            log.info("[%s] offline", username)
            return
        rec = Recorder(self.cfg, self.api, self.notifier, username, st.room_id)
        self.recorders[username] = rec
        rec.start()

    def _reap(self):
        for u, r in list(self.recorders.items()):
            if not r.is_alive():
                del self.recorders[u]
                # The room just ended; look again after a normal interval
                self.next_check[u] = time.time() + self.interval()
