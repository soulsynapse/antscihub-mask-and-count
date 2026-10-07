import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .box_editor import BoxEditorDialog
from .folder_settings import load_folder_settings
from .mask_window import BatchMaskDialog, MaskWindow
from .masking import MaskSettings
from .videos import Video, scan_folder

COLUMNS = ["Video", "Boxes drawn", "Masked video", "Tracked"]
MASK_COL = 2
MASK_STATE_TEXT = {"none": "—", "ok": "✔", "stale": "stale"}


LAST_FOLDER_KEY = "last_folder"


def _centered(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item


def _status_item(done: bool) -> QTableWidgetItem:
    return _centered("✔" if done else "—")


def _box_count_item(v: Video) -> QTableWidgetItem:
    try:
        n = v.box_count()
    except (OSError, ValueError, KeyError, TypeError) as e:
        item = _centered("unreadable")
        item.setToolTip(f"{v.boxes_path}\n{e}")
        return item
    return _centered(str(n) if n else "—")


def _safe_box_count(v: Video) -> int:
    try:
        return v.box_count()
    except (OSError, ValueError, KeyError, TypeError):
        return 0


class ColumnButtonBar(QWidget):
    """Buttons pinned above table columns; follows column resizes and horizontal scrolling.

    Must sit directly above the table in the same layout column, so both share an x origin.
    """

    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent)
        self.table = table
        self.buttons: dict[int, QPushButton] = {}
        header = table.horizontalHeader()
        header.sectionResized.connect(self._place)
        header.geometriesChanged.connect(self._place)
        table.horizontalScrollBar().valueChanged.connect(self._place)

    def add(self, col: int, button: QPushButton):
        button.setParent(self)
        self.buttons[col] = button
        self.setFixedHeight(max(b.sizeHint().height() for b in self.buttons.values()))
        self._place()

    def _place(self, *_):
        header = self.table.horizontalHeader()
        for col, b in self.buttons.items():
            x = header.x() + header.sectionViewportPosition(col)
            b.setGeometry(x, 0, header.sectionSize(col), self.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()


class MainWindow(QMainWindow):
    def __init__(self, folder: Path | None = None):
        super().__init__()
        self.setWindowTitle("Mask and Count")
        self.resize(900, 500)

        self.folder: Path | None = None
        self.videos: list[Video] = []

        self.folder_label = QLabel("No folder selected")
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = QPushButton("Open folder…")
        open_btn.clicked.connect(self.choose_folder)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.refresh_btn.setEnabled(False)
        self.boxes_btn = QPushButton("Draw boxes…")
        self.boxes_btn.clicked.connect(self.draw_boxes)
        self.boxes_btn.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(open_btn)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.boxes_btn)
        top.addWidget(self.folder_label, 1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(
            lambda: self.boxes_btn.setEnabled(bool(self.table.selectionModel().selectedRows()))
        )
        self.table.cellDoubleClicked.connect(lambda row, _col: self.draw_boxes(row))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.mask_all_btn = QPushButton("Mask all videos…")
        self.mask_all_btn.setToolTip("Mask every video with boxes whose masked video is missing or stale.")
        self.mask_all_btn.clicked.connect(self.mask_all)
        self.mask_all_btn.setEnabled(False)
        header.setSectionResizeMode(MASK_COL, QHeaderView.Fixed)
        header.resizeSection(MASK_COL, self.mask_all_btn.sizeHint().width() + 16)
        self.table.verticalHeader().setDefaultSectionSize(QPushButton("Open…").sizeHint().height() + 6)
        column_bar = ColumnButtonBar(self.table)
        column_bar.add(MASK_COL, self.mask_all_btn)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(column_bar)
        layout.addWidget(self.table)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        if folder is not None:
            self.set_folder(folder)
        else:
            # Reopen the last folder, silently skipping it if it has since moved or gone.
            last = QSettings().value(LAST_FOLDER_KEY, "")
            if last and Path(last).is_dir():
                self.set_folder(Path(last))

    def choose_folder(self):
        start = str(self.folder) if self.folder else ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose video folder", start)
        if chosen:
            self.set_folder(Path(chosen))

    def set_folder(self, folder: Path):
        if not folder.is_dir():
            QMessageBox.warning(self, "Not a folder", f"{folder} is not a folder.")
            return
        self.folder = folder
        QSettings().setValue(LAST_FOLDER_KEY, str(folder))
        self.folder_label.setText(str(folder))
        self.refresh_btn.setEnabled(True)
        self.refresh()

    def refresh(self):
        if self.folder is None:
            return
        try:
            self.videos = scan_folder(self.folder)
        except OSError as e:
            QMessageBox.critical(self, "Could not read folder", str(e))
            return

        self.table.setRowCount(len(self.videos))
        for row, v in enumerate(self.videos):
            name = QTableWidgetItem(v.source.name)
            name.setToolTip(str(v.source))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, _box_count_item(v))
            self.table.setItem(row, MASK_COL, QTableWidgetItem())
            self.table.setCellWidget(row, MASK_COL, self._mask_cell(row, v))
            self.table.setItem(row, 3, _status_item(v.has_tracking()))

        self.mask_all_btn.setEnabled(any(_safe_box_count(v) for v in self.videos))
        self.statusBar().showMessage(f"{len(self.videos)} video(s) found")

    def _mask_cell(self, row: int, v: Video) -> QWidget:
        state = v.mask_state()
        label = QLabel(MASK_STATE_TEXT[state])
        if state == "stale":
            label.setStyleSheet("color: #c60;")
            label.setToolTip("Boxes changed since this masked video was made.")
        button = QPushButton("Open…")
        button.clicked.connect(lambda: self.open_mask_window(row))
        if not _safe_box_count(v):
            button.setEnabled(False)
            button.setToolTip("Draw boxes first.")
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(6, 1, 4, 1)
        lay.addWidget(label, 1, Qt.AlignCenter)
        lay.addWidget(button)
        return cell

    def draw_boxes(self, row: int | None = None):
        if row is None or isinstance(row, bool):  # clicked() passes a bool
            rows = self.table.selectionModel().selectedRows()
            if not rows:
                return
            row = rows[0].row()
        video = self.videos[row]
        try:
            dialog = BoxEditorDialog(video, self.videos, self)
        except OSError as e:
            QMessageBox.critical(self, "Could not open video", str(e))
            return
        dialog.exec()
        self.refresh()
        self.table.selectRow(row)

    def _mask_window(self, video: Video, batch: list[Video] | None = None) -> MaskWindow | None:
        try:
            return MaskWindow(video, self.videos, batch, self)
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
            QMessageBox.critical(self, "Could not open mask preview", str(e))
            return None

    def open_mask_window(self, row: int):
        window = self._mask_window(self.videos[row])
        if window is not None:
            window.exec()
            self.refresh()

    def mask_all(self):
        drawn = [v for v in self.videos if _safe_box_count(v)]
        todo = [v for v in drawn if v.mask_state() != "ok"]
        if not drawn:
            QMessageBox.information(self, "Mask all videos", "Draw boxes on at least one video first.")
            return
        if not todo:
            QMessageBox.information(self, "Mask all videos",
                                    f"All {len(drawn)} masked video(s) are up to date. "
                                    "Use a row's Open… button to remake one.")
            return

        folder_settings = load_folder_settings(self.folder)
        if folder_settings["mask_settings_confirmed"]:
            settings = MaskSettings.from_folder(folder_settings)
            no_boxes = len(self.videos) - len(drawn)
            box = QMessageBox(self)
            box.setWindowTitle("Mask all videos")
            box.setText(f"Mask {len(todo)} video(s)?")
            box.setInformativeText(
                "\n".join(f"• {v.source.name}" for v in todo)
                + f"\n\nSettings: {settings.describe()}"
                + (f"\n{no_boxes} video(s) without boxes will be skipped." if no_boxes else "")
            )
            go = box.addButton("Mask all", QMessageBox.AcceptRole)
            adjust = box.addButton("Adjust settings…", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(go)
            box.exec()
            if box.clickedButton() is adjust:
                if not self._confirm_settings(todo):
                    return
            elif box.clickedButton() is not go:
                return
        elif not self._confirm_settings(todo):
            return

        settings = MaskSettings.from_folder(load_folder_settings(self.folder))
        BatchMaskDialog(todo, self.videos, settings, self).exec()
        self.refresh()

    def _confirm_settings(self, todo: list[Video]) -> bool:
        """Settings step of Mask all: preview the first video to be masked. True if confirmed."""
        window = self._mask_window(todo[0], batch=todo)
        return window is not None and window.exec() == QDialog.Accepted
