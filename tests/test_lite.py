"""The compact app must offer real streams and exercise both real output paths."""

import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest
import yt_dlp
from test_ui import wait_until

from ytdlp_g import lite
from ytdlp_g.media import probe
from ytdlp_g.settings import Settings
from ytdlp_g.ui.lite_window import LiteWindow


def formats(height=720, bitrate=128):
    return {
        "title": "Example",
        "formats": [
            {"format_id": "v", "ext": "mp4", "height": height, "vcodec": "avc1", "acodec": "none"},
            {
                "format_id": "a",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": bitrate,
            },
            {
                "format_id": "locked",
                "ext": "mp4",
                "height": 2160,
                "vcodec": "avc1",
                "acodec": "aac",
                "has_drm": True,
            },
            {
                "format_id": "storyboard",
                "ext": "mhtml",
                "height": 1080,
                "vcodec": "images",
                "acodec": "none",
            },
        ],
    }


def test_catalog_only_mp4_with_sound_and_mp3():
    catalog = lite.quality_catalog(formats())
    assert set(catalog) == {"video:mp4:720:?:?", "audio:mp3:convert"}
    assert catalog["video:mp4:720:?:?"]["video_stream"] == "v"
    assert catalog["video:mp4:720:?:?"]["audio_stream"] == "a"
    assert all(c["container"] != "mp3" for c in catalog.values() if not c.get("conversion"))


def test_playlist_offers_individual_best_and_maximum_resolutions():
    choices = lite.common_choices(
        [lite.quality_catalog(formats()), lite.quality_catalog(formats(480, 96))]
    )
    assert [c["key"] for c in choices] == [lite.BEST, "video:max:720", "video:max:480", lite.MP3]
    assert "audio_stream" not in choices[0]


def test_playlist_checks_every_item_and_counts_private_entries(monkeypatch):
    first = formats()
    first["url"] = "https://example.org/one"
    second = formats(480, 96)
    second["url"] = "https://example.org/two"
    extracted = []

    class YDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=False):
            extracted.append(url)
            return (
                {"title": "List", "entries": [first, None, second]}
                if url.endswith("/list")
                else {first["url"]: first, second["url"]: second}[url]
            )

    monkeypatch.setattr(yt_dlp, "YoutubeDL", YDL)
    result = lite.inspect_lite("https://example.org/list")
    assert len(extracted) == 1
    assert [item["index"] for item in result["items"]] == [1, 2, 3]
    assert result["skipped"] == 1
    assert [c["key"] for c in result["choices"]] == [
        lite.BEST,
        "video:max:720",
        "video:max:480",
        lite.MP3,
    ]


def test_quality_disappearing_is_reported_without_fallback(monkeypatch, tmp_path):
    analysis = {
        "choices": [{"key": "video:mp4:720:?:?"}],
        "items": [{"url": "https://example.org/one", "title": "one", "index": 1}],
        "title": "one",
        "playlist": False,
    }

    class YDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, *args, **kwargs):
            return formats(480)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", YDL)
    result = lite.download_lite(
        {
            "analysis": analysis,
            "quality": "video:mp4:720:?:?",
            "mode": "normal",
            "destination": str(tmp_path),
        }
    )
    assert result["failed"] == 1 and result["failures"][0]["code"] == "format_unavailable"
    assert list(tmp_path.iterdir()) == []


def test_real_link_mp3_audio_and_mp4_zip_only(media_url, tmp_path):
    analysis = lite.inspect_lite(media_url)
    assert {c["key"] for c in analysis["choices"]} == {lite.BEST, lite.MP3, "video:mp4:90:15.0:SDR"}
    audio = lite.download_lite(
        {
            "analysis": analysis,
            "quality": "audio:mp3:convert",
            "mode": "normal",
            "destination": str(tmp_path / "audio"),
        }
    )
    streams = probe(audio["files"][0])["streams"]
    assert len(streams) == 1 and streams[0]["codec_name"] == "mp3"
    zipped = lite.download_lite(
        {
            "analysis": analysis,
            "quality": lite.BEST,
            "mode": "zip",
            "destination": str(tmp_path / "zip"),
        }
    )
    assert len(zipped["files"]) == 1
    with zipfile.ZipFile(zipped["files"][0]) as archive:
        assert len(archive.namelist()) == 1 and archive.testzip() is None
    assert not list((tmp_path / "zip").rglob("*.mp4"))


def test_zip_failure_preserves_downloaded_sources(media_url, tmp_path, monkeypatch):
    analysis = lite.inspect_lite(media_url)

    def failed_zip(*args, **kwargs):
        raise ValueError("zip_integrity")

    monkeypatch.setattr(lite, "create_zip", failed_zip)
    result = lite.download_lite(
        {
            "analysis": analysis,
            "quality": lite.BEST,
            "mode": "zip",
            "destination": str(tmp_path),
        }
    )
    assert result["archive_error"]["code"] == "zip_integrity"
    assert list(tmp_path.rglob("*.mp4"))


