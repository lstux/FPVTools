"""Video from a UVC capture device (HDMI->USB dongle on the goggles / VRX output), relayed to the
browser as MJPEG (multipart/x-mixed-replace), which every browser shows in a plain <img>.

ffmpeg does the capture. With a dongle that already outputs MJPEG (MS2109/MS2130 and nearly all
cheap HDMI dongles do) the frames are copied, not re-encoded, so a Raspberry Pi 3B copes easily.
Capture only runs while at least one browser is watching (plus a short grace period).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("esptracker.video")

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_FRAME = 8 * 1024 * 1024
IDLE_STOP_S = 5.0

# Standard Huffman tables (JPEG spec, Annex K.3), as one DHT segment. Many UVC devices send
# "MJPEG" frames without a DHT segment (the tables are implied, AVI1 style); browsers need them.
_DC_L_BITS = bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
_DC_C_BITS = bytes([0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
_DC_VALS = bytes(range(12))
_AC_L_BITS = bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D])
_AC_L_VALS = bytes.fromhex(
    "01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a"
    "3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a9293949596"
    "9798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2"
    "f3f4f5f6f7f8f9fa"
)
_AC_C_BITS = bytes([0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77])
_AC_C_VALS = bytes.fromhex(
    "000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a26272829"
    "2a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a929394"
    "95969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9ea"
    "f2f3f4f5f6f7f8f9fa"
)


def _dht_segment() -> bytes:
    body = b""
    for cls_id, bits, vals in (
        (0x00, _DC_L_BITS, _DC_VALS),
        (0x10, _AC_L_BITS, _AC_L_VALS),
        (0x01, _DC_C_BITS, _DC_VALS),
        (0x11, _AC_C_BITS, _AC_C_VALS),
    ):
        assert sum(bits) == len(vals), "bad Huffman table"
        body += bytes([cls_id]) + bits + vals
    return b"\xff\xc4" + (len(body) + 2).to_bytes(2, "big") + body


DHT = _dht_segment()


def ensure_dht(frame: bytes) -> bytes:
    """Insert the standard Huffman tables if the JPEG has none (before the start-of-scan marker)."""
    i = 2
    n = len(frame)
    while i + 4 <= n:
        if frame[i] != 0xFF:
            return frame  # not a marker where we expect one: leave it alone
        marker = frame[i + 1]
        if marker == 0xC4:
            return frame
        if marker == 0xDA:
            return frame[:i] + DHT + frame[i:]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        seglen = int.from_bytes(frame[i + 2 : i + 4], "big")
        i += 2 + seglen
    return frame


class JpegSplitter:
    """Cuts a byte stream of concatenated JPEG images into frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[bytes]:
        self._buf += data
        out: List[bytes] = []
        while True:
            start = self._buf.find(SOI)
            if start < 0:
                # keep a trailing 0xFF in case it is the first half of a split SOI
                del self._buf[: max(0, len(self._buf) - 1)]
                return out
            if start:
                del self._buf[:start]
            end = self._buf.find(EOI, 2)
            if end < 0:
                if len(self._buf) > MAX_FRAME:
                    self._buf.clear()
                return out
            out.append(bytes(self._buf[: end + 2]))
            del self._buf[: end + 2]


# ---- device discovery -------------------------------------------------------------------------------


def list_devices(sysfs: str = "/sys/class/video4linux") -> List[Dict[str, Any]]:
    """V4L2 capture nodes. A UVC device usually creates two nodes (video + metadata); only the node
    with index 0 carries the picture."""
    root = Path(sysfs)
    out: List[Dict[str, Any]] = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir(), key=lambda p: (len(p.name), p.name)):
        if not d.name.startswith("video"):
            continue
        try:
            index = int((d / "index").read_text().strip() or "0")
        except (OSError, ValueError):
            index = 0
        if index != 0:
            continue
        try:
            name = (d / "name").read_text().strip()
        except OSError:
            name = d.name
        out.append({"path": "/dev/" + d.name, "name": name})
    return out


def pick_device(spec: str, sysfs: str = "/sys/class/video4linux") -> Optional[str]:
    if spec != "auto":
        return spec
    devs = list_devices(sysfs)
    # prefer something that looks like a capture dongle over a laptop webcam
    for d in devs:
        n = d["name"].lower()
        if any(k in n for k in ("usb video", "capture", "hdmi", "ms2109", "ms2130", "uvc", "macrosilicon")):
            return d["path"]
    return devs[0]["path"] if devs else None


# ---- capture ----------------------------------------------------------------------------------------


def parse_size(text: str) -> Tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        size = int(w), int(h)
    except ValueError:
        raise ValueError("video size must look like 1280x720, got %r" % text)
    if not (16 <= size[0] <= 8192 and 16 <= size[1] <= 8192):
        raise ValueError("unreasonable video size %r" % text)
    return size


