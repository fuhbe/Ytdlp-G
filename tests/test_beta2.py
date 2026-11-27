import errno
import json
import subprocess
import threading
import zipfile
from fractions import Fraction
from pathlib import Path

import pytest

from ytdlp_g import lite, media, paths
from ytdlp_g.archive import Cancelled
from ytdlp_g.diagnostics import diagnostic


def source(height, fps, codec="av01", dynamic="SDR"):
    return {
        "format_id": f"v-{height}-{fps}-{dynamic}",
        "fps": fps,
        "height": height,
        "vcodec": codec,
        "dynamic_range": dynamic,
        "acodec": "none",
    }


AUDIO = {"format_id": "sound", "vcodec": "none", "acodec": "mp4a"}


def test_rates_are_individually_selectable():
    rates = [None, 24000 / 1001, 24, 25, 30000 / 1001, 30, 48, 50, 60000 / 1001, 60]
    info = {
        "formats": [source(1080, r) for r in rates] + [source(1080, 60, dynamic="HDR10"), AUDIO]
    }
    catalog = lite.quality_catalog(info)
    choices = lite.common_choices([catalog])
    assert len(choices) == len(rates) + 3
    for c in choices:
        if c.get("height"):
            picked = lite.select_format(catalog, c["key"])
            assert picked["fps"] == c["fps"] and picked["hdr"] == c["hdr"]


