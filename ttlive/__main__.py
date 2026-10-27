"""Command line: python3 -m ttlive {run,check,merge}"""

import argparse
import json
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


def setup(args, allow_empty=False):
    cfg = load_config(args.config, allow_empty)
    if not shutil.which(cfg.ffmpeg):
        sys.exit(f"ffmpeg not found ({cfg.ffmpeg}). Install it: sudo dnf install ffmpeg")
    if cfg.cookies_from_browser:
        # Start from Chrome's current cookies; CookieSync keeps them fresh afterwards
        from .browser_cookies import BrowserCookieError, read_tiktok_cookies
        try:
            text = read_tiktok_cookies(cfg.browser_profile)
            path = cfg.path(cfg.cookies_file)
            fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(path + ".new", path)
            log.info("loaded tiktok.com cookies from Chrome (%s)", cfg.browser_profile)
        except (BrowserCookieError, OSError) as e:
            log.warning("could not read cookies from Chrome, using %s: %s", cfg.cookies_file, e)
    http = HttpClient(cfg.path(cfg.cookies_file), cfg.user_agent,
                      cfg.min_request_gap, cfg.captcha_pause_minutes, require_cookies=not allow_empty)
    return cfg, http, TikTokApi(http)


def start_cookie_sync(cfg, http, notifier, on_change=None):
    if not cfg.cookies_from_browser:
        return None
    from .browser_cookies import CookieSync
    sync = CookieSync(http, notifier, cfg.browser_profile, on_change)
    sync.start()
    return sync


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
    start_cookie_sync(cfg, http, notifier)

    def on_signal(signum, _frame):
        log.info("stopping (finishing current recordings)...")
        monitor.stop()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    monitor.run()


def save_channels(config_path, names, paused=()):
    """Write the channel list (and which are paused) back to config.json, keeping every other setting."""
    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)
    raw["channels"] = names
    raw["paused_channels"] = list(paused)
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, config_path)


def save_new_config(config_path):
    example = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.example.json")
    with open(example, encoding="utf-8") as f:
        raw = json.load(f)
    raw["channels"] = []
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(config_path, 0o600)  # it can hold notification tokens


def cmd_web(args):
    import threading
    import webbrowser
    from .web import serve

    if not os.path.exists(args.config):
        save_new_config(args.config)
        log.info("created %s; add channels in the web UI", args.config)
    cfg, http, api = setup(args, allow_empty=True)
    notifier = Notifier(cfg)
    monitor = Monitor(cfg, http, api, notifier,
                      on_channels_changed=lambda names, paused: save_channels(args.config, names, paused))
    server, url = serve(cfg, http, api, monitor, notifier, args.host, args.port)
    app = server.RequestHandlerClass.app
    app.cookie_sync = start_cookie_sync(
        cfg, http, notifier,
        # a fresh login in Chrome should show up in the UI without waiting 6 hours
        on_change=lambda: app.account.get("state") != "ok" and app.refresh_account())
    threading.Thread(target=monitor.run, name="monitor", daemon=True).start()

    def on_signal(signum, _frame):
        log.info("stopping (finishing current recordings)...")
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        monitor.stop()
        for r in list(monitor.recorders.values()):
            r.join(timeout=120)


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

    w = sub.add_parser("web", help="watch and record, with a web UI to manage channels")
    w.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (0.0.0.0 = reachable from your phone on the home network)")
    w.add_argument("--port", type=int, default=8080)
    w.add_argument("--open", action="store_true", help="open the UI in your browser")
    w.set_defaults(func=cmd_web)

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
