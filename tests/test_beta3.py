import errno
import hashlib
import subprocess
from pathlib import Path

import pytest

from ytdlp_g import lite, media, offline
from ytdlp_g.settings import Settings
from ytdlp_g.ui.lite_window import LiteWindow


def ffmpeg(*args):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True, capture_output=True
    )


def fixture(path, video, audio="aac", size="160x90", fps="25", extra=()):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s={size}:r={fps}",
        "-f",
        "lavfi",
        "-i",
        "sine=r=48000",
        "-t",
        "0.48",
        "-threads",
        "2",
        "-c:v",
        video,
        *extra,
        "-ac",
        "2",
        "-c:a",
        audio,
        path,
    )
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def stream_digest(path, stream):
    return subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:" + stream,
            "-c",
            "copy",
            "-f",
            "hash",
            "-",
        ]
    )


@pytest.mark.parametrize(
    "video,audio,extra",
    [
        ("libaom-av1", "aac", ["-cpu-used", "8", "-row-mt", "1"]),
        ("libvpx-vp9", "libopus", ["-deadline", "realtime", "-cpu-used", "8"]),
        ("libx265", "ac3", ["-x265-params", "pools=1:log-level=error"]),
        ("libx264", "aac", ["-pix_fmt", "yuv422p10le"]),
        ("libx264", "aac", ["-profile:a", "aac_main"]),
    ],
)
def test_convert_existing_codecs(tmp_path, video, audio, extra):
    av1 = video == "libaom-av1"
    if "aac_main" in extra:
        # FFmpeg 8 still decodes AAC Main but its native encoder only produces LC.
        source = tmp_path / "vídeo.mkv"
        sound = Path(__file__).parent / "fixtures" / "aac-main.m4a"
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x90:r=25",
            "-i",
            sound,
            "-t",
            "0.48",
            "-c:v",
            video,
            "-c:a",
            "copy",
            source,
        )
        assert media.tracks(media.probe(source))[1]["profile"] == "Main"
    else:
        source = fixture(
            tmp_path / "vídeo.mkv", video, audio, "1920x1080" if av1 else "160x90", extra=extra
        )
    if av1:
        mp4 = source.with_suffix(".mp4")
        ffmpeg("-i", source, "-c", "copy", mp4)
        source = mp4
    original = digest(source)
    result = offline.convert_batch(
        dict(inputs=[str(source)], destination=str(tmp_path / "Convertidos")), lambda e: None
    )
    assert not result["failures"], result
    output = Path(result["files"][0])
    info = media.probe(output)
    v, a = media.tracks(info)
    assert (
        media.fits_profile(info, "compatible")
        and v["height"] == (1080 if av1 else 90)
        and lite.frame_rate(v) == 25
    )
    assert (a["codec_name"], a["profile"], a["channels"], a["sample_rate"]) == (
        "aac",
        "LC",
        2,
        "48000",
    )
    assert v["codec_tag_string"] == "avc1" and digest(source) == original
    ffmpeg("-xerror", "-i", output, "-f", "null", "-")
    if audio == "aac" and "aac_main" not in extra:
        assert stream_digest(source, "a") == stream_digest(output, "a")
    if "aac_main" in extra:
        assert stream_digest(source, "v") == stream_digest(output, "v")


@pytest.mark.parametrize("size,rate", [("1920x1080", 60), ("320x240", 24)])
def test_legacy_preserves_or_caps(tmp_path, size, rate):
    source = fixture(tmp_path / "in.mp4", "libx264", size=size, fps=rate)
    result = media.ensure_mp4(source, profile="legacy", output_path=tmp_path / "out.mp4")
    info = media.probe(result)
    assert media.fits_profile(info, "legacy")
    v, _ = media.tracks(info)
    assert (v["height"], round(lite.frame_rate(v))) == ((720, 30) if rate == 60 else (240, 24))
    ffmpeg("-xerror", "-i", result, "-f", "null", "-")


def test_offline_skip_copy_collision_and_errors(tmp_path, monkeypatch):
    source = fixture(tmp_path / "local.mp4", "libx264")
    dest = tmp_path / "Convertidos"
    job = dict(inputs=[str(tmp_path)], destination=str(dest), recursive=True)
    assert offline.convert_batch(job, lambda e: None)["skipped"] == [str(source)]
    job["skip"] = False
    for _ in range(2):
        r = offline.convert_batch(job, lambda e: None)
        assert len(r["files"]) == 1 and digest(Path(r["files"][0])) == digest(source)
    assert len(list(dest.glob("*.mp4"))) == 2

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(offline, "publish", full)
    assert (
        offline.convert_batch(job, lambda e: None)["failures"][0]["diagnostic"]["code"]
        == "disk_full"
    )