@pytest.mark.parametrize("count", [10, 50, 100])
def test_order_partial_retry_and_limits(count, tmp_path, monkeypatch):
    playback = [(2160, 60), (1080, 30), (720, 24), (2160, 30), (1080, 60)]
    entries = [
        dict(index=i, url=f"https://example.org/{i}", title=str(i)) for i in range(1, count + 1)
    ]
    plan = dict(
        title="🎞", items=entries, url="https://example.org/list", playlist=True, catalog_version=2
    )
    payload = dict(analysis=plan, quality=lite.BEST, mode="normal", destination=str(tmp_path))
    seen, selected, failing = [], {}, {count // 2, count}
    lock = threading.Lock()

    def inspect(url, *args, **kwargs):
        i = int(url.split("/")[-1])
        with lock:
            seen.append(i)
        if i in failing:
            raise RuntimeError("private video")
        height, fps = playback[(i - 1) % 5]
        return {"formats": [source(360, 24, "avc1"), source(height, fps), AUDIO]}

    def transfer(job, progress, **kw):
        i = job["playlist_index"]
        selected[i] = (job["selected"]["height"], job["selected"]["fps"])
        p = tmp_path / f"{i:03d}.mp4"
        with p.open("xb") as out:
            out.write(bytes([i]))
        progress(dict(status="running", progress=50))
        return {"files": [str(p)]}

    monkeypatch.setattr(lite, "full_info", inspect)
    monkeypatch.setattr(lite, "download", transfer)
    monkeypatch.setattr(
        lite,
        "valid_saved_video",
        lambda path, profile: path.read_bytes() == bytes([int(path.stem)]),
    )
    events = []
    first = lite.download_lite(payload, events.append)
    assert first["status"] == "partial" and [f["index"] for f in first["failures"]] == sorted(
        failing
    )
    percentages = [e["progress"] for e in events]
    assert percentages == sorted(percentages) and max(percentages) < 100
    seen.clear()
    failing.clear()
    second = lite.download_lite(payload)
    assert set(seen) == {count // 2, count} and second["status"] == "complete"
    assert [int(Path(p).stem) for p in second["files"]] == list(range(1, count + 1))
    assert [selected[i] for i in range(1, count + 1)] == (playback * (count // 5))


def test_playlist_cap_reports_lower_choice():
    c = lite.quality_catalog({"formats": [source(2160, 60), source(720, 50), AUDIO]})
    assert lite.select_format(c, "video:max:1080")["height"] == 720
    with pytest.raises(ValueError, match="format_unavailable"):
        lite.select_format(c, "video:max:480")


def test_zip_retry_offline(tmp_path, media_url, monkeypatch):
    payload = dict(url=media_url, quality=lite.BEST, mode="zip", destination=str(tmp_path))
    with monkeypatch.context() as patch:

        def full(*args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left")

        patch.setattr(lite, "create_zip", full)
        result = lite.download_lite(payload)
    assert result["status"] == "zip_failed" and result["archive_error"]["code"] == "disk_full"
    assert Path(result["files"][0]).exists()
    monkeypatch.setattr(lite, "playlist_source", lambda *a: pytest.fail("Network during ZIP retry"))
    result = lite.download_lite(payload)
    with zipfile.ZipFile(result["files"][0]) as archive:
        assert (
            archive.testzip() is None and archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        )


def test_diagnostics_only_emit_known_fields(caplog):
    exc = RuntimeError(
        "HTTP Error 429 https://p/?s=SECRETA Authorization: Bearer SECRETB Cookie: SECRETC"
    )
    result = diagnostic("download", exc, 4, 2)
    assert result["http"] == 429 and result["attempt"] == 2
    assert "SECRET" not in json.dumps(result) + caplog.text


def test_corrupt_cache_uses_conventional_extraction(monkeypatch, tmp_path, media_url):
    plan = lite.inspect_lite(media_url)
    from yt_dlp import YoutubeDL

    original = YoutubeDL.extract_info
    calls = []

    def record(self, *args, **kwargs):
        calls.append(kwargs.get("download"))
        return original(self, *args, **kwargs)

    def broken(self, *args, **kwargs):
        if "media.%(ext)s" == self.params.get("outtmpl", {}).get("default") and not calls:
            raise ValueError("incompatible metadata")
        return process(self, *args, **kwargs)

    process = YoutubeDL.process_ie_result
    monkeypatch.setattr(YoutubeDL, "extract_info", record)
    monkeypatch.setattr(YoutubeDL, "process_ie_result", broken)
    r = lite.download_lite(
        dict(analysis=plan, quality=lite.BEST, mode="normal", destination=str(tmp_path))
    )
    assert r["completed"] == 1 and True in calls


def test_cancel_is_not_an_item_failure(tmp_path, monkeypatch):
    def stop(*a, **k):
        raise Cancelled()

    monkeypatch.setattr(lite, "full_info", stop)
    plan = dict(
        title="list", playlist=True, items=[dict(url="https://example.org/1", index=1, title="1")]
    )
    with pytest.raises(Cancelled):
        lite.download_lite(
            dict(analysis=plan, quality=lite.BEST, destination=str(tmp_path), mode="normal")
        )


@pytest.mark.parametrize(
    "height,fps", [(720, "24"), (1080, "60000/1001"), (1440, "60"), (2160, "60")]
)
def test_delivered_geometry_timestamps_and_audio(height, fps, tmp_path, media_file, media_url):
    name = f"test-{height}.mp4"
    source_file = media_file.parent / name
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=s={height * 16 // 9 // 2 * 2}x{height}:r={fps}",
            "-f",
            "lavfi",
            "-i",
            "sine",
            "-t",
            "0.50",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(source_file),
        ],
        check=True,
    )
    base = media_url.rsplit("/", 1)[0]
    video = source_file.with_name(f"v{height}.mp4")
    audio = source_file.with_name(f"a{height}.m4a")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source_file),
            "-an",
            "-c:v",
            "copy",
            str(video),
            "-vn",
            "-c:a",
            "copy",
            str(audio),
        ],
        check=True,
    )
    manifest = source_file.with_suffix(".mpd")
    manifest.write_text(f'''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT0.5S" minBufferTime="PT0.1S">
    <Period duration="PT0.5S"><AdaptationSet mimeType="video/mp4" contentType="video">
    <Representation id="vid" bandwidth="200000" height="{height}" width="{height * 16 // 9 // 2 * 2}" frameRate="{fps}" codecs="avc1">
    <BaseURL>{base}/{video.name}</BaseURL><SegmentBase/></Representation></AdaptationSet>
    <AdaptationSet mimeType="audio/mp4" contentType="audio"><Representation id="aud" bandwidth="96000" codecs="mp4a.40.2">
    <BaseURL>{base}/{audio.name}</BaseURL><SegmentBase/></Representation></AdaptationSet></Period></MPD>''')
    url = base + "/" + manifest.name
    result = lite.download_lite(
        dict(url=url, quality=lite.BEST, destination=str(tmp_path), mode="normal")
    )
    assert result["status"] == "complete", result
    streams = media.probe(result["files"][0])["streams"]
    v, a = streams
    assert v["height"] == height and abs(lite.frame_rate(v) - float(Fraction(fps))) < 0.01
    assert a["codec_type"] == "audio" and abs(float(v["duration"]) - float(a["duration"])) < 0.06
    assert abs(float(v["start_time"]) - float(a["start_time"])) < 0.06


def test_vfr_hdr_copy_preserves_pts(media_file, media_url, tmp_path):
    original = media_file.parent / "hdr-vfr.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=256x144:r=60",
            "-f",
            "lavfi",
            "-i",
            "sine",
            "-t",
            "1",
            "-vf",
            r"select=if(lt(n\,30)\,1\,not(mod(n\,3)))",
            "-fps_mode",
            "vfr",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "smpte2084",
            "-colorspace",
            "bt2020nc",
            "-pix_fmt",
            "yuv420p10le",
            "-c:v",
            "libx265",
            "-x265-params",
            "pools=1:log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
            "-threads",
            "1",
            "-c:a",
            "aac",
            str(original),
        ],
        check=True,
    )
    url = media_url.rsplit("/", 1)[0] + "/" + original.name
    result = lite.download_lite(
        dict(
            url=url, quality=lite.BEST, mode="normal", profile="original", destination=str(tmp_path)
        )
    )
    assert result["status"] == "complete", result

    def packets(path):
        return subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts,duration",
                "-of",
                "csv=p=0",
                str(path),
            ]
        )

    assert packets(original) == packets(result["files"][0])
    v = media.probe(result["files"][0])["streams"][0]
    assert v["color_transfer"] == "smpte2084" and v["avg_frame_rate"] != v["r_frame_rate"]


