"""yt-dlp API adapter. Network work is called only inside an isolated worker."""

import errno
import json
import subprocess
from functools import lru_cache
from pathlib import Path

import yt_dlp  # noqa: F401 (public adapter reference)

from . import turbo
from .archive import create_zip
from .media import ensure_mp4, executable, hidden_process, mp4_video, verify_selection
from .models import Options
from .paths import cleanup_stage, publish, safe_name, validate_url


class QuietLogger:
    def debug(self, message):
        pass

    info = debug

    def warning(self, message):
        from .diagnostics import diagnostic

        diagnostic("extraction", RuntimeError(message))

    error = warning


@lru_cache(maxsize=1)
def runtime_paths():
    runtimes = {}
    for name, key in (("deno", "deno"), ("qjs", "quickjs")):
        try:
            runtimes[key] = {"path": executable(name)}
        except ValueError:
            continue
    return runtimes


def base_options():
    return {
        "js_runtimes": runtime_paths().copy(),
        "quiet": True,
        "no_warnings": False,
        "logger": QuietLogger(),
        "socket_timeout": 15,
        "windowsfilenames": True,
        "noprogress": True,
        "cachedir": turbo.native_dir(),
        "concurrent_fragment_downloads": turbo.connections(),
        "color": "never",
    }


def summarize(info):
    """Restrict metadata to UI fields; never serialize extraction credentials."""
    keys = (
        "id",
        "title",
        "thumbnail",
        "uploader",
        "channel",
        "extractor_key",
        "duration",
        "upload_date",
        "description",
        "webpage_url",
        "playlist_count",
        "availability",
        "playlist_index",
    )
    result = {key: info.get(key) for key in keys}
    if not result["thumbnail"] and info.get("thumbnails"):
        result["thumbnail"] = info["thumbnails"][-1].get("url")
    result["description"] = str(result["description"] or "")[:3000]
    result["formats"] = [
        {
            key: fmt.get(key)
            for key in (
                "format_id",
                "ext",
                "height",
                "width",
                "fps",
                "vcodec",
                "acodec",
                "language",
                "filesize",
                "filesize_approx",
                "format_note",
                "audio_channels",
            )
        }
        for fmt in info.get("formats", [])
    ]
    result["subtitles"] = list((info.get("subtitles") or {}).keys())
    result["automatic_captions"] = list((info.get("automatic_captions") or {}).keys())
    result["chapters"] = [
        {key: item.get(key) for key in ("title", "start_time", "end_time")}
        for item in info.get("chapters") or []
    ]
    return result


