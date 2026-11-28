"""External media tools, per-item selection, conversion and validation."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from ytdlp_g.paths import safe_name, validate_url

VERSION = "0.1.0 Beta 1"
HOME = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
TOOLS = HOME / "tools"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def tool(name):
    path = TOOLS / (name + ".exe")
    if path.is_file() or os.name == "nt":
        if not path.exists():
            raise FileNotFoundError(name)
        return str(path)
    return shutil.which(name) or name


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, notify):
        self.notify = notify
        self.cancel = threading.Event()

    def run(self, args, on_line=None):
        if self.cancel.is_set():
            raise Cancelled()
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                              creationflags=NO_WINDOW, start_new_session=os.name != "nt") as proc:
            def watch():
                while not finished.wait(.15):
                    if self.cancel.is_set() and proc.poll() is None:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                           capture_output=True, creationflags=NO_WINDOW)
                        else:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        return
            finished = threading.Event()
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            lines = []
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if on_line:
                        on_line(line)
                    lines.append(line)
                    if len(lines) > 100:
                        del lines[0]
                code = proc.wait()
            finally:
                finished.set()
                watcher.join()
            if self.cancel.is_set():
                raise Cancelled()
            if code:
                raise RuntimeError("\n".join(lines[-10:]))
            return "\n".join(lines)

    def ydl(self):
        args = [tool("yt-dlp"), "--ignore-config", "--encoding", "utf-8", "--color", "never",
                "--socket-timeout", "30", "--retries", "0", "--fragment-retries", "0",
                "--ffmpeg-location", str(Path(tool("ffmpeg")).parent)]
        if os.name == "nt":
            args += ["--js-runtimes", "deno:" + tool("deno")]
        return args

    def inspect(self, url, whole):
        text = self.run(self.ydl() + ["--flat-playlist", "--dump-single-json", "--no-warnings",
                        "--yes-playlist" if whole else "--no-playlist", "--", validate_url(url)])
        info = json.loads(text.splitlines()[-1])
        if "entries" not in info:
            return [(url, info.get("title") or info["id"], "", 0, info.get("thumbnail"))]
        group = info.get("title") or "Playlist"
        entries = info["entries"] or []
        return [(entry.get("webpage_url") or entry.get("url"), entry.get("title") or group,
                 group, entry.get("playlist_index") or i, entry.get("thumbnail") or
                 next((t.get("url") for t in entry.get("thumbnails") or []), None))
                if entry else (None, group, group, i, None)
                for i, entry in enumerate(entries, 1) if whole or i == 1]

    def probe(self, path):
        return json.loads(self.run([tool("ffprobe"), "-v", "error", "-show_streams", "-show_format",
                                    "-of", "json", str(path)]))

    def process(self, item, dest, ext, cap):
        url, title, group, index, _ = item
        if not url:
            raise ValueError("unavailable")
        url = validate_url(url)
        folder = dest / safe_name(group) if group else dest
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ((f"{index:03} - " if index else "") + safe_name(title) + "." + ext)
        if target.exists():
            raise FileExistsError(target.name)
        key = hashlib.sha256(json.dumps([item[:4], ext, cap]).encode()).hexdigest()[:24]
        work = folder / ".ytdlp-g-lite" / key
        work.mkdir(parents=True, exist_ok=True)
        limit = f"[height<=?{cap}]" if cap else ""
        avc = f"[vcodec^=avc1]{limit}"
        fmt = (f"bv*{avc}+ba[acodec^=mp4a]/b{avc}/bv*{avc}+ba/bv*{limit}+ba/b{limit}"
               if ext == "mp4" else "ba/b")
        def progress(line):
            if line.startswith("P|"):
                _, video, percent, speed, size, eta = line.split("|", 5)
                self.notify("audio" if video == "none" or ext == "mp3" else "video",
                            " · ".join([percent.strip(), speed, size, eta]))
            elif line.startswith("[Merger]"):
                self.notify("merge", "")
        self.notify("video" if ext == "mp4" else "audio", "")
        self.run(self.ydl() + ["--no-playlist", "--newline", "--progress", "--progress-template",
                 "download:P|%(info.vcodec)s|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._downloaded_bytes_str)s|%(progress._eta_str)s",
                 "--merge-output-format", "mkv", "--write-info-json", "-f", fmt, "-o",
                 str(work / "source.%(ext)s").replace("%", "%%").replace("%%(ext)s","%(ext)s"),
                 "--print-to-file", "after_move:filepath", str(work / "path.txt"), "--", url], progress)
        source = Path((work / "path.txt").read_text("utf-8").splitlines()[-1])
        info = json.loads((work / "source.info.json").read_text("utf-8"))
        output = work / ("ready." + ext)
        self.convert(source, output, ext, cap, info)
        if os.name == "nt":
            output.rename(target)
        else:
            os.link(output, target)
        shutil.rmtree(work)
        return target

    def convert(self, source, output, ext, cap=0, info=None):
        self.notify("verify", "")
        src = self.probe(source)
        a, v = streams(src)
        args = [tool("ffmpeg"), "-nostdin", "-y", "-v", "error", "-i", str(source)]
        if ext == "mp3":
            args += ["-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k", "-ac", "2",
                     "-ar", "48000" if a.get("sample_rate") == "48000" else "44100"]
        else:
            args += ["-map", f"0:{v['index']}", "-map", f"0:{a['index']}"]
            if video_ok(v, cap):
                args += ["-c:v", "copy"]
            else:
                filters = []
                if hdr(v):
                    filters += ["zscale=t=linear:npl=100", "format=gbrpf32le",
                                "zscale=p=bt709", "tonemap=mobius", "zscale=t=bt709:m=bt709:r=tv"]
                    args += ["-colorspace","bt709","-color_primaries","bt709","-color_trc","bt709"]
                filters += [f"scale=-2:trunc(min(ih\\,{cap or v['height']})/2)*2", "format=yuv420p"]
                # Width is derived from aspect ratio. Keep the height even for 4:2:0.
                args += ["-vf", ",".join(filters), "-c:v", "libx264", "-crf", "23", "-preset", "medium"]
            args += ["-c:a", "copy"] if audio_ok(a) else [
                "-c:a", "aac", "-profile:a", "aac_low", "-ar", "48000", "-ac", "2", "-b:a", "192k"]
            args += ["-movflags", "+faststart"]
        for key in ("title", "artist", "album", "genre", "track", "date", "comment"):
            value = (info or {}).get(key)
            if value:
                args += ["-metadata", f"{key}={value}"]
        self.notify("merge" if ext == "mp4" and video_ok(v, cap) and audio_ok(a) else ext, "")
        self.run(args + [str(output)])
        self.notify("verify", "")
        result = self.probe(output)
        a2, v2 = streams(result)
        if ext == "mp4":
            valid = ("mp4" in result["format"]["format_name"].split(",") and video_ok(v2, cap)
                     and audio_ok(a2) and (not hdr(v) or all(v2.get(k) == "bt709" for k in
                          ("color_transfer", "color_space", "color_primaries"))))
        else:
            valid = (a2.get("codec_name") == "mp3" and a2.get("sample_rate") in ("44100","48000")
                     and a2.get("channels") == 2 and a2.get("bit_rate") == "320000" and not v2)
        if not valid:
            raise ValueError("validation")


def streams(result):
    streams_ = result["streams"]
    audio = next((s for s in streams_ if s["codec_type"] == "audio"), {})
    video = next((s for s in streams_ if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), {})
    return audio, video


def hdr(v):
    return v.get("color_transfer") in ("smpte2084", "arib-std-b67")


def video_ok(v, cap):
    return (v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"
            and not hdr(v) and (not cap or v["height"] <= cap))


def audio_ok(a):
    return (a.get("codec_name") == "aac" and a.get("profile") == "LC"
            and a.get("sample_rate") == "48000" and a.get("channels") == 2)


def update(runner, request=urllib.request.urlopen):
    exe = Path(tool("yt-dlp"))
    old = runner.run([str(exe), "--version"])
    with request("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", timeout=30) as response:
        release = json.load(response)
    version = release["tag_name"]
    if old == version:
        return version
    asset = next(a for a in release["assets"] if a["name"] == "yt-dlp.exe")
    staged = exe.with_name("update.new.exe")
    backup = exe.with_name("update.previous.exe")
    try:
        runner.notify("update", f"{old} → {version}")
        with request(asset["browser_download_url"], timeout=60) as response, staged.open("wb") as f:
            shutil.copyfileobj(response, f)
        with staged.open("rb") as f:
            if "sha256:" + hashlib.file_digest(f, "sha256").hexdigest() != asset["digest"]:
                raise ValueError("checksum")
        if runner.run([str(staged), "--version"]) != version:
            raise ValueError("version")
        shutil.copy2(exe, backup)
        os.replace(staged, exe)
        try:
            if runner.run([str(exe), "--version"]) != version:
                raise ValueError("version")
        except BaseException:
            os.replace(backup, exe)
            raise
        backup.unlink()
        return version
    finally:
        staged.unlink(missing_ok=True)