def test_quality_preferences_and_recovery_keys():
    avc = dict(
        format_id="h", vcodec="avc1", acodec="aac", width=1920, height=1080, fps=60, vbr=5000
    )
    av1 = avc | dict(format_id="av", vcodec="av01")
    for profile, expected in [("compatible", "h"), ("original", "av")]:
        c = lite.quality_catalog({"formats": [avc, av1]}, profile)
        assert lite.select_format(c, lite.BEST)["video_stream"] == expected
    for difference in (dict(vbr=2000), dict(fps=30), dict(height=720)):
        c = lite.quality_catalog({"formats": [avc | difference, av1]})
        assert lite.select_format(c, lite.BEST)["video_stream"] == "av"
    assert len({lite.job_id("url", lite.BEST, "zip", p) for p in media.PROFILES}) == 3


def test_profile_migration_translation_and_audio_visibility(qapp, tmp_path):
    settings = Settings(tmp_path / "old.json")
    settings.load({"performance": {}})
    window = LiteWindow(settings)
    window.show()
    assert window.profile.currentData() == "compatible"
    for lang in ("pt-BR", "en", "es"):
        window.tr.set_language(lang)
        assert window.profile.itemText(0) == window.tr("profile_compatible")
    window.profile.setCurrentIndex(1)
    window.kind.setCurrentIndex(window.kind.findData("audio"))
    assert not window.profile.isVisible()
    assert Settings(settings.path).values["video_profile"] == "original"
    window.close()


def test_hdr_to_sdr_validated(tmp_path):
    source = fixture(
        tmp_path / "hdr.mp4",
        "libx265",
        extra=[
            "-pix_fmt",
            "yuv420p10le",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "smpte2084",
            "-colorspace",
            "bt2020nc",
            "-x265-params",
            "pools=1:log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
        ],
    )
    target = tmp_path / "sdr.mp4"
    filters = subprocess.check_output(["ffmpeg", "-hide_banner", "-filters"], text=True)
    if " zscale " not in filters or " tonemap " not in filters:
        with pytest.raises(ValueError, match="hdr_unsupported"):
            media.ensure_mp4(source, profile="compatible", output_path=target)
        assert not target.exists()
        return
    events = []
    media.ensure_mp4(source, profile="compatible", output_path=target, progress=events.append)
    v, _ = media.tracks(media.probe(target))
    assert [v[k] for k in ("color_primaries", "color_transfer", "color_space")] == ["bt709"] * 3
    assert v["pix_fmt"] == "yuv420p" and any(e["status"] == "tone_mapping" for e in events)
    ffmpeg("-xerror", "-i", target, "-f", "null", "-")


def test_offline_dialog_retries_only_failed(qapp, tmp_path):
    from test_ui import wait_until

    from ytdlp_g.ui.offline import OfflineDialog

    source = fixture(tmp_path / "ok.mp4", "libx264")
    missing = tmp_path / "missing.mp4"
    main = LiteWindow(Settings(tmp_path / "prefs.json"))
    dialog = OfflineDialog(main)
    dialog.add([str(source), str(missing)])
    dialog.skip.setChecked(False)
    dialog.start(False)
    wait_until(qapp, lambda: dialog.task is None)
    assert dialog.failed == [str(missing)]
    missing.write_bytes(source.read_bytes())
    dialog.start(True)
    wait_until(qapp, lambda: dialog.task is None)
    assert not dialog.failed and len(list((tmp_path / "Convertidos").glob("*.mp4"))) == 2
    dialog.close()
    main.close()


def test_level_matches_coded_geometry_and_frame_rate():
    v = dict(width=1920, height=1080, avg_frame_rate="60/1")
    assert not media.level_fits(v | {"level": 41})
    assert media.level_fits(v | {"level": 42})
    uhd = v | {"width": 3840, "height": 2160}
    assert not media.level_fits(uhd | {"level": 51})
    assert media.level_fits(uhd | {"level": 52})


def test_cancel_offline_batch(qapp, tmp_path):
    from test_ui import wait_until

    from ytdlp_g.tasks import Task

    source = fixture(tmp_path / "source.mp4", "libx264", size="1920x1080", fps="60")
    dest = tmp_path / "out"
    job = Task("offline_batch", dict(inputs=[str(source)], destination=str(dest), profile="legacy"))
    errors = []
    job.error.connect(errors.append)
    job.start()
    wait_until(qapp, lambda: bool(job.process.processId()))
    job.cancel()
    wait_until(qapp, lambda: bool(errors))
    assert errors[-1]["code"] == "cancelled" and source.exists() and not list(dest.glob("*.mp4"))
