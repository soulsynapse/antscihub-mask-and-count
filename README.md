# antscihub-mask-and-count

A PySide6 desktop tool for preparing videos for [TRex](https://trex.run) tracking:

1. Point it at a folder; it lists every video in that folder in a table.
2. For each video, open a pop-over with the video, a seek bar, and box parameters, and
   click two opposite corners to draw (possibly rotated) squares over the regions to keep.
3. Use ffmpeg to burn the mask into a **new** video file that TRex can read.
4. Run TRex on the masked video and collect its CSV tracking output.

The table shows, per video, how many squares have been drawn ("unreadable" if the
boxes file is corrupt; hover for the error), whether the masked file exists, and whether
tracking has run.

**Original videos are never modified or overwritten.** Everything the tool produces goes
into a `mask_and_count_output/` subfolder next to the videos, and the code refuses to write to
any path that is a source video.

## Status

| Stage | State |
|---|---|
| Folder picker + video table | working |
| Box-drawing pop-over | working (two-click rotated squares) |
| ffmpeg masking | working (preview, per-video and batch) |
| TRex run + CSV collection | not started |

## Requirements

- Windows, macOS, or Linux
- Python 3.10–3.13
- [ffmpeg](https://ffmpeg.org/download.html) on `PATH` (check with `ffmpeg -version`)
- TRex, installed separately in its own conda environment (see below)

## Installation

The GUI runs in a plain virtual environment. TRex is *not* installed into it — TRex
ships as a conda package with its own native dependencies, and the app will call it
as an external program.

### 1. Clone and create the venv

Windows (PowerShell):

```powershell
git clone <repo-url> antscihub-mask-and-count
cd antscihub-mask-and-count
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Build the venv from a python.org install (via the `py` launcher), **not** from
Anaconda's base Python. A venv created from Anaconda inherits a PATH that includes
`anaconda3\Library\bin`, whose Qt and MSVC runtime DLLs shadow PySide6's and fail with
`ImportError: DLL load failed while importing QtWidgets`. `py -0` lists the installed
interpreters; any 3.10–3.13 works.

If PowerShell refuses to run `Activate.ps1`, allow local scripts once for your user:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

macOS / Linux:

```bash
git clone <repo-url> antscihub-mask-and-count
cd antscihub-mask-and-count
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Install ffmpeg

Windows: download a build from <https://www.gyan.dev/ffmpeg/builds/> (or
`winget install Gyan.FFmpeg`) and add its `bin` folder to `PATH`.
macOS: `brew install ffmpeg`. Debian/Ubuntu: `sudo apt install ffmpeg`.

Verify with `ffmpeg -version` in a new terminal.

### 3. Install TRex

Follow the official instructions at <https://trex.run/docs/install.html>. The usual
route is a dedicated conda environment:

```bash
conda create -n trex -c trexing trex
```

Keep TRex in its own environment; do not install it into `.venv`. Once tracking is
wired up, the app will need the path to the `trex` executable inside that
environment (find it with `conda run -n trex where trex` on Windows or
`conda run -n trex which trex` elsewhere).

## Running

With the venv active, from the repository root:

```bash
python main.py
```

or open a folder directly:

```bash
python main.py "D:\path\to\videos"
```

`python -m mask_and_count` is equivalent.

Use **Open folder…** to pick a folder; the app reopens the last folder on the next
launch (a folder given on the command line takes precedence, and a remembered folder
that no longer exists is skipped). The scan is non-recursive: only video files
directly inside the chosen folder are listed (`.mp4 .avi .mov .mkv .m4v .mpg .mpeg
.wmv .mts .m2ts`). **Refresh** rescans the folder and re-reads each video's status.

### Drawing boxes

Select a video and click **Draw boxes…**, or double-click its row. The pop-over opens
maximized, showing the frame at 100% — one video pixel per physical screen pixel, so
on a display scaled to 150% in Windows the frame looks smaller than "100%" in other apps.
It opens centred on the frame. In the pop-over:

- Move around with the **Navigator** thumbnail (click or drag; the white outline is the
  visible region), middle-drag on the video, or the scroll wheel (Alt+wheel scrolls
  sideways). Clicking a row in the box list centres that square.
- Use the seek bar to pick a representative frame; the boxes apply to every frame.
- Draw a square with two clicks (outlined 2 physical pixels thick): one corner, then the opposite corner. The line between
  the clicks is the square's diagonal, so it sets both the size (side = diagonal / √2)
  and the rotation; a red dashed preview follows the cursor after the first click.
  Pressing and dragging does not draw. Clicks are clamped to the frame, but a rotated
  square's other two corners can extend past the frame edge. For a square larger than
  the visible region: click, pan, click.
- **Mask border** (integer %) sets how big the masked square is relative to the drawn
  one, with the same centre and rotation: +10 keeps a square 10 % larger per side, −10
  one 10 % smaller (range −90 to +500). When non-zero, each square gets a magenta dashed
  outline showing the region the mask will keep. The value is remembered per folder in
  `mask_and_count_output/folder_settings.json` and pre-fills the next video opened from
  that folder. Each video's boxes file also records the border it was saved with, and
  reopening that video shows its own value, so changing the folder default later does
  not silently alter videos already drawn.
- Right-click removes the most recent square; if a square is in progress, right-click
  (or Esc) cancels it instead. Select a row in the list and press Del (or **Delete
  selected**) to remove a specific one.
- The list shows centre x, centre y, side and angle in source-video pixels and degrees;
  edit a cell to adjust a square numerically. Angle is clockwise on screen and shown in
  [-45°, 45°), since a square looks the same after a 90° turn.
- **Save** writes `<name>.boxes.json` (format version 2: the two clicked corners `p1`,
  `p2`, and `mask_border_pct`, plus derived `center`, `side`, `angle_deg`, all four `corners`, and the
  scaled `mask_side` / `mask_corners` that masking uses). Version-1
  files (axis-aligned `x, y, w, h`) still load. Saving with no squares removes that file
  after confirmation. **Cancel** asks before discarding unsaved changes.

### Masking

The **Masked video** column shows ✔ (up to date), **stale** (the boxes or mask border
changed after the masked video was made), or —, plus an **Open…** button (enabled once a
video has boxes) that opens the mask window for that video:

- The preview is rendered by ffmpeg with the exact filter chain used for the output, so
  it shows what the file will contain, deinterlacing included. Use the seek bar to check
  other frames.
- Everything outside the mask squares (the magenta outlines in the box editor) is black;
  the inside is kept unchanged.
- **Mask settings** are shared by every video in the folder (stored in
  `folder_settings.json`):
  - *Deinterlace* `auto` (default) turns on for videos ffprobe reports as interlaced,
    such as 1080i AVCHD `.MTS`. It uses `bwdif` with one output frame per input frame, so
    the frame rate and frame numbers match the original. `on`/`off` force it.
  - *Quality (CRF)*: libx264 constant quality, default 18 (visually near-lossless).
    Lower values are better quality and larger files.
  - *Speed preset*: libx264 preset, default `fast`. Slower presets give smaller files at
    the same CRF.
- **Generate masked video** saves the settings and encodes, with a progress bar and a
  cancel button. Output is H.264 `yuv420p` `.mp4` without audio. It is written to
  `<name>_masked.partial.mp4` and renamed only when ffmpeg succeeds, so a failed or
  cancelled run never shows as done.

**Mask all videos…** (the button above the column) masks every video that has boxes and
whose masked video is missing or stale. Videos without boxes, and videos already up to
date, are skipped. The first time in a folder, it opens the mask window on the first
video to be masked so you can check the preview and settings. **Save settings & mask
all** then runs the batch. After that, it asks for confirmation (listing the videos and
settings) with an **Adjust settings…** option. The batch runs one video at a time and can
be stopped; a stopped video's partial output is deleted.

## Output layout

For a source folder `videos/` containing `colony_A.mp4`:

```
videos/
├── colony_A.mp4                     # original, never touched
└── mask_and_count_output/
    ├── folder_settings.json         # folder defaults (mask border, mask settings)
    ├── colony_A.boxes.json          # drawn boxes        → "Boxes drawn"
    ├── colony_A_mask.png            # mask image used by the last encode
    ├── colony_A_masked.mp4          # ffmpeg output      → "Masked video"
    ├── colony_A_masked.json         # what the masked video was made from (stale check)
    └── colony_A_trex/               # TRex output dir    → "Tracked" (any .csv inside)
```

Status in the table is derived entirely from which of these files exist, so there is
no separate database to fall out of sync; deleting a file resets that stage.

## Project layout

```
main.py              # entry point: python main.py [folder]
mask_and_count/
├── __main__.py      # same entry point: python -m mask_and_count
├── main_window.py   # folder picker + video table
├── box_editor.py    # box-drawing pop-over (frame view, seek bar, box list)
├── boxes.py         # boxes.json load/save, Square geometry
├── folder_settings.py  # per-folder settings (mask border, mask settings)
├── masking.py       # mask image, ffprobe, ffmpeg encode/preview, MaskJob
├── mask_window.py   # mask preview/settings window and Mask-all batch dialog
└── videos.py        # folder scanning, output paths, per-video status
requirements.txt
videos_for_test/     # local test footage; contents are gitignored
```
