"""Folder-level TRex tracking parameters and the window for editing them.

Only parameters the user sets are written to TRex's settings file; anything left at
"TRex default" is omitted so TRex's own default applies. Parameter names are those of
TRex 2.0 (checked against the installed binary); help text is TRex's own where it
was unambiguous, otherwise paraphrased.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .folder_settings import load_folder_settings, save_folder_settings
from .trex_help import show_trex_help
from .videos import Video

DEFAULT_TEXT = "TRex default"
UNSET = -1  # spin-box sentinel shown as DEFAULT_TEXT
APP_OWNED_KEYS = {"track_include", "output_format"}  # written per video by trex.write_settings


@dataclass(frozen=True)
class Param:
    key: str
    kind: str  # "int", "float", "bool", "range", "choice"
    label: str
    help: str
    maximum: float = 1e6
    decimals: int = 0
    choices: tuple[str, ...] = ()


PARAMS = [
    Param("detect_type", "choice", "Detection method",
          "How objects are found. background_subtraction: pixels that differ from the "
          "averaged background image. yolo: a neural network model (the default model in "
          "this TRex build detects human poses, so it is not useful for ants without a "
          "custom model).",
          choices=("background_subtraction", "yolo")),
    Param("track_max_individuals", "int", "Number of individuals",
          "How many individuals TRex should keep identities for. 0 means unknown. TRex's "
          "identity features need this to be the real group size."),
    Param("meta_real_width", "float", "Frame width (cm)",
          "Real-world width of the whole video frame in cm. TRex derives cm_per_pixel from "
          "it (meta_real_width / video width), which scales the size filters and the "
          "maximum speed. If unset, TRex assumes 30 cm.", decimals=2),
    Param("detect_threshold", "int", "Conversion threshold",
          "How different a pixel must be from the background to be stored as part of an "
          "object when TRex converts the video (0–255). Pixels below it never reach the "
          ".pv, so keep it generous; changing it means converting again.", maximum=255),
    Param("detect_size_filter", "range", "Conversion size range",
          "Objects outside this range are dropped during conversion and are gone for good. "
          "Keep it wide: the lower bound only removes specks, the upper bound keeps clumps of "
          "touching ants. Sizes are cm² via cm_per_pixel, which the app writes from the frame "
          "width. TRex's own default is [10, 100000] in its units.", decimals=4),
    Param("track_threshold", "int", "Tracking threshold",
          "Threshold applied again during tracking to the converted objects (0–255). "
          "Best left at TRex default and tuned live in TRex after conversion, where it "
          "does not require converting again.", maximum=255),
    Param("track_size_filter", "range", "Tracking size range",
          "Size range (cm²) of a single individual during tracking. Best left at TRex default "
          "and tuned live in TRex; the calibration shows a single-ant range for reference.",
          decimals=4),
    Param("track_max_speed", "float", "Maximum speed (cm/s)",
          "The maximum distance an individual can travel within one second, in cm/s "
          "(speed in px/s × cm_per_pixel).", decimals=2),
    Param("track_background_subtraction", "bool", "Subtract background when tracking",
          "If enabled, objects are first contrasted against the background before "
          "thresholding (background colours − object colours) during tracking."),
    Param("calculate_posture", "bool", "Calculate posture",
          "Enables or disables posture calculation. Can only be set before the video is "
          "analysed."),
]
PARAM_KEYS = {p.key for p in PARAMS}
DEFAULT_PARAMS = {"detect_type": "background_subtraction"}

_LINE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*=\s*(\S.*?)\s*$")


def load_trex_params(folder: Path) -> tuple[dict, str]:
    s = load_folder_settings(folder)
    # Defaults apply only before the first save, so "TRex default" chosen later sticks.
    params = s["trex_params"] if "trex_params" in s else dict(DEFAULT_PARAMS)
    return dict(params), s.get("trex_extra", "")


def format_value(p: Param, value) -> str:
    if p.kind == "bool":
        return "true" if value else "false"
    if p.kind == "range":
        lo, hi = value
        return f"[[{lo:g},{hi:g}]]"
    if p.kind == "float":
        return f"{value:g}"
    return str(value)


def parse_extra(text: str) -> list[tuple[str, str]]:
    """`name = value` lines in TRex's syntax; blank lines and lines starting with # are skipped.

    Raises ValueError naming the first bad line.
    """
    pairs = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"Line {n} is not `name = value`: {line.strip()}")
        key = m.group(1)
        if key in APP_OWNED_KEYS:
            raise ValueError(f"Line {n}: {key} is written by this app from each video's squares.")
        if key in PARAM_KEYS:
            raise ValueError(f"Line {n}: {key} has its own field above; set it there.")
        pairs.append((key, m.group(2)))
    return pairs


def settings_lines(folder: Path) -> list[str]:
    """The folder's TRex parameters as settings-file lines (form fields, then extras)."""
    params, extra = load_trex_params(folder)
    lines = [f"{p.key} = {format_value(p, params[p.key])}" for p in PARAMS if p.key in params]
    lines += [f"{k} = {v}" for k, v in parse_extra(extra)]
    return lines


