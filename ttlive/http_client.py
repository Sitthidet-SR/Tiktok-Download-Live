"""The one HTTP client every TikTok request goes through.

It owns the cookie jar, spaces requests out (one at a time, with a minimum
gap), backs off on 429, and stops on CAPTCHA instead of retrying.
"""

import gzip
import http.cookiejar
import json
import logging
import os
import stat
import threading
import time
import urllib.error
import urllib.request
import zlib

log = logging.getLogger(__name__)

CAPTCHA_MARKERS = ("captcha", "verify-center", "verifycenter", "secsdk-captcha", "/verify?")


class TikTokError(Exception):
    pass


class CaptchaRequired(TikTokError):
    """TikTok wants a human check. We never try to solve it."""


class RateLimited(TikTokError):
    pass


class CookieError(TikTokError):
    pass


def load_cookies(path):
    if not os.path.exists(path):
        raise CookieError(f"cookie file not found: {path}")
    mode = os.stat(path).st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        log.warning("%s is readable by other users. Run: chmod 600 %s", path, path)
    jar = http.cookiejar.MozillaCookieJar(path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (http.cookiejar.LoadError, OSError) as e:
        raise CookieError(f"cannot read {path} (must be Netscape cookies.txt format): {e}") from e
    names = {c.name for c in jar if "tiktok.com" in c.domain}
    if not names:
        raise CookieError(f"{path} has no tiktok.com cookies; export them while logged in to tiktok.com")
    if not names & {"sessionid", "sessionid_ss"}:
        log.warning("cookies have no sessionid/sessionid_ss: you may not be logged in")
    return jar


class HttpClient:
    def __init__(self, cookies_file, user_agent, min_gap=3.0, captcha_pause_minutes=30,
                 require_cookies=True):
        self.cookies_file = cookies_file
        self.user_agent = user_agent
        self.min_gap = min_gap
        self.captcha_pause = captcha_pause_minutes * 60
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._paused_until = 0.0
        self._pause_reason = ""
        self._backoff_step = 0
        self._cookie_mtime = 0.0
        self.jar = None
        try:
            self.reload_cookies()
        except CookieError as e:
            if require_cookies:
                raise
            # The web UI can start without cookies; nothing is sent until they are uploaded
            log.warning("%s", e)
            self._paused_until = float("inf")
            self._pause_reason = "no_cookies"

    def reload_cookies(self):
        self.jar = load_cookies(self.cookies_file)
        self._cookie_mtime = os.path.getmtime(self.cookies_file)
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def cookies_changed(self):
        try:
            return os.path.getmtime(self.cookies_file) != self._cookie_mtime
        except OSError:
            return False

    # ---- pause state -------------------------------------------------

    def paused(self):
        """Return seconds left in a pause (0 if not paused). A CAPTCHA pause
        ends early once the user re-exports cookies.txt."""
        left = self._paused_until - time.time()
        if left > 0 and self._pause_reason in ("captcha", "no_cookies") and self.cookies_changed():
            try:
                self.reload_cookies()
            except CookieError as e:
                log.warning("%s", e)
                self._cookie_mtime = os.path.getmtime(self.cookies_file)  # don't retry until it changes again
                return left
            log.info("cookies.txt changed; reloading and resuming")
            self._paused_until = 0
            return 0
        return max(0.0, left)

    def pause_info(self):
        left = self.paused()
        return {"seconds": -1 if left == float("inf") else int(left),
                "reason": self._pause_reason if left else ""}

    def replace_cookies(self, text, resume=True):
        """Validate new cookies.txt content, save it (owner-only) and use it now.
        resume=False keeps a CAPTCHA pause (fresh cookies alone don't prove it was solved)."""
        tmp = self.cookies_file + ".new"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            load_cookies(tmp)
        except CookieError:
            os.remove(tmp)
            raise
        os.replace(tmp, self.cookies_file)
        os.chmod(self.cookies_file, 0o600)
        with self._lock:
            self.reload_cookies()
            if self._pause_reason == "no_cookies" or (resume and self._pause_reason == "captcha"):
                self._paused_until = 0

    def probe(self, url):
        """One request that ignores a CAPTCHA pause, to see if the check was solved.
        Ends the pause and returns True if TikTok answers normally."""
        with self._lock:
            wait = self._last_request + self.min_gap - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                self._do_get(url, "https://www.tiktok.com/")
            except CaptchaRequired:
                return False
            except TikTokError as e:
                log.info("probe failed: %s", e)
                return False
            finally:
                self._last_request = time.time()
            if self._pause_reason == "captcha":
                self._paused_until = 0
            return True

    def _pause(self, seconds, reason):
        self._paused_until = max(self._paused_until, time.time() + seconds)
        self._pause_reason = reason

    # ---- requests ----------------------------------------------------

    def get_json(self, url, referer="https://www.tiktok.com/"):
        body, final_url = self.get(url, referer)
        try:
            return json.loads(body)
        except ValueError:
            self._check_captcha(body, final_url)
            raise TikTokError(f"expected JSON from {url.split('?')[0]}, got {body[:120]!r}")

    def get(self, url, referer="https://www.tiktok.com/"):
        """GET a URL. Returns (text, final_url). Raises CaptchaRequired or RateLimited."""
        with self._lock:
            left = self.paused()
            if left:
                if left == float("inf"):
                    raise RateLimited(f"paused ({self._pause_reason})")
                raise RateLimited(f"paused for {int(left)}s ({self._pause_reason})")
            wait = self._last_request + self.min_gap - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                return self._do_get(url, referer)
            finally:
                self._last_request = time.time()

    def _do_get(self, url, referer):
        req = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        })
        try:
            with self._opener.open(req, timeout=20) as resp:
                text = _decode(resp)
                final_url = resp.geturl()
        except urllib.error.HTTPError as e:
            text = _decode(e)
            e.close()
            if e.code == 429:
                self._backoff_429(e.headers.get("Retry-After"))
            self._check_captcha(text, e.geturl())
            if e.code == 403:
                raise TikTokError("HTTP 403 Forbidden (cookies expired, or region/age restricted)")
            raise TikTokError(f"HTTP {e.code} for {url.split('?')[0]}")
        except urllib.error.URLError as e:
            raise TikTokError(f"network error: {e.reason}") from e
        self._check_captcha(text, final_url)
        self._backoff_step = 0
        return text, final_url

    def _backoff_429(self, retry_after):
        try:
            seconds = int(retry_after)
        except (TypeError, ValueError):
            seconds = min(120 * (2 ** self._backoff_step), 30 * 60)  # 2, 4, 8 ... max 30 min
            self._backoff_step += 1
        self._pause(seconds, "429 rate limited")
        raise RateLimited(f"HTTP 429: backing off {seconds}s")

    def _check_captcha(self, text, final_url):
        url = (final_url or "").lower()
        head = text[:20000].lower()
        if "verify" in url or (head.lstrip().startswith("<") and any(m in head for m in CAPTCHA_MARKERS)):
            self._pause(self.captcha_pause, "captcha")
            raise CaptchaRequired(
                "TikTok asked for a CAPTCHA/verification. Open tiktok.com in your browser, "
                "complete it, then export cookies.txt again")


def _decode(resp):
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        raw = zlib.decompress(raw)
    return raw.decode("utf-8", errors="replace")
