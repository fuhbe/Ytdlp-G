"""Record availability of public Blender video/playlist fixtures from the build runner."""

import json
import tempfile
from pathlib import Path

from yt_dlp.utils import download_range_func

from ytdlp_g import turbo
from ytdlp_g.diagnostics import diagnostic
from ytdlp_g.downloader import base_options
from ytdlp_g.media import probe

video = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
playlist = "https://www.youtube.com/user/BlenderFoundation/videos"
report = {}
options = base_options() | {"socket_timeout": 8, "retries": 0, "extractor_retries": 0}
with tempfile.TemporaryDirectory() as root:
    try:
        with turbo.youtube_dl(
            options
            | {
                "format": "bv*+ba/b",
                "noplaylist": True,
                "download_ranges": download_range_func(None, [(0, 2)]),
                "outtmpl": str(Path(root) / "sample.%(ext)s"),
                "merge_output_format": "mkv",
            }
        ) as ydl:
            info = ydl.extract_info(video)
        path = next(p for p in Path(root).glob("sample.*") if p.suffix != ".part")
        streams = probe(path)["streams"]
        assert {"video", "audio"} <= {s["codec_type"] for s in streams}
        report["video_excerpt"] = {
            "result": "passed",
            "height": info.get("height"),
            "fps": info.get("fps"),
        }
    except Exception as exc:
        report["video_excerpt"] = {"result": "unverified", **diagnostic("download", exc)}
    try:
        with turbo.youtube_dl(
            options | {"extract_flat": "in_playlist", "playlist_items": "1:2"}
        ) as ydl:
            info = ydl.extract_info(playlist, download=False)
            assert len(list(info["entries"])) == 2
        report["playlist_listing"] = {"result": "passed", "entries": 2}
    except Exception as exc:
        report["playlist_listing"] = {"result": "unverified", **diagnostic("extraction", exc)}
Path("build/public-media.json").write_text(json.dumps(report, indent=2), "utf8")
