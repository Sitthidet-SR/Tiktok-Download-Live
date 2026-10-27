import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ttlive.config import load_config  # noqa: E402
from ttlive.http_client import CaptchaRequired, CookieError, HttpClient, RateLimited  # noqa: E402
from ttlive.merge import merge_session  # noqa: E402
from ttlive.recorder import Recorder  # noqa: E402
from ttlive.tiktok_api import TikTokApi, extract_stream_urls  # noqa: E402

COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".tiktok.com\tTRUE\t/\tTRUE\t2147483647\tsessionid_ss\tabc\n"
    ".tiktok.com\tTRUE\t/\tTRUE\t2147483647\ttt-target-idc\tuseast\n"
)


class FakeTikTok(http.server.BaseHTTPRequestHandler):
    routes = {}  # path -> (status, headers, body)
    hits = []

    def do_GET(self):
        FakeTikTok.hits.append(self.path)
        path = self.path.split("?")[0]
        status, headers, body = self.routes.get(path, (404, {}, b"not found"))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cookies = os.path.join(self.tmp, "cookies.txt")
        with open(self.cookies, "w") as f:
            f.write(COOKIES)
        os.chmod(self.cookies, 0o600)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ConfigTests(Base):
    def write(self, data):
        p = os.path.join(self.tmp, "config.json")
        with open(p, "w") as f:
            json.dump(data, f)
        return p

    def test_strips_at_and_resolves_paths(self):
        cfg = load_config(self.write({"channels": ["@alice", " bob "]}))
        self.assertEqual(cfg.channels, ["alice", "bob"])
        self.assertEqual(cfg.path("cookies.txt"), os.path.join(self.tmp, "cookies.txt"))

    def test_rejects_fast_polling(self):
        with self.assertRaises(ValueError):
            load_config(self.write({"channels": ["a"], "check_interval_min": 5}))

    def test_rejects_unknown_key(self):
        with self.assertRaises(ValueError):
            load_config(self.write({"channels": ["a"], "chanels": []}))


class HttpClientTests(Base):
    def client(self):
        return HttpClient(self.cookies, "test-agent", min_gap=1, captcha_pause_minutes=30)

    def test_missing_or_empty_cookies(self):
        with self.assertRaises(CookieError):
            HttpClient(os.path.join(self.tmp, "nope.txt"), "ua")
        empty = os.path.join(self.tmp, "empty.txt")
        with open(empty, "w") as f:
            f.write("# Netscape HTTP Cookie File\n")
        with self.assertRaises(CookieError):
            HttpClient(empty, "ua")

    def test_sends_cookies_and_spaces_requests(self):
        FakeTikTok.routes = {"/j": (200, {"Content-Type": "application/json"}, b'{"ok":1}')}
        seen = {}

        class H(FakeTikTok):
            def do_GET(self):
                seen["cookie"] = self.headers.get("Cookie", "")
                super().do_GET()
        srv, base = serve(H)
        try:
            c = self.client()
            t = time.time()
            c.get_json(base + "/j")
            c.get_json(base + "/j")
            self.assertGreaterEqual(time.time() - t, 0.9)
        finally:
            srv.shutdown()
        # Cookies are for .tiktok.com, so they must NOT leak to other hosts
        self.assertNotIn("sessionid", seen["cookie"])

    def test_429_pauses_with_retry_after(self):
        FakeTikTok.routes = {"/r": (429, {"Retry-After": "120"}, b"")}
        srv, base = serve(FakeTikTok)
        try:
            c = self.client()
            with self.assertRaises(RateLimited):
                c.get(base + "/r")
            self.assertGreater(c.paused(), 100)
            with self.assertRaises(RateLimited):  # no request made while paused
                c.get(base + "/r")
        finally:
            srv.shutdown()

    def test_captcha_stops_and_resumes_after_new_cookies(self):
        page = b"<html><div id='captcha_container' class='secsdk-captcha'></div></html>"
        FakeTikTok.routes = {"/c": (200, {"Content-Type": "text/html"}, page)}
        srv, base = serve(FakeTikTok)
        try:
            c = self.client()
            with self.assertRaises(CaptchaRequired):
                c.get_json(base + "/c")
            self.assertGreater(c.paused(), 60 * 29)
            # user re-exports cookies -> pause ends
            time.sleep(0.01)
            os.utime(self.cookies, (time.time() + 5, time.time() + 5))
            self.assertEqual(c.paused(), 0)
        finally:
            srv.shutdown()


