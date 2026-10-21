import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ytdlp_g.archive import Cancelled, create_zip
from ytdlp_g.database import Database
from ytdlp_g.i18n import CATALOGS, translate
from ytdlp_g.models import BUILTIN_PROFILES, Options
from ytdlp_g.paths import publish, safe_name, validate_url
from ytdlp_g.scheduler import tick
from ytdlp_g.settings import Settings


def test_translation_parity_fallback_and_format_placeholders():
    baseline = set(CATALOGS["pt-BR"])
    for language, catalog in CATALOGS.items():
        assert set(catalog) == baseline, language
        assert all(value.strip() for value in catalog.values())
        for key in baseline:
            assert set(re.findall(r"\{(\w+)\}", catalog[key])) == set(
                re.findall(r"\{(\w+)\}", CATALOGS["pt-BR"][key])
            )
    assert translate("unknown", "download") == "Baixar"
    assert translate("es", "missing") == "missing"


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "ftp://server",
        "javascript:alert(1)",
        "https://user:password@example.com",
        "https://",
        "https://example.com:bad",
        "https://example.com/\nsecret",
    ],
)
def test_reject_invalid_urls(value):
    with pytest.raises(ValueError, match="invalid_url"):
        validate_url(value)


def test_url_normalization_keeps_media_query():
    assert (
        validate_url(" HTTPS://Example.COM/watch?v=123#fragment ")
        == "https://example.com/watch?v=123"
    )
    assert validate_url("http://[::1]:8080/media") == "http://[::1]:8080/media"


@pytest.mark.parametrize(
    "value", ["CON", "aux.txt", "LPT1.mp4", "../title", "<bad>:file?*", "...", "é música  ", "COM2"]
)
def test_windows_safe_names(value):
    name = safe_name(value)
    assert name and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
    assert not name.endswith((" ", "."))
    assert name.split(".")[0].upper() not in {"CON", "AUX", "LPT1", "COM2"}


def test_concurrent_publish_never_overwrites(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(b"verified")
    target = tmp_path / "out" / "media.mp4"
    with ThreadPoolExecutor(max_workers=8) as pool:
        files = list(pool.map(lambda _: publish(source, target), range(20)))
    assert len(set(files)) == 20
    assert all(path.read_bytes() == b"verified" for path in files)
    assert not list(target.parent.glob("*.ytdlpg-lock"))


def test_profiles_settings_persist_and_reject_invalid_restore(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(path)
    assert settings.values["clipboard"] is False
    for name, options in BUILTIN_PROFILES.items():
        assert settings.profile(name) == options
    settings.values["language"] = "es"
    settings.values["profiles"]["Custom"] = Options(quality="720", output_mode="both").to_dict()
    settings.save()
    restored = Settings(path)
    assert restored.values["language"] == "es"
    assert restored.profile("Custom").quality == "720"
    with pytest.raises(ValueError):
        restored.load({"accent": "red; arbitrary:style"})
    assert restored.values["language"] == "es"
    path.write_text("broken", "utf-8")
    assert Settings(path).values["clipboard"] is False


def test_queue_history_migration_and_restart_recovery(tmp_path):
    path = tmp_path / "db.sqlite3"
    db = Database(path)
    identifier = db.add_job("https://example.org/video", "Title", tmp_path, Options().to_dict())
    db.update(identifier, status="running", downloaded=30, total=100, progress=30)
    db.close()
    db = Database(path)
    assert db.jobs()[0]["status"] == "interrupted"
    assert db.jobs("Title")[0]["downloaded"] == 30
    db.update(identifier, status="queued")
    db.update(identifier, status="running")
    db.update(identifier, status="completed", files=[str(tmp_path / "out.mp4")])
    assert db.jobs()[0]["files"] == [str(tmp_path / "out.mp4")]
    assert db.connection.execute("PRAGMA user_version").fetchone()[0] == 2
    with pytest.raises(ValueError):
        db.update(identifier, arbitrary_column="bad")
    db.delete(identifier)
    assert not db.jobs()
    db.close()


def test_schedule_claim_is_once_and_repeat_catches_up(tmp_path):
    db = Database(tmp_path / "db")
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    once = db.add_schedule(
        "https://example.org/one", "One", tmp_path, Options().to_dict(), now, "once"
    )
    daily = db.add_schedule(
        "https://example.org/two",
        "Two",
        tmp_path,
        Options().to_dict(),
        now - timedelta(days=3),
        "daily",
    )
    assert len(tick(db, now)) == 2
    assert tick(db, now) == []
    schedules = {s["id"]: s for s in db.schedules()}
    assert schedules[once]["enabled"] == 0
    assert datetime.fromisoformat(schedules[daily]["due"]) == now + timedelta(days=1)
    db.cancel_schedule(daily)
    assert tick(db, now + timedelta(days=2)) == []
    db.close()


def test_zip_deduplicates_checks_contents_and_preserves_sources(tmp_path):
    sources = []
    for folder, contents in (("a", b"first"), ("b", b"second")):
        path = tmp_path / folder / "same.mp4"
        path.parent.mkdir()
        path.write_bytes(contents)
        sources.append(path)
    events = []
    target = create_zip(sources, tmp_path / "out.zip", compression=5, progress=events.append)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"same.mp4", "same (1).mp4"}
        assert {archive.read(name) for name in archive.namelist()} == {b"first", b"second"}
    assert all(path.exists() for path in sources)
    assert events[-1]["progress"] == 100
    second = create_zip(sources, target, preserve=False)
    assert second != target and target.exists()
    assert not any(path.exists() for path in sources)


def test_zip_cancel_and_publication_failure_keep_originals(tmp_path, monkeypatch):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"a" * 3_000_000)
    target = tmp_path / "out.zip"
    calls = []
    with pytest.raises(Cancelled):
        create_zip(
            [source], target, preserve=False, progress=calls.append, cancelled=lambda: bool(calls)
        )
    assert source.exists() and not target.exists()
    assert not list(tmp_path.glob(".ytdlpg-zip-*"))

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("ytdlp_g.archive.publish", fail)
    with pytest.raises(OSError):
        create_zip([source], target, preserve=False)
    assert source.read_bytes() == b"a" * 3_000_000
    assert not target.exists()


