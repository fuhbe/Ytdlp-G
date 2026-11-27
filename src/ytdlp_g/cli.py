"""Windows console interface to the shared download engine."""

import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from . import cli_queue
from .paths import data_dir, validate_url

VERSION = "0.1.0-beta.1"
LANGS = ("pt-BR", "en", "es")
MENUS = (
    "Baixar vídeo MP4|Baixar áudio MP3|Baixar playlist|Baixar vários links|Converter vídeos existentes|Gerenciar fila|Histórico de downloads|Configurações|Atualizar motor yt-dlp|Diagnóstico do sistema|Sair",
    "Download MP4 video|Download MP3 audio|Download playlist|Download several links|Convert existing videos|Manage queue|Download history|Settings|Update yt-dlp|System diagnostics|Exit",
    "Descargar vídeo MP4|Descargar audio MP3|Descargar lista|Descargar varios enlaces|Convertir vídeos existentes|Administrar cola|Historial|Configuración|Actualizar yt-dlp|Diagnóstico|Salir",
)


def parser():
    p = argparse.ArgumentParser(prog="ytdlp-g", description="Ytdlp-G CLI • Windows Edition")
    p.add_argument("--version", action="version", version=f"Ytdlp-G CLI {VERSION}")
    p.add_argument("--json", action="store_true", help="JSON em stdout")
    commands = p.add_subparsers(dest="command")
    d = commands.add_parser("download", help="Baixar vídeos, áudio ou playlists")
    d.add_argument("urls", nargs="*")
    d.add_argument("--input-file", help="Um link por linha, ou - para stdin")
    fmt = d.add_mutually_exclusive_group()
    for kind in ("mp3", "mp4"):
        fmt.add_argument("--" + kind, action="store_true")
    q = d.add_mutually_exclusive_group()
    q.add_argument("--quality", type=int, help="Altura máxima por vídeo, ex. 1080")
    q.add_argument("--best", action="store_true")
    d.add_argument(
        "--playlist", action="store_true", help="Processar a playlist (detecção automática)"
    )
    d.add_argument("--zip", action="store_true")
    d.add_argument("--downloader", choices=("auto", "native", "aria2c"))
    c = commands.add_parser("convert", help="Converter arquivos locais")
    c.add_argument("paths", nargs="+", type=Path)
    c.add_argument("--recursive", action="store_true")
    c.add_argument("--copy-compatible", action="store_true")
    for sub in (c, d):
        sub.add_argument("--destination", "-o", type=Path)
        group = sub.add_mutually_exclusive_group()
        for profile in ("compatible", "original", "legacy"):
            group.add_argument("--" + profile, dest="profile", action="store_const", const=profile)
    queue = commands.add_parser("queue", help="Controlar fila persistente")
    queue.add_argument("action", choices=("list", "pause", "resume", "retry", "cancel", "run"))
    queue.add_argument("id", type=int, nargs="?")
    settings = commands.add_parser("config", help="Mostrar ou alterar preferências")
    settings.add_argument("--language", choices=LANGS)
    settings.add_argument("--destination", type=Path)
    settings.add_argument("--downloads", type=int, choices=range(1, 9))
    settings.add_argument("--conversions", type=int, choices=range(1, 5))
    for cmd, help_text in (
        ("history", "Itens processados"),
        ("doctor", "Verificar ferramentas e encoders"),
        ("update", "Atualizar motor"),
        ("clear-cache", "Limpar cache de análise"),
    ):
        commands.add_parser(cmd, help=help_text)
    return p


def catalog(lang):
    return json.loads((Path(__file__).parent / "i18n" / (lang + ".json")).read_text("utf-8"))


def progress_renderer(quiet):
    last = {}

    def emit(event):
        if quiet:
            return
        item = event.get("current") or event.get("index") or ""
        stage = event.get("phase") or event.get("status", "")
        key = (item, stage)
        now = time.monotonic()
        if now - last.get(key, -10) < 0.4:
            return
        last[key] = now
        fields = [str(x) for x in (item, event.get("name"), stage, event.get("encoder")) if x]
        for key_name in ("height", "fps", "codec", "downloaded", "total", "eta"):
            if event.get(key_name):
                fields.append(f"{key_name}={event[key_name]}")
        if event.get("speed"):
            fields.append(f"{event['speed'] / 1048576:.2f} MiB/s")
        if event.get("total") and event.get("downloaded"):
            fields.append(f"{100 * event['downloaded'] / event['total']:.1f}%")
        elif event.get("encoder") and event.get("progress"):
            fields.append(f"{event['progress']:.1f}%")
        print(" · ".join(fields), file=sys.stderr, flush=True)

    return emit


