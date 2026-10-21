"""Windows-safe naming and atomic, non-overwriting publication."""

import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def data_dir() -> Path:
    portable = Path(sys.executable).parent / "portable.flag"
    if getattr(sys, "frozen", False) and portable.exists():
        root = portable.parent / "data"
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Ytdlp-G"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Ytdlp-G"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_name(value: str, limit: int = 100) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    name = name[:limit].rstrip(" .") or "untitled"
    if name.split(".")[0].upper() in RESERVED:
        name = "_" + name
    return name


def validate_url(value: str) -> str:
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        raise ValueError("invalid_url")
    try:
        parts = urlsplit(value)
        if (
            parts.scheme.lower() not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("invalid_url")
        _ = parts.port
        host = parts.hostname.encode("idna").decode("ascii")
        if not re.fullmatch(r"[a-zA-Z0-9._:-]+", host):
            raise ValueError("invalid_url")
        sensitive = {
            "access_token",
            "token",
            "password",
            "passwd",
            "authorization",
            "auth",
            "cookie",
            "cookies",
            "session",
            "sessionid",
            "api_key",
            "apikey",
            "sig",
            "signature",
            "jwt",
            "credential",
        }
        if any(
            key.lower() in sensitive or key.lower().startswith("x-amz-")
            for key, _ in parse_qsl(parts.query)
        ):
            raise ValueError("invalid_url")
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid_url") from exc


def publish(source: Path, target: Path) -> Path:
    """Copy once, then publish atomically without replacing any existing file.

    Windows rename refuses existing destinations; POSIX hardlink has the same
    no-clobber property. No sidecar lock is necessary, avoiding Windows races
    while another process deletes a reservation that the filesystem still holds.
    """
    import tempfile

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".ytdlpg-", delete=False) as out:
            temporary = Path(out.name)
            with source.open("rb") as incoming:
                shutil.copyfileobj(incoming, out)
            out.flush()
            os.fsync(out.fileno())
        for index in range(10000):
            candidate = (
                target if not index else target.with_name(f"{target.stem} ({index}){target.suffix}")
            )
            try:
                if os.name == "nt":
                    os.rename(temporary, candidate)
                else:
                    os.link(temporary, candidate)
            except FileExistsError:
                continue
            return candidate
        raise FileExistsError("collision_limit")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
