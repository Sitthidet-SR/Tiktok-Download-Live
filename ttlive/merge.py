"""Join a session's .ts segments into one .mp4."""

import glob
import logging
import os
import subprocess

log = logging.getLogger(__name__)


def _ffprobe_for(ffmpeg):
    d, name = os.path.split(ffmpeg)
    return os.path.join(d, name.replace("ffmpeg", "ffprobe"))


def _duration(ffprobe, path):
    """Length of a media file in seconds, or None if ffprobe can't tell."""
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def merge_session(session_dir, ffmpeg="ffmpeg", delete_segments=False):
    """Concatenate session_dir/*.ts (in name order) into <session_dir>.mp4.
    Returns the mp4 path, or None if there was nothing to merge."""
    parts = sorted(p for p in glob.glob(os.path.join(session_dir, "*.ts")) if os.path.getsize(p) > 0)
    if not parts:
        log.info("no segments in %s", session_dir)
        return None
    out = session_dir.rstrip("/") + ".mp4"
    # Write to a temp name so the UI never offers a half-written video
    tmp = out + ".part"
    list_file = os.path.join(session_dir, "concat.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", list_file,
           "-c", "copy", "-movflags", "+faststart", "-f", "mp4", tmp]
    log.info("merging %d segment(s) -> %s", len(parts), out)
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and os.path.exists(tmp)
    if ok:
        # Check nothing was lost: the .mp4 must be about as long as all segments together
        probe = _ffprobe_for(ffmpeg)
        want = sum(_duration(probe, p) or 0 for p in parts)
        got = _duration(probe, tmp)
        if got is not None and want and got < want * 0.95 - 2:
            ok = False
            log.error("merged file is %.0fs but segments add up to %.0fs", got, want)
    if not ok:
        log.error("merge failed, segments kept in %s: %s", session_dir, r.stderr.strip()[-500:])
        if os.path.exists(tmp):
            os.remove(tmp)
        return None
    os.replace(tmp, out)
    os.remove(list_file)
    if delete_segments:
        for p in parts:
            os.remove(p)
        try:
            os.rmdir(session_dir)
        except OSError:
            pass
    return out
