"""Pop-over for drawing square keep-regions on a video frame."""

import cv2
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .boxes import Box, load_boxes, save_boxes
from .videos import Video, ensure_not_source

MIN_BOX = 4  # px in video coords; smaller drags are treated as stray clicks

BOX_COLOR = QColor(0, 220, 255)
SELECTED_COLOR = QColor(255, 200, 0)
PREVIEW_COLOR = QColor(255, 80, 80)


class FrameReader:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise OSError(f"Could not open video: {path}")
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        # Container-reported; can be off by a few frames for VFR or damaged files.
        self.frame_count = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))

    def read(self, index: int) -> QImage | None:
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        if not ok:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()

    def close(self):
        self.cap.release()


class FrameView(QWidget):
    """Shows one frame scaled to fit, with boxes overlaid; drag to draw a new box."""

    box_drawn = Signal(QRect)

    def __init__(self, frame_w: int, frame_h: int, parent=None):
        super().__init__(parent)
        self.frame_w, self.frame_h = frame_w, frame_h
        self.image: QImage | None = None
        self.boxes: list[QRect] = []
        self.selected = -1
        self._anchor: QPoint | None = None
        self._preview: QRect | None = None
        self.setMinimumSize(480, 320)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.ClickFocus)

    # --- coordinate mapping -------------------------------------------------

    def _scale_and_offset(self) -> tuple[float, QPointF]:
        s = min(self.width() / self.frame_w, self.height() / self.frame_h)
        off = QPointF((self.width() - self.frame_w * s) / 2, (self.height() - self.frame_h * s) / 2)
        return s, off

    def _to_video(self, p: QPointF) -> QPoint:
        s, off = self._scale_and_offset()
        x = round((p.x() - off.x()) / s)
        y = round((p.y() - off.y()) / s)
        return QPoint(min(max(x, 0), self.frame_w), min(max(y, 0), self.frame_h))

    def _to_widget(self, r: QRect) -> QRectF:
        s, off = self._scale_and_offset()
        return QRectF(off.x() + r.x() * s, off.y() + r.y() * s, r.width() * s, r.height() * s)

    # --- box geometry -------------------------------------------------------

    def _square(self, a: QPoint, b: QPoint) -> QRect:
        """Axis-aligned square anchored at corner `a`, growing toward `b`.

        Side is max(|dx|, |dy|), capped so the square stays inside the frame.
        """
        dx, dy = b.x() - a.x(), b.y() - a.y()
        room_x = self.frame_w - a.x() if dx >= 0 else a.x()
        room_y = self.frame_h - a.y() if dy >= 0 else a.y()
        side = min(max(abs(dx), abs(dy)), room_x, room_y)
        x = a.x() if dx >= 0 else a.x() - side
        y = a.y() if dy >= 0 else a.y() - side
        return QRect(x, y, side, side)

    # --- events -------------------------------------------------------------
    # Corner 1 on press. Corner 2 is either the release point (drag) or, if the
    # press didn't move, the next click — so click-click and drag both work.

    def _finish(self, p: QPoint):
        box = self._square(self._anchor, p)
        self._anchor = None
        self._preview = None
        if box.width() >= MIN_BOX:
            self.box_drawn.emit(box)
        self.update()

    def cancel(self):
        self._anchor = None
        self._preview = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.cancel()
            return
        if e.button() != Qt.LeftButton:
            return
        p = self._to_video(e.position())
        if self._anchor is None:
            self._anchor = p
            self._preview = self._square(p, p)
        else:
            self._finish(p)
        self.update()

    def mouseMoveEvent(self, e):
        if self._anchor is not None:
            self._preview = self._square(self._anchor, self._to_video(e.position()))
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._anchor is None:
            return
        p = self._to_video(e.position())
        if self._square(self._anchor, p).width() >= MIN_BOX:
            self._finish(p)  # it was a drag
        # else: a click; wait for the second corner

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._anchor is not None:
            self.cancel()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        if self.image is not None:
            s, off = self._scale_and_offset()
            p.drawImage(QRectF(off.x(), off.y(), self.frame_w * s, self.frame_h * s), self.image)
        for i, r in enumerate(self.boxes):
            color = SELECTED_COLOR if i == self.selected else BOX_COLOR
            p.setPen(QPen(color, 2))
            wr = self._to_widget(r)
            p.drawRect(wr)
            p.drawText(wr.topLeft() + QPointF(4, 14), str(i + 1))
        if self._preview is not None:
            p.setPen(QPen(PREVIEW_COLOR, 2, Qt.DashLine))
            p.drawRect(self._to_widget(self._preview))


