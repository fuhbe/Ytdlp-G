import functools
import http.server
import io
import json
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import engine

if os.getenv("LITE_TEST_TOOLS"):
    engine.TOOLS = Path(os.environ["LITE_TEST_TOOLS"])


@pytest.fixture
def runner():
    return engine.Runner(lambda *args: None)


def source(root, codec, audio="aac", rate=48000, size="128x72"):
    file = root / "source.mp4"
    subprocess.run([engine.tool("ffmpeg"), "-loglevel","error","-y","-f","lavfi","-i",
        f"color=s={size}:r=60:d=0.2","-f","lavfi","-i","sine=d=0.2","-c:v",codec,
        "-c:a",audio,"-ar",str(rate),"-ac","2","-strict","experimental",str(file)],check=True)
    return file


@pytest.mark.parametrize("codec",["libaom-av1","libvpx-vp9","libx265","libx264"])
def test_video(tmp_path,runner,codec):
    src = source(tmp_path,codec,size="1920x1080" if codec=="libx264" else "128x72")
    output = tmp_path/"música com espaço.mp4"
    with patch.object(runner,"run",wraps=runner.run) as calls:
        runner.convert(src,output,"mp4")
    ff = next(args.args[0] for args in calls.call_args_list if "-movflags" in args.args[0])
    assert ff[ff.index("-c:v")+1] == ("copy" if codec=="libx264" else "libx264")
    assert ff[ff.index("-c:a")+1]=="copy"
    _,v = engine.streams(runner.probe(output))
    assert v["r_frame_rate"]=="60/1"
    assert output.read_bytes().index(b"moov") < output.read_bytes().index(b"mdat")


def test_audio_only(tmp_path,runner):
    src = source(tmp_path,"libx264",rate=44100)
    with patch.object(runner,"run",wraps=runner.run) as calls:
        runner.convert(src,tmp_path/"ready.mp4","mp4")
    ff = next(args.args[0] for args in calls.call_args_list if "-movflags" in args.args[0])
    assert ff[ff.index("-c:v")+1]=="copy" and ff[ff.index("-c:a")+1]=="aac"


@pytest.mark.parametrize("ext",["mp4","mp3"])
def test_http_download(tmp_path,runner,ext):
    source(tmp_path,"libx264")
    server = http.server.ThreadingHTTPServer(("127.0.0.1",0),
               functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/source.mp4"
        items = runner.inspect(url,False)
        assert runner.process(items[0],tmp_path/"á b",ext,0).is_file()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("fail",[True,False])
def test_update(tmp_path,runner,fail,monkeypatch):
    exe = tmp_path/"yt-dlp.exe"
    exe.write_bytes(b"old")
    monkeypatch.setattr(engine,"tool",lambda _:str(exe))
    release = {"tag_name":"2","assets":[{"name":"yt-dlp.exe","browser_download_url":"asset",
               "digest":"sha256:"+engine.hashlib.sha256(b"new").hexdigest()}]}
    responses = iter(["1","2","broken" if fail else "2"])
    runner.run = lambda _:next(responses)
    request = lambda url,timeout:io.BytesIO(b"new" if url=="asset" else json.dumps(release).encode())
    if fail:
        with pytest.raises(ValueError):
            engine.update(runner,request)
        assert exe.read_bytes()==b"old"
    else:
        assert engine.update(runner,request)=="2" and exe.read_bytes()==b"new"


def test_cancel(runner):
    import sys
    timer = threading.Timer(.25,runner.cancel.set)
    timer.start()
    with pytest.raises(engine.Cancelled):
        runner.run([sys.executable,"-c","import time; time.sleep(60)"])
