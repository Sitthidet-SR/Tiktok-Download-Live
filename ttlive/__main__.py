"""Command line: python3 -m ttlive {run,check,merge}"""

import argparse
import logging
import os
import shutil
import signal
import sys

from .config import load_config
from .http_client import CookieError, HttpClient, TikTokError
from .merge import merge_session
from .monitor import Monitor
from .notifier import Notifier
from .tiktok_api import TikTokApi

log = logging.getLogger("ttlive")


def setup(args):
    cfg = load_config(args.config)
    if not shutil.which(cfg.ffmpeg):
        sys.exit(f"ffmpeg not found ({cfg.ffmpeg}). Install it: sudo dnf install ffmpeg")
    http = HttpClient(cfg.path(cfg.cookies_file), cfg.user_agent,
                      cfg.min_request_gap, cfg.captcha_pause_minutes)
    return cfg, http, TikTokApi(http)


def check_login(api):
    try:
        name = api.account_name()
    except TikTokError as e:
        log.warning("could not verify login: %s", e)
        return None
    if name:
        log.info("logged in as @%s", name)
    else:
        log.warning("cookies are NOT logged in. Log in to tiktok.com in your browser and export cookies.txt again")
    return name


def cmd_run(args):
    cfg, http, api = setup(args)
    notifier = Notifier(cfg)
    if check_login(api) is None:
        notifier.send("⚠️ cookie อาจหมดอายุหรือยังไม่ได้ล็อกอิน: export cookies.txt ใหม่")
    monitor = Monitor(cfg, http, api, notifier)

    def on_signal(signum, _frame):
        log.info("stopping (finishing current recordings)...")
        monitor.stop()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    monitor.run()


def cmd_check(args):
    cfg, http, api = setup(args)
    check_login(api)
    users = args.users or cfg.channels
    for u in users:
        u = u.lstrip("@")
        try:
            st = api.room_status(u)
        except TikTokError as e:
            print(f"@{u}: error: {e}")
            if "CAPTCHA" in str(e):
                return 2
            continue
        line = f"@{u}: {'LIVE' if st.is_live else 'offline'}"
        if st.room_id:
            line += f" (room {st.room_id})"
        if st.is_live and args.stream:
            try:
                url, q = api.stream_url(st.room_id, cfg.stream_preference)
                line += f"\n  stream [{q}]: {url[:120]}..."
            except TikTokError as e:
                line += f"\n  stream error: {e}"
        print(line)
    return 0


def cmd_merge(args):
    for d in args.session_dirs:
        if not os.path.isdir(d):
            print(f"not a folder: {d}")
            continue
        out = merge_session(d, args.ffmpeg, args.delete)
        print(out or f"nothing merged in {d}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ttlive", description="Record TikTok lives you have the right to save.")
    p.add_argument("-c", "--config", default="config.json", help="config file (default: config.json)")
    p.add_argument("-v", "--verbose", action="store_true", help="show debug logs (including ffmpeg output)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="watch channels and record when they go live").set_defaults(func=cmd_run)

    c = sub.add_parser("check", help="check cookies and live status once, then exit")
    c.add_argument("users", nargs="*", help="usernames (default: channels from config)")
    c.add_argument("--stream", action="store_true", help="also fetch the stream URL when live")
    c.set_defaults(func=cmd_check)

    m = sub.add_parser("merge", help="merge a session folder's .ts files into one .mp4")
    m.add_argument("session_dirs", nargs="+")
    m.add_argument("--delete", action="store_true", help="delete the .ts files after merging")
    m.add_argument("--ffmpeg", default="ffmpeg")
    m.set_defaults(func=cmd_merge)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    try:
        return args.func(args) or 0
    except (CookieError, ValueError, FileNotFoundError) as e:
        log.error("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
