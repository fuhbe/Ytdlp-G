import json

from ytdlp_g import cli, cli_queue


def test_cli_queue_and_media(tmp_path, media_url, monkeypatch, capsys):
    monkeypatch.setenv("YTDLPG_CLI_HOME", str(tmp_path / "state"))
    from ytdlp_g import engine

    monkeypatch.setattr(engine, "prepare_engine", lambda **kw: {"version": "fixture", "path": ""})
    args = [
        "download",
        media_url,
        media_url,
        "--quality",
        "1080",
        "--json",
        "-o",
        str(tmp_path / "out"),
    ]
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["files"][0].endswith(".mp4")
    assert cli.main(args) == 0
    assert len(list((tmp_path / "out").glob("*.mp4"))) == 1


def test_cli_control_recovery(tmp_path):
    db = cli_queue.connect(tmp_path)
    job = cli_queue.enqueue(db, {"url": "http://example.com"})
    db.execute("UPDATE jobs SET state='running'")
    with cli_queue.runner(tmp_path, db):
        assert cli_queue.control(db, "pause", job) == 1
        assert cli_queue.control(db, "resume", job) == 1
        assert cli_queue.control(db, "cancel", job) == 1
        assert cli_queue.control(db, "retry", job) == 1
    db.close()
