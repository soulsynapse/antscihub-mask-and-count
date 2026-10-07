"""Start Mask and Count: python main.py [folder]   (or double-click "Mask and Count.bat")

Run it with any Python 3. On first run, and whenever requirements.txt changes, it creates
.venv next to this file, installs requirements.txt into it, and then runs the app from
.venv. `--setup-only` does the setup and exits.

This file must stay runnable by old interpreters (3.7 is on some lab machines): no
newer syntax here. The app itself requires a Python in SUPPORTED.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / "requirements.sha256"  # hash of the requirements.txt last installed
SUPPORTED = ((3, 10), (3, 13))  # PySide6 wheels exist for this range
LOGLEVEL_VAR = "OPENCV_FFMPEG_LOGLEVEL"  # see mask_and_count/__main__.py


def say(msg):
    print("[mask-and-count] " + msg, flush=True)


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def is_conda(prefix):
    # Anaconda/Miniconda installs carry conda-meta. A venv built from one inherits
    # Anaconda's Library/bin on PATH, whose Qt/MSVC DLLs break PySide6 on Windows.
    return (Path(prefix) / "conda-meta").is_dir()


def probe(cmd):
    """(major, minor, base_prefix) of the Python started by `cmd`, or None."""
    try:
        out = subprocess.run(
            cmd + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1], sys.base_prefix)"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    major, minor, prefix = out.stdout.strip().split(" ", 2)
    return int(major), int(minor), prefix


def usable(info):
    return info is not None and SUPPORTED[0] <= info[:2] <= SUPPORTED[1] and not is_conda(info[2])


def pick_base_python():
    """Command for a supported, non-conda Python to build the venv from."""
    candidates = [[sys.executable]]
    versions = ["3.{}".format(m) for m in range(SUPPORTED[1][1], SUPPORTED[0][1] - 1, -1)]
    if os.name == "nt" and shutil.which("py"):
        candidates += [["py", "-" + v] for v in versions]
    candidates += [[exe] for exe in (shutil.which("python" + v) for v in versions) if exe]
    candidates += [[exe] for exe in (shutil.which("python3"), shutil.which("python")) if exe]
    for cmd in candidates:
        if usable(probe(cmd)):
            return cmd
    sys.exit(
        "No suitable Python found. Install Python {}.{}–{}.{} from https://www.python.org "
        "(not Anaconda) and run this again.".format(*SUPPORTED[0], *SUPPORTED[1])
    )


def venv_is_healthy():
    if not venv_python().is_file():
        return False
    cfg = VENV / "pyvenv.cfg"
    home = ""
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.split("=")[0].strip() == "home":
                home = line.split("=", 1)[1].strip()
    if home and is_conda(Path(home)):
        say("existing .venv was built from Anaconda's Python, which breaks PySide6; rebuilding it")
        return False
    if not usable(probe([str(venv_python())])):
        say("existing .venv is unusable (its Python moved, or is an unsupported version); rebuilding it")
        return False
    return True


def requirements_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_venv():
    if not venv_is_healthy():
        if VENV.exists():
            shutil.rmtree(str(VENV))
        base = pick_base_python()
        say("creating .venv with " + " ".join(base) + " (first run only)")
        subprocess.check_call(base + ["-m", "venv", str(VENV)])
    if not STAMP.is_file() or STAMP.read_text().strip() != requirements_hash():
        say("installing requirements into .venv (first run, or requirements.txt changed)")
        py = str(venv_python())
        subprocess.check_call([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
        subprocess.check_call([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)])
        STAMP.write_text(requirements_hash())


def warn_missing_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            say("warning: {} not found on PATH; masking will not work until it is installed (see README)".format(tool))
    if not (os.environ.get("CONDA_EXE") or shutil.which("conda")):
        say("warning: conda not found; Track (TRex) will not work until conda and TRex are installed (see README)")


def main():
    args = sys.argv[1:]
    try:
        ensure_venv()
    except subprocess.CalledProcessError as e:
        sys.exit("Setup failed: {}".format(e))
    warn_missing_tools()
    if "--setup-only" in args:
        say("setup complete")
        return 0
    env = dict(os.environ)
    env.setdefault(LOGLEVEL_VAR, "8")
    return subprocess.call([str(venv_python()), "-m", "mask_and_count"] + args, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    sys.exit(main())
