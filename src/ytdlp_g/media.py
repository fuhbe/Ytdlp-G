"""FFmpeg/FFprobe services, without shell execution or output overwrites."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from .paths import publish, safe_name


def hidden_process():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def executable(name, configured=""):
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            raise ValueError("dependency_missing")
        return str(candidate.resolve())
    bundled = (
        Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        / "bin"
        / (name + (".exe" if os.name == "nt" else ""))
    )
    found = str(bundled) if bundled.exists() else shutil.which(name)
    if not found:
        raise ValueError("dependency_missing")
    return found


def version(name, configured=""):
    tool = executable(name, configured)
    result = subprocess.run(
        [tool, "-version"], capture_output=True, text=True, timeout=10, **hidden_process()
    )
    first = result.stdout.splitlines()[0] if result.stdout else ""
    if result.returncode or not first.lower().startswith(name + " version"):
        raise ValueError("dependency_invalid")
    return first


def probe(path, configured=""):
    path = Path(path).resolve(strict=True)
    result = subprocess.run(
        [
            executable("ffprobe", configured),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        **hidden_process(),
    )
    if result.returncode:
        from .diagnostics import diagnostic

        diagnostic("probe", RuntimeError(result.stderr))
        raise ValueError("media_invalid")
    return json.loads(result.stdout)


def parse_time(text):
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        parts = text.strip().split(":")
        if len(parts) != 3:
            raise ValueError("invalid_time")
        try:
            hour, minute, second = int(parts[0]), int(parts[1]), float(parts[2])
        except ValueError as exc:
            raise ValueError("invalid_time") from exc
        if hour < 0 or not 0 <= minute < 60 or not 0 <= second < 60:
            raise ValueError("invalid_time")
        value = hour * 3600 + minute * 60 + second
    if not __import__("math").isfinite(value) or value < 0:
        raise ValueError("invalid_time")
    return value


def ffmpeg_args(
    source,
    output,
    container,
    remux=False,
    codec="h264",
    bitrate=192,
    height=0,
    start=None,
    end=None,
    precise=True,
    ffmpeg="",
):
    """Build validated argv; file paths remain individual arguments."""
    if container not in {
        "mp4",
        "mkv",
        "webm",
        "mov",
        "mp3",
        "m4a",
        "aac",
        "opus",
        "ogg",
        "wav",
        "flac",
    }:
        raise ValueError("invalid_options")
    if codec not in {"h264", "hevc", "av1"} or int(bitrate) not in {64, 96, 128, 192, 256, 320}:
        raise ValueError("invalid_options")
    if int(height) not in {0, 144, 240, 360, 480, 720, 1080, 1440, 2160, 4320}:
        raise ValueError("invalid_options")
    args = [executable("ffmpeg", ffmpeg), "-hide_banner", "-nostdin", "-n"]
    if start is not None:
        start, end = parse_time(start), parse_time(end)
        if end <= start:
            raise ValueError("invalid_time")
        if not precise:
            args += ["-ss", str(start)]
    args += ["-i", str(Path(source).resolve())]
    if start is not None:
        if precise:
            args += ["-ss", str(start)]
        args += ["-t", str(end - start)]
    if remux or (start is not None and not precise):
        args += ["-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy"]
    elif container in {"mp3", "m4a", "aac", "opus", "ogg", "wav", "flac"}:
        codecs = {
            "mp3": "libmp3lame",
            "m4a": "aac",
            "aac": "aac",
            "opus": "libopus",
            "ogg": "libvorbis",
            "wav": "pcm_s16le",
            "flac": "flac",
        }
        args += ["-vn", "-c:a", codecs[container]]
        if container not in {"wav", "flac"}:
            args += ["-b:a", f"{bitrate}k"]
    else:
        encoder = {"h264": "libx264", "hevc": "libx265", "av1": "libaom-av1"}[codec]
        if container == "webm" and codec != "av1":
            raise ValueError("incompatible_container")
        args += [
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            encoder,
            "-crf",
            "23",
            "-c:a",
            "libopus" if container == "webm" else "aac",
            "-b:a",
            f"{bitrate}k",
        ]
        if codec == "h264":
            args += ["-preset", "medium", "-pix_fmt", "yuv420p"]
        if height:
            args += ["-vf", f"scale=-2:{int(height)}"]
    args += [
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]
    return args


def convert(payload, progress=lambda event: None):
    source = Path(payload["source"]).resolve(strict=True)
    info = probe(source, payload.get("ffprobe", ""))
    duration = float(info.get("format", {}).get("duration", 0))
    start, end = payload.get("start"), payload.get("end")
    if start is not None:
        start, end = parse_time(start), parse_time(end)
        if end <= start or (duration and end > duration + 0.1):
            raise ValueError("invalid_time")
        duration = end - start
    destination = Path(payload["destination"]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    container = payload["container"]
    with tempfile.TemporaryDirectory(dir=destination, prefix=".ytdlpg-convert-") as temp:
        output = Path(temp) / ("output." + container)
        args = ffmpeg_args(
            source,
            output,
            container,
            remux=payload.get("remux", False),
            codec=payload.get("codec", "h264"),
            bitrate=int(payload.get("bitrate", 192)),
            height=int(payload.get("height", 0)),
            start=start,
            end=end,
            precise=payload.get("precise", True),
            ffmpeg=payload.get("ffmpeg", ""),
        )
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=errors, text=True, **hidden_process()
            )
            try:
                for line in process.stdout:
                    if line.startswith("out_time_us="):
                        try:
                            seconds = int(line.split("=", 1)[1]) / 1_000_000
                        except ValueError:
                            continue
                        progress(
                            {
                                "status": "processing",
                                "progress": min(99, seconds / duration * 100) if duration else 0,
                            }
                        )
                if process.wait():
                    raise ValueError("conversion_failed")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
        probe(output, payload.get("ffprobe", ""))
        name = (
            safe_name(source.stem + (" - cut" if start is not None else " - converted"))
            + "."
            + container
        )
        result = publish(output, destination / name, immutable=True)
    return {"files": [str(result)], "progress": 100}


ENCODER_ARGS = {
    "h264_qsv": ["-global_quality", "18", "-preset", "fast"],
    "h264_nvenc": ["-preset", "p5", "-rc", "vbr", "-cq", "18", "-b:v", "0"],
    "h264_amf": [
        "-usage",
        "transcoding",
        "-quality",
        "quality",
        "-rc",
        "cqp",
        "-qp_i",
        "18",
        "-qp_p",
        "18",
    ],
    "libx264": ["-crf", "18", "-preset", "veryfast"],
}


@lru_cache(maxsize=12)
def working_encoders(binary, requested):
    if requested == "libx264":
        return ["libx264"]
    result = subprocess.run(
        [binary, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        timeout=10,
        **hidden_process(),
    )
    working = []
    for name in ENCODER_ARGS:
        if name == "libx264" or requested not in {"auto", name} or name not in result.stdout:
            continue
        try:
            check = subprocess.run(
                [
                    binary,
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=size=256x144:rate=30",
                    "-frames:v",
                    "4",
                    "-c:v",
                    name,
                    *ENCODER_ARGS[name],
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                timeout=10,
                **hidden_process(),
            )
            if not check.returncode:
                working.append(name)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return working + ["libx264"]


def mp4_video(codec):
    return (
        str(codec or "")
        .lower()
        .startswith(
            ("avc", "h264", "av01", "av1", "vp9", "vp09", "hevc", "h265", "hvc1", "hev1", "mpeg4")
        )
    )


def verify_selection(path, selected, ffprobe=""):
    from .lite import frame_rate

    info = probe(path, ffprobe)
    streams = info["streams"]
    video = next(
        (
            s
            for s in streams
            if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        {},
    )
    if video.get("height") != selected["height"] or not any(
        s["codec_type"] == "audio" for s in streams
    ):
        raise ValueError("selection_mismatch")
    # Extractors can report nominal rates for variable frame rate streams.
    # Accept either measured average or the stream time base's nominal rate.
    expected = selected.get("fps")
    rates = [frame_rate({field: video.get(field)}) for field in ("avg_frame_rate", "r_frame_rate")]
    if (
        expected
        and any(rates)
        and all(abs(rate - expected) > max(0.12, expected * 0.015) for rate in rates if rate)
    ):
        raise ValueError("selection_mismatch")
    duration = selected.get("duration")
    actual = float(info.get("format", {}).get("duration") or 0)
    if duration and actual and abs(duration - actual) > max(2, duration * 0.02):
        raise ValueError("selection_mismatch")


def ensure_mp4(
    source,
    require_audio=True,
    ffmpeg="",
    ffprobe="",
    progress=lambda event: None,
    preserve_codec=True,
):
    from . import turbo

    """Verify sound and normalize incompatible source codecs to H.264/AAC MP4."""
    source = Path(source)
    info = probe(source, ffprobe)
    streams = info.get("streams", [])
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video or (require_audio and not audio):
        raise ValueError("format_unavailable")
    copy_video = mp4_video(video.get("codec_name"))
    if not preserve_codec:
        copy_video = video.get("codec_name") == "h264" and video.get("pix_fmt") in {
            "yuv420p",
            "yuvj420p",
        }
    copy_audio = not audio or audio.get("codec_name") in {"aac", "mp3", "ac3", "eac3", "alac"}
    if not copy_video and video.get("color_transfer") in {"smpte2084", "arib-std-b67"}:
        raise ValueError("hdr_unsupported")
    if source.suffix.lower() == ".mp4" and copy_video and copy_audio:
        return source
    with tempfile.TemporaryDirectory(dir=source.parent, prefix=".mp4-") as temporary:
        output = Path(temporary) / "output.mp4"
        args = [
            executable("ffmpeg", ffmpeg),
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-i",
            str(source),
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy" if copy_video else "libx264",
        ]
        base = args[:-1]
        encoders = ["copy"] if copy_video else working_encoders(args[0], turbo.prefs["encoder"])
        duration = float(info.get("format", {}).get("duration") or 0)
        with turbo.conversion_slots:
            for encoder in encoders:
                output.unlink(missing_ok=True)
                args = base + [encoder]
                if not copy_video:
                    args += [
                        *ENCODER_ARGS[encoder],
                        "-threads",
                        str(min(8, max(1, (os.cpu_count() or 2) // turbo.prefs["conversions"]))),
                        "-pix_fmt",
                        "yuv420p",
                        "-vf",
                        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                        "-fps_mode",
                        "passthrough",
                    ]
                args += ["-c:a", "copy" if copy_audio else "aac"]
                if not copy_audio:
                    args += ["-b:a", "320k"]
                args += [
                    "-map",
                    "0:s?",
                    "-c:s",
                    "mov_text",
                    "-map_metadata",
                    "0",
                    "-map_chapters",
                    "0",
                    "-movflags",
                    "+faststart",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    str(output),
                ]
                with (
                    tempfile.TemporaryFile() as errors,
                    subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=errors,
                        text=True,
                        **hidden_process(),
                    ) as proc,
                ):
                    for line in proc.stdout:
                        if line.startswith("out_time_us=") and duration:
                            try:
                                fraction = float(line.split("=", 1)[1]) / 1e6 / duration
                            except ValueError:
                                continue
                            progress(
                                {
                                    "status": "processing",
                                    "encoder": encoder,
                                    "progress": max(0, min(99, 100 * fraction)),
                                }
                            )
                    if proc.wait():
                        from .diagnostics import diagnostic

                        errors.seek(0)
                        diagnostic(
                            "conversion",
                            RuntimeError(errors.read(4096).decode("utf8", "replace")),
                            encoder=encoder,
                        )
                if not proc.returncode:
                    break
            else:
                raise ValueError("conversion_failed")
        final = probe(output, ffprobe)
        types = {s.get("codec_type") for s in final["streams"]}
        if "video" not in types or (require_audio and "audio" not in types):
            raise ValueError("media_invalid")
        target = source.with_suffix(".mp4")
        if target != source and target.exists():
            raise ValueError("conversion_failed")
        os.replace(output, target)
        if source != target:
            source.unlink()
    return target
