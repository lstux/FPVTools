import shutil
import sys
import time

import pytest

from esptracker import video as vid


def tiny_jpeg(payload=b"abc"):
    # SOI, APP0-ish segment, DQT, SOS ... EOI: enough structure for ensure_dht()
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x06JFIF"
        + b"\xff\xdb\x00\x04\x00\x01"
        + b"\xff\xda\x00\x04\x01\x02"
        + payload
        + b"\xff\xd9"
    )


def test_splitter_handles_chunks_and_garbage():
    a, b = tiny_jpeg(b"one"), tiny_jpeg(b"two")
    stream = b"junk" + a + b"\x00\x00" + b
    sp = vid.JpegSplitter()
    frames = []
    for i in range(0, len(stream), 5):
        frames += sp.feed(stream[i : i + 5])
    assert frames == [a, b]
    # a split SOI marker across two reads
    sp = vid.JpegSplitter()
    assert sp.feed(b"xx\xff") == []
    assert sp.feed(a[1:]) == [a]


def test_ensure_dht_inserts_tables_once():
    f = tiny_jpeg()
    fixed = vid.ensure_dht(f)
    assert len(fixed) == len(f) + len(vid.DHT)
    assert fixed.index(b"\xff\xc4") < fixed.index(b"\xff\xda")
    assert vid.ensure_dht(fixed) == fixed
    assert vid.ensure_dht(b"not a jpeg") == b"not a jpeg"


def test_list_and_pick_devices(tmp_path):
    def node(name, label, index):
        d = tmp_path / name
        d.mkdir()
        (d / "name").write_text(label + "\n")
        (d / "index").write_text("%d\n" % index)

    node("video0", "Integrated Camera", 0)
    node("video1", "Integrated Camera", 1)
    node("video2", "USB Video: USB Video", 0)
    node("video3", "USB Video: USB Video", 1)
    node("video10", "bcm2835-codec-decode", 0)
    devs = vid.list_devices(str(tmp_path))
    assert [d["path"] for d in devs] == ["/dev/video0", "/dev/video2", "/dev/video10"]
    assert vid.pick_device("auto", str(tmp_path)) == "/dev/video2"
    assert vid.pick_device("/dev/video7", str(tmp_path)) == "/dev/video7"
    assert vid.list_devices(str(tmp_path / "missing")) == []


def test_ffmpeg_command_variants():
    cmd = vid.ffmpeg_command("/dev/video2", (1920, 1080), 30, "mjpeg")
    assert cmd[cmd.index("-input_format") + 1] == "mjpeg"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert "1920x1080" in cmd and cmd[-1] == "pipe:1"
    raw = vid.ffmpeg_command("/dev/video2", (1280, 720), 60, "yuyv422")
    assert raw[raw.index("-c:v") + 1] == "mjpeg"
    test = vid.ffmpeg_command("test")
    assert "lavfi" in test
    with pytest.raises(ValueError):
        vid.parse_size("1280*720")
    assert vid.parse_size("1280x720") == (1280, 720)


def fake_camera_cmd(n_frames=50):
    # a stand-in for ffmpeg that writes JPEG-looking frames to stdout
    code = (
        "import sys,time\n"
        "f=%r\n"
        "for i in range(%d):\n"
        "    sys.stdout.buffer.write(f); sys.stdout.flush(); time.sleep(0.01)\n"
        "time.sleep(5)\n" % (tiny_jpeg(), n_frames)
    )
    return [sys.executable, "-c", code]


def test_capture_starts_on_demand_and_stops_when_idle():
    v = vid.VideoSource(command=fake_camera_cmd(), idle_stop_s=0.3)
    assert v.info()["running"] is False
    v.acquire()
    seq, frame = v.wait_frame(0, timeout=5)
    assert seq >= 1 and frame.startswith(b"\xff\xd8") and b"\xff\xc4" in frame  # DHT added
    v.release()
    deadline = time.time() + 5
    while v.info()["running"] and time.time() < deadline:
        time.sleep(0.05)
    assert v.info()["running"] is False
    assert v.latest()[1] is None
    v.close()


def test_capture_reports_ffmpeg_errors():
    v = vid.VideoSource(command=[sys.executable, "-c", "import sys; sys.stderr.write('Device busy\\n'); sys.exit(1)"])
    v.acquire()
    deadline = time.time() + 5
    while not v.info()["error"] and time.time() < deadline:
        time.sleep(0.05)
    assert v.info()["error"] == "Device busy"
    v.release()
    v.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_ffmpeg_test_pattern():
    v = vid.VideoSource("test", size=(320, 240), fps=15)
    v.acquire()
    try:
        seq, frame = v.wait_frame(0, timeout=10)
        assert frame is not None and frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9")
    finally:
        v.release()
        v.close()