class TrexSettingsWindow(QDialog):
    """Edit the folder's TRex parameters. `track_after=True` relabels Save as "Save & track"."""

    def __init__(self, folder: Path, videos: list[Video], track_after: bool = False,
                 default_video: Video | None = None, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.videos = videos
        self.setWindowTitle("TRex tracking settings")
        self.resize(760, 860)
        params, extra = load_trex_params(folder)
        self.editors: dict[str, object] = {}

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        for p in PARAMS:
            editor = self._make_editor(p, params.get(p.key))
            self.editors[p.key] = editor
            help_label = QLabel(f"<code>{p.key}</code> — {p.help}")
            help_label.setWordWrap(True)
            help_label.setStyleSheet("color: palette(mid);")
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(editor if isinstance(editor, QWidget) else editor[2])
            box.addWidget(help_label)
            holder = QWidget()
            holder.setLayout(box)
            form.addRow(p.label, holder)
        form_box = QGroupBox("Parameters (shared by every video in this folder)")
        form_box.setLayout(form)

        self.extra = QPlainTextEdit(extra)
        self.extra.setPlaceholderText(
            "Any other TRex parameter, one per line in TRex's syntax, e.g.\n"
            "track_max_reassign_time = 0.5\n# lines starting with # are ignored"
        )
        self.extra.setFixedHeight(110)
        self.extra.textChanged.connect(self._update_preview)
        extra_box = QGroupBox("Other parameters")
        extra_layout = QVBoxLayout(extra_box)
        extra_layout.addWidget(self.extra)

        self.preview = QPlainTextEdit(readOnly=True)
        self.preview.setFixedHeight(150)
        preview_box = QGroupBox("Settings file TRex will receive")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(self.preview)

        self.calib_video = QComboBox()
        for v in videos:
            self.calib_video.addItem(v.source.name, v)
        if default_video is not None and default_video in videos:
            self.calib_video.setCurrentIndex(videos.index(default_video))
        calib_btn = QPushButton("Calibrate from video…")
        calib_btn.setEnabled(bool(videos))
        calib_btn.clicked.connect(self._calibrate)
        calib_box = QGroupBox("Calibrate interactively")
        cl = QVBoxLayout(calib_box)
        cl.addWidget(QLabel("Draw a scale line and head-to-gaster lines on a few ants, and set the "
                            "threshold against a live preview. Fills in the frame width, thresholds "
                            "and size ranges below."))
        cl.itemAt(0).widget().setWordWrap(True)
        crow = QHBoxLayout()
        crow.addWidget(self.calib_video, 1)
        crow.addWidget(calib_btn)
        cl.addLayout(crow)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(calib_box)
        content_layout.addWidget(form_box)
        content_layout.addWidget(extra_box)
        content_layout.addWidget(preview_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        save = QPushButton("Save && track" if track_after else "Save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        help_btn = QPushButton("Tuning in TRex…")
        help_btn.clicked.connect(lambda: show_trex_help(self))
        buttons = QHBoxLayout()
        buttons.addWidget(help_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        root = QVBoxLayout(self)
        root.addWidget(scroll, 1)
        root.addLayout(buttons)
        self._update_preview()

    # --- editors ------------------------------------------------------------

    def _spin(self, p: Param, value) -> QWidget:
        spin = QSpinBox() if p.decimals == 0 else QDoubleSpinBox()
        if p.decimals:
            spin.setDecimals(p.decimals)
        spin.setRange(UNSET, p.maximum if p.decimals else int(p.maximum))
        spin.setSpecialValueText(DEFAULT_TEXT)  # shown at the minimum, i.e. UNSET
        spin.setValue(UNSET if value is None else value)
        spin.valueChanged.connect(self._update_preview)
        return spin

    def _make_editor(self, p: Param, value):
        if p.kind in ("int", "float"):
            return self._spin(p, value)
        if p.kind in ("bool", "choice"):
            combo = QComboBox()
            options = ["true", "false"] if p.kind == "bool" else list(p.choices)
            combo.addItems([DEFAULT_TEXT, *options])
            if value is not None:
                combo.setCurrentText(("true" if value else "false") if p.kind == "bool" else value)
            combo.currentTextChanged.connect(self._update_preview)
            return combo
        # range: min and max spins side by side
        lo, hi = value if value is not None else (None, None)
        lo_spin, hi_spin = self._spin(p, lo), self._spin(p, hi)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("min"))
        lay.addWidget(lo_spin, 1)
        lay.addWidget(QLabel("max"))
        lay.addWidget(hi_spin, 1)
        return lo_spin, hi_spin, row  # keep `row` referenced until it is in a layout

    def _values(self) -> dict:
        out = {}
        for p in PARAMS:
            e = self.editors[p.key]
            if p.kind in ("int", "float"):
                if e.value() != UNSET:
                    out[p.key] = e.value()
            elif p.kind in ("bool", "choice"):
                t = e.currentText()
                if t != DEFAULT_TEXT:
                    out[p.key] = (t == "true") if p.kind == "bool" else t
            else:
                lo, hi = e[0].value(), e[1].value()
                if lo != UNSET and hi != UNSET:
                    out[p.key] = [lo, hi]
        return out

    def _calibrate(self):
        from .calibration import CalibrationDialog  # imports OpenCV; only needed here

        video = self.calib_video.currentData()
        values = self._values()
        try:
            dialog = CalibrationDialog(video, int(values.get("detect_threshold", 15)),
                                       values.get("meta_real_width"), self)
        except OSError as e:
            QMessageBox.critical(self, "Could not open video", str(e))
            return
        if dialog.exec() != QDialog.Accepted:
            return
        for key, value in dialog.result_values.items():
            e = self.editors[key]
            if isinstance(e, tuple):
                e[0].setValue(value[0])
                e[1].setValue(value[1])
            else:
                e.setValue(value)
        self._update_preview()

    # --- preview / save -----------------------------------------------------

    def _update_preview(self, *_):
        values = self._values()
        lines = [f"{p.key} = {format_value(p, values[p.key])}" for p in PARAMS if p.key in values]
        try:
            lines += [f"{k} = {v}" for k, v in parse_extra(self.extra.toPlainText())]
        except ValueError as e:
            lines.append(f"# ⚠ {e}")
        lines += ["output_format = csv", "track_include = (this video's mask squares)"]
        self.preview.setPlainText("\n".join(lines))

    def _save(self):
        values = self._values()
        for key in ("detect_size_filter", "track_size_filter"):
            if key in values and values[key][0] >= values[key][1]:
                QMessageBox.warning(self, "Check the size range", f"{key}: min must be smaller than max.")
                return
        try:
            parse_extra(self.extra.toPlainText())
        except ValueError as e:
            QMessageBox.warning(self, "Check other parameters", str(e))
            return
        try:
            save_folder_settings(self.folder, trex_params=values, trex_extra=self.extra.toPlainText(),
                                 trex_settings_confirmed=True)
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return
        self.accept()
