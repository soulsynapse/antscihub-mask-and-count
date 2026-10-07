"""Folder scanning and per-video status, derived from files in the output folder."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .boxes import load_squares

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".mpg", ".mpeg", ".wmv", ".mts", ".m2ts"}
OUTPUT_DIRNAME = "mask_and_count_output"


@dataclass(frozen=True)
class Video:
    source: Path

    @property
    def output_dir(self) -> Path:
        return self.source.parent / OUTPUT_DIRNAME

    @property
    def boxes_path(self) -> Path:
        return self.output_dir / f"{self.source.stem}.boxes.json"

    @property
    def masked_path(self) -> Path:
        return self.output_dir / f"{self.source.stem}_masked.mp4"

    @property
    def mask_png_path(self) -> Path:
        return self.output_dir / f"{self.source.stem}_mask.png"

    @property
    def mask_meta_path(self) -> Path:
        """What the masked video was made from; written only after a successful encode."""
        return self.output_dir / f"{self.source.stem}_masked.json"

    @property
    def trex_dir(self) -> Path:
        return self.output_dir / f"{self.source.stem}_trex"

    def has_boxes(self) -> bool:
        return self.boxes_path.is_file()

    def box_count(self) -> int:
        """Squares saved for this video (0 if none). Raises if the file is unreadable."""
        return len(load_squares(self.boxes_path))

    def has_masked(self) -> bool:
        return self.masked_path.is_file()

    def mask_state(self) -> str:
        """'none', 'ok', or 'stale' (boxes changed or removed since the masked video was made)."""
        if not self.masked_path.is_file():
            return "none"
        try:
            made_from = json.loads(self.mask_meta_path.read_text(encoding="utf-8"))["boxes_sha256"]
        except (OSError, ValueError, KeyError):
            return "ok"  # no record to compare against; trust the file
        return "ok" if made_from == boxes_digest(self) else "stale"

    def has_tracking(self) -> bool:
        return self.trex_dir.is_dir() and any(self.trex_dir.rglob("*.csv"))


def boxes_digest(video: Video) -> str | None:
    """Hash of the boxes file (squares and mask border), or None if there is none."""
    try:
        return hashlib.sha256(video.boxes_path.read_bytes()).hexdigest()
    except OSError:
        return None


def scan_folder(folder: Path) -> list[Video]:
    """Video files directly inside `folder` (non-recursive), sorted by name."""
    return [
        Video(p)
        for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]


def ensure_not_source(target: Path, videos: list[Video]) -> None:
    """Raise if `target` would overwrite a source video. Call before every write."""
    resolved = target.resolve()
    for v in videos:
        if v.source.resolve() == resolved:
            raise PermissionError(f"Refusing to overwrite source video: {v.source}")