def test_compact_gui_real_download_and_live_language(qapp, tmp_path, media_url):
    settings = Settings(tmp_path / "settings.json")
    settings.values["destination"] = str(tmp_path / "outputs")
    window = LiteWindow(settings)
    window.smoke_mode = True
    window.show()
    window.url.setText(media_url)
    assert window.output.count() == 2 and window.download_button.isEnabled()
    window.analyze()
    wait_until(qapp, lambda: not window.tasks)
    assert window.analysis is not None, window.status.text()
    assert window.quality.count() == 2 and window.quality.currentData() == lite.BEST
    window.kind.setCurrentIndex(window.kind.findData("audio"))
    assert "MP3" in window.quality.currentText()
    for language in ("es", "en", "pt-BR"):
        window.language.setCurrentIndex(window.language.findData(language))
        assert window.url.text() == media_url
        assert window.quality.currentData() == "audio:mp3:convert"
    window.start_download()
    wait_until(qapp, lambda: not window.tasks)
    assert window.last_result and window.last_result["completed"] == 1, window.status.text()
    assert Path(window.last_result["files"][0]).suffix == ".mp3"
    assert window.size().width() == 600 and window.size().height() == 440
    assert window.download_button.geometry().height() > 0
    window.quality.setCurrentIndex(window.quality.findData("audio:mp3:convert"))
    for language in ("es", "en", "pt-BR"):
        window.language.setCurrentIndex(window.language.findData(language))
        assert window.quality.currentData() == "audio:mp3:convert"
        assert "MP3" in window.quality.currentText()
    window.start_download()
    wait_until(qapp, lambda: not window.tasks)
    assert Path(window.last_result["files"][0]).suffix == ".mp3"
    window.url.setText("https://example.org/new")
    assert window.analysis is None and window.download_button.isEnabled()
    window.close()


@pytest.mark.parametrize(
    "mode,quality,suffix",
    [
        ("normal", lite.BEST, ".mp4"),
        ("zip", lite.BEST, ".mp4"),
        ("normal", "audio:mp3:convert", ".mp3"),
        ("zip", "audio:mp3:convert", ".mp3"),
    ],
)
def test_real_embedded_playlist_with_two_entries(
    media_file, media_url, tmp_path, mode, quality, suffix
):
    page = media_file.parent / "lite-playlist.html"
    page.write_text(
        '<html><head><title>Two videos</title></head><body><video src="sample.mp4" controls></video><video src="sample.mp4?second" controls></video></body></html>'
    )
    analysis = lite.inspect_lite(media_url.rsplit("/", 1)[0] + "/lite-playlist.html")
    assert analysis["playlist"] and len(analysis["items"]) == 2
    assert [i["source_index"] for i in analysis["items"]] == [1, 2]
    result = lite.download_lite(
        {"analysis": analysis, "quality": quality, "mode": mode, "destination": str(tmp_path)}
    )
    assert result["completed"] == 2 and result["failed"] == 0
    if mode == "normal":
        assert len(result["files"]) == 2
        assert [Path(f).name[:3] for f in result["files"]] == ["001", "002"]
    else:
        assert len(result["files"]) == 1
        with zipfile.ZipFile(result["files"][0]) as archive:
            assert len(archive.namelist()) == 2 and archive.testzip() is None
            assert all(name.endswith(suffix) for name in archive.namelist())
        assert not list(tmp_path.rglob(suffix))


def test_mp3_conversion_requires_audio_and_excludes_drm():
    info = formats()
    info["formats"] = [f for f in info["formats"] if f["format_id"] != "a"]
    assert "audio:mp3:convert" not in lite.quality_catalog(info)


def test_mp3_is_common_across_different_native_codecs():
    aac, opus = formats(), formats(480)
    opus["formats"][1].update(acodec="opus", ext="webm")
    choices = lite.common_choices([lite.quality_catalog(aac), lite.quality_catalog(opus)])
    assert lite.MP3 in {c["key"] for c in choices}


def test_real_mp3_conversion_has_320kbps_audio_only(media_url, tmp_path):
    analysis = lite.inspect_lite(media_url)
    result = lite.download_lite(
        {
            "analysis": analysis,
            "quality": "audio:mp3:convert",
            "mode": "normal",
            "destination": str(tmp_path),
        }
    )
    streams = probe(result["files"][0])["streams"]
    assert len(streams) == 1 and streams[0]["codec_name"] == "mp3"
    assert int(streams[0]["bit_rate"]) == 320000
    assert 1.9 < float(streams[0]["duration"]) < 2.2


