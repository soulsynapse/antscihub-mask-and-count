"""Opening a video in TRex with the drawn squares applied as `track_include` polygons.

`track_include` (TRex 2.x): "If this is not empty, objects within the given rectangles
or polygons (>= 3 points) [[x0,y0],[x1,y1](, ...)], ...] will be the only objects being
tracked." It filters detected objects, not pixels, so no re-encode is needed when TRex
can read the source directly.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .boxes import border_factor, load_box_file
from .masking import probe
from .trex_settings import settings_lines
from .videos import Video, ensure_not_source

DEFAULT_CONDA_ENV = "track"
SETTINGS_NAME = "mask_and_count.settings"
LOG_NAME = "trex_launch.log"

# TRex 2.0.0 reads AVCHD transport streams as 0 frames ("length = 0"), converts nothing,
# and quits. Verified on .MTS from this project; .m2ts is the same container.
TREX_UNREADABLE_SUFFIXES = {".mts", ".m2ts"}

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def find_conda() -> str:
    conda = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not conda:
        raise FileNotFoundError("conda was not found (CONDA_EXE unset and conda not on PATH).")
    return conda


def choose_input(video: Video) -> tuple[Path | None, str]:
    """(file to open in TRex, why). None means a masked video must be generated first."""
    state = video.mask_state()
    if state == "ok":
        return video.masked_path, "masked video"
    suffix = video.source.suffix.lower()
    if suffix in TREX_UNREADABLE_SUFFIXES:
        why = f"TRex cannot read {suffix} files (it sees 0 frames)"
    elif probe(video.source).interlaced:
        why = "the video is interlaced, and TRex would track combed frames"
    else:
        return video.source, "original video, squares applied as track_include"
    if state == "stale":
        why += ", and the masked video is stale (boxes changed since it was made)"
    return None, why


def track_include(video: Video) -> str:
    """The mask squares (drawn squares scaled by the mask border) as TRex polygons."""
    squares, border = load_box_file(video.boxes_path)
    if not squares:
        raise ValueError(f"No boxes drawn for {video.source.name}.")
    factor = border_factor(border or 0)
    polys = [
        "[" + ",".join(f"[{x:.1f},{y:.1f}]" for x, y in sq.scaled(factor).corners()) + "]"
        for sq in squares
    ]
    return "[" + ",".join(polys) + "]"


def write_settings(video: Video, all_videos: list[Video]) -> Path:
    """Rewritten on every launch from the folder's TRex parameters plus this video's
    squares, so TRex always gets the current values."""
    path = video.trex_dir / SETTINGS_NAME
    ensure_not_source(path, all_videos)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = settings_lines(video.source.parent)  # the folder's TRex parameters
    # TRex 2.0 did not derive cm_per_pixel from meta_real_width when converting an .mp4:
    # it stayed 1, so cm² size filters were read as px² and every blob was dropped.
    # Write it explicitly, unless the user set it under "other parameters".
    real_width = next((float(l.split("=", 1)[1]) for l in lines if l.startswith("meta_real_width =")), None)
    if real_width and not any(l.startswith("cm_per_pixel =") for l in lines):
        lines.append(f"cm_per_pixel = {real_width / probe(video.source).width:.8g}")
    lines += ["output_format = csv", f"track_include = {track_include(video)}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def conversion_files(video: Video, source: Path) -> list[Path]:
    """TRex's files from an earlier run on `source` in this video's TRex folder.

    If a `<input>.pv` exists, TRex opens it instead of converting again. It may be
    partial (TRex closed mid-conversion) or made with old detection settings, which
    only take effect during conversion.
    """
    d, stem = video.trex_dir, source.stem
    candidates = [d / f"{stem}.pv", d / f"{stem}.results", d / f"{stem}.settings", d / f"average_{stem}.png"]
    return [p for p in candidates if p.exists()]


def clear_conversion(video: Video, source: Path, all_videos: list[Video]) -> None:
    for p in conversion_files(video, source):
        ensure_not_source(p, all_videos)
        p.unlink()


def launch(video: Video, source: Path, all_videos: list[Video], conda_env: str) -> Path:
    """Start TRex (GUI) on `source` without waiting; it converts and tracks with the
    written settings. Returns the log file path."""
    log_path = video.trex_dir / LOG_NAME
    ensure_not_source(log_path, all_videos)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    args = [find_conda(), "run", "-n", conda_env, "--no-capture-output", "trex",
            "-i", str(source), "-s", str(write_settings(video, all_videos)), "-d", str(video.trex_dir)]
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(" ".join(f'"{a}"' if " " in a else a for a in args) + "\n\n")
        log.flush()
        # The TRex window still appears; CREATE_NO_WINDOW only hides conda's console.
        subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=_NO_WINDOW, cwd=str(video.trex_dir))
    return log_path