def test_cleanup_failure_does_not_invalidate_output(monkeypatch, tmp_path, media_url):
    def locked(path):
        raise PermissionError("locked")

    monkeypatch.setattr(paths.shutil, "rmtree", locked)
    result = lite.download_lite(
        dict(url=media_url, quality=lite.BEST, mode="normal", destination=str(tmp_path))
    )
    assert result["status"] == "complete" and Path(result["files"][0]).exists()


def test_encoder_failure_reuses_local_source(monkeypatch, tmp_path):
    original = tmp_path / "source.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=256x144:r=25",
            "-f",
            "lavfi",
            "-i",
            "sine",
            "-t",
            "0.4",
            "-c:v",
            "ffv1",
            "-c:a",
            "aac",
            str(original),
        ],
        check=True,
    )
    monkeypatch.setattr(media, "working_encoders", lambda *a: ["h264_nvenc", "libx264"])
    monkeypatch.setitem(media.ENCODER_ARGS, "h264_nvenc", ["-invalid-test-option", "1"])
    result = media.ensure_mp4(original)
    assert [s["codec_name"] for s in media.probe(result)["streams"]] == ["h264", "aac"]


def test_external_downloader_failure_retries_native(monkeypatch, media_url, tmp_path):
    native = lite.download
    attempts = []

    def fail_external(*args, **kwargs):
        attempts.append(kwargs["aria"])
        if kwargs["aria"]:
            raise RuntimeError("aria2c exited with code 1")
        return native(*args, **kwargs)

    monkeypatch.setattr(lite, "use_aria", lambda *a: True)
    monkeypatch.setattr(lite, "download", fail_external)
    r = lite.download_lite(
        dict(url=media_url, quality=lite.BEST, mode="normal", destination=str(tmp_path))
    )
    assert r["status"] == "complete" and attempts == [True, False]


def test_long_unicode_zip_including_suffix(tmp_path, monkeypatch):
    from ytdlp_g.archive import create_zip

    title = paths.safe_name("🎞️ Música — " * 25)
    media_path = tmp_path / (title + ".mp4")
    media_path.write_bytes(b"sample")
    target = tmp_path / "other" / "arquivo.mp4"
    link = paths.os.link

    def cross_volume(source, dest):
        if Path(source) == media_path:
            raise OSError(errno.EXDEV, "cross-device")
        return link(source, dest)

    monkeypatch.setattr(paths.os, "link", cross_volume)
    result = paths.publish(media_path, target, immutable=True)
    assert result.read_bytes() == media_path.read_bytes()
    with zipfile.ZipFile(create_zip([media_path], tmp_path / "playlist.zip")) as z:
        assert z.namelist()[0].endswith(".mp4") and z.testzip() is None


def test_hundred_real_mp3_entries_without_analysis(media_url, media_file, tmp_path):
    audio = media_file.parent / "short.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(media_file),
            "-vn",
            "-t",
            "0.1",
            "-c:a",
            "libmp3lame",
            str(audio),
        ],
        check=True,
    )
    page = media_file.parent / "hundred.html"
    page.write_text(
        "<html><title>List</title>"
        + "".join(f'<video src="short.mp3?item={i}"></video>' for i in range(100))
        + "</html>"
    )
    result = lite.download_lite(
        dict(
            url=media_url.rsplit("/", 1)[0] + "/hundred.html",
            quality=lite.MP3,
            mode="zip",
            destination=str(tmp_path),
        )
    )
    assert result["completed"] == 100 and result["status"] == "complete", result
    with zipfile.ZipFile(result["files"][0]) as z:
        assert len(z.infolist()) == 100 and z.testzip() is None
        assert all(
            z.read(n) == audio.read_bytes() and n.startswith(f"{i:03d} - ")
            for i, n in enumerate(z.namelist(), 1)
        )