def test_zip_does_not_delete_source_modified_during_creation(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"a" * 100)
    changed = []

    def mutate(event):
        if not changed:
            source.write_bytes(b"new content")
            changed.append(True)

    result = create_zip([source], tmp_path / "out.zip", preserve=False, progress=mutate)
    assert result.exists()
    assert source.read_bytes() == b"new content"


def test_zip_rejects_self_and_symlinks(tmp_path):
    source = tmp_path / "out.zip"
    source.write_bytes(b"source")
    with pytest.raises(ValueError):
        create_zip([source], source, preserve=False)
    if __import__("os").name != "nt":
        link = tmp_path / "link"
        link.symlink_to(source)
        with pytest.raises(ValueError):
            create_zip([link], tmp_path / "other.zip")


def test_sources_use_no_shell_true_or_untranslated_keys():
    root = Path(__file__).parents[1] / "src/ytdlp_g"
    for file in root.rglob("*.py"):
        contents = file.read_text("utf-8")
        assert "shell=True" not in contents
        for key in re.findall(r'(?:self\.tr|tr)\(["\']([a-z_]+)["\']\)', contents):
            assert key in CATALOGS["pt-BR"], (file, key)


def test_profile_export_roundtrip_is_real():
    options = Options(kind="audio", container="mp3", bitrate=320)
    assert Options.from_dict(json.loads(json.dumps(options.to_dict()))) == options


@pytest.mark.parametrize(
    "data", [[], "wrong", {"bitrate": "320"}, {"metadata": "false"}, {"name_primary": "../../bad"}]
)
def test_malformed_profile_input_is_rejected(data):
    with pytest.raises(ValueError, match="invalid_options"):
        Options.from_dict(data)


def test_credentials_in_url_are_rejected_before_persistence(tmp_path):
    db = Database(tmp_path / "db")
    for url in (
        "https://example.org/?token=secret",
        "https://example.org/?X-Amz-Credential=secret",
        "https://bad host/video",
    ):
        with pytest.raises(ValueError, match="invalid_url"):
            db.add_job(url, "Title", tmp_path, Options().to_dict())
    assert not db.jobs()
    db.close()


def test_v1_migration_preserves_jobs_and_resumes_batch_claims(tmp_path):
    path = tmp_path / "db"
    db = Database(path)
    identifier = db.add_job(
        "https://example.org/media", "Before migration", tmp_path, Options().to_dict()
    )
    db.connection.executescript(
        "ALTER TABLE jobs DROP COLUMN estimated; DROP TABLE batches; PRAGMA user_version=1;"
    )
    db.close()
    db = Database(path)
    assert db.jobs()[0]["id"] == identifier
    assert db.jobs()[0]["estimated"] == 0
    batch = db.add_batch({"ids": [identifier], "target": "playlist.zip", "preserve": True})
    db.set_batch_status(batch, "running")
    db.close()
    db = Database(path)
    assert db.batches()[0]["id"] == batch
    db.set_batch_status(batch, "completed")
    assert not db.batches()
    db.close()


def test_cleanup_only_owned_staging_and_keeps_final_files(tmp_path):
    from ytdlp_g.diagnostics import cleanup_temporary

    stage = tmp_path / ".ytdlp-g" / "job"
    stage.mkdir(parents=True)
    (stage / "partial.part").write_bytes(b"partial")
    (tmp_path / "finished.mp4").write_bytes(b"final")
    user_folder = tmp_path / "my-video"
    user_folder.mkdir()
    (user_folder / "keep.mp4").write_bytes(b"keep")
    assert cleanup_temporary(tmp_path) == 1
    assert (tmp_path / "finished.mp4").read_bytes() == b"final"
    assert (user_folder / "keep.mp4").exists()
