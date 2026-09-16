"""Install a built wheel in a fresh environment and check its public command."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, help="Directory containing built artifacts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    dist = args.dist.resolve()
    wheels = sorted(dist.glob("workflow_cockpit-*.whl"))
    sdists = sorted(dist.glob("workflow_cockpit-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        parser().error(f"expected one wheel and one sdist in {dist}")

    with tarfile.open(sdists[0]) as archive:
        names = archive.getnames()
    if not any(name.endswith("/LICENSE") for name in names):
        parser().error("sdist does not contain LICENSE")

    with tempfile.TemporaryDirectory() as directory:
        venv = Path(directory) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        scripts = venv / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        cockpit = scripts / ("workflow-cockpit.exe" if sys.platform == "win32" else "workflow-cockpit")
        subprocess.run([str(python), "-m", "pip", "install", str(wheels[0])], check=True)
        result = subprocess.run([str(cockpit), "--help"], check=False, text=True, capture_output=True)
        if result.returncode != 0 or "Own one Spec Kit workflow run" not in result.stdout:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return 1
        subprocess.run(
            [
                str(python),
                "-c",
                (
                    "from importlib.resources import files; "
                    "assert files('workflow_cockpit.ui').joinpath('styles.tcss').is_file(); "
                    "assert files('workflow_cockpit.styling').joinpath('templates/cockpit.json').is_file(); "
                    "assert files('workflow_cockpit.skills').joinpath('cockpit-run-context/SKILL.md').is_file()"
                ),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
