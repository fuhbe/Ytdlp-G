import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ytdlp_g import lite, turbo
from ytdlp_g.media import executable, working_encoders
from ytdlp_g.paths import publish


@pytest.fixture(autouse=True)
def reset():
    turbo.configure({})
    turbo.invalidate()
    yield
    turbo.configure({})
    turbo.invalidate()


def test_cache_deduplicates_and_detaches_results():
    calls = []

    def load():
        calls.append(True)
        time.sleep(0.05)
        return {"value": []}

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: turbo.cached("same", load), range(4)))
    assert len(calls) == 1
    results[0]["value"].append(1)
    assert not results[1]["value"]
    turbo.invalidate()
    turbo.cached("same", load)
    assert len(calls) == 2


def test_cache_expiry(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(turbo.time, "monotonic", lambda: now[0])
    assert turbo.cached("key", lambda: 1) == 1
    now[0] += 301
    assert turbo.cached("key", lambda: 2) == 2


@pytest.mark.parametrize(
    "profile,budget", [("eco", 2), ("balanced", 4), ("fast", 8), ("turbo", 16)]
)
def test_fragments_and_global_budget(profile, budget):
    turbo.configure({"profile": profile, "downloads": 1})
    assert turbo.connections() == budget
    turbo.configure({"profile": profile, "downloads": 4})
    assert turbo.connections() * 4 <= 16


def test_network_congestion_reduces_auto_budget():
    turbo.feedback(9 * 1024**2)
    old = turbo.connections()
    turbo.feedback(failed=True)
    assert turbo.connections() < old


def test_single_extraction_and_reuse(tmp_path, media_url, monkeypatch):
    original = lite.yt_dlp.YoutubeDL.extract_info
    calls = []

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(lite.yt_dlp.YoutubeDL, "extract_info", counted)
    analysis = lite.inspect_lite(media_url)
    assert lite.inspect_lite(media_url) == analysis
    result = lite.download_lite(
        dict(analysis=analysis, quality="video:mp4:90", mode="normal", destination=str(tmp_path))
    )
    assert Path(result["files"][0]).is_file() and len(calls) == 1


def test_immutable_publication_handles_races(tmp_path):
    src = tmp_path / "stage"
    src.write_bytes(b"final")
    with ThreadPoolExecutor(4) as pool:
        paths = list(
            pool.map(lambda _: publish(src, tmp_path / "video.mp4", immutable=True), range(8))
        )
    assert len(set(paths)) == 8 and all(p.samefile(src) for p in paths)


@pytest.mark.parametrize("encoder", ["h264_qsv", "h264_nvenc", "h264_amf"])
def test_actual_hardware_encoder(encoder):
    usable = working_encoders(executable("ffmpeg"), encoder)
    if encoder not in usable:
        pytest.skip(f"{encoder}: no functioning device/driver")
    assert usable[0] == encoder


def test_cpu_always_available():
    assert working_encoders(executable("ffmpeg"), "libx264") == ["libx264"]


def test_bounded_large_playlist_order():
    state = [0, 0]
    lock = threading.Lock()

    def analyze(i):
        with lock:
            state[0] += 1
            state[1] = max(state)
        time.sleep(0.001)
        with lock:
            state[0] -= 1
        return i

    assert list(turbo.ordered_map(analyze, range(100), 3)) == list(range(100))
    assert 1 < state[1] <= 3