def ffmpeg_command(
    device: str, size: Tuple[int, int] = (1280, 720), fps: int = 30, input_format: str = "mjpeg", quality: int = 6
) -> List[str]:
    """Command line that writes concatenated JPEGs to stdout. `device` may be 'test' (built-in pattern)."""
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    wh = "%dx%d" % size
    if device == "test":
        src = ["-re", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d" % (wh, fps)]
        enc = ["-c:v", "mjpeg", "-q:v", str(quality), "-pix_fmt", "yuvj420p"]
    else:
        src = ["-fflags", "nobuffer", "-flags", "low_delay", "-f", "v4l2", "-thread_queue_size", "8"]
        if input_format == "mjpeg":
            src += ["-input_format", "mjpeg"]
            enc = ["-c:v", "copy"]
        else:  # raw (yuyv422...) devices: encode here - costs CPU, prefer a dongle with MJPEG
            src += ["-input_format", input_format]
            enc = ["-c:v", "mjpeg", "-q:v", str(quality), "-pix_fmt", "yuvj420p"]
        src += ["-video_size", wh, "-framerate", str(fps), "-i", device]
    return base + src + ["-an"] + enc + ["-f", "mjpeg", "-flush_packets", "1", "pipe:1"]


class VideoSource:
    """One capture process shared by every viewer; viewers always get the latest frame."""

    def __init__(
        self,
        device: str = "auto",
        size: Tuple[int, int] = (1280, 720),
        fps: int = 30,
        input_format: str = "mjpeg",
        command: Optional[Sequence[str]] = None,
        idle_stop_s: float = IDLE_STOP_S,
    ) -> None:
        self.spec = device
        self.size = size
        self.fps = fps
        self.input_format = input_format
        self._command = list(command) if command else None
        self.idle_stop_s = idle_stop_s

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._frame: Optional[bytes] = None
        self._seq = 0
        self._viewers = 0
        self._last_viewer = 0.0
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._closed = False
        self.device: Optional[str] = None
        self.error: Optional[str] = None
        self.running = False
        self._fps_t0 = time.monotonic()
        self._fps_n = 0
        self.measured_fps = 0.0

    # -- public ---------------------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "spec": self.spec,
                "device": self.device,
                "size": "%dx%d" % self.size,
                "fps": self.fps,
                "format": self.input_format,
                "running": self.running,
                "viewers": self._viewers,
                "measured_fps": round(self.measured_fps, 1),
                "error": self.error,
            }

    def acquire(self) -> None:
        with self._lock:
            self._viewers += 1
            self._last_viewer = time.monotonic()
            if self._closed:
                return
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="video", daemon=True)
                self._thread.start()

    def release(self) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers - 1)
            self._last_viewer = time.monotonic()

    def latest(self) -> Tuple[int, Optional[bytes]]:
        with self._lock:
            return self._seq, self._frame

    def wait_frame(self, after_seq: int, timeout: float) -> Tuple[int, Optional[bytes]]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq != after_seq or self._closed, timeout)
            return self._seq, self._frame

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._stop.set()
        self._kill()
        if self._thread:
            self._thread.join(timeout=3)

    # -- capture loop -----------------------------------------------------------------------------

    def _kill(self) -> None:
        p = self._proc
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()

    def _idle(self) -> bool:
        with self._lock:
            return self._viewers == 0 and time.monotonic() - self._last_viewer > self.idle_stop_s

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set() and not self._idle():
            cmd = self._build()
            if cmd is None:
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            got = self._capture(cmd)
            if self._stop.is_set():
                break
            backoff = 1.0 if got else min(backoff * 2, 10.0)
            self._stop.wait(backoff)
        with self._lock:
            self.running = False
            self._frame = None
        log.info("video capture stopped")

    def _build(self) -> Optional[List[str]]:
        if self._command:
            return self._command
        if shutil.which("ffmpeg") is None:
            self.error = "ffmpeg not found (install it: sudo apt install ffmpeg)"
            return None
        dev = pick_device(self.spec)
        if dev is None:
            self.error = "no video capture device found"
            return None
        if dev != "test" and not os.path.exists(dev):
            self.error = "%s does not exist" % dev
            return None
        self.device = dev
        return ffmpeg_command(dev, self.size, self.fps, self.input_format)

    def _capture(self, cmd: List[str]) -> bool:
        log.info("video: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        except OSError as exc:
            self.error = "cannot start ffmpeg: %s" % exc
            return False
        proc = self._proc
        assert proc.stdout is not None
        splitter = JpegSplitter()
        got = False
        with self._lock:
            self.running = True
        fd = proc.stdout.fileno()
        while not self._stop.is_set():
            if self._idle():
                break
            try:
                data = os.read(fd, 1 << 16)
            except OSError:
                break
            if not data:
                break
            for frame in splitter.feed(data):
                self._publish(ensure_dht(frame))
                if not got:
                    got = True
                    self.error = None
        self._kill()
        err = b""
        if proc.stderr is not None:
            try:
                err = proc.stderr.read() or b""
            except (OSError, ValueError):
                pass
        if not got and not self._stop.is_set() and not self._idle():
            msg = err.decode("utf-8", "replace").strip().splitlines()
            self.error = (msg[-1] if msg else "ffmpeg exited (code %s)" % proc.returncode)[:200]
            log.warning("video: %s", self.error)
        with self._lock:
            self.running = False
            self._frame = None  # never hand an old picture to the next viewer
        return got

    def _publish(self, frame: bytes) -> None:
        with self._cond:
            self._frame = frame
            self._seq += 1
            self._cond.notify_all()
        self._fps_n += 1
        now = time.monotonic()
        dt = now - self._fps_t0
        if dt >= 2.0:
            self.measured_fps = self._fps_n / dt
            self._fps_n = 0
            self._fps_t0 = now