def execute(args, db, root, prefs, emit):
    cmd = args.command
    if cmd == "config":
        for key in ("language", "destination", "downloads", "conversions"):
            value = getattr(args, key, None)
            if value is not None:
                prefs[key] = str(value.resolve()) if isinstance(value, Path) else value
                db.execute(
                    "INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(prefs[key]))
                )
        return prefs
    if cmd == "history" or (cmd == "queue" and args.action == "list"):
        condition = " WHERE result IS NOT NULL" if cmd == "history" else ""
        return [
            dict(r)
            for r in db.execute("SELECT id,state,result FROM jobs" + condition + " ORDER BY id")
        ]
    if cmd == "queue" and args.action not in ("run", "list"):
        changed = cli_queue.control(db, args.action, args.id)
        if args.action not in ("resume", "retry") or not changed:
            return {"changed": changed}
    from .engine import activate_engine, prepare_engine

    engine = activate_engine(
        prepare_engine(
            force=cmd == "update", check=cmd in ("download", "update"), root=root / "engines"
        )
    )
    if cmd == "update":
        return {"version": engine["version"], "status": engine["status"]}
    from . import lite, media, offline, turbo

    turbo.configure(prefs)
    if cmd == "doctor":
        deps = {}
        for tool in ("ffmpeg", "ffprobe", "qjs", "aria2c"):
            try:
                deps[tool] = media.executable(tool)
            except ValueError:
                deps[tool] = None
        return {
            "version": VERSION,
            "yt-dlp": engine["version"],
            "dependencies": deps,
            "encoders": media.working_encoders(deps["ffmpeg"], "auto") if deps["ffmpeg"] else [],
            "status": "complete" if all(deps.values()) else "partial",
        }
    if cmd == "clear-cache":
        return turbo.clear_cache()
    if cmd == "convert":
        first = args.paths[0].resolve()
        dest = args.destination or (first if first.is_dir() else first.parent) / "Convertidos"
        result = offline.convert_batch(
            dict(
                inputs=args.paths,
                destination=dest,
                recursive=args.recursive,
                skip=not args.copy_compatible,
                profile=args.profile or "compatible",
            ),
            emit,
        )
        return result | {"status": "partial" if result["failures"] else "complete"}
    ids = []
    if cmd == "download":
        urls = list(args.urls)
        if args.input_file == "-" or (not urls and not args.input_file and not sys.stdin.isatty()):
            urls.extend(sys.stdin.read().splitlines())
        elif args.input_file:
            urls.extend(Path(args.input_file).read_text("utf-8-sig").splitlines())
        urls = [validate_url(u.strip()) for u in urls if u.strip()]
        if not urls or args.quality is not None and (args.quality < 1 or args.mp3):
            raise ValueError("invalid_options")
        quality = (
            lite.MP3 if args.mp3 else f"video:max:{args.quality}" if args.quality else lite.BEST
        )
        for url in urls:
            payload = dict(
                url=url,
                resolution_limit=args.quality,
                quality=quality,
                mode="zip" if args.zip else "normal",
                destination=str(Path(args.destination or prefs["destination"]).resolve()),
                profile=args.profile or "compatible",
                downloader=args.downloader or "auto",
            )
            ids.append(cli_queue.enqueue(db, payload))
    elif args.id is not None:
        ids = [args.id]
    results = []
    with cli_queue.runner(root, db):
        rows = db.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        for row in rows:
            i = row["id"]
            if ids and i not in ids:
                continue
            if not db.execute(
                "UPDATE jobs SET state='running' WHERE id=? AND state='pending'", (i,)
            ).rowcount:
                results.append(
                    {
                        "id": i,
                        "state": db.execute("SELECT state FROM jobs WHERE id=?", (i,)).fetchone()[
                            0
                        ],
                    }
                )
                continue
            payload = json.loads(row["request"])
            turbo.configure(prefs | {"downloader": payload.pop("downloader")})
            from .archive import Cancelled

            last_check = [0.0]
            guard = threading.Lock()

            def monitored(event, guard=guard, i=i, last_check=last_check):  # noqa: B023
                with guard:
                    if time.monotonic() - last_check[0] > 0.25:
                        last_check[0] = time.monotonic()
                        current = control_db.execute(
                            "SELECT state FROM jobs WHERE id=?", (i,)
                        ).fetchone()[0]
                        if current != "running":
                            raise Cancelled()
                emit(event)

            try:
                with closing(
                    sqlite3.connect(root / "queue.sqlite", check_same_thread=False)
                ) as control_db:
                    result = lite.download_lite(payload, monitored)
                state = result["status"]
            except KeyboardInterrupt:
                db.execute("UPDATE jobs SET state='paused' WHERE id=?", (i,))
                raise
            except Exception as exc:
                from .diagnostics import diagnostic

                result = {"failures": [diagnostic("download", exc)]}
                state = "failed"
            db.execute(
                "UPDATE jobs SET state=?,result=? WHERE id=? AND state='running'",
                (state, json.dumps(result), i),
            )
            results.append(
                {
                    "id": i,
                    "state": state,
                    "files": result.get("files", []),
                    "failures": result.get("failures", []),
                }
            )
    return {
        "jobs": results,
        "status": "complete" if all(r["state"] == "complete" for r in results) else "partial",
    }


