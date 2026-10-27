"""Deleting clips, by hand from the web UI or automatically when the disk fills up."""

import glob
import logging
import os
import shutil
import threading

log = logging.getLogger(__name__)
GB = 1024 ** 3


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def delete_clip(full, active_dirs=(), busy=()):
    """Delete one merged .mp4, or a session folder of .ts segments that is not
    being recorded. Returns the number of bytes freed."""
    real = os.path.realpath(full)
    if real in busy:
        raise ValueError("คลิปนี้กำลังอัปโหลดอยู่ ลบไม่ได้ตอนนี้")
    if os.path.isfile(real) and real.endswith(".mp4"):
        size = os.path.getsize(real)
        os.remove(real)
        return size
    if os.path.isdir(real):
        if real in active_dirs:
            raise ValueError("ช่องนี้กำลังอัดอยู่ ลบไม่ได้จนกว่าจะอัดเสร็จ")
        if any(not n.endswith((".ts", ".txt")) for n in os.listdir(real)):
            raise ValueError("โฟลเดอร์นี้มีไฟล์อื่นปนอยู่ จึงไม่ลบให้")
        size = sum(os.path.getsize(p) for p in glob.glob(os.path.join(real, "*")))
        shutil.rmtree(real)
        return size
    raise FileNotFoundError(full)


def oldest_clips(out_dir):
    """Merged .mp4 files, oldest first."""
    clips = glob.glob(os.path.join(out_dir, "*", "*.mp4"))
    return sorted(clips, key=os.path.getmtime)


class Janitor(threading.Thread):
    """Every few minutes, if auto-delete is on and free space is below the limit,
    delete the oldest merged clips until there is enough room again.
    Never touches recordings in progress, unmerged segments, or clips being uploaded."""

    def __init__(self, cfg, out_dir, notifier, busy=lambda: (), every=300):
        super().__init__(name="janitor", daemon=True)
        self.cfg, self.out_dir, self.notifier, self.busy, self.every = cfg, out_dir, notifier, busy, every
        self._wake = threading.Event()

    def run(self):
        while True:
            try:
                self.clean()
            except Exception:  # never let the thread die
                log.exception("auto-delete failed")
            self._wake.wait(self.every)
            self._wake.clear()

    def poke(self):
        self._wake.set()

    def clean(self):
        if not self.cfg.auto_delete_enabled:
            return []
        want = self.cfg.auto_delete_free_gb * GB
        deleted = []
        busy = set(self.busy())
        for clip in oldest_clips(self.out_dir):
            if free_bytes(self.out_dir) >= want:
                break
            if os.path.realpath(clip) in busy:
                continue
            size = delete_clip(clip)
            deleted.append(clip)
            log.warning("auto-delete: removed %s (%.1f GB) to keep %s GB free",
                        clip, size / GB, self.cfg.auto_delete_free_gb)
        if deleted:
            names = ", ".join(os.path.basename(c) for c in deleted)
            self.notifier.send(f"🧹 พื้นที่เหลือน้อย ลบคลิปเก่า {len(deleted)} ไฟล์อัตโนมัติ: {names}")
        return deleted
