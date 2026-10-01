"""Build the deployment packages for Azure.

    python hcm_agent/deploy/package.py server <output.zip>        # Clara server (App Service)
    python hcm_agent/deploy/package.py function <output.zip|dir>  # call-request Azure Function

Uses zipfile (forward-slash paths) because Windows PowerShell's Compress-Archive can write
backslash paths that Linux extracts as literal file names.
"""

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "hcm_agent"
FUNCTION = PACKAGE / "azure_functions"
# Parts of the repo's hcm_agent/ folder that are not application code.
NOT_APP_CODE = {"azure_functions", "deploy", "__pycache__"}


def app_files() -> list[tuple[Path, str]]:
    """The hcm_agent package as the apps import it, placed at hcm_agent/... in the package."""
    return [(path, path.relative_to(ROOT).as_posix())
            for path in sorted(PACKAGE.rglob("*"))
            if path.is_file() and not NOT_APP_CODE.intersection(path.relative_to(PACKAGE).parts)]


def server_files() -> list[tuple[Path, str]]:
    # requirements.txt at the root tells App Service what to install; gunicorn imports hcm_agent.
    return [(ROOT / "requirements.txt", "requirements.txt")] + app_files()


def function_files() -> list[tuple[Path, str]]:
    # function_app.py, host.json and requirements.txt must sit at the root of a Function package.
    return [(path, path.relative_to(FUNCTION).as_posix())
            for path in sorted(FUNCTION.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts] + app_files()


def build(files: list[tuple[Path, str]], target: str) -> None:
    target_path = Path(target)
    if target_path.suffix == ".zip":
        with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, name in files:
                archive.write(path, name)
    else:  # a folder, for the GitHub Actions function deploy
        shutil.rmtree(target_path, ignore_errors=True)
        for path, name in files:
            (target_path / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target_path / name)


if __name__ == "__main__":
    kinds = {"server": server_files, "function": function_files}
    if len(sys.argv) != 3 or sys.argv[1] not in kinds:
        raise SystemExit(__doc__)
    build(kinds[sys.argv[1]](), sys.argv[2])