def menu(language):
    labels = MENUS[LANGS.index(language)].split("|")
    print("\nYTDLP-G CLI")
    for i, label in enumerate(labels[:-1], 1):
        print(f"{i:2}. {label}")
    print(" 0. " + labels[-1])
    choice = input("> ").strip()
    if choice == "0":
        return None
    if choice in ("1", "2", "3", "4"):
        urls = []
        while True:
            url = input("URL > ").strip()
            if not url:
                break
            urls.append(url)
            if choice != "4":
                break
        if not urls:
            raise ValueError("invalid_url")
        kind = (
            "mp3"
            if choice == "2"
            else "mp4"
            if choice == "1"
            else input("MP4 / MP3 [MP4] > ").strip().lower() or "mp4"
        )
        args = ["download", *urls, "--" + kind]
        if kind == "mp4":
            quality = input("720 / 1080 / 2160 [auto] > ").strip()
            if quality:
                args += ["--quality", quality]
        destination = input(
            labels[7] + " · 📁 [Enter = default] > "
            if sys.stdout.encoding and sys.stdout.encoding.lower() == "utf-8"
            else "Folder [Enter = default] > "
        ).strip()
        return args + (["-o", destination] if destination else [])
    if choice == "5":
        return [
            "convert",
            input("📁 > " if sys.stdout.encoding == "utf-8" else "Path > ").strip().strip('"'),
        ]
    if choice == "6":
        return [
            "queue",
            input("list / pause / resume / cancel / retry [list] > ").strip() or "list",
        ]
    if choice == "8":
        lang = input("pt-BR / en / es > ").strip()
        dest = input("Folder > ").strip()
        return (
            ["config"]
            + (["--language", lang] if lang else [])
            + (["--destination", dest] if dest else [])
        )
    return [{"7": "history", "9": "update", "10": "doctor"}.get(choice, "--help")]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    machine = "--json" in argv
    argv = [v for v in argv if v != "--json"]
    p = parser()
    args = p.parse_args(argv)
    root = Path(os.environ.get("YTDLPG_CLI_HOME") or data_dir() / "cli")
    logging.getLogger("ytdlp_g").addHandler(logging.NullHandler())
    with closing(cli_queue.connect(root)) as db:
        prefs = {
            "destination": str(Path.home() / "Downloads"),
            "language": "pt-BR",
            "downloads": 2,
            "conversions": 1,
        }
        prefs.update(
            {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")}
        )
        interactive = args.command is None
        while True:
            try:
                if interactive:
                    words = menu(prefs["language"])
                    if words is None:
                        return 0
                    try:
                        args = p.parse_args(words)
                    except SystemExit:
                        continue
                emit = progress_renderer(machine)
                result = execute(args, db, root, prefs, emit)
                if machine:
                    print(json.dumps(result, ensure_ascii=True))
                else:
                    texts = catalog(prefs["language"])

                    def display(value, indent="", texts=texts):
                        if isinstance(value, list):
                            for item in value:
                                display(item, indent)
                        elif isinstance(value, dict):
                            for key, item in value.items():
                                if isinstance(item, (list, dict)):
                                    if item:
                                        print(indent + key)
                                        display(item, indent + "  ")
                                else:
                                    print(indent + key + " · " + str(texts.get(str(item), item)))
                        else:
                            print(indent + str(value))

                    display(result)
                code = int(
                    isinstance(result, dict)
                    and result.get("status") in {"partial", "failed", "offline"}
                )
            except EOFError:
                return 0 if interactive else 1
            except KeyboardInterrupt:
                return 130
            except Exception as exc:
                from .diagnostics import diagnostic

                err = diagnostic("cli", exc)
                if str(exc) == "queue_busy":
                    err["code"] = "queue_busy"
                if machine:
                    print(json.dumps({"error": err}))
                else:
                    print(catalog(prefs["language"]).get(err["code"], err["code"]), file=sys.stderr)
                code = 1
            if not interactive:
                return code


if __name__ == "__main__":
    raise SystemExit(main())
