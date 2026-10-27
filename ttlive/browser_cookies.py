"""Read the user's own tiktok.com cookies straight from Chrome on Linux.

Same idea as yt-dlp's --cookies-from-browser: copy Chrome's Cookies SQLite
file, decrypt the tiktok.com rows with the "Chrome Safe Storage" key from
the desktop keyring (KWallet or Secret Service), and turn them into a
Netscape cookies.txt. Only tiktok.com cookies are ever read.

Decryption uses the openssl command (always present on Fedora) so the
program still needs no pip packages.
"""

import glob
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time

log = logging.getLogger(__name__)

CHROME_DIRS = [
    "~/.config/google-chrome",
    "~/.var/app/com.google.Chrome/config/google-chrome",  # Flatpak
    "~/.config/chromium",
]
WINDOWS_EPOCH = 11644473600  # seconds from 1601-01-01 to 1970-01-01


class BrowserCookieError(Exception):
    pass


def find_cookie_db(profile="Default"):
    for base in CHROME_DIRS:
        base = os.path.expanduser(base)
        for rel in ("Network/Cookies", "Cookies"):
            path = os.path.join(base, profile, rel)
            if os.path.isfile(path):
                return path, "chromium" if "chromium" in base else "chrome"
    profiles = [os.path.basename(os.path.dirname(p))
                for b in CHROME_DIRS for p in glob.glob(os.path.join(os.path.expanduser(b), "*", "Cookies"))]
    hint = f" (profiles found: {', '.join(profiles)})" if profiles else ""
    raise BrowserCookieError(f"Chrome profile '{profile}' not found{hint}")


_password_cache = {}


def keyring_password(app="chrome"):
    """The 'Chrome Safe Storage' secret. Read once and kept in memory so the
    keyring is not asked again (and can't pop up unlock prompts repeatedly)."""
    if app in _password_cache:
        return _password_cache[app]
    folder = "Chrome Keys" if app == "chrome" else "Chromium Keys"
    label = "Chrome Safe Storage" if app == "chrome" else "Chromium Safe Storage"
    attempts = [
        ["kwallet-query", "-r", label, "-f", folder, "kdewallet"],
        ["secret-tool", "lookup", "application", app],
        ["secret-tool", "lookup", "xdg:schema", "chrome_libsecret_os_crypt_password_v2"],
    ]
    for cmd in attempts:
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            continue
        secret = r.stdout.strip()
        # kwallet-query prints an error sentence (with spaces) instead of failing
        if r.returncode == 0 and secret and " " not in secret:
            _password_cache[app] = secret
            return secret
    raise BrowserCookieError("could not read 'Chrome Safe Storage' from KWallet or the keyring "
                             "(is the wallet unlocked?)")


def _aes_key(password):
    return hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1, 16)


def _decrypt(blob, key, strip_hash):
    r = subprocess.run(["openssl", "enc", "-d", "-aes-128-cbc", "-K", key.hex(), "-iv", "20" * 16],
                       input=blob, capture_output=True, timeout=10)
    if r.returncode != 0:
        raise BrowserCookieError("could not decrypt a Chrome cookie (wrong keyring key?)")
    out = r.stdout[32:] if strip_hash else r.stdout  # DB v24+: SHA-256 of the domain comes first
    return out.decode("utf-8")


