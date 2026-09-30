"""Build the zip that deploy.ps1 uploads to Azure App Service.

Uses zipfile (forward-slash paths) because Windows PowerShell's Compress-Archive
can write backslash paths that Linux extracts as literal file names.
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(out: str) -> None:
    # The package goes at the zip root (hcm_agent/...), so gunicorn can import it without installing it.
    src = ROOT / "src"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "requirements.txt", "requirements.txt")
        for path in sorted((src / "hcm_agent").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(src).as_posix())


if __name__ == "__main__":
    build(sys.argv[1])
