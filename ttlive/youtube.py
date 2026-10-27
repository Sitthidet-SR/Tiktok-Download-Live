"""Upload clips to the user's own YouTube channel as private videos.

Uses the official YouTube Data API v3 with the user's own Google Cloud OAuth
client (client_secret.json, type "Desktop app"). Sign-in happens once in the
browser; the refresh token is kept in youtube_token.json (mode 0600).
Only the youtube.upload scope is requested.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
CHUNK = 16 * 1024 * 1024


class YouTubeError(Exception):
    pass


def _post_form(url, data):
    req = urllib.request.Request(url, data=urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
        except ValueError:
            err = {}
        raise YouTubeError(err.get("error_description") or err.get("error") or f"HTTP {e.code}") from None


def _write_secret(path, obj):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


class YouTube:
    def __init__(self, base_dir, notifier):
        self.base_dir, self.notifier = base_dir, notifier
        self.token_file = os.path.join(base_dir, "youtube_token.json")
        self.uploads_file = os.path.join(base_dir, "youtube_uploads.json")
        self.jobs = {}  # rel path -> {"state", "progress", "error"}
        self._pending = {}  # oauth state -> (verifier, redirect_uri, time)
        self._lock = threading.Lock()
        self._token = None

    # ---- files ------------------------------------------------------

    def client_file(self):
        for name in ("client_secret.json", *sorted(n for n in os.listdir(self.base_dir)
                                                  if n.startswith("client_secret") and n.endswith(".json"))):
            path = os.path.join(self.base_dir, name)
            if os.path.isfile(path):
                return path
        return None

    def _client(self):
        path = self.client_file()
        if not path:
            raise YouTubeError("ยังไม่มีไฟล์ client_secret.json ในโฟลเดอร์โปรแกรม")
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        c = raw.get("installed") or raw.get("web")
        if not c or "client_id" not in c:
            raise YouTubeError("client_secret.json ไม่ถูกต้อง ต้องเป็น OAuth client แบบ Desktop app")
        return c

    def uploads(self):
        try:
            with open(self.uploads_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_upload(self, rel, video_id):
        data = self.uploads()
        data[rel] = {"video_id": video_id, "time": time.time()}
        tmp = self.uploads_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.uploads_file)

    def connected(self):
        return os.path.isfile(self.token_file)

    def status(self):
        with self._lock:
            jobs = {k: dict(v) for k, v in self.jobs.items()}
        return {"configured": self.client_file() is not None, "connected": self.connected(), "jobs": jobs}

    def busy_paths(self):
        with self._lock:
            return [v["full"] for v in self.jobs.values() if v["state"] in ("queued", "uploading")]

    # ---- sign-in ----------------------------------------------------

    def auth_url(self, redirect_uri):
        c = self._client()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        self._pending = {k: v for k, v in self._pending.items() if time.time() - v[2] < 900}
        self._pending[state] = (verifier, redirect_uri, time.time())
        return AUTH_URL + "?" + urlencode({
            "client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
            "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })

    def finish(self, code, state):
        if state not in self._pending:
            raise YouTubeError("ลิงก์ยืนยันหมดอายุหรือไม่ถูกต้อง ลองกดเชื่อมต่อใหม่")
        verifier, redirect_uri, _ = self._pending.pop(state)
        c = self._client()
        tok = _post_form(TOKEN_URL, {
            "code": code, "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
        })
        if not tok.get("refresh_token"):
            raise YouTubeError("Google ไม่ได้ส่ง refresh token กลับมา ลองเชื่อมต่อใหม่")
        _write_secret(self.token_file, {"refresh_token": tok["refresh_token"]})
        self._token = (tok["access_token"], time.time() + int(tok.get("expires_in", 3600)) - 60)
        log.info("connected to YouTube")

    def disconnect(self):
        if self.connected():
            os.remove(self.token_file)
        self._token = None

    def _access_token(self):
        if self._token and self._token[1] > time.time():
            return self._token[0]
        try:
            with open(self.token_file, encoding="utf-8") as f:
                refresh = json.load(f)["refresh_token"]
        except (OSError, ValueError, KeyError):
            raise YouTubeError("ยังไม่ได้เชื่อมบัญชี YouTube") from None
        c = self._client()
        try:
            tok = _post_form(TOKEN_URL, {"refresh_token": refresh, "client_id": c["client_id"],
                                         "client_secret": c.get("client_secret", ""), "grant_type": "refresh_token"})
        except YouTubeError as e:
            if "invalid_grant" in str(e) or "expired" in str(e).lower() or "revoked" in str(e).lower():
                self.disconnect()
                raise YouTubeError("สิทธิ์ YouTube หมดอายุ กดเชื่อมบัญชีใหม่อีกครั้ง") from None
            raise
        self._token = (tok["access_token"], time.time() + int(tok.get("expires_in", 3600)) - 60)
        return self._token[0]

    # ---- upload -----------------------------------------------------

    def start_upload(self, full, rel, title, description=""):
        with self._lock:
            job = self.jobs.get(rel)
            if job and job["state"] in ("queued", "uploading"):
                raise YouTubeError("คลิปนี้กำลังอัปโหลดอยู่แล้ว")
            if rel in self.uploads():
                raise YouTubeError("คลิปนี้อัปโหลดขึ้น YouTube ไปแล้ว")
            self._access_token()  # fail now, not in the background, if not signed in
            self.jobs[rel] = {"state": "queued", "progress": 0.0, "error": "", "full": os.path.realpath(full)}
        threading.Thread(target=self._upload, args=(full, rel, title, description),
                         name="youtube-upload", daemon=True).start()

    def _set(self, rel, **kw):
        with self._lock:
            self.jobs[rel].update(kw)

    def _upload(self, full, rel, title, description):
        try:
            video_id = self._resumable_upload(full, rel, title, description)
        except Exception as e:  # shown in the UI
            log.warning("YouTube upload of %s failed: %s", rel, e)
            self._set(rel, state="error", error=str(e))
            self.notifier.send(f"❌ อัปโหลด {os.path.basename(rel)} ขึ้น YouTube ไม่สำเร็จ: {e}")
            return
        self._save_upload(rel, video_id)
        self._set(rel, state="done", progress=1.0, video_id=video_id)
        log.info("uploaded %s to YouTube as %s (private)", rel, video_id)
        self.notifier.send(f"✅ อัปโหลด {os.path.basename(rel)} ขึ้น YouTube แล้ว (ส่วนตัว) https://youtu.be/{video_id}")

    def _resumable_upload(self, full, rel, title, description):
        size = os.path.getsize(full)
        meta = {
            "snippet": {"title": title[:100], "description": description[:4900], "categoryId": "22"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        }
        req = urllib.request.Request(UPLOAD_URL, data=json.dumps(meta).encode(), method="POST", headers={
            "Authorization": "Bearer " + self._access_token(),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                session = r.headers["Location"]
        except urllib.error.HTTPError as e:
            raise YouTubeError(_api_error(e)) from None
        self._set(rel, state="uploading")

        sent, failures = 0, 0
        with open(full, "rb") as f:
            while sent < size:
                f.seek(sent)
                chunk = f.read(CHUNK)
                end = sent + len(chunk) - 1
                put = urllib.request.Request(session, data=chunk, method="PUT", headers={
                    "Authorization": "Bearer " + self._access_token(),
                    "Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{size}",
                })
                try:
                    with urllib.request.urlopen(put, timeout=300) as r:
                        return json.load(r)["id"]  # 200/201: finished
                except urllib.error.HTTPError as e:
                    if e.code == 308:  # chunk accepted, send the next one
                        sent = _received(e.headers.get("Range"))
                        failures = 0
                    elif e.code in (500, 502, 503, 504) and failures < 6:
                        failures += 1
                        time.sleep(2 ** failures)
                        sent = self._ask_received(session, size, sent)
                    else:
                        raise YouTubeError(_api_error(e)) from None
                except (OSError, TimeoutError):
                    if failures >= 6:
                        raise YouTubeError("เน็ตหลุดระหว่างอัปโหลดหลายครั้ง") from None
                    failures += 1
                    time.sleep(2 ** failures)
                    sent = self._ask_received(session, size, sent)
                self._set(rel, progress=sent / size)
        raise YouTubeError("YouTube ไม่ยืนยันว่าได้รับไฟล์ครบ")

    def _ask_received(self, session, size, fallback):
        req = urllib.request.Request(session, data=b"", method="PUT", headers={
            "Authorization": "Bearer " + self._access_token(), "Content-Range": f"bytes */{size}"})
        try:
            urllib.request.urlopen(req, timeout=60).close()
        except urllib.error.HTTPError as e:
            if e.code == 308:
                return _received(e.headers.get("Range"))
        except OSError:
            pass
        return fallback


def _received(range_header):
    """'bytes=0-1234' -> 1235 bytes received."""
    if not range_header:
        return 0
    return int(range_header.rsplit("-", 1)[1]) + 1


def _api_error(e):
    try:
        err = json.load(e).get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        if reason == "quotaExceeded":
            return "โควตา YouTube API วันนี้หมดแล้ว (ประมาณ 6 คลิปต่อวัน) ลองใหม่พรุ่งนี้"
        if reason == "uploadLimitExceeded":
            return "ช่อง YouTube นี้อัปโหลดครบจำนวนต่อวันแล้ว"
        return err.get("message") or f"HTTP {e.code}"
    except ValueError:
        return f"HTTP {e.code}"