def test_existing_mp3_preserves_original_without_lossy_reencoding(media_file, media_url, tmp_path):
    source = media_file.parent / "original.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(media_file),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(source),
        ],
        check=True,
    )
    analysis = lite.inspect_lite(media_url.rsplit("/", 1)[0] + "/original.mp3")
    result = lite.download_lite(
        {
            "analysis": analysis,
            "quality": "audio:mp3:convert",
            "mode": "normal",
            "destination": str(tmp_path),
        }
    )
    assert (
        hashlib.sha256(Path(result["files"][0]).read_bytes()).digest()
        == hashlib.sha256(source.read_bytes()).digest()
    )


def test_open_menus_stay_readable_with_dark_system_palette(qapp, tmp_path):
    from PySide6.QtGui import QColor, QPalette

    original = qapp.palette()
    dark = QPalette(original)
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button):
        dark.setColor(role, QColor("#121212"))
    dark.setColor(QPalette.ColorRole.Text, QColor("#dddddd"))
    dark.setColor(QPalette.ColorRole.WindowText, QColor("#dddddd"))
    qapp.setPalette(dark)
    window = None
    try:
        window = LiteWindow(Settings(tmp_path / "settings.json"))
        window.show()
        # Populate quality with the same real source-derived choices used by UI.
        window.analysis = {"choices": lite.common_choices([lite.quality_catalog(formats())])}
        window.kind.setCurrentIndex(window.kind.findData("audio"))
        window.refresh_choices()
        for combo in (window.kind, window.quality, window.output, window.language):
            combo.showPopup()
            qapp.processEvents()
            view = combo.view()
            image = view.viewport().grab().toImage()
            unselected = view.visualRect(
                combo.model().index(1 if combo.count() > 1 and combo.currentIndex() == 0 else 0, 0)
            )
            # The actual rendered unselected row must be light even on dark OS.
            background = image.pixelColor(image.width() - 12, unselected.center().y())
            if combo.count() > 1:
                assert background.lightness() > 200
            palette = view.palette()
            assert palette.color(QPalette.ColorRole.Text).lightness() < 100
            assert palette.color(QPalette.ColorRole.HighlightedText).lightness() > 200
            assert palette.color(QPalette.ColorRole.Highlight).lightness() < 150
            combo.hidePopup()
        assert window.width() == 600 and window.height() == 440
    finally:
        if window:
            window.close()
        qapp.setPalette(original)


def test_video_without_audio_is_not_offered():
    info = formats()
    info["formats"] = [info["formats"][0]]
    assert lite.quality_catalog(info) == {}


def test_webm_and_mixed_codec_playlists_offer_mp4_at_real_resolutions():
    webm = formats()
    webm["formats"][0].update(ext="webm", vcodec="vp9")
    webm["formats"][1].update(ext="webm", acodec="opus")
    catalogs = [lite.quality_catalog(formats()), lite.quality_catalog(webm)]
    assert {c["key"] for c in lite.common_choices(catalogs)} == {
        lite.BEST,
        "video:max:720",
        lite.MP3,
    }


def test_real_separate_webm_video_and_audio_become_mp4(media_file, media_url, tmp_path):
    """Exercise actual adaptive merging + incompatible codecs, without YouTube availability."""
    source_dir = media_file.parent
    for name, args in [
        ("separate-video.webm", ["-an", "-c:v", "libvpx-vp9"]),
        ("separate-audio.webm", ["-vn", "-c:a", "libvorbis"]),
    ]:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(media_file), *args, str(source_dir / name)],
            check=True,
        )
    base = media_url.rsplit("/", 1)[0]
    (source_dir / "adaptive.mpd").write_text(f"""<?xml version="1.0"?>
    <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT2S" minBufferTime="PT1S">
      <Period duration="PT2S">
        <AdaptationSet mimeType="video/webm" contentType="video"><Representation id="v" bandwidth="200000" width="160" height="90" codecs="vp9"><BaseURL>{base}/separate-video.webm</BaseURL><SegmentBase/></Representation></AdaptationSet>
        <AdaptationSet mimeType="audio/webm" contentType="audio"><Representation id="a" bandwidth="128000" codecs="vorbis" audioSamplingRate="44100"><BaseURL>{base}/separate-audio.webm</BaseURL><SegmentBase/></Representation></AdaptationSet>
      </Period>
    </MPD>""")
    analysis = lite.inspect_lite(base + "/adaptive.mpd")
    assert any(c.get("height") == 90 for c in analysis["choices"])
    result = lite.download_lite(
        {
            "analysis": analysis,
            "quality": lite.BEST,
            "mode": "normal",
            "destination": str(tmp_path),
        }
    )
    assert len(result["files"]) == 1 and result["files"][0].endswith(".mp4")
    streams = probe(result["files"][0])["streams"]
    assert {s["codec_type"] for s in streams} == {"video", "audio"}
    video = next(s for s in streams if s["codec_type"] == "video")
    assert video["height"] == 90 and video["codec_name"] == "vp9"
    assert next(s for s in streams if s["codec_type"] == "audio")["codec_name"] == "aac"
