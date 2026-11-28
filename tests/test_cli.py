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


def test_cli_recovers_after_source_returns(tmp_path, media_file, monkeypatch, capsys):
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from ytdlp_g import engine

    monkeypatch.setenv("YTDLPG_CLI_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(engine, "prepare_engine", lambda **kw: {"version": "fixture", "path": ""})
    source = tmp_path / "http"
    source.mkdir()
    (source / "a.mp4").write_bytes(media_file.read_bytes())
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(source))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        dst = tmp_path / ("á & longo " * 8).strip() / ("caminho " * 8).strip()
        assert cli.main(["download", url + "/a.mp4", url + "/b.mp4", "-o", str(dst), "--json"]) == 1
        result = json.loads(capsys.readouterr().out)
        assert [r["state"] for r in result["jobs"]] == ["complete", "failed"]
        original = next(dst.glob("*.mp4"))
        stamp = original.stat().st_mtime_ns
        (source / "b.mp4").write_bytes(media_file.read_bytes())
        assert cli.main(["queue", "retry", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert len(result["jobs"]) == 1 and result["jobs"][0]["id"] == 2
        assert len(list(dst.glob("*.mp4"))) == 2 and original.stat().st_mtime_ns == stamp
        original.unlink()
        assert cli.main(["download", url + "/a.mp4", "-o", str(dst), "--json"]) == 0
        assert len(list(dst.glob("*.mp4"))) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
