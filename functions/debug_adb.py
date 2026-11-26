"""Patch early-boot, authorization-free ADB."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from . import ext4
from .common import BuildError, log
from .config import (
    DEBUG_ADB_CONFIGFS_RC,
    DEBUG_ADB_PROPS,
    DEBUG_ADB_RC,
    DEBUG_ADB_RC_NAME,
    DEFAULT_UDC,
)


def set_prop_values(text: str, values: Sequence[Tuple[str, str]]) -> str:
    wanted = dict(values)
    lines = text.splitlines()
    seen = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.partition("=")[0].strip()
        if key in wanted:
            lines[index] = f"{key}={wanted[key]}"
            seen.add(key)
    for key, value in values:
        if key not in seen:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def prop_value(text: str, key: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            return value.strip()
    return None


def read_prop(image: Path, candidates: Sequence[str], key: str) -> Optional[str]:
    path = ext4.find_path(image, candidates)
    if path is None:
        return None
    return prop_value(ext4.debugfs(image, f"cat {path}").decode("utf-8", "replace"), key)


def patch(images: Dict[str, Path]) -> None:
    system = images["system"]

    build_prop = ext4.find_path(system, ("/system/build.prop", "/build.prop"))
    if build_prop is None:
        raise BuildError("cannot find build.prop in the system image")

    configfs = ext4.find_path(system, DEBUG_ADB_CONFIGFS_RC)
    if configfs is None:
        raise BuildError("cannot find init.usb.configfs.rc in the system image")
    init_dir = posixpath.dirname(posixpath.dirname(configfs))
    rc_path = f"{init_dir}/{DEBUG_ADB_RC_NAME}"

    udc = (
        read_prop(images["vendor"], ("/build.prop", "/etc/build.prop"), "vendor.usb.controller")
        or DEFAULT_UDC
    )

    original = ext4.debugfs(system, f"cat {build_prop}").decode("utf-8", "replace")
    ext4.debugfs_replace(
        system,
        build_prop,
        set_prop_values(original, DEBUG_ADB_PROPS).encode("utf-8"),
    )
    log(f"system:{build_prop}: early ADB properties set")

    label = ext4.debugfs_label(system, configfs) or "u:object_r:system_file:s0"
    ext4.debugfs_write_file(
        system, rc_path, DEBUG_ADB_RC.format(udc=udc).encode("utf-8"), label
    )
    log(f"system:{rc_path}: adb-only gadget for {udc}")

    # Later partition props override /system.
    wanted = {key for key, _value in DEBUG_ADB_PROPS}
    for name in ("system_ext", "product", "vendor", "odm"):
        image = images[name]
        for path in ("/etc/build.prop", "/build.prop", "/default.prop"):
            if not ext4.debugfs_exists(image, path):
                continue
            text = ext4.debugfs(image, f"cat {path}").decode("utf-8", "replace")
            present = {
                key
                for key in wanted
                if re.search(rf"^\s*{re.escape(key)}\s*=", text, re.MULTILINE)
            }
            if not present:
                continue
            values = tuple(
                (key, value) for key, value in DEBUG_ADB_PROPS if key in present
            )
            ext4.debugfs_replace(
                image, path, set_prop_values(text, values).encode("utf-8")
            )
            log(f"{name}:{path}: kept ADB properties in agreement")
