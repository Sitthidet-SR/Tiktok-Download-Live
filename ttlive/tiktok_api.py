"""TikTok web endpoints: room ID, live status and stream URLs.

These are the unofficial endpoints the TikTok website itself uses. They can
change at any time; if something breaks, compare with yt-dlp's tiktok:live
extractor.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import quote

from .http_client import TikTokError

log = logging.getLogger(__name__)

LIVE_STATUS = 2  # liveRoom.status / room status: 2 = live, 4 = ended


@dataclass
class RoomStatus:
    username: str
    room_id: str
    is_live: bool
    profile: dict = field(default_factory=dict)  # nickname, avatar, title, viewers


class TikTokApi:
    def __init__(self, http):
        self.http = http

    def account_name(self):
        """Return the logged-in username, or None if the cookies are not logged in."""
        data = self.http.get_json("https://www.tiktok.com/passport/web/account/info/?aid=1459")
        info = data.get("data") or {}
        return info.get("username") or info.get("screen_name") or None

    def room_status(self, username):
        """Look up a user's current room ID and whether they are live."""
        url = ("https://www.tiktok.com/api-live/user/room/?aid=1988&sourceType=54&uniqueId="
               + quote(username))
        try:
            data = self.http.get_json(url, referer=f"https://www.tiktok.com/@{quote(username)}/live")
            d = data.get("data") or {}
            room_id = str((d.get("user") or {}).get("roomId") or "")
            status = (d.get("liveRoom") or {}).get("status")
            if data.get("statusCode") not in (0, None) and not room_id:
                raise TikTokError(f"api-live error {data.get('statusCode')}: {data.get('message', '')}")
            return RoomStatus(username, room_id, bool(room_id) and status == LIVE_STATUS, parse_profile(d))
        except TikTokError as e:
            if "expected JSON" not in str(e):
                raise
            log.debug("api-live/user/room returned non-JSON for %s, trying the live page", username)
        return self._room_status_from_page(username)

    def _room_status_from_page(self, username):
        html, _ = self.http.get(f"https://www.tiktok.com/@{quote(username)}/live")
        m = re.search(r'"roomId"\s*:\s*"(\d+)"', html)
        room_id = m.group(1) if m else ""
        m = re.search(r'"status"\s*:\s*(\d+)', html[html.find('"liveRoom"'):] if '"liveRoom"' in html else "")
        is_live = bool(room_id) and m is not None and int(m.group(1)) == LIVE_STATUS
        return RoomStatus(username, room_id, is_live)

    def check_alive(self, room_ids):
        """Check several rooms in one request. Returns {room_id: bool}."""
        if not room_ids:
            return {}
        url = ("https://webcast.tiktok.com/webcast/room/check_alive/?aid=1988&region=CH"
               "&room_ids=" + ",".join(room_ids) + "&user_is_login=true")
        data = self.http.get_json(url)
        out = {}
        for item in data.get("data") or []:
            rid = str(item.get("room_id_str") or item.get("room_id") or "")
            out[rid] = bool(item.get("alive"))
        return out

    def room_info(self, room_id):
        data = self.http.get_json(
            f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}")
        return data.get("data") or {}

    def room_stats(self, room_id):
        """Current viewers, likes and total viewers of a live room."""
        return parse_stats(self.room_info(room_id))

    def stream_url(self, room_id, preference):
        """Return (url, quality_name) for the best available FLV stream, else HLS."""
        room = self.room_info(room_id)
        if room.get("status") not in (None, LIVE_STATUS):
            raise TikTokError(f"room {room_id} is not live (status {room.get('status')})")
        candidates = extract_stream_urls(room)
        if not candidates:
            raise TikTokError("live room has no stream URL (age/region restricted, or the API changed)")
        scores = stream_scores(room)
        q = pick_best(candidates, scores, preference)
        log.info("room %s offers: %s -> picked %s", room_id,
                 ", ".join(f"{n}({describe(scores.get(n))})" if n in scores else n for n in candidates), q)
        return candidates[q], q


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_profile(d):
    """Name, avatar and live title from an api-live/user/room payload."""
    user = d.get("user") or {}
    room = d.get("liveRoom") or {}
    stats = room.get("liveRoomStats") or {}
    return {
        "nickname": user.get("nickname") or "",
        "avatar": user.get("avatarMedium") or user.get("avatarThumb") or user.get("avatarLarger") or "",
        "title": room.get("title") or "",
        "viewers": _int(stats.get("userCount")),
    }


