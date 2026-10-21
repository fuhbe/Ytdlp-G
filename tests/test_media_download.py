import json
import subprocess
import zipfile

import pytest

from ytdlp_g.downloader import (
    download,
    download_options,
    error_code,
    format_selector,
    inspect,
    summarize,
)
from ytdlp_g.media import convert, ffmpeg_args, parse_time, probe
from ytdlp_g.models import Options


@pytest.mark.parametrize(
    "text,seconds", [("00:00:00", 0), ("01:02:03.5", 3723.5), ("00:00:10", 10)]
)
def test_time_parse(text, seconds):
    assert parse_time(text) == seconds


@pytest.mark.parametrize(
    "text", ["nan", "00:70:00", "-1:00:00", "0:0:nan", "00:00:inf", "1; rm -rf /", "00:00:-1"]
)
def test_time_parse_rejects(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_ffmpeg_paths_are_single_arguments_and_options_validated(tmp_path, media_file):
    source = tmp_path / "file; echo vulnerable $(x).mp4"
    argv = ffmpeg_args(source, tmp_path / "output.mp4", "mp4")
    assert str(source.resolve()) in argv
    assert "-n" in argv
    with pytest.raises(ValueError):
        ffmpeg_args(media_file, tmp_path / "o", "mp4;whoami")
    with pytest.raises(ValueError):
        ffmpeg_args(media_file, tmp_path / "o", "mp4", height="720;bad")
    with pytest.raises(ValueError):
        ffmpeg_args(media_file, tmp_path / "o", "webm", codec="h264")


def test_conversion_mp3_remux_and_precise_cut(tmp_path, media_file):
    original = media_file.read_bytes()
    events = []
    result = convert(
        {"source": str(media_file), "destination": str(tmp_path), "container": "mp3"}, events.append
    )
    assert probe(result["files"][0])["streams"][0]["codec_name"] == "mp3"
    assert events
    remux = convert(
        {"source": str(media_file), "destination": str(tmp_path), "container": "mkv", "remux": True}
    )
    assert any(stream["codec_name"] == "mpeg4" for stream in probe(remux["files"][0])["streams"])
    cut = convert(
        {
            "source": str(media_file),
            "destination": str(tmp_path),
            "container": "mp4",
            "start": "00:00:00.5",
            "end": "00:00:01.5",
            "precise": True,
        }
    )
    duration = float(probe(cut["files"][0])["format"]["duration"])
    assert abs(duration - 1) < 0.15
    assert media_file.read_bytes() == original
    with pytest.raises(ValueError, match="invalid_time"):
        convert(
            {
                "source": str(media_file),
                "destination": str(tmp_path),
                "container": "mp4",
                "start": "00:00:02",
                "end": "00:00:01",
            }
        )


def test_failed_remux_preserves_source_and_no_final_output(tmp_path, media_file):
    with pytest.raises(ValueError, match="conversion_failed"):
        convert(
            {
                "source": str(media_file),
                "destination": str(tmp_path),
                "container": "webm",
                "remux": True,
            }
        )
    assert media_file.exists()
    assert not list(tmp_path.iterdir())


def test_inspection_fixture_filters_headers_and_parses_formats():
    fixture = {
        "title": "Test",
        "http_headers": {"Authorization": "secret"},
        "formats": [
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize_approx": 1000,
                "url": "https://private/?token=secret",
            }
        ],
        "subtitles": {"pt": []},
        "automatic_captions": {"en": []},
        "chapters": [{"title": "One", "start_time": 0, "end_time": 3}],
    }
    result = summarize(fixture)
    assert result["formats"][0]["height"] == 1080
    assert result["automatic_captions"] == ["en"]
    assert result["subtitles"] == ["pt"]
    assert "secret" not in json.dumps(result)


def test_playlist_extraction_is_lazy_paged_and_skips_unavailable(monkeypatch):
    observed = {}

    class FakeYDL:
        def __init__(self, options):
            observed.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, *args, **kwargs):
            return {
                "title": "List",
                "playlist_count": 400,
                "entries": iter([None, {"title": "One", "url": "https://example.org/1"}]),
            }

    monkeypatch.setattr("ytdlp_g.downloader.yt_dlp.YoutubeDL", FakeYDL)
    result = inspect("https://example.org/playlist", playlist=True, page=2)
    assert observed["playlist_items"] == "101:200"
    assert observed["lazy_playlist"] is True
    assert len(result["entries"]) == 1


def test_real_local_http_inspection_video_download_and_zip(tmp_path, media_url):
    info = inspect(media_url)
    assert info["formats"]
    events = []
    result = download(
        {
            "id": "video",
            "url": media_url,
            "destination": str(tmp_path),
            "options": Options(output_mode="both").to_dict(),
        },
        events.append,
    )
    from pathlib import Path

    files = [Path(path) for path in result["files"]]
    assert any(path.suffix == ".mp4" for path in files)
    archive = next(path for path in files if path.suffix == ".zip")
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert any(name.endswith(".mp4") for name in zipped.namelist())
    assert any(event["status"] == "running" for event in events)
    assert any(event["status"] == "archiving" for event in events)
    assert all(path.exists() for path in files)


def test_real_audio_extraction_local_http(tmp_path, media_url):
    result = download(
        {
            "id": "audio",
            "url": media_url,
            "destination": str(tmp_path),
            "options": Options(kind="audio", container="mp3", bitrate=320).to_dict(),
        }
    )
    assert any(
        probe(path)["streams"][0]["codec_name"] == "mp3"
        for path in result["files"]
        if path.endswith(".mp3")
    )


def test_format_options_and_errors(tmp_path):
    options = Options(
        quality="1080",
        subtitles="pt,en",
        auto_subtitles=True,
        embed_subtitles=True,
        sponsor_mode="remove",
    )
    settings = download_options(options, tmp_path, lambda data: None)
    assert "[height<=1080]" in settings["format"]
    assert settings["subtitleslangs"] == ["pt", "en"]
    assert settings["continuedl"] and settings["overwrites"] is False
    assert any(pp["key"] == "ModifyChapters" for pp in settings["postprocessors"])
    assert "SponsorBlock" not in json.dumps(
        download_options(Options(), tmp_path, lambda data: None)["postprocessors"]
    )
    assert format_selector(Options(kind="audio")) == "bestaudio/best"
    assert error_code(RuntimeError("This video is private")) == "private_media"
    assert error_code(subprocess.TimeoutExpired("ffmpeg", 1)) == "operation_failed"


def test_visual_naming_is_safe_template_not_user_code(tmp_path):
    options = Options(
        name_primary="artist", name_secondary="upload_date", name_prefix="CON:%(bad)s"
    )
    settings = download_options(options, tmp_path, lambda data: None)
    template = settings["outtmpl"]
    assert "%%(bad)s" in template
    assert "%(artist)" in template and "%(upload_date)" in template
    assert "/../" not in template


def test_destination_is_separate_from_filename_template(tmp_path):
    stage = tmp_path / ("long-directory-" * 8) / ".ytdlp-g" / "job"
    options = download_options(Options(), stage, lambda data: None)
    assert options["paths"]["home"] == str(stage)
    assert options["outtmpl"] == "%(title).80s [%(id).30s].%(ext)s"
    assert "trim_file_name" not in options
