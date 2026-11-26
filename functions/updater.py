"""Remove the LineageOS Updater app."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from . import ext4
from .common import BuildError, log
from .config import UPDATER_DIR, UPDATER_FILES


def remove(images: Dict[str, Path]) -> None:
    removed = 0
    for name, image in images.items():
        if ext4.debugfs_exists(image, UPDATER_DIR):
            ext4.debugfs_remove_tree(image, UPDATER_DIR)
            log(f"{name}:{UPDATER_DIR}: removed (app and odex files)")
            removed += 1
        for path in UPDATER_FILES:
            if ext4.debugfs_exists(image, path):
                ext4.debugfs(image, f"rm {path}", write=True)
                log(f"{name}:{path}: removed")
                removed += 1
    if removed == 0:
        raise BuildError("the LineageOS Updater was not found; refusing to ship it")
