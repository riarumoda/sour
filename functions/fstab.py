"""Patch the guest vendor fstab."""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

from . import ext4
from .common import log, warn
from .config import FSTAB_FILES, PERSIST_MOUNTS


def flags(value: str) -> List[str]:
    return [item for item in value.split(",") if item]


def render_entry(fields: Sequence[str]) -> str:
    source, mount_point, fs_type, mount_flags, fs_mgr_flags = fields[:5]
    mount = flags(mount_flags)
    mgr = flags(fs_mgr_flags)

    if mount_point == "/data":
        mount = [item for item in mount if item != "rw"]
        if "inlinecrypt" not in mount:
            mount.append("inlinecrypt")
        mgr = [
            item
            for item in mgr
            if not item.startswith(("metadata_encryption=", "keydirectory="))
        ]
        for index, item in enumerate(mgr):
            if item.startswith("fileencryption="):
                mgr[index] = "fileencryption=ice"
                break
        else:
            mgr.append("fileencryption=ice")
    elif mount_point in PERSIST_MOUNTS:
        mount = [item for item in mount if item != "rw"]
        if "ro" not in mount:
            mount.insert(0, "ro")
        mgr = [item for item in mgr if item not in ("check", "formattable")]

    return " ".join((source, mount_point, fs_type, ",".join(mount), ",".join(mgr)))


def patch_text(text: str) -> Tuple[str, bool]:
    output: List[str] = []
    changed = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output.append(line)
            continue
        fields = stripped.split()
        if len(fields) < 5:
            output.append(line)
            continue

        if fields[1] == "/metadata":
            changed = True
            continue

        new_line = render_entry(fields)
        if new_line != stripped:
            changed = True
        output.append(new_line)

    result = "\n".join(output)
    if text.endswith("\n"):
        result += "\n"
    return result, changed


def patch_image(image: Path) -> None:
    for fstab_path in FSTAB_FILES:
        if not ext4.debugfs_exists(image, fstab_path):
            warn(f"vendor image has no {fstab_path}")
            continue
        original = ext4.debugfs(image, f"cat {fstab_path}")
        patched, changed = patch_text(original.decode("utf-8"))
        if changed:
            ext4.debugfs_replace(image, fstab_path, patched.encode("utf-8"))
            log(f"vendor:{fstab_path}: /metadata removed, /data is ICE, persist ro")
