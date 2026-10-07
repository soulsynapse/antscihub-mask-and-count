"""Folder scanning and per-video status, derived from files in the output folder."""

from dataclasses import dataclass
from pathlib import Path

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
    def trex_dir(self) -> Path:
        return self.output_dir / f"{self.source.stem}_trex"

    def has_boxes(self) -> bool:
        return self.boxes_path.is_file()

    def has_masked(self) -> bool:
        return self.masked_path.is_file()

    def has_tracking(self) -> bool:
        return self.trex_dir.is_dir() and any(self.trex_dir.rglob("*.csv"))


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
