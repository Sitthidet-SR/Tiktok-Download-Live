"""Local web UI: a small JSON API over the Monitor, plus the static page.

Binds to 127.0.0.1 by default. When bound to another address (to open it
from a phone on the home network), every request from another device needs
an access token, kept in .web_token and shown as a QR code in the UI.
Requests from this computer itself need no token, unless they come through
a reverse proxy or Cloudflare Tunnel: those arrive from 127.0.0.1 too, so
any request carrying a proxy header is treated as remote, and with public_url
set the token is always on.
"""

import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .config import QUICK_TUNNEL, QUICK_TUNNEL_METRICS, update_config
from .http_client import CookieError
from .library import Janitor, delete_clip
from .merge import merge_session
from .youtube import YouTube, YouTubeError

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PROXY_HEADERS = ("Cf-Connecting-Ip", "Cf-Ray", "X-Forwarded-For", "X-Real-Ip", "Forwarded")


class App:
    """State shared by all request handlers."""

    def __init__(self, cfg, http, api, monitor, notifier, token=None, config_path=None, port=8080):
        self.cfg, self.http, self.api, self.monitor, self.notifier = cfg, http, api, monitor, notifier
        self.token = token
        self.config_path, self.port = config_path, port
        self.cookie_sync = None  # set when cookies come from Chrome
        self.account = {"state": "checking", "name": None}
        self.out_dir = os.path.realpath(cfg.path(cfg.output_dir))
        os.makedirs(self.out_dir, exist_ok=True)
        self.youtube = YouTube(os.path.realpath(cfg.path(".")), notifier)
        self.janitor = Janitor(cfg, self.out_dir, notifier, busy=self.youtube.busy_paths)

    def active_dirs(self):
        return {os.path.realpath(c["recording"]["session_dir"])
                for c in self.monitor.snapshot() if c["recording"]}

    def set_auto_delete(self, enabled, free_gb):
        free_gb = float(free_gb)
        if not 5 <= free_gb <= 10000:
            raise ValueError("ตั้งพื้นที่ว่างขั้นต่ำได้ 5–10000 GB")
        self.cfg.auto_delete_enabled, self.cfg.auto_delete_free_gb = bool(enabled), free_gb
        if self.config_path:
            update_config(self.config_path, auto_delete_enabled=bool(enabled), auto_delete_free_gb=free_gb)
        self.janitor.poke()

    def watch_account(self, every=6 * 3600):
        """Re-check the login now and then, so expired cookies show up in the UI."""
        def loop():
            while True:
                time.sleep(every)
                self.refresh_account()
        threading.Thread(target=loop, name="account-check", daemon=True).start()

    def refresh_account(self):
        def work():
            if self.http.pause_info()["reason"] == "no_cookies":
                self.account = {"state": "no_cookies", "name": None}
                return
            self.account = {"state": "checking", "name": None}
            try:
                name = self.api.account_name()
                self.account = {"state": "ok" if name else "logged_out", "name": name}
            except Exception as e:  # shown in the UI; never crash the server
                self.account = {"state": "unknown", "name": None, "error": str(e)}
        threading.Thread(target=work, daemon=True).start()

    def state(self):
        return {
            "now": time.time(),
            "account": self.account,
            "pause": self.http.pause_info(),
            "cookie_sync": self.cookie_sync.status() if self.cookie_sync else None,
            "channels": self.monitor.snapshot(),
            "events": list(self.notifier.events)[-30:][::-1],
            "settings": {"check_min": self.cfg.check_interval_min, "check_max": self.cfg.check_interval_max,
                         "segment_seconds": self.cfg.segment_seconds, "output_dir": self.out_dir,
                         "auto_delete_enabled": self.cfg.auto_delete_enabled,
                         "auto_delete_free_gb": self.cfg.auto_delete_free_gb},
            "lan_url": f"{self.base_url()}/?token={self.token}" if self.token else None,
            "public": bool(self.cfg.public_url),
            "youtube": {**self.youtube.status(), "auto_upload": self.cfg.youtube_auto_upload},
        }

    def recordings(self):
        active = self.active_dirs()
        uploaded = self.youtube.uploads()
        items = []
        for user in sorted(os.listdir(self.out_dir)):
            udir = os.path.join(self.out_dir, user)
            if not os.path.isdir(udir):
                continue
            for e in os.scandir(udir):
                if e.is_file() and e.name.endswith(".mp4"):
                    st = e.stat()
                    rel = f"{user}/{e.name}"
                    items.append({"kind": "video", "user": user, "name": e.name, "path": rel,
                                  "size": st.st_size, "time": st.st_mtime,
                                  "youtube": (uploaded.get(rel) or {}).get("video_id")})
                elif e.is_dir():
                    segs = [s for s in os.scandir(e.path) if s.name.endswith(".ts")]
                    # Already merged (segments kept as a backup): the .mp4 row is enough
                    if not segs or os.path.exists(e.path + ".mp4"):
                        continue
                    items.append({"kind": "session", "user": user, "name": e.name,
                                  "path": f"{user}/{e.name}", "segments": len(segs),
                                  "size": sum(s.stat().st_size for s in segs),
                                  "time": max(s.stat().st_mtime for s in segs),
                                  "active": os.path.realpath(e.path) in active})
        items.sort(key=lambda i: i["time"], reverse=True)
        disk = os.statvfs(self.out_dir)
        return {"items": items, "free": disk.f_bavail * disk.f_frsize, "total": disk.f_blocks * disk.f_frsize}

    def base_url(self):
        if self.cfg.public_url == QUICK_TUNNEL:
            return quick_tunnel_url() or f"http://{lan_ip()}:{self.port}"
        return self.cfg.public_url or f"http://{lan_ip()}:{self.port}"

    def set_auto_upload(self, enabled):
        self.cfg.youtube_auto_upload = bool(enabled)
        if self.config_path:
            update_config(self.config_path, youtube_auto_upload=bool(enabled))

    def clip_ready(self, username, full):
        """Called by the Monitor after a clip is merged: upload it if auto upload is on."""
        if not self.cfg.youtube_auto_upload:
            return
        rel = os.path.relpath(os.path.realpath(full), self.out_dir)
        try:
            if not self.youtube.connected():
                raise YouTubeError("ยังไม่ได้เชื่อมบัญชี YouTube")
            self.youtube.start_upload(full, rel, self.clip_title(username, full),
                                      f"บันทึกจากไลฟ์ TikTok @{username}")
            log.info("auto upload of %s started", rel)
        except YouTubeError as e:
            log.warning("auto upload of %s not started: %s", rel, e)
            self.notifier.send(f"⚠️ อัปโหลด {os.path.basename(rel)} ขึ้น YouTube อัตโนมัติไม่ได้: {e}")

    def clip_title(self, username, full):
        nick = next((c.get("nickname") for c in self.monitor.snapshot() if c["username"] == username), "") or ""
        m = re.search(r"_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}", os.path.basename(full))
        when = f"{m[3]}/{m[2]}/{m[1]} {m[4]}:{m[5]}" if m else time.strftime("%d/%m/%Y %H:%M")
        who = f"{nick} (@{username})" if nick and nick != username else f"@{username}"
        return f"{who} ไลฟ์ {when}"

    def safe_path(self, rel):
        """Resolve a path under the output folder, refusing anything outside it."""
        full = os.path.realpath(os.path.join(self.out_dir, rel))
        if not full.startswith(self.out_dir + os.sep):
            raise PermissionError(rel)
        return full