class ApiParsingTests(unittest.TestCase):
    def test_extract_prefers_sdk_origin_then_flv_then_hls(self):
        sdk = {"data": {"origin": {"main": {"flv": "http://x/origin.flv"}},
                        "hd": {"main": {"flv": "http://x/hd_sdk.flv"}}}}
        room = {"stream_url": {
            "live_core_sdk_data": {"pull_data": {"stream_data": json.dumps(sdk)}},
            "flv_pull_url": {"FULL_HD1": "http://x/fhd.flv", "SD1": "http://x/sd.flv"},
            "hls_pull_url": "http://x/live.m3u8",
        }}
        got = extract_stream_urls(room)
        self.assertEqual(got["origin"], "http://x/origin.flv")
        self.assertEqual(got["FULL_HD1"], "http://x/fhd.flv")
        self.assertEqual(got["hls"], "http://x/live.m3u8")

    def test_profile_and_stats(self):
        from ttlive.tiktok_api import parse_profile, parse_stats
        prof = parse_profile({"user": {"nickname": "PJ", "avatarMedium": "https://a/b.jpg"},
                              "liveRoom": {"title": "hi", "liveRoomStats": {"userCount": 9, "enterCount": 74457}}})
        self.assertEqual(prof, {"nickname": "PJ", "avatar": "https://a/b.jpg", "title": "hi", "viewers": 9})
        st = parse_stats({"user_count": 120, "like_count": 0, "owner": {"id_str": "77"},
                          "stats": {"total_user": 441346, "follow_count": 51, "fan_ticket": 0}})
        self.assertEqual(st, {"viewers": 120, "total_viewers": 441346, "new_followers": 51, "anchor_id": "77"})

    def test_gifters_add_up_across_polls(self):
        from ttlive.recorder import Recorder
        rec = Recorder.__new__(Recorder)
        rec._gifters = {}
        rec._add_gifters({"1": ("A", 100), "2": ("B", 5)})
        rec._add_gifters({"1": ("A", 150), "3": ("C", 7)})  # B left the room; still counted
        self.assertEqual(rec._gift_totals(), {"gift_senders": 3, "diamonds": 162, "top_gifters": [
            {"name": "A", "coins": 150}, {"name": "C", "coins": 7}, {"name": "B", "coins": 5}]})

    def test_picks_best_quality(self):
        from ttlive.tiktok_api import pick_best, stream_scores
        def entry(res, kbps):
            return {"main": {"flv": f"http://x/{res}.flv",
                             "sdk_params": json.dumps({"resolution": res, "vbitrate": kbps * 1000})}}
        sdk = {"data": {"ld": entry("360x640", 500), "uhd": entry("1080x1920", 4000),
                        "hd": entry("720x1280", 2000), "ao": {"main": {"flv": "http://x/ao.flv"}}}}
        room = {"stream_url": {"live_core_sdk_data": {"pull_data": {"stream_data": json.dumps(sdk)}},
                               "flv_pull_url": {"HD1": "http://x/hd1.flv", "SD1": "http://x/sd1.flv"}}}
        cands = extract_stream_urls(room)
        pref = ["origin", "uhd", "FULL_HD1", "hd", "HD1", "sd", "SD1", "ld", "SD2"]
        self.assertEqual(pick_best(cands, stream_scores(room), pref), "uhd")
        # a preference order that would pick worse still loses to the measured best
        self.assertEqual(pick_best(cands, stream_scores(room), ["ld", "hd"]), "uhd")
        self.assertEqual(pick_best({**cands, "origin": "http://x/o.flv"}, stream_scores(room), pref), "origin")
        # no size info: fall back to the preference order, never audio-only
        self.assertEqual(pick_best({"ao": "a", "SD1": "s", "HD1": "h"}, {}, pref), "HD1")

    def test_empty_room(self):
        self.assertEqual(extract_stream_urls({}), {})