class BoxEditorDialog(QDialog):
    COLUMNS = ["#", "x", "y", "side"]

    def __init__(self, video: Video, all_videos: list[Video], parent=None):
        super().__init__(parent)
        self.video = video
        self.all_videos = all_videos
        self.setWindowTitle(f"Draw boxes — {video.source.name}")
        self.resize(1200, 750)

        self.reader = FrameReader(video.source)
        self.boxes = [QRect(b.x, b.y, b.w, b.h) for b in load_boxes(video.boxes_path)]
        self.dirty = False
        self._populating = False

        # Left: frame + seek bar
        self.view = FrameView(self.reader.width, self.reader.height)
        self.view.boxes = self.boxes
        self.view.box_drawn.connect(self._add_box)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.reader.frame_count - 1)
        self.frame_label = QLabel()
        self.frame_label.setMinimumWidth(170)
        # Seeking compressed video is slow; debounce so dragging the slider stays responsive.
        self._seek_timer = QTimer(self, singleShot=True, interval=40)
        self._seek_timer.timeout.connect(self._show_frame)
        self.slider.valueChanged.connect(lambda _: self._seek_timer.start())

        seek_row = QHBoxLayout()
        seek_row.addWidget(self.slider, 1)
        seek_row.addWidget(self.frame_label)

        left = QVBoxLayout()
        left.addWidget(self.view, 1)
        left.addLayout(seek_row)

        # Right: parameters + box list
        help_label = QLabel(
            "Click corner 1, then corner 2 (or drag) to draw a square.\n"
            "Right-click or Esc cancels a square in progress.\n"
            "Del removes the selected square."
        )
        help_label.setWordWrap(True)
        params = QVBoxLayout()
        params.addWidget(QLabel(f"Frame: {self.reader.width} × {self.reader.height} px"))
        params.addWidget(help_label)
        params_box = QGroupBox("Box parameters")
        params_box.setLayout(params)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemChanged.connect(self._table_edited)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._delete_selected)
        clear_btn = QPushButton("Clear all")
        clear_btn.clicked.connect(self._clear_all)
        list_btns = QHBoxLayout()
        list_btns.addWidget(delete_btn)
        list_btns.addWidget(clear_btn)

        list_layout = QVBoxLayout()
        list_layout.addWidget(self.table)
        list_layout.addLayout(list_btns)
        list_box = QGroupBox("Boxes (video pixels; editable)")
        list_box.setLayout(list_layout)

        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(save_btn)

        right = QVBoxLayout()
        right.addWidget(params_box)
        right.addWidget(list_box, 1)
        right.addLayout(bottom)
        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setFixedWidth(360)

        root = QHBoxLayout(self)
        root.addLayout(left, 1)
        root.addWidget(right_w)

        # Widget-scoped so Delete still works normally inside a cell editor.
        for w in (self.view, self.table):
            QShortcut(QKeySequence.Delete, w, activated=self._delete_selected, context=Qt.WidgetShortcut)

        self._populate_table()
        self._show_frame()

    # --- frame --------------------------------------------------------------

    def _show_frame(self):
        i = self.slider.value()
        img = self.reader.read(i)
        if img is not None:
            self.view.image = img
            self.view.update()
        t = f"  {i / self.reader.fps:.2f} s" if self.reader.fps else ""
        missing = "  (not decodable)" if img is None else ""
        self.frame_label.setText(f"frame {i} / {self.reader.frame_count - 1}{t}{missing}")

    # --- box list -----------------------------------------------------------

    def _populate_table(self):
        self._populating = True
        self.table.setRowCount(len(self.boxes))
        for row, r in enumerate(self.boxes):
            num = QTableWidgetItem(str(row + 1))
            num.setFlags(num.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, num)
            for col, val in enumerate((r.x(), r.y(), r.width()), start=1):
                self.table.setItem(row, col, QTableWidgetItem(str(val)))
        self._populating = False
        self.view.update()

    def _clamp(self, x: int, y: int, side: int) -> QRect:
        """Square of `side` at (x, y), shrunk/shifted as needed to fit the frame."""
        side = min(max(side, MIN_BOX), self.reader.width, self.reader.height)
        x = min(max(x, 0), self.reader.width - side)
        y = min(max(y, 0), self.reader.height - side)
        return QRect(x, y, side, side)

    def _add_box(self, r: QRect):
        self.boxes.append(self._clamp(r.x(), r.y(), r.width()))
        self.dirty = True
        self._populate_table()
        self.table.selectRow(len(self.boxes) - 1)

    def _table_edited(self, item: QTableWidgetItem):
        if self._populating:
            return
        row = item.row()
        try:
            vals = [int(self.table.item(row, c).text()) for c in range(1, 4)]
        except (ValueError, AttributeError):
            self._populate_table()  # revert bad input
            return
        self.boxes[row] = self._clamp(*vals)
        self.dirty = True
        self._populate_table()

    def _selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        self.view.selected = rows[0].row() if rows else -1
        self.view.update()

    def _delete_selected(self):
        i = self.view.selected
        if 0 <= i < len(self.boxes):
            del self.boxes[i]
            self.dirty = True
            self.view.selected = -1
            self._populate_table()

    def _clear_all(self):
        if self.boxes:
            self.boxes.clear()
            self.dirty = True
            self.view.selected = -1
            self._populate_table()

    # --- save / close -------------------------------------------------------

    def _save(self):
        path = self.video.boxes_path
        ensure_not_source(path, self.all_videos)
        if not self.boxes:
            if path.exists():
                answer = QMessageBox.question(
                    self, "Remove boxes?", "No boxes drawn. Remove the saved boxes for this video?"
                )
                if answer != QMessageBox.Yes:
                    return
                path.unlink()
            self.dirty = False
            self.accept()
            return
        try:
            save_boxes(
                path,
                [Box(r.x(), r.y(), r.width(), r.height()) for r in self.boxes],
                (self.reader.width, self.reader.height),
                self.video.source.name,
            )
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return
        self.dirty = False
        self.accept()

    def reject(self):
        if self.dirty:
            answer = QMessageBox.question(self, "Discard changes?", "Discard unsaved boxes?")
            if answer != QMessageBox.Yes:
                return
        super().reject()

    def done(self, result):
        self.reader.close()
        super().done(result)
