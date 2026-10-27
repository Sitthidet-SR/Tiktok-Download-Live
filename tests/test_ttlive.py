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

    def test_record_reconnect_then_merge(self):
        flv = self.make_flv()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=self.tmp)
        handler.log_message = lambda *a: None
        srv, base = serve(handler)

        class FakeApi:
            calls = 0
            alive = [True, False]  # dropped once while still live, then ended

            def stream_url(self, room_id, pref):
                FakeApi.calls += 1
                return base + "/live.flv", "origin"

            def check_alive(self, ids):
                return {ids[0]: FakeApi.alive.pop(0)}

        class Cfg:
            user_agent = "ua"
            ffmpeg = "ffmpeg"
            segment_seconds = 2
            stream_preference = ["origin"]
            reconnect_delays = [0, 0]
            merge_on_end = True
            delete_segments_after_merge = True
            output_dir = os.path.join(self.tmp, "rec")

            def path(self, p):
                return p

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
        self.assertEqual(FakeApi.calls, 2)  # reconnected once
        mp4 = r.session_dir + ".mp4"
        self.assertTrue(os.path.exists(mp4), sent)
        self.assertFalse(os.path.exists(r.session_dir))  # segments deleted after merge
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
            capture_output=True, text=True).stdout)
        self.assertGreater(dur, 6)  # two 4s recordings joined
        self.assertTrue(any("ไลฟ์จบ" in s for s in sent))

    def test_merge_nothing(self):
        d = os.path.join(self.tmp, "empty")
        os.makedirs(d)
        self.assertIsNone(merge_session(d))


if __name__ == "__main__":
    unittest.main()