class RoomStatusTests(Base):
    def test_room_status_live_and_offline(self):
        import ttlive.tiktok_api as mod
        live = {"statusCode": 0, "data": {"user": {"roomId": "7123"}, "liveRoom": {"status": 2}}}
        FakeTikTok.routes = {"/api-live/user/room/": (200, {}, json.dumps(live).encode())}
        srv, base = serve(FakeTikTok)
        orig = HttpClient.get

        def redirect(self, url, referer="https://www.tiktok.com/"):
            return orig(self, url.replace("https://www.tiktok.com", base), referer)
        HttpClient.get = redirect
        try:
            api = TikTokApi(HttpClient(self.cookies, "ua", min_gap=1))
            st = api.room_status("alice")
            self.assertTrue(st.is_live)
            self.assertEqual(st.room_id, "7123")
            live["data"]["liveRoom"]["status"] = 4
            FakeTikTok.routes["/api-live/user/room/"] = (200, {}, json.dumps(live).encode())
            self.assertFalse(api.room_status("alice").is_live)
        finally:
            HttpClient.get = orig
            srv.shutdown()
        self.assertTrue(mod)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class RecordAndMergeTests(Base):
    def make_flv(self, seconds=4):
        path = os.path.join(self.tmp, "live.flv")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=duration={seconds}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-f", "flv", path],
                       check=True)
        return path

    def run_recorder(self, live_answers, rejoin_minutes=0.05):
        """Record from a local FLV. live_answers = what room_status says on each re-check."""
        flv = self.make_flv()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=self.tmp)
        handler.log_message = lambda *a: None
        srv, base = serve(handler)
        from ttlive.tiktok_api import RoomStatus

        class FakeApi:
            streams = 0
            answers = list(live_answers)

            def stream_url(self, room_id, pref):
                FakeApi.streams += 1
                return base + "/live.flv", "origin"

            def room_status(self, user):
                live = FakeApi.answers.pop(0) if FakeApi.answers else False
                return RoomStatus(user, "2" if live else "", live)

            def room_stats(self, room_id):
                return {"viewers": 120, "total_viewers": 900, "anchor_id": "9"}

            def gifters(self, room_id, anchor_id):
                return {"1": ("A", 40)}

        tmp = self.tmp

        class Cfg:
            user_agent = "ua"
            ffmpeg = "ffmpeg"
            segment_seconds = 2
            stream_preference = ["origin"]
            stats_interval = 30
            reconnect_delays = [0.2]
            merge_on_end = True
            delete_segments_after_merge = True
            output_dir = os.path.join(tmp, "rec")

            def path(self, p):
                return p
        Cfg.rejoin_minutes = rejoin_minutes

        sent = []

        class N:
            def send(self, t):
                sent.append(t)

        try:
            r = Recorder(Cfg(), FakeApi(), N(), "alice", "1")
            r.start()
            r.join(timeout=60)
        finally:
            srv.shutdown()
        self.assertFalse(r.is_alive())
        return r, FakeApi, sent

    def duration(self, path):
        return float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True).stdout)

    def test_drop_then_back_within_window_is_one_clip(self):
        # live again after the first drop (new room ID), then gone for good
        r, api, sent = self.run_recorder([True])
        self.assertEqual(api.streams, 2)
        self.assertEqual(r.room_id, "2")  # followed the restarted live's new room
        mp4 = r.session_dir + ".mp4"
        self.assertTrue(os.path.exists(mp4), sent)
        self.assertFalse(os.path.exists(r.session_dir))  # segments deleted after a verified merge
        self.assertGreater(self.duration(mp4), 6)  # both 4s recordings in one file
        self.assertTrue(any("ไลฟ์จบ" in s and "คนดูสูงสุด 120" in s for s in sent), sent)

    def test_not_back_within_window_ends_clip(self):
        start = time.time()
        r, api, sent = self.run_recorder([False, False, False], rejoin_minutes=0.03)
        self.assertEqual(api.streams, 1)
        self.assertLess(time.time() - start, 20)  # gave up after ~2s of waiting
        self.assertGreater(self.duration(r.session_dir + ".mp4"), 3)

    def test_merge_nothing(self):
        d = os.path.join(self.tmp, "empty")
        os.makedirs(d)
        self.assertIsNone(merge_session(d))


