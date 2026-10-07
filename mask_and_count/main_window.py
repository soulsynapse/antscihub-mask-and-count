from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
from .videos import Video, scan_folder

COLUMNS = ["Video", "Boxes drawn", "Masked video", "Tracked"]


def _status_item(done: bool) -> QTableWidgetItem:
    item = QTableWidgetItem("✔" if done else "—")
    item.setTextAlignment(Qt.AlignCenter)
    return item


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

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.table)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        if folder is not None:
            self.set_folder(folder)

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
            self.table.setItem(row, 1, _status_item(v.has_boxes()))
            self.table.setItem(row, 2, _status_item(v.has_masked()))
            self.table.setItem(row, 3, _status_item(v.has_tracking()))

        self.statusBar().showMessage(f"{len(self.videos)} video(s) found")

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
