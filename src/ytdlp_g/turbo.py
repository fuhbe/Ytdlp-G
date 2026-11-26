"""Worker-local bounded caches and resource budgets for Turbo Engine."""

import copy
import os
import shutil
import sys
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
download_slots = threading.BoundedSemaphore(2)
disk_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publish")
zip_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="archive")
analysis_slots = threading.BoundedSemaphore(4)
network_level = 4
lock = threading.RLock()
entries = OrderedDict()
inflight = {}
generation = 0
last_clean = 0.0


def available_memory():
    try:
        if os.name == "nt":
            import ctypes

            class Memory(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_uint32),
                    ("load", ctypes.c_uint32),
                    ("total", ctypes.c_uint64),
                    ("available", ctypes.c_uint64),
                    ("other", ctypes.c_uint64 * 5),
                ]

            state = Memory()
            state.length = ctypes.sizeof(state)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return state.available
        elif "SC_AVPHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        pass
    return None


def cache_size(value):
    # Bound native Python metadata, including nested extractor dictionaries.
    seen = set()

    def size(obj):
        if id(obj) in seen:
            return 0
        seen.add(id(obj))
        count = sys.getsizeof(obj)
        if isinstance(obj, dict):
            count += sum(size(k) + size(v) for k, v in obj.items())
        elif isinstance(obj, (list, tuple)):
            count += sum(size(v) for v in obj)
        return count

    return size(value)


def configure(values):
    global conversion_slots, download_slots
    previous = prefs.copy()
    for key in DEFAULTS:
        value = values.get(key, DEFAULTS[key])
        if key in ("downloads", "conversions", "fragments"):
            value = max(
                1, min(int(value), {"downloads": 8, "conversions": 4, "fragments": 16}[key])
            )
        prefs[key] = value
    if prefs["profile"] == "auto":
        free = available_memory()
        cpu = os.cpu_count() or 2
        prefs["downloads"] = min(prefs["downloads"], max(1, cpu // 2))
        prefs["conversions"] = min(prefs["conversions"], max(1, cpu // 4))
        if free is not None:
            prefs["downloads"] = min(prefs["downloads"], max(1, free // (768 * 1024**2)))
            prefs["conversions"] = min(prefs["conversions"], max(1, free // (2 * 1024**3)))
    if previous != prefs:
        invalidate()
    conversion_slots = threading.BoundedSemaphore(prefs["conversions"])
    download_slots = threading.BoundedSemaphore(prefs["downloads"])


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
        weight = cache_size(value)
        with lock:
            if weight <= 8 * 1024**2:
                entries[key] = (time.monotonic() + 300, value, weight)
            while len(entries) > 64 or sum(record[2] for record in entries.values()) > 32 * 1024**2:
                entries.popitem(last=False)
        future.set_result(value)
        return copy.deepcopy(value)
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with lock:
            inflight.pop(key, None)


def take_seed(url, index):
    with lock:
        record = entries.pop((generation, ("seed", url, index)), None)
    return record[1] if record and time.monotonic() < record[0] else None


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
    if hasattr(ydl, "dl"):
        transfer = ydl.dl

        def download(*args, **kwargs):
            with download_slots:
                return transfer(*args, **kwargs)

        ydl.dl = download
    if hasattr(ydl, "run_pp"):
        run = ydl.run_pp

        def limited(pp, *args, **kwargs):
            with conversion_slots:
                return run(pp, *args, **kwargs)

        ydl.run_pp = limited
    return ydl