class WebTests(Base):
    """Drive the web API with a Monitor whose TikTok calls are faked."""

    def setUp(self):
        super().setUp()
        import urllib.request
        from ttlive.config import Config
        from ttlive.monitor import Monitor
        from ttlive.notifier import Notifier
        from ttlive.web import serve
        self.urllib = urllib.request
        cfg = Config(channels=["alice"])
        cfg._base_dir = self.tmp
        self.saved = []
        http_client = HttpClient(os.path.join(self.tmp, "missing.txt"), "ua", require_cookies=False)

        class Api:
            def account_name(self):
                return "me"

        self.monitor = Monitor(cfg, http_client, Api(), Notifier(cfg),
                               on_channels_changed=lambda names, paused: self.saved.append((names, paused)))
        self.server, _ = serve(cfg, http_client, Api(), self.monitor, Notifier(cfg), port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        os.makedirs(os.path.join(self.tmp, "recordings", "alice"))
        with open(os.path.join(self.tmp, "recordings", "alice", "a.mp4"), "wb") as f:
            f.write(b"0123456789")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if body is not None else {}
        req = self.urllib.Request(self.base + path, data=data, headers={**h, **(headers or {})})
        try:
            with self.urllib.urlopen(req) as r:
                return r.status, r.read()
        except self.urllib.HTTPError as e:
            return e.code, e.read()

    def test_state_starts_without_cookies(self):
        code, body = self.call("/api/state")
        st = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(st["pause"]["reason"], "no_cookies")
        self.assertEqual([c["username"] for c in st["channels"]], ["alice"])

    def test_add_pause_remove_channel(self):
        self.assertEqual(self.call("/api/channels", {"username": "@bob"})[0], 200)
        self.assertEqual(self.saved[-1], (["alice", "bob"], []))
        self.assertEqual(self.call("/api/channels", {"username": "bob"})[0], 400)  # duplicate
        self.assertEqual(self.call("/api/channels", {"username": "bad name!"})[0], 400)
        self.assertEqual(self.call("/api/channels/bob/pause", {})[0], 200)
        self.assertTrue(self.monitor.channels["bob"].paused)
        self.assertEqual(self.saved[-1], (["alice", "bob"], ["bob"]))  # pause survives a restart
        self.assertEqual(self.call("/api/channels/bob/remove", {})[0], 200)
        self.assertEqual(self.saved[-1], (["alice"], []))
        self.assertEqual(self.call("/api/channels/nobody/check", {})[0], 404)

    def test_rejects_cross_site_posts(self):
        code, _ = self.call("/api/channels", {"username": "x"}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        req = self.urllib.Request(self.base + "/api/channels", data=b"username=x",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(self.urllib.HTTPError):
            self.urllib.urlopen(req)

    def test_cookie_upload(self):
        self.assertEqual(self.call("/api/cookies", {"text": "junk"})[0], 400)
        self.assertEqual(self.call("/api/cookies", {"text": COOKIES})[0], 200)
        path = os.path.join(self.tmp, "missing.txt")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(self.monitor.http.pause_info()["reason"], "")

    def test_media_range_and_path_safety(self):
        code, body = self.call("/media/alice/a.mp4", headers={"Range": "bytes=2-4"})
        self.assertEqual((code, body), (206, b"234"))
        self.assertIn(self.call("/media/../cookies.txt")[0], (403, 404))
        self.assertEqual(self.call("/media/alice/%2e%2e/%2e%2e/cookies.txt")[0], 403)
        items = json.loads(self.call("/api/recordings")[1])["items"]
        self.assertEqual([i["path"] for i in items], ["alice/a.mp4"])

    def test_token_required_off_localhost(self):
        handler = self.server.RequestHandlerClass
        handler.app.token = "secret"
        try:
            self.assertEqual(self.call("/api/state")[0], 200)  # this computer itself
            handler._local = lambda self: False  # pretend the request comes from a phone
            self.assertEqual(self.call("/api/state")[0], 401)
            self.assertEqual(self.call("/api/state?token=secret")[0], 200)
            self.assertEqual(self.call("/api/state", headers={"Cookie": "ttlive_token=secret"})[0], 200)
            self.assertIn("token=secret", json.loads(self.call("/api/state?token=secret")[1])["lan_url"])
        finally:
            handler.app.token = None
            del handler._local

    def test_delete_clip_and_auto_delete_setting(self):
        self.assertEqual(self.call("/api/delete", {"path": "../cookies.txt"})[0], 403)
        self.assertEqual(self.call("/api/delete", {"path": "alice/nope.mp4"})[0], 404)
        code, body = self.call("/api/delete", {"path": "alice/a.mp4"})
        self.assertEqual((code, json.loads(body)["freed"]), (200, 10))
        self.assertEqual(json.loads(self.call("/api/recordings")[1])["items"], [])
        self.assertEqual(self.call("/api/auto-delete", {"enabled": True, "free_gb": 1})[0], 400)
        self.assertEqual(self.call("/api/auto-delete", {"enabled": True, "free_gb": 80})[0], 200)
        st = json.loads(self.call("/api/state")[1])["settings"]
        self.assertEqual((st["auto_delete_enabled"], st["auto_delete_free_gb"]), (True, 80))

    def test_janitor_deletes_oldest_until_enough_room(self):
        from ttlive import library
        from ttlive.config import Config
        out = os.path.join(self.tmp, "recordings")
        for i, name in enumerate(["old.mp4", "mid.mp4", "new.mp4"]):
            path = os.path.join(out, "alice", name)
            with open(path, "wb") as f:
                f.write(b"x")
            os.utime(path, (1000 + i, 1000 + i))
        cfg = Config(channels=[], auto_delete_enabled=True, auto_delete_free_gb=10)
        freed = []
        orig = library.free_bytes
        library.free_bytes = lambda p: (8 + 1.5 * len(freed)) * library.GB  # each delete frees 1.5 GB
        sent = []
        j = library.Janitor(cfg, out, type("N", (), {"send": lambda s, t: sent.append(t)})(),
                            busy=lambda: [os.path.realpath(os.path.join(out, "alice", "a.mp4"))])
        real_delete = library.delete_clip
        library.delete_clip = lambda c, *a: (freed.append(c), real_delete(c))[1]
        try:
            deleted = j.clean()
        finally:
            library.free_bytes, library.delete_clip = orig, real_delete
        # a.mp4 is "being uploaded" and is skipped; old and mid go, new stays
        self.assertEqual([os.path.basename(d) for d in deleted], ["old.mp4", "mid.mp4"])
        self.assertTrue(os.path.exists(os.path.join(out, "alice", "new.mp4")))
        self.assertEqual(len(sent), 1)


class ChromeCookieTests(Base):
    def make_db(self, rows, version=24):
        """A fake Chrome profile with v10 ("peanuts") encrypted cookies."""
        import hashlib
        import sqlite3
        prof = os.path.join(self.tmp, "chrome", "Default")
        os.makedirs(prof)
        con = sqlite3.connect(os.path.join(prof, "Cookies"))
        con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        con.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
        con.execute("CREATE TABLE cookies (host_key TEXT, path TEXT, is_secure INT, expires_utc INT, "
                    "name TEXT, value TEXT, encrypted_value BLOB)")
        key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
        for host, name, value in rows:
            plain = (hashlib.sha256(host.encode()).digest() if version >= 24 else b"") + value.encode()
            enc = subprocess.run(["openssl", "enc", "-aes-128-cbc", "-K", key.hex(), "-iv", "20" * 16],
                                 input=plain, capture_output=True, check=True).stdout
            con.execute("INSERT INTO cookies VALUES (?, '/', 1, 13400000000000000, ?, '', ?)",
                        (host, name, b"v10" + enc))
        con.commit()
        con.close()
        return os.path.join(self.tmp, "chrome")

    def test_reads_only_tiktok_and_decrypts(self):
        import ttlive.browser_cookies as bc
        base = self.make_db([(".tiktok.com", "sessionid", "abc123"), (".google.com", "SID", "secret"),
                             ("www.tiktok.com", "msToken", "tok")])
        old = bc.CHROME_DIRS
        bc.CHROME_DIRS = [base]
        try:
            text = bc.read_tiktok_cookies()
        finally:
            bc.CHROME_DIRS = old
        self.assertIn("\tsessionid\tabc123", text)
        self.assertIn("\tmsToken\ttok", text)
        self.assertNotIn("google", text)
        path = os.path.join(self.tmp, "from_chrome.txt")
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o600)
        HttpClient(path, "ua")  # loads as a valid Netscape file

    def test_captcha_resumes_only_after_a_passing_probe(self):
        import ttlive.browser_cookies as bc

        class FakeHttp:
            reason = "captcha"
            probes = 0
            pass_probe = False
            replaced = []

            def pause_info(self):
                return {"reason": self.reason, "seconds": 100}

            def replace_cookies(self, text, resume=True):
                self.replaced.append(resume)

            def probe(self, url):
                FakeHttp.probes += 1
                if self.pass_probe:
                    self.reason = ""
                return self.pass_probe

        texts = iter(["a", "b", "c", "d"])
        old = bc.read_tiktok_cookies
        bc.read_tiktok_cookies = lambda profile: next(texts)
        sent = []

        class N:
            def send(self, t):
                sent.append(t)
        try:
            http_ = FakeHttp()
            sync = bc.CookieSync(http_, N())
            self.assertEqual(sync.sync(), "still_captcha")   # new cookies -> one probe, fails
            self.assertEqual(FakeHttp.probes, 1)
            self.assertEqual(sync.sync(), "still_captcha")   # changed again, but probes are 2 min apart
            self.assertEqual(FakeHttp.probes, 1)
            self.assertEqual(http_.replaced, [False, False])  # cookies saved, pause kept
            http_.pass_probe = True
            self.assertEqual(sync.sync(force_probe=True), "resumed")  # the "ยืนยันแล้ว" button
            self.assertTrue(any("ผ่านการยืนยัน" in t for t in sent))
        finally:
            bc.read_tiktok_cookies = old


if __name__ == "__main__":
    unittest.main()
