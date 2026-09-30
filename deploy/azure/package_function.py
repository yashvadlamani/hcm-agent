"""Build the call-request Azure Function package: functions/ plus the hcm_agent package.

    python deploy/azure/package_function.py <output.zip>     # zip for az functionapp deploy
    python deploy/azure/package_function.py <output-folder>  # folder for the GitHub Actions deploy
"""

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def files() -> list[tuple[Path, str]]:
    out = [(path, path.relative_to(ROOT / "functions").as_posix())
           for path in sorted((ROOT / "functions").rglob("*")) if path.is_file()]
    out += [(path, path.relative_to(ROOT / "src").as_posix())
            for path in sorted((ROOT / "src" / "hcm_agent").rglob("*")) if path.is_file()]
    return [(path, name) for path, name in out if "__pycache__" not in name and ".egg-info" not in name]


def build(target: str) -> None:
    target_path = Path(target)
    if target_path.suffix == ".zip":
        with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, name in files():
                archive.write(path, name)
    else:
        shutil.rmtree(target_path, ignore_errors=True)
        for path, name in files():
            (target_path / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target_path / name)


if __name__ == "__main__":
    build(sys.argv[1])