class Handler(BaseHTTPRequestHandler):
    app: App = None
    server_version = "ttlive"

    def log_message(self, fmt, *args):
        log.debug("web: " + fmt, *args)

    # ---- plumbing -----------------------------------------------------

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _error(self, code, msg):
        self._json({"error": msg}, code)

    def _proxied(self):
        return any(h in self.headers for h in PROXY_HEADERS)

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1") and not self._proxied()

    def _authorized(self):
        token = self.app.token
        if not token:
            # Bound to localhost with no token: refuse anything a proxy forwarded from outside
            return not self._proxied()
        if self._local():
            return True
        q = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        if secrets.compare_digest(q, token):
            return True
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return "ttlive_token" in c and secrets.compare_digest(c["ttlive_token"].value, token)

    def _same_origin(self):
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def _body(self):
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ValueError("expected JSON")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- routes ---------------------------------------------------------

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        if not self._authorized():
            return self._send(401, ("ต้องเปิดด้วยลิงก์ที่มี token ที่แสดงตอนเริ่มโปรแกรม" if self.app.token else
                                    "เข้าผ่าน proxy/tunnel ได้เมื่อตั้ง public_url หรือ --public-url แล้วเท่านั้น").encode(),
                              "text/plain; charset=utf-8")
        path = url.path
        if path in ("/", "/index.html"):
            headers = {}
            if self.app.token:
                secure = "; Secure" if self.app.cfg.public_url.startswith(("https://", QUICK_TUNNEL)) and self._proxied() else ""
                headers["Set-Cookie"] = (f"ttlive_token={self.app.token}; Path=/; HttpOnly; SameSite=Strict; "
                                         f"Max-Age=31536000{secure}")
            return self._static("index.html", headers)
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/state":
            return self._json(self.app.state())
        if path == "/api/recordings":
            return self._json(self.app.recordings())
        if path == "/oauth/youtube":
            return self._youtube_callback(parse_qs(url.query))
        if path.startswith("/media/"):
            return self._media(unquote(path[len("/media/"):]), download="download" in url.query)
        self._error(404, "not found")

    def do_POST(self):
        if not self._authorized() or not self._same_origin():
            return self._error(403, "forbidden")
        try:
            body = self._body()
        except ValueError as e:
            return self._error(400, str(e))
        path = urlparse(self.path).path
        m = self.app.monitor
        try:
            if path == "/api/channels":
                name = m.add_channel(str(body.get("username", "")))
                return self._json({"ok": True, "username": name})
            hit = re.fullmatch(r"/api/channels/([\w.]+)/(pause|resume|check|remove)", path)
            if hit:
                user, action = hit.groups()
                if action == "remove":
                    m.remove_channel(user)
                elif action == "check":
                    m.check_now(user)
                else:
                    m.set_paused(user, action == "pause")
                return self._json({"ok": True})
            if path == "/api/cookies":
                try:
                    self.app.http.replace_cookies(str(body.get("text", "")))
                except CookieError as e:
                    log.warning("rejected uploaded cookies: %s", e)
                    return self._error(400, "ไฟล์นี้ไม่ใช่ cookies.txt แบบ Netscape หรือไม่มี cookie ของ tiktok.com")
                self.app.refresh_account()
                return self._json({"ok": True})
            if path == "/api/cookies/sync":
                if not self.app.cookie_sync:
                    return self._error(400, "ยังไม่ได้ตั้งให้อ่าน cookie จาก Chrome")
                result = self.app.cookie_sync.sync(force_probe=True)
                if result == "error":
                    return self._error(500, "อ่าน cookie จาก Chrome ไม่ได้: " + self.app.cookie_sync.error)
                if result != "still_captcha":
                    self.app.refresh_account()
                return self._json({"ok": True, "result": result})
            if path == "/api/merge":
                full = self.app.safe_path(str(body.get("path", "")))
                if not os.path.isdir(full):
                    return self._error(404, "ไม่พบโฟลเดอร์")
                out = merge_session(full, self.app.cfg.ffmpeg, self.app.cfg.delete_segments_after_merge)
                if not out:
                    return self._error(500, "รวมไฟล์ไม่สำเร็จ ดูรายละเอียดใน log")
                return self._json({"ok": True, "output": os.path.relpath(out, self.app.out_dir)})
            if path == "/api/delete":
                rel = str(body.get("path", ""))
                freed = delete_clip(self.app.safe_path(rel), self.app.active_dirs(), self.app.youtube.busy_paths())
                log.info("deleted %s from the web UI (%.1f MB)", rel, freed / 1e6)
                return self._json({"ok": True, "freed": freed})
            if path == "/api/auto-delete":
                self.app.set_auto_delete(body.get("enabled"), body.get("free_gb", self.app.cfg.auto_delete_free_gb))
                return self._json({"ok": True})
            if path == "/api/youtube/connect":
                # Google always sends the browser back to 127.0.0.1. On this computer that reaches
                # the UI; anywhere else the page fails to load and the user pastes its address back.
                url = self.app.youtube.auth_url(f"http://127.0.0.1:{self.app.port}/oauth/youtube")
                return self._json({"ok": True, "url": url, "paste": not self._local()})
            if path == "/api/youtube/finish":
                self.app.youtube.finish_url(str(body.get("url", "")))
                return self._json({"ok": True})
            if path == "/api/youtube/auto":
                self.app.set_auto_upload(body.get("enabled"))
                return self._json({"ok": True})
            if path == "/api/youtube/disconnect":
                self.app.youtube.disconnect()
                return self._json({"ok": True})
            if path == "/api/youtube/upload":
                rel = str(body.get("path", ""))
                full = self.app.safe_path(rel)
                if not os.path.isfile(full) or not full.endswith(".mp4"):
                    return self._error(404, "ไม่พบคลิป")
                title = str(body.get("title") or os.path.splitext(os.path.basename(rel))[0])
                self.app.youtube.start_upload(full, rel, title, f"บันทึกจากไลฟ์ TikTok @{rel.split('/')[0]}")
                return self._json({"ok": True})
        except YouTubeError as e:
            return self._error(400, str(e))
        except FileNotFoundError:
            return self._error(404, "ไม่พบไฟล์")
        except KeyError:
            return self._error(404, "ไม่พบช่องนี้")
        except (ValueError, CookieError) as e:
            return self._error(400, str(e))
        except PermissionError:
            return self._error(403, "forbidden")
        self._error(404, "not found")

    def _youtube_callback(self, q):
        if "error" in q:
            msg = "ยกเลิกการเชื่อม YouTube" if q["error"][0] == "access_denied" else "Google: " + q["error"][0]
        else:
            try:
                self.app.youtube.finish(q.get("code", [""])[0], q.get("state", [""])[0])
                msg = "ok"
            except (YouTubeError, OSError, ValueError) as e:
                msg = str(e)
        from urllib.parse import quote
        self._send(302, b"", headers={"Location": f"http://localhost:{self.app.port}/?yt={quote(msg)}#library"})

    def _static(self, name, headers=None):
        full = os.path.realpath(os.path.join(STATIC, name))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype, headers)

    def _media(self, rel, download=False):
        try:
            full = self.app.safe_path(rel)
        except PermissionError:
            return self._error(403, "forbidden")
        if not os.path.isfile(full) or not full.endswith((".mp4", ".ts")):
            return self._error(404, "not found")
        size = os.path.getsize(full)
        start, end = 0, size - 1
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4" if full.endswith(".mp4") else "video/mp2t")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(full)}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(full, "rb") as f:
            f.seek(start)
            left = length
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser stopped reading, which is normal for video seeking


