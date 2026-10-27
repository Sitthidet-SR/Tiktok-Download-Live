"""Join a session's .ts segments into one .mp4."""

import glob
import logging
import os
import subprocess

log = logging.getLogger(__name__)


def merge_session(session_dir, ffmpeg="ffmpeg", delete_segments=False):
    """Concatenate session_dir/*.ts (in name order) into <session_dir>.mp4.
    Returns the mp4 path, or None if there was nothing to merge."""
    parts = sorted(p for p in glob.glob(os.path.join(session_dir, "*.ts")) if os.path.getsize(p) > 0)
    if not parts:
        log.info("no segments in %s", session_dir)
        return None
    out = session_dir.rstrip("/") + ".mp4"
    list_file = os.path.join(session_dir, "concat.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", list_file,
           "-c", "copy", "-movflags", "+faststart", out]
    log.info("merging %d segment(s) -> %s", len(parts), out)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        log.error("merge failed, segments kept in %s: %s", session_dir, r.stderr.strip()[-500:])
        return None
    os.remove(list_file)
    if delete_segments:
        for p in parts:
            os.remove(p)
        try:
            os.rmdir(session_dir)
        except OSError:
            pass
    return out
