"""Load and validate config.json."""

import json
import os
from dataclasses import dataclass, field

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass
class Config:
    channels: list
    paused_channels: list = field(default_factory=list)  # set from the web UI
    cookies_file: str = "cookies.txt"
    output_dir: str = "recordings"
    # Seconds between status checks for each channel (a random value in this range, then +/- jitter)
    check_interval_min: int = 60
    check_interval_max: int = 180
    jitter: float = 0.2
    # Minimum gap between any two requests to TikTok, across the whole program
    min_request_gap: float = 3.0
    segment_seconds: int = 1800
    # While recording, refresh viewer/like counts this often (seconds)
    stats_interval: int = 60
    # Highest first. "origin" is the streamer's own upload; uhd/hd/sd/ld come from the
    # newer stream data, FULL_HD1/HD1/SD1/SD2 from the older list. "ao" (audio only) is never picked.
    stream_preference: list = field(default_factory=lambda: [
        "origin", "uhd", "FULL_HD1", "hd", "HD1", "sd", "SD1", "ld", "SD2"])
    # After the stream drops, keep the same clip if the channel is live again within
    # this many minutes (even as a brand new live); after that it becomes a new clip
    rejoin_minutes: float = 8
    # Wait between checks while waiting for the live to come back (seconds, capped at 30)
    reconnect_delays: list = field(default_factory=lambda: [5, 10, 20, 30])
    merge_on_end: bool = True
    delete_segments_after_merge: bool = False
    captcha_pause_minutes: int = 30
    user_agent: str = DEFAULT_UA
    ffmpeg: str = "ffmpeg"
    discord_webhook_url: str = ""
    line_channel_token: str = ""
    line_to: str = ""

    @property
    def base_dir(self):
        return self._base_dir

    def path(self, p):
        """Resolve a path relative to the config file's folder."""
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(self._base_dir, p)


def load_config(path, allow_empty=False):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    known = set(Config.__dataclass_fields__)
    unknown = [k for k in raw if k not in known and not k.startswith("_")]
    if unknown:
        raise ValueError(f"Unknown config keys: {', '.join(unknown)}")
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}

    channels = [str(c).strip().lstrip("@") for c in raw.get("channels", []) if str(c).strip()]
    if not channels and not allow_empty:
        raise ValueError("config 'channels' is empty: add at least one TikTok username (or use the web UI)")
    raw["channels"] = channels

    cfg = Config(**raw)
    cfg._base_dir = os.path.dirname(os.path.abspath(path))
    if cfg.check_interval_min < 30:
        raise ValueError("check_interval_min must be at least 30 seconds (the plan recommends 60-180)")
    if cfg.check_interval_max < cfg.check_interval_min:
        raise ValueError("check_interval_max must be >= check_interval_min")
    if cfg.rejoin_minutes < 0 or cfg.rejoin_minutes > 120:
        raise ValueError("rejoin_minutes must be between 0 and 120")
    if cfg.stats_interval < 30:
        raise ValueError("stats_interval must be at least 30 seconds")
    if cfg.min_request_gap < 1:
        raise ValueError("min_request_gap must be at least 1 second")
    return cfg