_quick = {"url": None, "time": 0.0}


def quick_tunnel_url():
    """The current https://….trycloudflare.com address; it changes whenever cloudflared restarts."""
    if time.time() - _quick["time"] > 30:
        import urllib.request
        try:
            with urllib.request.urlopen(QUICK_TUNNEL_METRICS, timeout=2) as r:
                host = json.load(r).get("hostname")
            _quick["url"] = f"https://{host}" if host else None
        except (OSError, ValueError):
            _quick["url"] = None
        _quick["time"] = time.time()
    return _quick["url"]


def lan_ip():
    """This computer's address on the home network (no packet is sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def load_token(path):
    """The phone access token, kept across restarts so a saved QR link keeps working."""
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        if len(token) >= 16:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(16)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


def serve(cfg, http, api, monitor, notifier, host="127.0.0.1", port=8080, config_path=None):
    need_token = host not in LOOPBACK or cfg.public_url
    token = load_token(cfg.path(".web_token")) if need_token else None
    app = App(cfg, http, api, monitor, notifier, token, config_path, port)
    app.refresh_account()
    app.watch_account()
    app.janitor.start()
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    shown = "localhost" if host in LOOPBACK else (lan_ip() if host in ("0.0.0.0", "::") else host)
    url = f"http://{shown}:{port}/" + (f"?token={token}" if token else "")
    log.info("web UI: %s", url)
    if cfg.public_url == QUICK_TUNNEL:
        log.info("public UI: the trycloudflare.com address from cloudflared, plus ?token=%s", token)
    elif cfg.public_url:
        log.info("public UI: %s/?token=%s", cfg.public_url, token)
    if token:
        log.warning("the UI is reachable from other devices: only share this link with people you trust")
    return server, url
