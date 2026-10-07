"""Per-folder settings, shared by every video in a folder (e.g. the mask border default)."""

import json
import os
from pathlib import Path

from .videos import OUTPUT_DIRNAME

FILENAME = "folder_settings.json"
# mask_settings_confirmed: the user has reviewed the mask_* encode settings in the mask
# window for this folder, so "Mask all videos" can run without sending them there first.
# trex_settings_confirmed: likewise for the TRex parameters before the first Track.
DEFAULTS = {"mask_border_pct": 0, "mask_settings_confirmed": False, "trex_settings_confirmed": False}


def settings_path(folder: Path) -> Path:
    return folder / OUTPUT_DIRNAME / FILENAME


def load_folder_settings(folder: Path) -> dict:
    """Defaults overlaid with whatever the file holds; a missing or corrupt file gives defaults."""
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(settings_path(folder).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return settings


def save_folder_settings(folder: Path, **changes) -> None:
    """Merge `changes` into the folder's settings file (atomic write)."""
    path = settings_path(folder)
    settings = load_folder_settings(folder)
    settings.update(changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp, path)
