"""Box storage: one JSON file per video, in source-video pixel coordinates."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

FORMAT_VERSION = 1


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


def load_boxes(path: Path) -> list[Box]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Box(**b) for b in data.get("boxes", [])]


def save_boxes(path: Path, boxes: list[Box], frame_size: tuple[int, int], source_name: str) -> None:
    """Write atomically, so a crash mid-write never leaves a half-written file that reads as 'drawn'."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": FORMAT_VERSION,
        "source": source_name,
        "frame_width": frame_size[0],
        "frame_height": frame_size[1],
        "boxes": [asdict(b) for b in boxes],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
