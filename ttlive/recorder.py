"""Record one live session with ffmpeg, reconnecting while the room is still live."""

import logging
import os
import subprocess
import threading
import time

from .http_client import CaptchaRequired, TikTokError
from .merge import merge_session

log = logging.getLogger(__name__)


def build_ffmpeg_cmd(cfg, url, session_dir, username):
    headers = f"User-Agent: {cfg.user_agent}\r\nReferer: https://www.tiktok.com/\r\n"
    pattern = os.path.join(session_dir, f"{username}_%Y%m%d_%H%M%S.ts")
    return [
        cfg.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-headers", headers,
        "-rw_timeout", "15000000",
        "-i", url,
        "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(cfg.segment_seconds),
        "-segment_format", "mpegts", "-reset_timestamps", "1", "-strftime", "1",
        pattern,
    ]


class Recorder(threading.Thread):
    def __init__(self, cfg, api, notifier, username, room_id):
        super().__init__(name=f"rec-{username}", daemon=True)
        self.cfg, self.api, self.notifier = cfg, api, notifier
        self.username, self.room_id = username, room_id
        self._stop_event = threading.Event()
        self._proc = None
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(cfg.path(cfg.output_dir), username, f"{username}_{stamp}")

    def stop(self):
        self._stop_event.set()
        p = self._proc
        if p and p.poll() is None:
            p.terminate()  # ffmpeg finishes the current .ts cleanly on SIGTERM

    def run(self):
        os.makedirs(self.session_dir, exist_ok=True)
        log.info("[%s] live! recording to %s", self.username, self.session_dir)
        self.notifier.send(f"🔴 @{self.username} เริ่มไลฟ์แล้ว กำลังบันทึก")
        try:
            self._record_loop()
        except Exception:
            log.exception("[%s] recorder crashed", self.username)
        if self.cfg.merge_on_end:
            out = merge_session(self.session_dir, self.cfg.ffmpeg, self.cfg.delete_segments_after_merge)
            if out:
                self.notifier.send(f"✅ @{self.username} ไลฟ์จบ บันทึกไว้ที่ {out}")
        else:
            self.notifier.send(f"✅ @{self.username} ไลฟ์จบ ไฟล์อยู่ใน {self.session_dir}")

    def _record_loop(self):
        delays = self.cfg.reconnect_delays
        attempt = 0
        while not self._stop_event.is_set():
            started = time.time()
            try:
                url, quality = self.api.stream_url(self.room_id, self.cfg.stream_preference)
                log.info("[%s] stream quality %s", self.username, quality)
                self._run_ffmpeg(url)
            except CaptchaRequired as e:
                self.notifier.send(f"⚠️ @{self.username}: {e}")
                return
            except TikTokError as e:
                log.warning("[%s] cannot get stream: %s", self.username, e)

            if self._stop_event.is_set():
                return
            if time.time() - started > 120:
                attempt = 0  # it recorded for a while, so this is a fresh drop
            if attempt >= len(delays):
                log.info("[%s] gave up after %d reconnect attempts", self.username, attempt)
                return
            if not self._still_live():
                log.info("[%s] live has ended", self.username)
                return
            delay = delays[attempt]
            attempt += 1
            log.info("[%s] stream dropped, still live; reconnecting in %ss (%d/%d)",
                     self.username, delay, attempt, len(delays))
            if self._stop_event.wait(delay):
                return

    def _still_live(self):
        try:
            return self.api.check_alive([self.room_id]).get(self.room_id, False)
        except CaptchaRequired:
            raise
        except TikTokError as e:
            log.warning("[%s] check_alive failed (%s); assuming still live", self.username, e)
            return True

    def _run_ffmpeg(self, url):
        cmd = build_ffmpeg_cmd(self.cfg, url, self.session_dir, self.username)
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                log.debug("[%s] ffmpeg: %s", self.username, line)
        rc = self._proc.wait()
        self._proc.stderr.close()
        log.info("[%s] ffmpeg exited (code %s)", self.username, rc)
