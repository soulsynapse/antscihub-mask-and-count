"""Masked-video preview/settings window, and the batch runner behind "Mask all videos"."""

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .boxes import load_box_file
from .folder_settings import load_folder_settings, save_folder_settings
from .masking import (
    DEINTERLACE_CHOICES,
    PRESETS,
    MaskJob,
    MaskSettings,
    find_tool,
    preview_args,
    probe,
    write_mask_png,
)
from .videos import Video

FIELD_ORDER_TEXT = {
    "progressive": "progressive",
    "tt": "interlaced, top field first",
    "bb": "interlaced, bottom field first",
    "tb": "interlaced (tb)",
    "bt": "interlaced (bt)",
}
STATE_TEXT = {"none": "not made yet", "ok": "up to date", "stale": "stale — boxes changed since it was made"}


def save_mask_settings(folder: Path, settings: MaskSettings) -> None:
    save_folder_settings(folder, **settings.to_folder(), mask_settings_confirmed=True)


class MaskWindow(QDialog):
    """Preview one video with the mask applied, adjust the folder's mask settings, and encode.

    With `batch` set, this is the settings step of "Mask all videos": the main button saves
    the settings and accepts, and the caller runs the batch.
    """

    def __init__(self, video: Video, all_videos: list[Video], batch: list[Video] | None = None, parent=None):
        super().__init__(parent)
        self.video = video
        self.all_videos = all_videos
        self.batch = batch
        self.folder = video.source.parent
        self.info = probe(video.source)  # raises if ffprobe is missing or the file is unreadable
        self.squares, border = load_box_file(video.boxes_path)
        self.job: MaskJob | None = None

        self._tmp = Path(tempfile.mkdtemp(prefix="mask_preview_"))
        self._preview_mask = write_mask_png(video, all_videos, self.info.width, self.info.height,
                                            self._tmp / "mask.png")
        self._ffmpeg = find_tool("ffmpeg")
        self._preview_proc: QProcess | None = None
        self._preview_img: QImage | None = None
        self._rerender = False

        title = "Mask all videos — settings" if batch else f"Masked video — {video.source.name}"
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setWindowState(Qt.WindowMaximized)

        # Left: preview + seek bar
        self.preview = QLabel("Rendering…")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: black; color: #bbb;")
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.info.frame_count - 1)
        self.slider.setValue(self.info.frame_count // 2)
        self.frame_label = QLabel()
        self.frame_label.setMinimumWidth(200)
        self._seek_timer = QTimer(self, singleShot=True, interval=150)
        self._seek_timer.timeout.connect(self._render)
        self.slider.valueChanged.connect(lambda _: self._seek_timer.start())
        seek_row = QHBoxLayout()
        seek_row.addWidget(self.slider, 1)
        seek_row.addWidget(self.frame_label)
        left = QVBoxLayout()
        left.addWidget(self.preview, 1)
        left.addLayout(seek_row)

        # Right: video facts, folder settings, action
        facts = QFormLayout()
        facts.addRow("Video", QLabel(video.source.name))
        facts.addRow("Frame", QLabel(f"{self.info.width} × {self.info.height}, {self.info.fps:.3f} fps"))
        facts.addRow("Scan", QLabel(FIELD_ORDER_TEXT.get(self.info.field_order, self.info.field_order)))
        facts.addRow("Squares", QLabel(f"{len(self.squares)}, mask border {border or 0:+d} %"))
        facts_box = QGroupBox("This video")
        facts_box.setLayout(facts)

        current = MaskSettings.from_folder(load_folder_settings(self.folder))
        self.deint_combo = QComboBox()
        self.deint_combo.addItems(DEINTERLACE_CHOICES)
        self.deint_combo.setCurrentText(current.deinterlace)
        self.deint_combo.setToolTip(
            "auto: deinterlace when ffprobe reports interlaced video (e.g. 1080i AVCHD).\n"
            "Uses bwdif, one output frame per input frame, so frame numbers match the original."
        )
        self.deint_combo.currentTextChanged.connect(self._settings_changed)
        self.deint_resolved = QLabel()
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 51)
        self.crf_spin.setValue(current.crf)
        self.crf_spin.setToolTip("H.264 quality: lower is better and larger. 18 is visually near-lossless.")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS)
        self.preset_combo.setCurrentText(current.preset)
        self.preset_combo.setToolTip("Encode speed vs file size. Slower presets give smaller files at the same CRF.")
        settings_form = QFormLayout()
        settings_form.addRow("Deinterlace", self.deint_combo)
        settings_form.addRow("", self.deint_resolved)
        settings_form.addRow("Quality (CRF)", self.crf_spin)
        settings_form.addRow("Speed preset", self.preset_combo)
        settings_box = QGroupBox("Mask settings (shared by this folder)")
        settings_box.setLayout(settings_form)

        right = QVBoxLayout()
        right.addWidget(facts_box)
        right.addWidget(settings_box)

        if batch:
            names = "\n".join(f"• {v.source.name}" for v in batch)
            todo = QLabel(f"{len(batch)} video(s) will be masked with these settings:\n{names}")
            todo.setWordWrap(True)
            right.addWidget(todo)
            right.addStretch(1)
            go = QPushButton(f"Save settings && mask all {len(batch)}")
            go.setDefault(True)
            go.clicked.connect(self._confirm_batch)
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            buttons.addWidget(cancel)
            buttons.addWidget(go)
            right.addLayout(buttons)
        else:
            self.state_label = QLabel()
            self.state_label.setWordWrap(True)
            out_label = QLabel(str(video.masked_path))
            out_label.setWordWrap(True)
            out_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.progress = QProgressBar()
            self.progress.setVisible(False)
            self.generate_btn = QPushButton("Generate masked video")
            self.generate_btn.setDefault(True)
            self.generate_btn.clicked.connect(self._generate)
            self.cancel_encode_btn = QPushButton("Cancel encode")
            self.cancel_encode_btn.setVisible(False)
            self.cancel_encode_btn.clicked.connect(lambda: self.job and self.job.cancel())
            close = QPushButton("Close")
            close.clicked.connect(self.reject)
            out_layout = QVBoxLayout()
            out_layout.addWidget(out_label)
            out_layout.addWidget(self.state_label)
            out_layout.addWidget(self.progress)
            out_box = QGroupBox("Output")
            out_box.setLayout(out_layout)
            right.addWidget(out_box)
            right.addStretch(1)
            buttons = QHBoxLayout()
            buttons.addWidget(self.cancel_encode_btn)
            buttons.addStretch(1)
            buttons.addWidget(close)
            buttons.addWidget(self.generate_btn)
            right.addLayout(buttons)
            self._update_state()

        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setFixedWidth(380)
        root = QHBoxLayout(self)
        root.addLayout(left, 1)
        root.addWidget(right_w)

        self._settings_changed()

    # --- settings -----------------------------------------------------------

    def settings(self) -> MaskSettings:
        return MaskSettings(self.deint_combo.currentText(), self.crf_spin.value(), self.preset_combo.currentText())

    def _settings_changed(self, *_):
        on = self.settings().resolve_deinterlace(self.info)
        self.deint_resolved.setText(f"→ {'on' if on else 'off'} for this video")
        self._render()

    # --- preview ------------------------------------------------------------

    def _render(self):
        if self._preview_proc is not None and self._preview_proc.state() != QProcess.NotRunning:
            self._rerender = True  # render the latest request once the current one finishes
            return
        i = self.slider.value()
        t = i / self.info.fps
        self.frame_label.setText(f"frame {i} / {self.info.frame_count - 1}  {t:.2f} s")
        deint = self.settings().resolve_deinterlace(self.info)
        self._preview_proc = QProcess(self)
        self._preview_proc.finished.connect(self._preview_done)
        self._preview_proc.start(self._ffmpeg, preview_args(self.video.source, self._preview_mask, t, deint))

    def _preview_done(self, exit_code, _status):
        proc = self._preview_proc
        data = bytes(proc.readAllStandardOutput())
        if exit_code == 0 and data:
            self._preview_img = QImage.fromData(data, "PNG")
            self._show_preview()
        else:
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            self.preview.setText(f"Preview failed:\n{err[-500:]}")
        if self._rerender:
            self._rerender = False
            self._render()

    def _show_preview(self):
        if self._preview_img is None or self._preview_img.isNull():
            return
        dpr = self.preview.devicePixelRatioF()
        pm = QPixmap.fromImage(self._preview_img).scaled(
            self.preview.size() * dpr, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        pm.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pm)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show_preview()

    # --- actions ------------------------------------------------------------

    def _confirm_batch(self):
        try:
            save_mask_settings(self.folder, self.settings())
        except OSError as e:
            QMessageBox.critical(self, "Could not save settings", str(e))
            return
        self.accept()

    def _update_state(self):
        self.state_label.setText(f"Status: {STATE_TEXT[self.video.mask_state()]}")

    def _generate(self):
        if self.video.has_masked():
            answer = QMessageBox.question(self, "Replace masked video?",
                                          "A masked video already exists for this video. Replace it?")
            if answer != QMessageBox.Yes:
                return
        try:
            save_mask_settings(self.folder, self.settings())
        except OSError as e:
            QMessageBox.critical(self, "Could not save settings", str(e))
            return
        self.job = MaskJob(self.video, self.all_videos, self.settings(), self)
        self.job.progress.connect(lambda f: self.progress.setValue(round(f * 100)))
        self.job.finished.connect(self._encode_done)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_encode_btn.setVisible(True)
        for w in (self.generate_btn, self.deint_combo, self.crf_spin, self.preset_combo):
            w.setEnabled(False)
        self.job.start()

    def _encode_done(self, ok: bool, message: str):
        self.job = None
        self.cancel_encode_btn.setVisible(False)
        for w in (self.generate_btn, self.deint_combo, self.crf_spin, self.preset_combo):
            w.setEnabled(True)
        self._update_state()
        if ok:
            QMessageBox.information(self, "Masked video created", message)
        elif message != "Cancelled.":
            QMessageBox.critical(self, "Masking failed", message)
        self.progress.setVisible(False)

    def reject(self):
        if self.job is not None:
            answer = QMessageBox.question(self, "Stop encoding?", "An encode is running. Stop it and close?")
            if answer != QMessageBox.Yes:
                return
            self.job.cancel()
        super().reject()

    def done(self, result):
        if self._preview_proc is not None:
            self._preview_proc.kill()
            self._preview_proc.waitForFinished(2000)
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().done(result)


