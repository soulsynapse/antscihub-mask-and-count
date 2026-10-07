"""Mask image construction and the ffmpeg runs that produce (and preview) the masked video.

The mask keeps the inside of each mask square (drawn square scaled by the mask border)
and paints everything else opaque black. It is applied as an RGBA overlay: opaque black
outside, fully transparent inside. ffmpeg's overlay repeats the single mask frame for the
whole video.
"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QProcess, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPolygonF

from .boxes import Square, border_factor, load_box_file
from .videos import Video, boxes_digest, ensure_not_source

INTERLACED_FIELD_ORDERS = {"tt", "bb", "tb", "bt"}
PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
DEINTERLACE_CHOICES = ["auto", "on", "off"]


@dataclass(frozen=True)
class MaskSettings:
    """Folder-level encode settings. Stored flat in folder_settings.json under mask_* keys."""

    deinterlace: str = "auto"  # auto = on when ffprobe reports an interlaced field order
    crf: int = 18  # libx264 quality; lower = better/larger. 18 is visually near-lossless.
    preset: str = "fast"  # libx264 speed/size trade-off; does not change quality at a fixed CRF much

    @classmethod
    def from_folder(cls, settings: dict) -> "MaskSettings":
        return cls(
            deinterlace=settings.get("mask_deinterlace", cls.deinterlace),
            crf=int(settings.get("mask_crf", cls.crf)),
            preset=settings.get("mask_preset", cls.preset),
        )

    def to_folder(self) -> dict:
        return {"mask_deinterlace": self.deinterlace, "mask_crf": self.crf, "mask_preset": self.preset}

    def resolve_deinterlace(self, info: "ProbeInfo") -> bool:
        return info.interlaced if self.deinterlace == "auto" else self.deinterlace == "on"

    def describe(self) -> str:
        return f"deinterlace {self.deinterlace}, H.264 CRF {self.crf}, preset {self.preset}"

# Keep ffprobe from flashing a console window when the app runs under pythonw.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"{name} was not found on PATH. Install ffmpeg (see README).")
    return path


@dataclass(frozen=True)
class ProbeInfo:
    width: int
    height: int
    duration: float  # seconds
    fps: float  # output frame rate (frames, not fields)
    field_order: str  # "progressive", "tt", "bb", ... or "unknown"

    @property
    def interlaced(self) -> bool:
        return self.field_order in INTERLACED_FIELD_ORDERS

    @property
    def frame_count(self) -> int:
        return max(1, round(self.duration * self.fps))


def _rate(s: str) -> float:
    num, _, den = s.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> ProbeInfo:
    out = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,field_order,avg_frame_rate,r_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True, creationflags=_NO_WINDOW,
    )
    data = json.loads(out.stdout)
    st = data["streams"][0]
    # avg_frame_rate is the frame rate; r_frame_rate is the field rate for interlaced streams.
    fps = _rate(st.get("avg_frame_rate", "0/0")) or _rate(st.get("r_frame_rate", "0/0")) or 25.0
    return ProbeInfo(
        width=int(st["width"]),
        height=int(st["height"]),
        duration=float(data.get("format", {}).get("duration", 0) or 0),
        fps=fps,
        field_order=st.get("field_order", "unknown"),
    )


def mask_image(squares: list[Square], mask_border_pct: int, width: int, height: int) -> QImage:
    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(Qt.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, False)  # hard edge: a pixel is kept or it is not
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.transparent)
    factor = border_factor(mask_border_pct)
    for sq in squares:
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in sq.scaled(factor).corners()]))
    p.end()
    return img


def filtergraph(deinterlace: bool) -> str:
    src = "[0:v]bwdif=mode=send_frame:parity=auto:deint=all[v];[v]" if deinterlace else "[0:v]"
    return f"{src}[1:v]overlay=0:0:format=auto:eof_action=repeat,format=yuv420p[out]"


def encode_args(src: Path, mask_png: Path, out: Path, deinterlace: bool, settings: MaskSettings) -> list[str]:
    return [
        "-hide_banner", "-nostdin", "-v", "error", "-nostats", "-y",
        "-i", str(src), "-i", str(mask_png),
        "-filter_complex", filtergraph(deinterlace), "-map", "[out]",
        "-c:v", "libx264", "-preset", settings.preset, "-crf", str(settings.crf),
        "-pix_fmt", "yuv420p", "-an",
        "-progress", "pipe:1",
        str(out),
    ]


def preview_args(src: Path, mask_png: Path, seconds: float, deinterlace: bool) -> list[str]:
    """One masked frame as PNG on stdout. Input seeking (-ss before -i) is frame-accurate when decoding."""
    return [
        "-hide_banner", "-nostdin", "-v", "error",
        "-ss", f"{seconds:.6f}", "-i", str(src), "-i", str(mask_png),
        "-filter_complex", filtergraph(deinterlace), "-map", "[out]",
        "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-",
    ]


def write_mask_png(video: Video, all_videos: list[Video], width: int, height: int, path: Path | None = None) -> Path:
    squares, border = load_box_file(video.boxes_path)
    if not squares:
        raise ValueError(f"No boxes drawn for {video.source.name}.")
    path = path or video.mask_png_path
    ensure_not_source(path, all_videos)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not mask_image(squares, border or 0, width, height).save(str(path), "PNG"):
        raise OSError(f"Could not write mask image {path}")
    return path


class MaskJob(QObject):
    """Runs ffmpeg for one video. Writes to a .partial file and renames it only on success."""

    progress = Signal(float)  # 0..1
    finished = Signal(bool, str)  # ok, message

    def __init__(self, video: Video, all_videos: list[Video], settings: MaskSettings, parent=None):
        super().__init__(parent)
        self.video = video
        self.all_videos = all_videos
        self.settings = settings
        self.deinterlace = False
        self.proc: QProcess | None = None
        self._cancelled = False
        self._stderr = b""
        self._duration = 0.0

    @property
    def partial_path(self) -> Path:
        return self.video.masked_path.with_name(self.video.masked_path.stem + ".partial.mp4")

    def start(self):
        try:
            info = probe(self.video.source)
            self.deinterlace = self.settings.resolve_deinterlace(info)
            self._duration = info.duration
            for p in (self.partial_path, self.video.masked_path, self.video.mask_meta_path):
                ensure_not_source(p, self.all_videos)
            mask_png = write_mask_png(self.video, self.all_videos, info.width, info.height)
            self._args = encode_args(self.video.source, mask_png, self.partial_path, self.deinterlace, self.settings)
            ffmpeg = find_tool("ffmpeg")
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
            self.finished.emit(False, str(e))
            return
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read_progress)
        self.proc.readyReadStandardError.connect(self._read_stderr)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self.proc.start(ffmpeg, self._args)

    def cancel(self):
        self._cancelled = True
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            # Synchronous, so _done (which deletes the .partial file) runs even if the
            # window that owns this job is about to close.
            self.proc.waitForFinished(5000)

    def _read_progress(self):
        for line in bytes(self.proc.readAllStandardOutput()).decode(errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key == "out_time_us" and value.strip().isdigit() and self._duration > 0:
                self.progress.emit(min(1.0, int(value) / 1e6 / self._duration))

    def _read_stderr(self):
        self._stderr = (self._stderr + bytes(self.proc.readAllStandardError()))[-4000:]

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self.finished.emit(False, "ffmpeg failed to start.")

    def _done(self, exit_code: int, _status):
        if self._cancelled or exit_code != 0:
            self.partial_path.unlink(missing_ok=True)
            msg = "Cancelled." if self._cancelled else (
                f"ffmpeg exited with code {exit_code}:\n" + self._stderr.decode(errors="replace").strip()
            )
            self.finished.emit(False, msg)
            return
        try:
            os.replace(self.partial_path, self.video.masked_path)
            self.video.mask_meta_path.write_text(json.dumps({
                "boxes_sha256": boxes_digest(self.video),
                "settings": self.settings.to_folder(),
                "deinterlaced": self.deinterlace,
                "ffmpeg_args": self._args,
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, indent=2), encoding="utf-8")
        except OSError as e:
            self.finished.emit(False, str(e))
            return
        self.progress.emit(1.0)
        self.finished.emit(True, str(self.video.masked_path))
