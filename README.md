# antscihub-mask-and-count

A desktop tool for preparing ant videos for [TRex](https://trex.run) tracking. Point it at
a folder of videos, draw squares over the regions to keep, optionally burn that mask
into a new video with ffmpeg, and open each video in TRex with the squares and your
tracking settings applied.

Original videos are never modified. Everything the tool writes goes into a
`mask_and_count_output/` folder next to the videos.

## Install

1. Install [Python](https://www.python.org/downloads/) 3.10–3.13 from python.org, not
   Anaconda: a venv built from Anaconda's Python fails to load PySide6 on Windows.
2. Install ffmpeg and put it on `PATH` (Windows: `winget install Gyan.FFmpeg`; macOS:
   `brew install ffmpeg`; Debian/Ubuntu: `sudo apt install ffmpeg`).
3. For tracking, install TRex in its own conda environment named `track`
   ([instructions](https://trex.run/docs/install.html)):
   `conda create -n track -c trexing trex`
4. Get this repository and start it: double-click **`Mask and Count.bat`** (Windows), or
   run `python main.py [folder]`.

The first start creates `.venv` and installs the Python packages (a minute or two; needs
internet). Later starts just check it. `main.py` runs under any Python 3 and picks a
suitable one to build `.venv` from. It rebuilds `.venv` if it is broken or was built from
Anaconda, and reinstalls packages when `requirements.txt` changes. `python main.py
--setup-only` sets up without starting the app.

## Workflow

The main window lists the videos in a folder (`.mp4 .avi .mov .mkv .m4v .mpg .mpeg .wmv
.mts .m2ts`, not subfolders) with three status columns. It reopens the last folder on
start. Status comes only from the files in `mask_and_count_output/`, so deleting a file
resets that step.

### 1. Draw boxes

Select a video and click **Draw boxes…** (or double-click its row). The frame is shown
at 100%, one video pixel per screen pixel.

- **Draw:** click one corner, then the opposite corner. The line between them is the
  square's diagonal, so it sets both size and rotation.
- **Remove:** right-click removes the last square (or cancels one in progress). Del
  removes the selected square.
- **Navigate:** use the navigator thumbnail, middle-drag, or the scroll wheel; the seek
  bar picks a frame.
- **Mask border %:** makes the kept region larger (+) or smaller (−) than the drawn
  square (magenta outline). It is remembered for the folder, and each video keeps the
  value it was saved with.
- **Edit numerically:** the square list shows centre, side and angle; edit a cell to
  adjust a square.

### 2. Mask (optional for most videos; required for `.MTS` and interlaced footage)

**Open…** in the Masked video column shows an ffmpeg-rendered preview of the masked
video: black outside the squares, unchanged inside. The settings are shared by the
folder:

- **Deinterlace:** `auto` turns it on for interlaced video, keeping the original frame
  count.
- **Quality (CRF):** 18 is visually near-lossless.
- **Speed preset.**

**Generate masked video** encodes one video. **Mask all videos…** (above the column)
masks every video with boxes whose masked video is missing or stale. The first time, it
shows the preview and settings first. **Stale** means the boxes changed after the masked
video was made.

### 3. Track

1. **TRex settings…** (above the Tracked column) sets the parameters TRex gets for every
   video in the folder. The first **Track…** opens it automatically. Fields left at
   *TRex default* are not sent.
2. **Calibrate from video…** in that window sets the conversion values from the video:
   - Draw a line across something of known length and enter its length.
   - Click head tip → gaster end on several ants, including the smallest.
   - Move the threshold slider while a live overlay shows what would be detected.

   Apply sets a generous conversion range, so small ants and clumps of touching ants
   survive into TRex's converted file. Anything dropped at conversion is gone until you
   convert again.
3. **Track…** opens TRex, which converts the video and tracks it. The squares are passed
   as `track_include` polygons, so objects outside them are ignored. TRex uses the
   masked video if it is up to date, otherwise the original. If the video is `.MTS` or
   interlaced and has no up-to-date masked video, Track asks you to generate one first.
   If TRex already converted the video, Track asks whether to **Convert again**. Choose
   it after changing conversion settings or if TRex was closed mid-conversion.
4. Tune the tracking (`track_*`) parameters live in TRex. They don't require converting
   again. Then export CSVs and copy the final values back into **TRex settings…** so
   every video gets them. **Tuning in TRex…** (toolbar) walks through this step by step.

## Files

```
videos/
├── colony_A.mp4                    original, never touched
└── mask_and_count_output/
    ├── folder_settings.json        mask border, mask and TRex settings for the folder
    ├── colony_A.boxes.json         squares             → Boxes drawn
    ├── colony_A_mask.png           mask image used for the masked video
    ├── colony_A_masked.mp4         masked video        → Masked video
    ├── colony_A_masked.json        what it was made from (stale check)
    └── colony_A_trex/              TRex output         → Tracked (once CSVs are exported)
        ├── mask_and_count.settings settings sent to TRex (rewritten on every Track)
        └── trex_launch.log         TRex's console output
```

## Known limits

- TRex 2.0.0 reads `.MTS`/`.m2ts` as 0 frames, so those videos must be masked first.
- TRex starts converting as soon as it opens a file. Its command line cannot open a
  file on its settings screen first, which is why the settings live in this app.
- TRex 2.0.0 did not derive `cm_per_pixel` from `meta_real_width`, so the app writes it
  explicitly. The size ranges are in cm² according to TRex 1.x's documentation; this is
  not confirmed for 2.0.
- The calibration overlay approximates TRex's background subtraction rather than running
  TRex.
- The TRex conda env name can only be changed through the Qt setting `trex_conda_env`.
- There is no unattended tracking or CSV collection yet; TRex runs in its GUI.

## Code

`main.py` is the launcher. The app is in `mask_and_count/`:

| File | Contents |
|---|---|
| `main_window.py` | video table |
| `box_editor.py` | box drawing |
| `boxes.py` | square geometry and storage |
| `masking.py`, `mask_window.py` | ffmpeg masking and its windows |
| `trex.py` | TRex launch |
| `trex_settings.py` | TRex settings window |
| `calibration.py` | calibration window |
| `trex_help.py` | tuning help |
| `folder_settings.py` | per-folder settings |
| `videos.py` | folder scan and status |