def inspect(url, playlist=False, page=1, page_size=100):
    url = validate_url(url)
    options = base_options() | {"skip_download": True, "noplaylist": not playlist}
    if playlist:
        if not 1 <= int(page) <= 10000:
            raise ValueError("invalid_options")
        options |= {
            "extract_flat": "in_playlist",
            "lazy_playlist": True,
            "playlist_items": f"{(page - 1) * page_size + 1}:{page * page_size}",
            "ignoreerrors": True,
        }
    with turbo.youtube_dl(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("unavailable")
        result = summarize(info)
        if "entries" in info:
            result["entries"] = []
            for index, entry in enumerate(info["entries"], (page - 1) * page_size + 1):
                if not entry:
                    continue
                item = summarize(entry)
                item["playlist_index"] = item.get("playlist_index") or index
                candidate = entry.get("webpage_url") or entry.get("url", "")
                if (
                    not candidate.startswith(("https://", "http://"))
                    and entry.get("ie_key") == "Youtube"
                ):
                    candidate = "https://www.youtube.com/watch?v=" + str(entry.get("id", ""))
                try:
                    item["webpage_url"] = validate_url(candidate)
                except ValueError:
                    item["webpage_url"] = ""
                result["entries"].append(item)
            result["page"] = page
        return result


def format_selector(options):
    if options.kind in {"audio", "subtitles"}:
        if options.kind == "audio" and options.container == "mp3":
            return options.audio_stream or "bestaudio[ext=mp3]/bestaudio/best"
        return options.audio_stream or "bestaudio/best"
    if options.video_stream:
        return options.video_stream + (
            "+" + options.audio_stream
            if options.audio_stream and options.kind != "video_only"
            else ""
        )
    constraint = f"[height<={options.quality}]" if options.quality.isdigit() else ""
    video = "bv" if options.kind == "video_only" else "bv*"
    if options.quality == "compatible":
        if options.kind == "video_only":
            return "bv[vcodec^=avc1]/bv"
        return f"{video}[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/b"
    if options.quality == "small":
        return "wv*+wa/w" if options.kind != "video_only" else "wv"
    if options.kind == "video_only":
        return f"bv{constraint}"
    return f"{video}{constraint}+ba/b{constraint}"


def download_options(options, stage, progress):
    postprocessors = []
    prefix = (
        (safe_name(options.name_prefix, 30).replace("%", "%%") + " - ")
        if options.name_prefix
        else ""
    )
    template = prefix + f"%({options.name_primary}).80s"
    if options.name_secondary != "none":
        template += f" [%({options.name_secondary}).30s]"
    template += ".%(ext)s"
    result = base_options() | {
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        # Keep the destination out of the template: yt-dlp's filename trimming
        # operates on the whole template and can truncate long Windows parents.
        "outtmpl": template,
        "paths": {"home": str(stage)},
        "format": format_selector(options),
        "retries": options.retries,
        "fragment_retries": options.retries,
        "retry_sleep_functions": {"http": lambda n: min(30, 2**n)},
        "progress_hooks": [progress],
        "postprocessor_hooks": [lambda event: progress({"status": "postprocessing"})],
        "writethumbnail": options.thumbnail or options.embed_thumbnail,
        "writeinfojson": False,
        "clean_infojson": True,
        "writedescription": options.description,
        "skip_download": options.kind == "subtitles",
        "writesubtitles": bool(options.subtitles),
        "writeautomaticsub": options.auto_subtitles,
        "subtitleslangs": [v.strip() for v in options.subtitles.split(",") if v.strip()],
        "subtitlesformat": "vtt/best",
        "allow_unplayable_formats": False,
    }
    try:
        result["ffmpeg_location"] = str(Path(executable("ffmpeg", options.ffmpeg)).parent)
    except ValueError:
        if not (options.kind == "audio" and options.container == "original"):
            raise
    if options.rate_limit:
        result["ratelimit"] = options.rate_limit * 1024
    if options.codec != "auto":
        result["format_sort"] = [
            {"h264": "vcodec:h264", "hevc": "vcodec:h265", "av1": "vcodec:av01"}[options.codec]
        ]
    if options.kind == "audio" and options.container != "original":
        codec = "vorbis" if options.container == "ogg" else options.container
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": str(options.bitrate),
            }
        )
    elif options.kind == "audio" and options.container == "original":
        postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": "best"})
    elif options.kind in {"video", "video_only"}:
        # Matroska accepts source codecs such as VP9/Vorbis; normalize the final
        # MP4 after merging so an incompatible audio codec cannot abort the merge.
        result["merge_output_format"] = "mkv" if options.container == "mp4" else options.container
        if options.container != "mp4":
            postprocessors.append(
                {"key": "FFmpegVideoRemuxer", "preferedformat": options.container}
            )
    if options.subtitles and options.subtitle_format == "srt":
        postprocessors.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})
    if options.embed_subtitles:
        if options.container not in {"mp4", "mkv", "mov", "webm"} or options.kind == "subtitles":
            raise ValueError("incompatible_container")
        postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True})
    if options.metadata and options.kind != "subtitles":
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
    if options.embed_thumbnail:
        if options.container not in {"mp3", "m4a", "opus", "flac", "mkv", "mp4", "mov"}:
            raise ValueError("incompatible_container")
        postprocessors.append(
            {"key": "EmbedThumbnail", "already_have_thumbnail": options.thumbnail}
        )
    if options.sponsor_mode != "off":
        categories = set(options.sponsor_categories.split(","))
        postprocessors.insert(
            0, {"key": "SponsorBlock", "categories": categories, "when": "after_filter"}
        )
        if options.sponsor_mode == "remove":
            postprocessors.append({"key": "ModifyChapters", "remove_sponsor_segments": categories})
    result["postprocessors"] = postprocessors
    return result


def organization_folder(info, options):
    field = {
        "channel": "uploader",
        "artist": "artist",
        "album": "album",
        "playlist": "playlist",
        "date": "upload_date",
        "platform": "extractor_key",
        "resolution": "height",
    }.get(options.organization)
    if options.organization == "flat":
        return Path()
    if options.organization == "type":
        return Path(options.kind)
    value = info.get(field) or info.get("_playlist_title") or "unknown"
    if options.organization == "album":
        return Path(safe_name(info.get("artist") or "unknown")) / safe_name(value)
    return Path(safe_name(value))


