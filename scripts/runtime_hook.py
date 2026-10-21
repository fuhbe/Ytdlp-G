"""Expose bundled helper executables to yt-dlp without global installation."""

import os
import sys
from pathlib import Path

bundled_bin = Path(sys._MEIPASS) / "bin"
os.environ["PATH"] = str(bundled_bin) + os.pathsep + os.environ.get("PATH", "")
