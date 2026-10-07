"""Square storage: one JSON file per video, in source-video pixel coordinates."""

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

FORMAT_VERSION = 2


@dataclass(frozen=True)
class Square:
    """A square, possibly rotated, defined by the two ends of one diagonal as clicked.

    Everything else (centre, side, angle, the other two corners) derives from these.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_center(cls, cx: float, cy: float, side: float, angle_deg: float) -> "Square":
        """Inverse of (center, side, angle_deg): rebuilds a canonical diagonal."""
        half = side / math.sqrt(2)
        a = math.radians(angle_deg + 45)
        dx, dy = half * math.cos(a), half * math.sin(a)
        return cls(cx - dx, cy - dy, cx + dx, cy + dy)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    @property
    def diagonal(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def side(self) -> float:
        return self.diagonal / math.sqrt(2)

    @property
    def angle_deg(self) -> float:
        """Rotation of the square's edges from the image axes (y down, so clockwise on screen).

        A square has 90° symmetry, so this is reported in [-45, 45).
        """
        a = math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1)) - 45
        return (a + 45) % 90 - 45

    def scaled(self, factor: float) -> "Square":
        """Same centre and rotation, side multiplied by `factor`."""
        cx, cy = self.center
        return Square(
            cx + (self.x1 - cx) * factor,
            cy + (self.y1 - cy) * factor,
            cx + (self.x2 - cx) * factor,
            cy + (self.y2 - cy) * factor,
        )

    def corners(self) -> list[tuple[float, float]]:
        """Four corners in drawing order: clicked 1, side, clicked 2, side."""
        cx, cy = self.center
        hx, hy = (self.x2 - self.x1) / 2, (self.y2 - self.y1) / 2
        return [(self.x1, self.y1), (cx + hy, cy - hx), (self.x2, self.y2), (cx - hy, cy + hx)]


def border_factor(mask_border_pct: int) -> float:
    """+10 -> mask side 1.10x the drawn side; -10 -> 0.90x."""
    return 1 + mask_border_pct / 100


def load_box_file(path: Path) -> tuple[list[Square], int | None]:
    """Squares and the mask border they were saved with (None if absent or no file)."""
    if not path.is_file():
        return [], None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version", 1) == 1:  # axis-aligned x, y, w, h
        return [Square(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]) for b in data.get("boxes", [])], None
    squares = [Square(*s["p1"], *s["p2"]) for s in data.get("squares", [])]
    return squares, data.get("mask_border_pct")


def load_squares(path: Path) -> list[Square]:
    return load_box_file(path)[0]


def save_squares(
    path: Path,
    squares: list[Square],
    frame_size: tuple[int, int],
    source_name: str,
    mask_border_pct: int,
) -> None:
    """Write atomically, so a crash mid-write never leaves a half-written file that reads as 'drawn'.

    p1/p2 and mask_border_pct are authoritative; the other fields are derived, written for
    downstream readers. `mask_corners` is the region the masking step keeps.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    factor = border_factor(mask_border_pct)
    data = {
        "version": FORMAT_VERSION,
        "source": source_name,
        "frame_width": frame_size[0],
        "frame_height": frame_size[1],
        "mask_border_pct": mask_border_pct,
        "squares": [
            {
                "p1": [s.x1, s.y1],
                "p2": [s.x2, s.y2],
                "center": list(s.center),
                "side": s.side,
                "angle_deg": s.angle_deg,
                "corners": [list(c) for c in s.corners()],
                "mask_side": s.side * factor,
                "mask_corners": [list(c) for c in s.scaled(factor).corners()],
            }
            for s in squares
        ],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