class BatchMaskDialog(QDialog):
    """Masks `videos` one after another with the folder's saved settings."""

    def __init__(self, videos: list[Video], all_videos: list[Video], settings: MaskSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mask all videos")
        self.resize(640, 420)
        self.queue = list(videos)
        self.total = len(videos)
        self.all_videos = all_videos
        self.settings = settings
        self.job: MaskJob | None = None
        self.results: list[tuple[str, bool, str]] = []
        self._stopping = False

        self.current = QLabel()
        self.video_bar = QProgressBar()
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, self.total)
        self.log = QPlainTextEdit(readOnly=True)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Cancel the current video (its partial output is deleted) and skip the rest.")
        self.stop_btn.clicked.connect(self._stop)
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Settings: {settings.describe()}"))
        layout.addWidget(self.current)
        layout.addWidget(self.video_bar)
        layout.addWidget(QLabel("Overall"))
        layout.addWidget(self.overall_bar)
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        QTimer.singleShot(0, self._next)

    def _next(self):
        if self._stopping or not self.queue:
            self._finish()
            return
        video = self.queue.pop(0)
        n = self.total - len(self.queue)
        self.current.setText(f"Masking {n} of {self.total}: {video.source.name}")
        self.video_bar.setValue(0)
        self.job = MaskJob(video, self.all_videos, self.settings, self)
        self.job.progress.connect(lambda f: self.video_bar.setValue(round(f * 100)))
        self.job.finished.connect(lambda ok, msg, v=video: self._job_done(v, ok, msg))
        self.job.start()

    def _job_done(self, video: Video, ok: bool, message: str):
        self.job = None
        self.results.append((video.source.name, ok, message))
        self.log.appendPlainText(f"{'✔' if ok else '✘'} {video.source.name}" + ("" if ok else f" — {message}"))
        self.overall_bar.setValue(self.total - len(self.queue))
        QTimer.singleShot(0, self._next)

    def _stop(self):
        self._stopping = True
        self.stop_btn.setEnabled(False)
        if self.job is not None:
            self.job.cancel()

    def _finish(self):
        done = sum(ok for _, ok, _ in self.results)
        skipped = len(self.queue)
        self.current.setText(f"Done: {done} masked, {len(self.results) - done} failed"
                             + (f", {skipped} not started" if skipped else ""))
        self.stop_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

    def reject(self):
        if self.job is not None:
            answer = QMessageBox.question(self, "Stop masking?", "Masking is running. Stop it and close?")
            if answer != QMessageBox.Yes:
                return
            self._stopping = True
            self.job.cancel()
        super().reject()