def recover_merge(stage, options):
    """Both split downloads are complete when FFmpegMerger reports a PP error."""
    from .diagnostics import diagnostic

    inputs = []
    for identifier in (options.video_stream, options.audio_stream):
        matches = [
            p
            for p in stage.iterdir()
            if p.stem == "media.f" + identifier
            and p.suffix.lower() not in {".part", ".ytdl", ".aria2"}
        ]
        if len(matches) != 1:
            raise ValueError("merge_failed")
        inputs.extend(["-i", str(matches[0])])
    output = stage / "recovered.mkv"
    with turbo.conversion_slots:
        proc = subprocess.run(
            [
                executable("ffmpeg", options.ffmpeg),
                "-v",
                "error",
                "-nostdin",
                "-y",
                *inputs,
                "-map",
                "0:V:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                str(output),
            ],
            capture_output=True,
            **hidden_process(),
        )
    if proc.returncode:
        diagnostic("merge", RuntimeError(proc.stderr.decode("utf8", "replace")))
        raise ValueError("merge_failed")
    return output


def download(
    payload,
    emit=lambda event: None,
    *,
    info_cache=None,
    direct_mp4=False,
    aria=False,
    recovery=False,
):
    profile = payload.get("profile", "compatible") if payload.get("lite") else None
    options = Options.from_dict(payload["options"])
    destination = Path(payload["destination"]).resolve()
    identifier = safe_name(payload["id"], 40)
    stage = destination / ".ytdlp-g" / identifier
    stage.mkdir(parents=True, exist_ok=True)

    def hook(event):
        status = event.get("status")
        if status in {"finished", "postprocessing"}:
            emit({"status": "processing", "progress": 0})
        elif status == "downloading":
            total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
            downloaded = event.get("downloaded_bytes", 0)
            turbo.feedback(event.get("speed") or 0)
            emit(
                {
                    "status": "running",
                    "downloaded": downloaded,
                    "total": total,
                    "progress": min(100, downloaded * 100 / total) if total else 0,
                    "speed": event.get("speed") or 0,
                    "eta": event.get("eta") or 0,
                    "estimated": int(not bool(event.get("total_bytes"))),
                }
            )

    extraction = download_options(options, stage, hook)
    if payload.get("lite"):
        extraction["postprocessor_hooks"] = [
            lambda e: emit(
                {"status": "merging" if e.get("postprocessor") == "Merger" else "processing"}
            )
        ]
    if (
        not recovery
        and info_cache
        and options.audio_stream
        and options.video_stream
        and options.container == "mp4"
    ):
        streams = {f["format_id"]: f for f in info_cache.get("formats", [])}
        video = streams.get(options.video_stream, {})
        audio = streams.get(options.audio_stream, {})
        # FFmpegMerger defaults to stream copy. Unsupported video is merged
        # losslessly in MKV before the capability-tested, locally retryable encode.
        direct_mp4 = mp4_video(video.get("vcodec"))
        if profile in {"compatible", "legacy"}:
            direct_mp4 = direct_mp4 and str(audio.get("acodec", "")).startswith(
                ("aac", "mp4a", "opus", "ac3", "eac3", "mp3", "alac")
            )
        elif direct_mp4 and not str(audio.get("acodec", "")).startswith(
            ("aac", "mp4a", "mp3", "ac3", "eac3", "alac")
        ):
            extraction["postprocessor_args"] = {"merger+ffmpeg_o": ["-c:a", "aac", "-b:a", "320k"]}
    if payload.get("lite"):
        extraction["outtmpl"] = "media.%(ext)s"
        extraction["skip_unavailable_fragments"] = False
    if direct_mp4:
        extraction["merge_output_format"] = "mp4"
    if aria:
        n = turbo.connections()
        extraction["external_downloader"] = {
            "http": executable("aria2c"),
            "https": executable("aria2c"),
        }
        extraction["external_downloader_args"] = {
            "aria2c": ["-x", str(n), "-s", str(n), "-k", "1M", "--max-tries=2", "--retry-wait=1"]
        }
    if payload.get("source_index"):
        extraction["playlist_items"] = str(int(payload["source_index"]))
    recovered = None
    with turbo.youtube_dl(extraction) as ydl:
        if info_cache is None or recovery:
            info = ydl.extract_info(validate_url(payload["url"]), download=True)
        else:
            try:
                info = ydl.process_ie_result(info_cache, download=True)
            except yt_dlp.utils.DownloadError as exc:
                if not payload.get("lite") or not direct_mp4 or error_code(exc) != "merge_failed":
                    raise
                recovered = recover_merge(stage, options)
                info = info_cache
        if info and "entries" in info:
            info = next((entry for entry in info["entries"] if entry), None)
        if not info:
            raise ValueError("unavailable")
    if options.kind in {"video", "video_only"} and options.container == "mp4":
        candidates = [
            p
            for p in stage.iterdir()
            if p.suffix.lower()
            in {".mp4", ".mkv", ".webm", ".mov", ".flv", ".avi", ".ts", ".m4v", ".ogv"}
        ]
        if recovered:
            candidates = [recovered]
        if len(candidates) != 1:
            raise ValueError("no_output")
        output = ensure_mp4(
            candidates[0],
            progress=emit,
            require_audio=options.kind == "video",
            preserve_codec=bool(payload.get("lite")),
            profile=profile,
            ffmpeg=options.ffmpeg,
            ffprobe=options.ffprobe,
        )
        if payload.get("selected") and profile != "legacy":
            verify_selection(output, payload["selected"], options.ffprobe)
    if options.info_json:
        # Do not export signed media URLs or request headers from yt-dlp's raw info.
        clean = summarize(info)
        clean.pop("webpage_url", None)
        clean.pop("thumbnail", None)
        json_file = stage / (safe_name(info.get("title") or "download") + ".info.json")
        json_file.write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")
    info["_playlist_title"] = payload.get("playlist_title", "")
    if payload.get("playlist_title"):
        info["playlist"] = payload["playlist_title"]
    files = sorted(
        p
        for p in stage.iterdir()
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp", ".aria2"))
    )
    if payload.get("lite") and options.kind == "video":
        files = [output]
    if not files:
        raise ValueError("no_output")
    folder = destination / organization_folder(info, options)
    prefix = f"{int(payload['playlist_index']):03d} - " if payload.get("playlist_index") else ""
    published = []
    # Source staging remains intact on errors. Publication never replaces a file.
    if options.output_mode in {"normal", "both"}:
        for source in files:
            stem = (info.get("title") or source.stem) if payload.get("lite") else source.stem
            target = folder / (prefix + safe_name(stem, 86) + source.suffix)
            try:
                published.append(
                    str(turbo.disk_pool.submit(publish, source, target, immutable=True).result())
                )
            except OSError as exc:
                exc.stage = "publish"
                raise
    if options.output_mode in {"zip", "both"}:
        emit({"status": "archiving", "progress": 0})
        result = turbo.zip_pool.submit(
            create_zip,
            files,
            folder / (prefix + safe_name(info.get("title", "download")) + ".zip"),
            options.compression,
            progress=emit,
        ).result()
        published.append(str(result))
    cleanup_stage(stage)
    # Sensitive URL query values are never put in progress or diagnostics.
    return {"files": published, "title": info.get("title", ""), "progress": 100}


