"""Copy installed distribution licenses for the portable and installed app."""

import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
manifest = []
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, root / "Python-LICENSE.txt")
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    if name.lower() in {"ytdlp-g", "pip", "setuptools", "pytest", "ruff", "pyinstaller", "pillow"}:
        continue
    licenses = []
    for entry in dist.files or []:
        if ".dist-info/" in str(entry) and any(
            part.lower().startswith(("license", "copying", "notice")) for part in entry.parts
        ):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                target = root / name / entry.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                licenses.append(str(target.relative_to(root)))
    manifest.append(
        {
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression")
            or dist.metadata.get("License", "See upstream"),
            "files": licenses,
        }
    )
(root / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
