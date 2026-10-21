"""Atomic preferences and real, serializable profiles."""

import json
import locale
import os
import tempfile
from pathlib import Path

from .models import BUILTIN_PROFILES, Options


def system_language():
    code = (locale.getlocale()[0] or "pt_BR").lower()
    return "es" if code.startswith("es") else "en" if code.startswith("en") else "pt-BR"


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self.values = {
            "language": system_language(),
            "theme": "auto",
            "accent": "#5268eb",
            "destination": str(Path.home() / "Downloads" / "Ytdlp-G"),
            "concurrency": 2,
            "clipboard": False,
            "notifications": True,
            "sounds": False,
            "minimize_tray": False,
            "close_tray": False,
            "options": Options().to_dict(),
            "profiles": {},
        }
        if path.exists():
            try:
                self.load(json.loads(path.read_text("utf-8")))
            except (ValueError, TypeError, OSError):
                # Keep corrupt input for diagnosis, start with safe defaults.
                pass

    def load(self, values):
        if not isinstance(values, dict):
            raise ValueError("invalid_options")
        merged = self.values | {k: v for k, v in values.items() if k in self.values}
        for key, default in self.values.items():
            if type(merged[key]) is not type(default):
                raise ValueError("invalid_options")
        if merged["language"] not in {"pt-BR", "en", "es"} or merged["theme"] not in {
            "auto",
            "light",
            "dark",
        }:
            raise ValueError("invalid_options")
        if not 1 <= int(merged["concurrency"]) <= 8:
            raise ValueError("invalid_options")
        if not isinstance(merged["destination"], str) or not isinstance(merged["profiles"], dict):
            raise ValueError("invalid_options")
        if not __import__("re").fullmatch(r"#[0-9a-fA-F]{6}", merged["accent"]):
            raise ValueError("invalid_options")
        merged["options"] = Options.from_dict(merged["options"]).to_dict()
        for name, options in merged["profiles"].items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("invalid_options")
            Options.from_dict(options)
        self.values = merged

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(self.values, out, ensure_ascii=False, indent=2)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def profile(self, name):
        if name in self.values["profiles"]:
            return Options.from_dict(self.values["profiles"][name])
        return Options.from_dict(BUILTIN_PROFILES[name].to_dict())