def error_code(error):
    if isinstance(error, yt_dlp.utils.DownloadCancelled):
        return "cancelled"
    if isinstance(error, subprocess.TimeoutExpired):
        return "process_timeout"
    if isinstance(error, PermissionError):
        return "access_denied"
    if isinstance(error, OSError) and (
        error.errno == errno.ENOSPC or getattr(error, "winerror", 0) == 112
    ):
        return "disk_full"
    text = str(error).lower()
    for marker, code in (
        ("postprocessing:", "merge_failed"),
        ("unable to download", "network_error"),
        ("private", "private_media"),
        ("sign in", "private_media"),
        ("unsupported url", "unsupported_url"),
        ("requested format", "format_unavailable"),
        ("not available", "unavailable"),
        ("removed", "unavailable"),
        ("http error", "network_error"),
        ("timed out", "network_error"),
    ):
        if marker in text:
            return code
    if isinstance(error, ValueError) and str(error) in {
        "lite_no_common",
        "hdr_unsupported",
        "selection_mismatch",
        "extract_failed",
        "transfer_failed",
        "publish_failed",
        "zip_failed",
        "merge_failed",
        "process_timeout",
        "access_denied",
        "disk_full",
        "network_error",
        "private_media",
        "unsupported_url",
        "format_unavailable",
        "invalid_options",
        "invalid_url",
        "invalid_time",
        "dependency_missing",
        "dependency_invalid",
        "conversion_failed",
        "media_invalid",
        "incompatible_container",
        "no_output",
        "unavailable",
        "zip_integrity",
        "invalid_files",
    }:
        return str(error)
    return "operation_failed"
