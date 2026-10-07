"""Help window: tuning tracking inside TRex after conversion.

Labels and symbols are taken from TRex 2.0.0's GUI layout files
(usr/share/trex/tracking_layout.json, export_options_layout.json). If TRex's layout
changes, update this text from those files rather than from memory.
"""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

HELP_HTML = """
<h2>Tuning tracking in TRex</h2>

<p><b>Track…</b> starts TRex on the video. TRex first <i>converts</i> it (progress bar),
using the conversion threshold and size range from <b>TRex settings…</b>. Those are now
fixed: changing them means clicking Track again and choosing <i>Convert again</i>.
Everything below changes <i>tracking</i> only. It works on the converted file, so you can
adjust it and re-run tracking in seconds without converting again.</p>

<h3>1 · Look at what was detected</h3>
<ul>
<li>Use the toggle at the top to switch between <b>⭍ Tracked</b> (individuals with
identities) and <b>🎞 Raw</b> (every converted blob, before tracking filters).
In Raw, every ant should be a blob. If small ants are missing here, the conversion
threshold or size range dropped them, and only converting again brings them back.</li>
<li>In <b>🖵 Display</b>, turn on <i>Blob Images</i> and <i>Outline</i> to see each
blob's shape, and <i>Trajectories</i> to spot broken or swapped tracks.</li>
</ul>

<h3>2 · Read real sizes</h3>
<p>Click an ant. Its panel shows <b>Size</b> (cm²), <b>Pixels</b> and <b>Speed</b>
(cm/s). Click a few of the smallest single ants, a few of the largest, and a clump of
touching ants. These numbers set the tracking size range. The <i>single-ant range</i>
shown in this app's calibration is a starting point.</p>

<h3>3 · Change tracking parameters</h3>
<p>Type a name into the <b>🔍 Parameters</b> field and edit its value. Useful ones:</p>
<ul>
<li><code>track_threshold</code>: raise it until legs and specks fall away but each ant
stays one blob. It cannot recover pixels the conversion threshold already dropped.</li>
<li><code>track_size_filter</code>: <code>[[min,max]]</code> in cm², around a
<i>single</i> ant (smallest to largest you measured). According to the TRex 1.x docs,
blobs above <i>max</i> are treated as possibly several individuals and may be split;
blobs below <i>min</i> are ignored as noise.</li>
<li><code>track_max_individuals</code>: how many ants to keep identities for (0 = unknown).</li>
<li><code>track_max_speed</code>: cm/s. Too low breaks tracks when ants run; too high lets
identities jump between neighbours. Check typical <i>Speed</i> values of running ants.</li>
<li><b>🖵 Subtract Background</b> (image settings panel, or
<code>track_background_subtraction</code>) contrasts blobs against the background
before thresholding.</li>
</ul>

<h3>4 · Re-run tracking</h3>
<p>After changing parameters, use the <b>🗘</b> re-analyse button. One option re-tracks
from the current frame, the other reanalyses the whole video from frame 0. Check the
result in Tracked view and repeat steps 2–4 until single ants are tracked continuously.</p>

<h3>5 · Export the tracks</h3>
<p><b>☰ Menu → 🖫 Export data</b>. <i>output_format</i> is already <code>csv</code> and
the destination is already this video's <code>_trex</code> folder. Click
<b>🖫 Export</b>. Back in this app, <b>Refresh</b> turns the Tracked column to ✔.</p>

<h3>6 · Use the same values for every video</h3>
<p>Enter the final tracking values (<code>track_threshold</code>,
<code>track_size_filter</code>, <code>track_max_speed</code>, …) in <b>TRex settings…</b>
in this app, so every video in the folder gets them on its next Track.
<b>☰ Menu → 🛠 Save config</b> in TRex writes them only to TRex's own settings file for
this one video, and <i>Convert again</i> deletes that file.</p>

<p style="color:gray"><small>Button names are from TRex 2.0.0's interface files.
Behaviour described as from the TRex 1.x documentation was not checked separately in
2.0. Full reference: <a href="https://trex.run/docs/">trex.run/docs</a>.</small></p>
"""


class TrexHelpWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tuning tracking in TRex")
        self.resize(720, 820)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml(HELP_HTML)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(text, 1)
        layout.addLayout(buttons)


_open_window: TrexHelpWindow | None = None


def show_trex_help(parent=None):
    """Non-modal, so it can stay open beside TRex while tuning. Reuses one window."""
    global _open_window
    if _open_window is None or not _open_window.isVisible():
        _open_window = TrexHelpWindow(parent)
    _open_window.show()
    _open_window.raise_()
    _open_window.activateWindow()