def parse_stats(room):
    """Viewer, like and gift totals from a room/info payload.

    gift_senders = stats.gift_uv_count (unique people who sent gifts) and
    diamonds = stats.fan_ticket (diamonds received). Both are totals for the
    whole live; the per-gift list needs the signed chat websocket, which we
    deliberately don't use."""
    stats = room.get("stats") or {}
    likes = _int(room.get("like_count")) or _int(stats.get("like_count"))
    return {
        "viewers": _int(room.get("user_count")),
        "likes": likes,
        "total_viewers": _int(stats.get("total_user")) or _int(stats.get("enter_count")),
        "gift_senders": _int(stats.get("gift_uv_count")),
        "diamonds": _int(stats.get("fan_ticket")),
    }


def _sdk_data(room):
    sdk = (((room.get("stream_url") or {}).get("live_core_sdk_data") or {})
           .get("pull_data") or {}).get("stream_data")
    if isinstance(sdk, str) and sdk:
        try:
            sdk = json.loads(sdk)
        except ValueError:
            return {}
    return (sdk or {}).get("data") or {} if isinstance(sdk, dict) else {}


def stream_scores(room):
    """{quality: (pixels, video_bitrate)} for the qualities that say how big they are."""
    scores = {}
    for name, entry in _sdk_data(room).items():
        params = ((entry or {}).get("main") or {}).get("sdk_params")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = None
        if not isinstance(params, dict):
            continue
        w, _, h = str(params.get("resolution") or "").partition("x")
        pixels = (_int(w) or 0) * (_int(h) or 0)
        bitrate = _int(params.get("vbitrate")) or 0
        if pixels or bitrate:
            scores[name] = (pixels, bitrate)
    return scores


def describe(score):
    pixels, bitrate = score
    side = int(pixels ** 0.5) if pixels else 0
    parts = []
    if pixels:
        parts.append(f"~{side}px")
    if bitrate:
        parts.append(f"{bitrate // 1000}kbps")
    return " ".join(parts)


def pick_best(candidates, scores, preference):
    """Always take the best picture on offer: the streamer's original ("origin")
    if there is one, else the largest resolution/bitrate TikTok reports, else
    the first match in the preference list. Never audio-only unless that's all."""
    video = [q for q in candidates if q != "ao"] or list(candidates)
    if "origin" in video:
        return "origin"
    scored = [q for q in video if q in scores]
    if scored:
        return max(scored, key=lambda q: scores[q])
    for q in preference:
        if q in video:
            return q
    return video[0]


def extract_stream_urls(room):
    """Collect {quality: url} from a room/info payload. FLV first, HLS as fallback."""
    found = {}
    stream = room.get("stream_url") or {}

    sdk = ((stream.get("live_core_sdk_data") or {}).get("pull_data") or {}).get("stream_data")
    if isinstance(sdk, str) and sdk:
        try:
            sdk = json.loads(sdk)
        except ValueError:
            sdk = None
    if isinstance(sdk, dict):
        for name, entry in (sdk.get("data") or {}).items():
            main = (entry or {}).get("main") or {}
            if main.get("flv"):
                found.setdefault(name, main["flv"])

    for name, url in (stream.get("flv_pull_url") or {}).items():
        if url:
            found.setdefault(name, url)

    hls = stream.get("hls_pull_url")
    if hls:
        found.setdefault("hls", hls)
    for name, url in (stream.get("hls_pull_url_map") or {}).items():
        if url:
            found.setdefault(f"hls_{name}", url)
    return found
