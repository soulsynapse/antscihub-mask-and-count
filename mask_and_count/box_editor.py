"""Pop-over for drawing (possibly rotated) square keep-regions on a video frame."""

import cv2  # decoder log level: see __main__.py
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .boxes import Square, border_factor, load_box_file, save_squares
from .folder_settings import load_folder_settings, save_folder_settings
from .videos import Video, ensure_not_source

MIN_BOX = 4  # side, in video px; smaller squares are treated as stray double-clicks

BOX_COLOR = QColor(0, 220, 255)
SELECTED_COLOR = QColor(255, 200, 0)
PREVIEW_COLOR = QColor(255, 80, 80)
MASK_COLOR = QColor(255, 0, 255)  # the region the mask actually keeps


class FrameReader:
    # OpenCV's seek can land on the wrong frame near the start of a stream: on AVCHD
    # .MTS, seeks to frames 0-19 (the first GOP) all returned frame 18 or 19, while
    # later seeks were exact. Below this index, decode forward from the start instead.
    EXACT_DECODE_BELOW = 64

    def __init__(self, path):
        self.path = str(path)
        self.cap = cv2.VideoCapture(self.path)
        if not self.cap.isOpened():
            raise OSError(f"Could not open video: {path}")
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        # Container-reported; can be off by a few frames for VFR or damaged files.
        self.frame_count = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))

    def read_array(self, index: int):
        """BGR uint8 array for frame `index`, or None if it does not decode."""
        if index < self.EXACT_DECODE_BELOW:
            self.cap.release()
            self.cap = cv2.VideoCapture(self.path)
            for _ in range(index):
                self.cap.grab()
        else:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        return frame if ok else None

    def read(self, index: int) -> QImage | None:
        frame = self.read_array(index)
        if frame is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()

    def close(self):
        self.cap.release()


class FrameView(QWidget):
    """One frame at 100% (one video pixel per physical screen pixel), with boxes overlaid.

    Lives inside a QScrollArea; its size is the frame size in logical pixels.
    """

    box_drawn = Signal(object)  # Square
    remove_last_requested = Signal()
    pan_requested = Signal(QPoint)  # middle-drag delta, in widget pixels

    def __init__(self, frame_w: int, frame_h: int, parent=None):
        super().__init__(parent)
        self.frame_w, self.frame_h = frame_w, frame_h
        self.image: QImage | None = None
        self.boxes: list[Square] = []
        self.selected = -1
        self._anchor: QPoint | None = None
        self._preview: Square | None = None
        self._pan_last: QPoint | None = None
        self.mask_border_pct = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self._apply_size()

    def _apply_size(self):
        s = self.scale()
        self.setFixedSize(round(self.frame_w * s), round(self.frame_h * s))

    def showEvent(self, e):
        self._apply_size()  # DPR is only final once the widget is on a screen
        super().showEvent(e)

    # --- coordinate mapping -------------------------------------------------

    def scale(self) -> float:
        """Logical pixels per video pixel."""
        return 1.0 / self.devicePixelRatioF()

    def _to_video(self, p: QPointF) -> QPoint:
        s = self.scale()
        x, y = round(p.x() / s), round(p.y() / s)
        return QPoint(min(max(x, 0), self.frame_w), min(max(y, 0), self.frame_h))

    def _poly(self, sq: Square) -> QPolygonF:
        s = self.scale()
        return QPolygonF([QPointF(x * s, y * s) for x, y in sq.corners()])

    # --- events -------------------------------------------------------------
    # Squares are drawn with two clicks only: click 1 is one corner, click 2 the
    # opposite corner. The line between them is the diagonal, so it sets both size
    # and rotation. Pressing and dragging does not complete a square.

    def cancel(self):
        self._anchor = None
        self._preview = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._pan_last = e.globalPosition().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton:
            if self._anchor is not None:
                self.cancel()
            else:
                self.remove_last_requested.emit()
            return
        if e.button() != Qt.LeftButton:
            return
        p = self._to_video(e.position())
        if self._anchor is None:
            self._anchor = p
            self._preview = None
        else:
            sq = Square(self._anchor.x(), self._anchor.y(), p.x(), p.y())
            self.cancel()
            if sq.side >= MIN_BOX:
                self.box_drawn.emit(sq)
        self.update()

    def mouseMoveEvent(self, e):
        if self._pan_last is not None:
            g = e.globalPosition().toPoint()
            self.pan_requested.emit(g - self._pan_last)
            self._pan_last = g
        if self._anchor is not None:
            p = self._to_video(e.position())
            self._preview = Square(self._anchor.x(), self._anchor.y(), p.x(), p.y())
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._pan_last = None
            self.setCursor(Qt.CrossCursor)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._anchor is not None:
            self.cancel()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        s = self.scale()
        if self.image is not None:
            p.drawImage(QRectF(0, 0, self.frame_w * s, self.frame_h * s), self.image)
        px = 2.0 / self.devicePixelRatioF()  # two physical pixels, in logical units
        factor = border_factor(self.mask_border_pct)
        for i, sq in enumerate(self.boxes):
            color = SELECTED_COLOR if i == self.selected else BOX_COLOR
            p.setPen(QPen(color, px))
            p.drawPolygon(self._poly(sq))
            if self.mask_border_pct:
                p.setPen(QPen(MASK_COLOR, px, Qt.DashLine))
                p.drawPolygon(self._poly(sq.scaled(factor)))
                p.setPen(QPen(color, px))
            cx, cy = sq.center
            p.drawText(QPointF(cx * s + 3, cy * s - 3), str(i + 1))
        if self._preview is not None:
            p.setPen(QPen(PREVIEW_COLOR, px, Qt.DashLine))
            p.drawPolygon(self._poly(self._preview))
            if self.mask_border_pct:
                p.setPen(QPen(MASK_COLOR, px, Qt.DashLine))
                p.drawPolygon(self._poly(self._preview.scaled(factor)))
            p.setPen(QPen(PREVIEW_COLOR, px, Qt.DotLine))
            a = self._anchor
            p.drawLine(QPointF(a.x() * s, a.y() * s), QPointF(self._preview.x2 * s, self._preview.y2 * s))


