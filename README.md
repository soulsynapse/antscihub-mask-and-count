# antscihub-mask-and-count

A PySide6 desktop tool for preparing videos for [TRex](https://trex.run) tracking:

1. Point it at a folder; it lists every video in that folder in a table.
2. For each video, open a pop-over with the video, a seek bar, and box parameters, and
   mark two corners to draw squares over the regions to keep.
3. Use ffmpeg to burn the mask into a **new** video file that TRex can read.
4. Run TRex on the masked video and collect its CSV tracking output.

The table shows, per video, whether boxes have been drawn, whether the masked file
exists, and whether tracking has run.

**Original videos are never modified or overwritten.** Everything the tool produces goes
into a `mask_and_count_output/` subfolder next to the videos, and the code refuses to write to
any path that is a source video.

## Status

| Stage | State |
|---|---|
| Folder picker + video table | working |
| Box-drawing pop-over | working (axis-aligned squares) |
| ffmpeg masking | not started |
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

Use **Open folder…** to pick a folder. The scan is non-recursive: only video files
directly inside the chosen folder are listed (`.mp4 .avi .mov .mkv .m4v .mpg .mpeg
.wmv .mts .m2ts`). **Refresh** rescans the folder and re-reads each video's status.

### Drawing boxes

Select a video and click **Draw boxes…**, or double-click its row. In the pop-over:

- Use the seek bar to pick a representative frame; the boxes apply to every frame.
- Click corner 1, then corner 2, to draw a square (dragging from one corner to the other
  also works). The square is anchored at corner 1 and its side is the larger of the
  horizontal and vertical distance to corner 2, so the two clicks need not lie exactly
  on a diagonal. Squares are capped to stay inside the frame.
- Right-click or Esc cancels a square in progress. Select a row in the box list and
  press Del (or **Delete selected**) to remove one.
- The box list shows x, y, and side in source-video pixels; edit a cell to adjust a
  square numerically.
- **Save** writes `<name>.boxes.json`. Saving with no boxes removes that file after
  confirmation. **Cancel** asks before discarding unsaved changes.

## Output layout

For a source folder `videos/` containing `colony_A.mp4`:

```
videos/
├── colony_A.mp4                     # original, never touched
└── mask_and_count_output/
    ├── colony_A.boxes.json          # drawn boxes        → "Boxes drawn"
    ├── colony_A_masked.mp4          # ffmpeg output      → "Masked video"
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
├── boxes.py         # boxes.json load/save
└── videos.py        # folder scanning, output paths, per-video status
requirements.txt
videos_for_test/     # local test footage; contents are gitignored
```