def read_tiktok_cookies(profile="Default"):
    """Return tiktok.com cookies from Chrome as Netscape cookies.txt text."""
    db, app = find_cookie_db(profile)
    with tempfile.TemporaryDirectory(prefix="ttlive-") as tmp:
        copy = os.path.join(tmp, "Cookies")
        shutil.copyfile(db, copy)  # Chrome keeps the original locked while running
        for extra in ("-wal", "-journal"):
            if os.path.exists(db + extra):
                shutil.copyfile(db + extra, copy + extra)
        con = sqlite3.connect(copy)
        try:
            version = int((con.execute("SELECT value FROM meta WHERE key='version'").fetchone() or [0])[0])
            rows = con.execute(
                "SELECT host_key, path, is_secure, expires_utc, name, value, encrypted_value "
                "FROM cookies WHERE host_key = 'tiktok.com' OR host_key LIKE '%.tiktok.com' "
                "ORDER BY host_key, name").fetchall()
        finally:
            con.close()
    if not rows:
        raise BrowserCookieError("Chrome has no tiktok.com cookies: log in to tiktok.com in Chrome first")

    keys = {}
    lines = ["# Netscape HTTP Cookie File", "# Read from Chrome by ttlive; tiktok.com only", ""]
    for host, path, secure, expires, name, value, enc in rows:
        if not value and enc:
            prefix = bytes(enc[:3])
            if prefix == b"v10":
                password = "peanuts"
            elif prefix == b"v11":
                password = keyring_password(app)
            else:
                log.debug("skipping cookie %s with unknown encryption %r", name, prefix)
                continue
            if password not in keys:
                keys[password] = _aes_key(password)
            value = _decrypt(bytes(enc[3:]), keys[password], version >= 24)
        expiry = max(0, int(expires / 1_000_000 - WINDOWS_EPOCH)) if expires else 0
        lines.append("\t".join([host, "TRUE" if host.startswith(".") else "FALSE", path,
                                "TRUE" if secure else "FALSE", str(expiry), name, value]))
    return "\n".join(lines) + "\n"


PROBE_URL = "https://www.tiktok.com/passport/web/account/info/?aid=1459"


class CookieSync(threading.Thread):
    """Keep cookies.txt in step with Chrome.

    Every minute (every 10 s while stuck on a CAPTCHA or without cookies) it
    re-reads Chrome's tiktok.com cookies and saves them when they changed.
    While on a CAPTCHA it sends at most one test request every 2 minutes to
    see whether the user has passed the check in Chrome, and resumes if so."""

    def __init__(self, http, notifier, profile="Default", on_change=None):
        super().__init__(name="cookie-sync", daemon=True)
        self.http, self.notifier, self.profile, self.on_change = http, notifier, profile, on_change
        self.last_hash = None
        self.last_sync = None
        self.error = ""
        self._last_probe = 0.0
        self._wake = threading.Event()
        self._lock = threading.Lock()

    def status(self):
        return {"browser": "chrome", "profile": self.profile, "last_sync": self.last_sync, "error": self.error}

    def run(self):
        while True:
            try:
                self.sync()
            except Exception:  # never let the sync thread die
                log.exception("cookie sync crashed")
            reason = self.http.pause_info()["reason"]
            self._wake.wait(10 if reason in ("captcha", "no_cookies") else 60)
            self._wake.clear()

    def sync(self, force_probe=False):
        """Read Chrome now. Returns a short status word for the UI."""
        with self._lock:
            try:
                text = read_tiktok_cookies(self.profile)
            except (BrowserCookieError, OSError, sqlite3.Error) as e:
                if str(e) != self.error:
                    log.warning("reading cookies from Chrome failed: %s", e)
                self.error = str(e)
                return "error"
            self.error = ""
            self.last_sync = time.time()
            digest = hashlib.sha256(text.encode()).hexdigest()
            captcha = self.http.pause_info()["reason"] == "captcha"
            changed = digest != self.last_hash
            if changed:
                self.http.replace_cookies(text, resume=False)
                self.last_hash = digest
                log.info("cookies updated from Chrome")
                if self.on_change:
                    self.on_change()
            if not captcha:
                return "updated" if changed else "same"
            if force_probe or (changed and time.time() - self._last_probe > 120):
                self._last_probe = time.time()
                if self.http.probe(PROBE_URL):
                    self.notifier.send("✅ ผ่านการยืนยันแล้ว ใช้ cookie ใหม่จาก Chrome ทำงานต่อแล้ว")
                    return "resumed"
            return "still_captcha"
