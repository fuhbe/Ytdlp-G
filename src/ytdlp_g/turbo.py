"""Worker-local bounded caches and resource budgets for Turbo Engine."""

import copy
import shutil
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor

from yt_dlp.version import __version__

from .paths import data_dir

DEFAULTS = dict(
    profile="auto",
    encoder="auto",
    downloader="auto",
    downloads=2,
    conversions=1,
    fragments=16,
    cache=True,
)
PROFILES = {"eco": 2, "balanced": 4, "fast": 8, "turbo": 16}
prefs = DEFAULTS.copy()
conversion_slots = threading.BoundedSemaphore(1)
network_level = 4
lock = threading.RLock()
entries = OrderedDict()
inflight = {}
generation = 0
last_clean = 0.0


def configure(values):
    global conversion_slots
    previous = prefs.copy()
    for key in DEFAULTS:
        value = values.get(key, DEFAULTS[key])
        if key in ("downloads", "conversions", "fragments"):
            value = max(
                1, min(int(value), {"downloads": 8, "conversions": 4, "fragments": 16}[key])
            )
        prefs[key] = value
    if previous != prefs:
        invalidate()
    conversion_slots = threading.BoundedSemaphore(prefs["conversions"])


def connections():
    wanted = PROFILES.get(prefs["profile"], network_level)
    return max(1, min(wanted, prefs["fragments"], 16 // prefs["downloads"]))


def feedback(speed=0, failed=False):
    global network_level
    with lock:
        if failed:
            network_level = max(2, network_level // 2)
        elif speed:
            network_level = 8 if speed > 4 * 1024**2 else 4 if speed > 500000 else 2


def invalidate():
    global generation
    with lock:
        entries.clear()
        generation += 1


def cached(key, load, refresh=False):
    if not prefs["cache"]:
        return load()
    with lock:
        key = (generation, key)
        record = entries.get(key)
        if not refresh and record and time.monotonic() < record[0]:
            entries.move_to_end(key)
            return copy.deepcopy(record[1])
        future = inflight.get(key)
        owner = future is None
        if owner:
            future = Future()
            inflight[key] = future
    if not owner:
        return copy.deepcopy(future.result())
    try:
        value = load()
        with lock:
            entries[key] = (time.monotonic() + 300, value)
            while len(entries) > 64:
                entries.popitem(last=False)
        future.set_result(value)
        return copy.deepcopy(value)
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with lock:
            inflight.pop(key, None)


def native_root():
    return data_dir() / "extractor-cache"


def native_dir():
    global last_clean
    if not prefs["cache"]:
        return False
    root = native_root()
    with lock:
        if time.monotonic() - last_clean > 60 or not last_clean:
            files = []
            for p in root.glob("*/*/*.json"):
                try:
                    st = p.stat()
                    files.append((st.st_mtime, st.st_size, p))
                except OSError:
                    continue
            total = sum(x[1] for x in files)
            for stamp, size, p in sorted(files):
                if total <= 32 * 1024**2 and time.time() - stamp < 30 * 86400:
                    break
                try:
                    p.unlink(missing_ok=True)
                    total -= size
                except OSError:
                    continue
            last_clean = time.monotonic()
    return str(root / __version__)


def clear_cache():
    invalidate()
    root = native_root()
    if root.is_dir():
        shutil.rmtree(root)
    return {"cleared": True}


def ordered_map(fn, items, limit):
    """Bound submissions even when yt-dlp returns a lazy playlist."""
    from collections import deque
    from itertools import islice

    items = iter(items)
    with ThreadPoolExecutor(max_workers=limit) as pool:
        pending = deque(pool.submit(fn, x) for x in islice(items, limit))
        while pending:
            yield pending.popleft().result()
            for item in islice(items, 1):
                pending.append(pool.submit(fn, item))


def youtube_dl(options):
    import yt_dlp
    from yt_dlp.cache import Cache

    class PlayerCache(Cache):
        def store(self, section, key, data, dtype="json"):
            # Other extractors may store login tokens. Persist only public player code.
            if section == "challenge-solver" and "?" not in key and "#" not in key:
                super().store(section, key, data, dtype)

    ydl = yt_dlp.YoutubeDL(options)
    if hasattr(ydl, "cache"):
        ydl.cache = PlayerCache(ydl)
    if hasattr(ydl, "run_pp"):
        run = ydl.run_pp

        def limited(pp, *args, **kwargs):
            with conversion_slots:
                return run(pp, *args, **kwargs)

        ydl.run_pp = limited
    return ydl
