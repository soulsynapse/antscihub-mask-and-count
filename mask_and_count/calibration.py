"""Interactive calibration for TRex parameters: scale bar, ant body lengths, threshold.

The threshold overlay and blob areas approximate TRex's background-subtraction
conversion (|frame − background| > threshold, background = per-pixel median of frames
sampled across the video). They are a guide for choosing values, not TRex's own output.
"""

import math

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .box_editor import FrameReader
from .videos import Video

BACKGROUND_SAMPLES = 25
# Conversion (detect_size_filter) is deliberately generous: what it drops never reaches the
# .pv. Lower bound removes specks but keeps small workers; upper keeps clumps of touching
# ants, which TRex can split later. Tracking-time filtering is left to TRex's GUI.
CONVERT_RANGE_FACTORS = (0.25, 50.0)  # × smallest, × largest measured ant blob
TRACK_RANGE_FACTORS = (0.5, 1.5)  # shown for reference only, for tuning track_size_filter in TRex
SCALE_COLOR = QColor(255, 200, 0)
ANT_COLOR = QColor(0, 230, 120)
PREVIEW_COLOR = QColor(255, 80, 80)
ZOOMS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def estimate_background(reader: FrameReader, frame_count: int, samples: int = BACKGROUND_SAMPLES) -> np.ndarray:
    """Per-pixel median of grayscale frames spread over the video. Moving ants drop out."""
    idx = np.linspace(0, max(0, frame_count - 2), samples).round().astype(int)
    frames = []
    for i in idx:
        f = reader.read_array(int(i))
        if f is not None:
            frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
        QApplication.processEvents()
    if not frames:
        raise OSError("No frames could be decoded to estimate the background.")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def blob_under_line(binary: np.ndarray, p1: QPointF, p2: QPointF) -> tuple[int, np.ndarray | None]:
    """Area (px) of the above-threshold component the line crosses most, and its mask."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    steps = max(2, int(math.hypot(p2.x() - p1.x(), p2.y() - p1.y())))
    h, w = binary.shape
    hits: dict[int, int] = {}
    for t in np.linspace(0, 1, steps):
        x = int(round(p1.x() + (p2.x() - p1.x()) * t))
        y = int(round(p1.y() + (p2.y() - p1.y()) * t))
        if 0 <= x < w and 0 <= y < h and labels[y, x]:
            hits[labels[y, x]] = hits.get(labels[y, x], 0) + 1
    if not hits:
        return 0, None
    best = max(hits, key=hits.get)
    return int(stats[best, cv2.CC_STAT_AREA]), labels == best


class LineCanvas(QWidget):
    """Frame at a chosen zoom with overlay and lines; two clicks draw a line."""

    line_drawn = Signal(QPointF, QPointF)  # video px
    remove_last = Signal()

    def __init__(self, frame_w: int, frame_h: int, parent=None):
        super().__init__(parent)
        self.frame_w, self.frame_h = frame_w, frame_h
        self.zoom = 1.0
        self.image: QImage | None = None
        self.overlay: QImage | None = None
        self.lines: list[tuple[QPointF, QPointF, QColor, str]] = []
        self._anchor: QPointF | None = None
        self._cursor: QPointF | None = None
        self.preview_color = ANT_COLOR
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.set_zoom(1.0)

    def scale(self) -> float:
        return self.zoom / self.devicePixelRatioF()

    def set_zoom(self, zoom: float):
        self.zoom = zoom
        s = self.scale()
        self.setFixedSize(round(self.frame_w * s), round(self.frame_h * s))
        self.update()

    def _to_video(self, p: QPointF) -> QPointF:
        s = self.scale()
        return QPointF(min(max(p.x() / s, 0), self.frame_w), min(max(p.y() / s, 0), self.frame_h))

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            if self._anchor is not None:
                self._anchor = None
            else:
                self.remove_last.emit()
            self.update()
            return
        if e.button() != Qt.LeftButton:
            return
        p = self._to_video(e.position())
        if self._anchor is None:
            self._anchor = p
        else:
            a, self._anchor = self._anchor, None
            if math.hypot(p.x() - a.x(), p.y() - a.y()) >= 2:
                self.line_drawn.emit(a, p)
        self.update()

    def mouseMoveEvent(self, e):
        self._cursor = self._to_video(e.position())
        if self._anchor is not None:
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._anchor = None
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        s = self.scale()
        target = QRectF(0, 0, self.frame_w * s, self.frame_h * s)
        p.fillRect(self.rect(), Qt.black)
        if self.image is not None:
            p.drawImage(target, self.image)
        if self.overlay is not None:
            p.drawImage(target, self.overlay)
        p.setRenderHint(QPainter.Antialiasing)
        px = 2.0 / self.devicePixelRatioF()
        for a, b, color, label in self.lines:
            p.setPen(QPen(color, px))
            p.drawLine(QPointF(a.x() * s, a.y() * s), QPointF(b.x() * s, b.y() * s))
            for q in (a, b):
                p.drawEllipse(QPointF(q.x() * s, q.y() * s), 3, 3)
            p.drawText(QPointF(b.x() * s + 5, b.y() * s - 5), label)
        if self._anchor is not None and self._cursor is not None:
            p.setPen(QPen(self.preview_color, px, Qt.DashLine))
            a, c = self._anchor, self._cursor
            p.drawLine(QPointF(a.x() * s, a.y() * s), QPointF(c.x() * s, c.y() * s))


class CalibrationDialog(QDialog):
    """Returns suggested TRex values in `self.result_values` when accepted."""

    def __init__(self, video: Video, threshold: int, meta_real_width: float | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Calibrate from video — {video.source.name}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setWindowState(Qt.WindowMaximized)
        self.reader = FrameReader(video.source)
        self.frame_w, self.frame_h = self.reader.width, self.reader.height
        self.result_values: dict = {}
        self.scale_line: tuple[QPointF, QPointF] | None = None
        self.ants: list[tuple[QPointF, QPointF]] = []
        self.gray: np.ndarray | None = None
        self.background: np.ndarray | None = None
        self.binary: np.ndarray | None = None
        # A saved frame width gives the scale before any scale line is drawn.
        self.cm_per_px_from_settings = meta_real_width / self.frame_w if meta_real_width else None

        self.canvas = LineCanvas(self.frame_w, self.frame_h)
        self.canvas.line_drawn.connect(self._line_drawn)
        self.canvas.remove_last.connect(self._remove_last)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.viewport().setStyleSheet("background: black;")
        self.scroll = scroll

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.reader.frame_count - 1)
        self.slider.setValue(self.reader.frame_count // 2)
        self._seek_timer = QTimer(self, singleShot=True, interval=60)
        self._seek_timer.timeout.connect(self._load_frame)
        self.slider.valueChanged.connect(lambda _: self._seek_timer.start())
        self.frame_label = QLabel()
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems([f"{round(z * 100)} %" for z in ZOOMS])
        self.zoom_combo.setCurrentIndex(ZOOMS.index(1.0))
        self.zoom_combo.currentIndexChanged.connect(self._zoom_changed)
        seek_row = QHBoxLayout()
        seek_row.addWidget(self.slider, 1)
        seek_row.addWidget(self.frame_label)
        seek_row.addWidget(QLabel("Zoom"))
        seek_row.addWidget(self.zoom_combo)
        left = QVBoxLayout()
        left.addWidget(scroll, 1)
        left.addLayout(seek_row)

        # Right panel
        self.mode_scale = QRadioButton("Scale line: across something of known length")
        self.mode_ant = QRadioButton("Ant: tip of head → end of gaster")
        self.mode_ant.setChecked(True)
        modes = QButtonGroup(self)
        for b in (self.mode_scale, self.mode_ant):
            modes.addButton(b)
            b.toggled.connect(self._mode_changed)
        self.known_cm = QDoubleSpinBox()
        self.known_cm.setRange(0, 10000)
        self.known_cm.setDecimals(2)
        self.known_cm.setSuffix(" cm")
        self.known_cm.setSpecialValueText("length?")
        self.known_cm.valueChanged.connect(self._update_results)
        draw_box = QGroupBox("1 · Draw (click start, click end; right-click removes the last line)")
        dl = QVBoxLayout(draw_box)
        dl.addWidget(self.mode_scale)
        row = QHBoxLayout()
        row.addSpacing(20)
        row.addWidget(QLabel("Known length"))
        row.addWidget(self.known_cm, 1)
        dl.addLayout(row)
        dl.addWidget(self.mode_ant)
        hint = QLabel("Measure several ants not touching others, including the smallest ones; the "
                      "size range is built from the smallest and largest you measure.")
        hint.setWordWrap(True)
        dl.addWidget(hint)

        self.thr_slider = QSlider(Qt.Horizontal)
        self.thr_slider.setRange(1, 120)
        self.thr_slider.setValue(threshold)
        self.thr_label = QLabel()
        self.thr_slider.valueChanged.connect(self._threshold_changed)
        thr_box = QGroupBox("2 · Threshold (magenta = would be detected)")
        tl = QVBoxLayout(thr_box)
        trow = QHBoxLayout()
        trow.addWidget(self.thr_slider, 1)
        trow.addWidget(self.thr_label)
        tl.addLayout(trow)
        note = QLabel("Estimate of TRex's background subtraction: |frame − median background| > "
                      "threshold. This is the conversion threshold: anything below it never reaches "
                      "TRex, so keep it low enough that the smallest ants stay mostly whole. "
                      "Leftover specks are removed by the size range.")
        note.setWordWrap(True)
        tl.addWidget(note)

        self.results = QLabel()
        self.results.setWordWrap(True)
        self.results.setTextFormat(Qt.RichText)
        res_box = QGroupBox("3 · Results")
        rl = QVBoxLayout(res_box)
        rl.addWidget(self.results)

        self.apply_btn = QPushButton("Apply to settings")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_btn)

        right = QVBoxLayout()
        for w in (draw_box, thr_box, res_box):
            right.addWidget(w)
        right.addStretch(1)
        right.addLayout(buttons)
        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setFixedWidth(400)

        root = QHBoxLayout(self)
        root.addLayout(left, 1)
        root.addWidget(right_w)

        QTimer.singleShot(0, self._start)

    # --- view -----------------------------------------------------------------

    def _view_center(self) -> QPointF:
        """Centre of the visible region, in video px."""
        s, vp = self.canvas.scale(), self.scroll.viewport()
        h, v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        return QPointF((h.value() + vp.width() / 2) / s, (v.value() + vp.height() / 2) / s)

    def _center_on(self, c: QPointF):
        s, vp = self.canvas.scale(), self.scroll.viewport()
        self.scroll.horizontalScrollBar().setValue(round(c.x() * s - vp.width() / 2))
        self.scroll.verticalScrollBar().setValue(round(c.y() * s - vp.height() / 2))

    def _zoom_changed(self, i: int):
        c = self._view_center()
        self.canvas.set_zoom(ZOOMS[i])
        # Scroll ranges update after the resize is processed.
        QTimer.singleShot(0, lambda: self._center_on(c))

    # --- data -----------------------------------------------------------------

    def _start(self):
        self.results.setText("Estimating background from the video…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.background = estimate_background(self.reader, self.reader.frame_count)
        except OSError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Could not read video", str(e))
            self.reject()
            return
        QApplication.restoreOverrideCursor()
        self._load_frame()
        self._center_on(QPointF(self.frame_w / 2, self.frame_h / 2))

    def _load_frame(self):
        i = self.slider.value()
        frame = self.reader.read_array(i)
        self.frame_label.setText(f"frame {i}" + ("" if frame is not None else " (not decodable)"))
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.canvas.image = QImage(rgb.data, self.frame_w, self.frame_h, 3 * self.frame_w,
                                   QImage.Format_RGB888).copy()
        self.gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._threshold_changed()

    def _threshold_changed(self, *_):
        thr = self.thr_slider.value()
        self.thr_label.setText(str(thr))
        if self.gray is None or self.background is None:
            return
        diff = cv2.absdiff(self.gray, self.background)
        self.binary = (diff > thr).astype(np.uint8)
        rgba = np.zeros((self.frame_h, self.frame_w, 4), np.uint8)
        rgba[self.binary > 0] = (255, 0, 255, 110)
        for a, b in self.ants:
            _, mask = blob_under_line(self.binary, a, b)
            if mask is not None:
                rgba[mask] = (0, 230, 120, 140)
        self.canvas.overlay = QImage(rgba.data, self.frame_w, self.frame_h, 4 * self.frame_w,
                                     QImage.Format_RGBA8888).copy()
        self._update_results()

    # --- lines ----------------------------------------------------------------

    def _mode_changed(self, *_):
        self.canvas.preview_color = SCALE_COLOR if self.mode_scale.isChecked() else ANT_COLOR

    def _line_drawn(self, a: QPointF, b: QPointF):
        if self.mode_scale.isChecked():
            self.scale_line = (a, b)
            if not self.known_cm.value():
                self.known_cm.setFocus()
        else:
            self.ants.append((a, b))
        self._threshold_changed()

    def _remove_last(self):
        if self.mode_ant.isChecked() and self.ants:
            self.ants.pop()
        elif self.mode_scale.isChecked():
            self.scale_line = None
        self._threshold_changed()

    @staticmethod
    def _length(line) -> float:
        a, b = line
        return math.hypot(b.x() - a.x(), b.y() - a.y())

    def cm_per_px(self) -> float | None:
        if self.scale_line is not None and self.known_cm.value() > 0:
            return self.known_cm.value() / self._length(self.scale_line)
        return self.cm_per_px_from_settings

    def _update_results(self, *_):
        cpp = self.cm_per_px()
        lines = []
        canvas_lines = []
        if self.scale_line is not None:
            px = self._length(self.scale_line)
            canvas_lines.append((*self.scale_line, SCALE_COLOR, f"{px:.0f} px"))
        if cpp:
            src = "scale line" if self.scale_line is not None and self.known_cm.value() else "saved frame width"
            lines.append(f"Scale ({src}): 1 px = {cpp:.5f} cm → frame width "
                         f"<b>{self.frame_w * cpp:.2f} cm</b> (meta_real_width)")
        else:
            lines.append("Scale: not set. Draw a scale line and enter its length to get cm values.")
        areas = []
        for n, ant in enumerate(self.ants, 1):
            area = blob_under_line(self.binary, *ant)[0] if self.binary is not None else 0
            areas.append(area)
            canvas_lines.append((*ant, ANT_COLOR, str(n)))
        if self.ants:
            lens = [self._length(a) for a in self.ants]
            rows = []
            for n, (ln, ar) in enumerate(zip(lens, areas), 1):
                cm = f", {ln * cpp:.3f} cm, {ar * cpp * cpp:.4f} cm²" if cpp else ""
                rows.append(f"{n}: {ln:.0f} px long, blob {ar} px²{cm}" + ("" if ar else " (no blob under the line)"))
            lines.append("Ants:<br>" + "<br>".join(rows))
            good = [a for a in areas if a > 0]
            if good and cpp:
                c2 = cpp * cpp
                clo, chi = min(good) * CONVERT_RANGE_FACTORS[0] * c2, max(good) * CONVERT_RANGE_FACTORS[1] * c2
                tlo, thi = min(good) * TRACK_RANGE_FACTORS[0] * c2, max(good) * TRACK_RANGE_FACTORS[1] * c2
                lines.append(f"Conversion size range (applied): <b>[{clo:.4f}, {chi:.4f}] cm²</b> "
                             f"({CONVERT_RANGE_FACTORS[0]:g}× smallest to {CONVERT_RANGE_FACTORS[1]:g}× largest "
                             "blob, so small ants and clumps of touching ants are kept)")
                lines.append(f"For tuning in TRex, single-ant range ≈ [{tlo:.4f}, {thi:.4f}] cm² "
                             "(track_size_filter; not applied here)")
            mean_len = sum(lens) / len(lens)
            lines.append(f"Mean body length {mean_len:.0f} px" + (f" = {mean_len * cpp:.3f} cm" if cpp else ""))
        else:
            lines.append("Ants: none measured yet.")
        lines.append(f"Threshold: <b>{self.thr_slider.value()}</b>")
        self.canvas.lines = canvas_lines
        self.canvas.update()
        self.results.setText("<br><br>".join(lines))

    # --- apply ----------------------------------------------------------------

    def _apply(self):
        thr = self.thr_slider.value()
        values = {"detect_threshold": thr}  # tracking threshold is tuned in TRex
        cpp = self.cm_per_px()
        if self.scale_line is not None and self.known_cm.value() > 0:
            values["meta_real_width"] = round(self.frame_w * cpp, 3)
        good = [blob_under_line(self.binary, *a)[0] for a in self.ants] if self.binary is not None else []
        good = [a for a in good if a > 0]
        if good and cpp:
            values["detect_size_filter"] = [round(min(good) * CONVERT_RANGE_FACTORS[0] * cpp * cpp, 5),
                                            round(max(good) * CONVERT_RANGE_FACTORS[1] * cpp * cpp, 5)]
        self.result_values = values
        self.accept()

    def done(self, result):
        self.reader.close()
        super().done(result)