class Navigator(QWidget):
    """Thumbnail of the whole frame with the visible region outlined; click or drag to move it."""

    moved = Signal(QPointF)  # requested viewport centre, in video pixels

    def __init__(self, frame_w: int, frame_h: int, width: int = 320, parent=None):
        super().__init__(parent)
        self.frame_w, self.frame_h = frame_w, frame_h
        self.k = width / frame_w  # navigator pixels per video pixel
        self.setFixedSize(width, round(frame_h * self.k))
        self.thumb: QImage | None = None
        self.boxes: list[Square] = []
        self.viewport = QRectF()  # visible region, in video pixels
        self.setCursor(Qt.PointingHandCursor)

    def set_image(self, img: QImage):
        dpr = self.devicePixelRatioF()
        self.thumb = img.scaled(self.size() * dpr, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb.setDevicePixelRatio(dpr)
        self.update()

    def set_viewport(self, r: QRectF):
        self.viewport = r
        self.update()

    def _emit(self, pos: QPointF):
        self.moved.emit(QPointF(pos.x() / self.k, pos.y() / self.k))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._emit(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._emit(e.position())

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        if self.thumb is not None:
            p.drawImage(QPointF(0, 0), self.thumb)
        k = self.k
        p.setPen(QPen(BOX_COLOR, 1.0 / self.devicePixelRatioF()))
        for sq in self.boxes:
            p.drawPolygon(QPolygonF([QPointF(x * k, y * k) for x, y in sq.corners()]))
        v = self.viewport
        p.setPen(QPen(Qt.white, 2))
        p.drawRect(QRectF(v.x() * k, v.y() * k, v.width() * k, v.height() * k).adjusted(1, 1, -1, -1))


class BoxEditorDialog(QDialog):
    COLUMNS = ["#", "centre x", "centre y", "side", "angle °"]

    def __init__(self, video: Video, all_videos: list[Video], parent=None):
        super().__init__(parent)
        self.video = video
        self.all_videos = all_videos
        self.setWindowTitle(f"Draw boxes — {video.source.name}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setWindowState(Qt.WindowMaximized)

        self.reader = FrameReader(video.source)
        self.folder = video.source.parent
        self.boxes, saved_border = load_box_file(video.boxes_path)
        # A video keeps the border it was saved with; otherwise use the folder's default.
        border = saved_border if saved_border is not None else load_folder_settings(self.folder)["mask_border_pct"]
        self.dirty = False
        self._populating = False

        # Left: frame + seek bar
        self.view = FrameView(self.reader.width, self.reader.height)
        self.view.boxes = self.boxes
        self.view.box_drawn.connect(self._add_box)
        self.view.remove_last_requested.connect(self._remove_last)
        self.view.pan_requested.connect(self._pan)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.view)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.viewport().setStyleSheet("background: black;")
        self.hbar = self.scroll.horizontalScrollBar()
        self.vbar = self.scroll.verticalScrollBar()
        # Scroll ranges settle over several layout passes after the maximized show, so keep
        # re-centring on range changes until the user first moves the view themselves.
        self._pending_center: QPointF | None = QPointF(self.reader.width / 2, self.reader.height / 2)
        for bar in (self.hbar, self.vbar):
            bar.valueChanged.connect(self._sync_navigator)
            bar.rangeChanged.connect(self._on_range_changed)
            bar.actionTriggered.connect(self._user_moved)  # wheel, arrows, track, handle drag

        self.navigator = Navigator(self.reader.width, self.reader.height)
        self.navigator.boxes = self.boxes
        self.navigator.moved.connect(self._user_center_on)

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
        left.addWidget(self.scroll, 1)
        left.addLayout(seek_row)

        # Right: parameters + box list
        help_label = QLabel(
            "Click one corner, then the opposite corner: the line between the two clicks "
            "is the square's diagonal, so it sets both size and rotation.\n"
            "Right-click removes the last square (or cancels one in progress; Esc also cancels).\n"
            "Del removes the selected square.\n"
            "Pan with the navigator, middle-drag, or the scroll wheel "
            "(Alt+wheel scrolls sideways). A square in progress survives panning."
        )
        help_label.setWordWrap(True)
        self.border_spin = QSpinBox()
        self.border_spin.setRange(-90, 500)
        self.border_spin.setSuffix(" %")
        self.border_spin.setValue(border)
        self.border_spin.setToolTip(
            "Size of the masked square relative to the drawn one, same centre and rotation.\n"
            "+10 % keeps a square 10 % larger per side; -10 % keeps one 10 % smaller.\n"
            "Remembered for this folder; each video also stores the value it was saved with."
        )
        self.border_spin.valueChanged.connect(self._border_changed)
        self.view.mask_border_pct = border
        border_row = QHBoxLayout()
        border_row.addWidget(QLabel("Mask border"))
        border_row.addWidget(self.border_spin, 1)

        params = QVBoxLayout()
        params.addWidget(QLabel(f"Frame: {self.reader.width} × {self.reader.height} px"))
        params.addLayout(border_row)
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
        # Only an explicit click jumps the view; selecting a just-drawn square must not.
        self.table.cellClicked.connect(lambda row, _c: self._user_center_on(QPointF(*self.boxes[row].center)))

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
        list_box = QGroupBox("Squares (video pixels; editable)")
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

        nav_layout = QVBoxLayout()
        nav_layout.addWidget(self.navigator, 0, Qt.AlignHCenter)
        nav_box = QGroupBox("Navigator")
        nav_box.setLayout(nav_layout)

        right = QVBoxLayout()
        right.addWidget(nav_box)
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

    # --- viewport -----------------------------------------------------------

    def _on_range_changed(self, *_):
        if self._pending_center is not None:
            self._center_on(self._pending_center)
        self._sync_navigator()

    def _user_moved(self, *_):
        self._pending_center = None

    def _user_center_on(self, c: QPointF):
        self._user_moved()
        self._center_on(c)

    def _center_on(self, c: QPointF):
        s = self.view.scale()
        vp = self.scroll.viewport()
        self.hbar.setValue(round(c.x() * s - vp.width() / 2))
        self.vbar.setValue(round(c.y() * s - vp.height() / 2))

    def _pan(self, delta: QPoint):
        self._user_moved()
        self.hbar.setValue(self.hbar.value() - delta.x())
        self.vbar.setValue(self.vbar.value() - delta.y())

    def _sync_navigator(self, *_):
        s = self.view.scale()
        vp = self.scroll.viewport()
        x, y = self.hbar.value() / s, self.vbar.value() / s
        w = min(vp.width() / s, self.reader.width)
        h = min(vp.height() / s, self.reader.height)
        self.navigator.set_viewport(QRectF(x, y, w, h))

    # --- frame --------------------------------------------------------------

    def _show_frame(self):
        i = self.slider.value()
        img = self.reader.read(i)
        if img is not None:
            self.view.image = img
            self.view.update()
            self.navigator.set_image(img)
        t = f"  {i / self.reader.fps:.2f} s" if self.reader.fps else ""
        missing = "  (not decodable)" if img is None else ""
        self.frame_label.setText(f"frame {i} / {self.reader.frame_count - 1}{t}{missing}")

    # --- box list -----------------------------------------------------------

    def _populate_table(self):
        self._populating = True
        self.table.setRowCount(len(self.boxes))
        for row, sq in enumerate(self.boxes):
            num = QTableWidgetItem(str(row + 1))
            num.setFlags(num.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, num)
            for col, val in enumerate((*sq.center, sq.side, sq.angle_deg), start=1):
                self.table.setItem(row, col, QTableWidgetItem(f"{val:.1f}"))
        self._populating = False
        self.view.update()
        self.navigator.update()

    def _add_box(self, sq: Square):
        self.boxes.append(sq)
        self.dirty = True
        self._populate_table()
        self.table.selectRow(len(self.boxes) - 1)

    def _remove_last(self):
        if self.boxes:
            self.boxes.pop()
            self.dirty = True
            self.view.selected = -1
            self._populate_table()

    def _table_edited(self, item: QTableWidgetItem):
        if self._populating:
            return
        row = item.row()
        try:
            cx, cy, side, angle = (float(self.table.item(row, c).text()) for c in range(1, 5))
        except (ValueError, AttributeError):
            self._populate_table()  # revert bad input
            return
        cx = min(max(cx, 0.0), self.reader.width)
        cy = min(max(cy, 0.0), self.reader.height)
        self.boxes[row] = Square.from_center(cx, cy, max(side, MIN_BOX), angle)
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

    def _border_changed(self, pct: int):
        self.view.mask_border_pct = pct
        self.view.update()
        self.dirty = True

    def _save(self):
        path = self.video.boxes_path
        ensure_not_source(path, self.all_videos)
        border = self.border_spin.value()
        try:
            save_folder_settings(self.folder, mask_border_pct=border)
        except OSError as e:
            QMessageBox.critical(self, "Could not save folder settings", str(e))
            return
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
            save_squares(
                path,
                self.boxes,
                (self.reader.width, self.reader.height),
                self.video.source.name,
                border,
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
