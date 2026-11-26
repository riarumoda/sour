"""Build orchestration and verification."""

from __future__ import annotations

import os
import posixpath
import zipfile
from pathlib import Path
from typing import Dict

from . import artifacts, debug_adb, ext4, fstab, sdat, updater, vendor_init
from .common import BuildError, check_dependencies, human_size, log, run
from .config import (
    DEBUG_ADB_CONFIGFS_RC,
    DEBUG_ADB_PROPS,
    DEBUG_ADB_RC_NAME,
    DSU_PREFIX,
    FSTAB_FILES,
    PARTITIONS,
    PERSIST_MOUNTS,
    STOCK_ARCHIVE,
    UPDATER_DIR,
    UPDATER_FILES,
)


def verify(images: Dict[str, Path]) -> None:
    vendor = images["vendor"]
    for fstab_path in FSTAB_FILES:
        if not ext4.debugfs_exists(vendor, fstab_path):
            raise BuildError(f"vendor:{fstab_path} disappeared")
        text = ext4.debugfs(vendor, f"cat {fstab_path}").decode("utf-8", "replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 5:
                continue
            mount_point = fields[1]
            if mount_point == "/metadata":
                raise BuildError(f"{fstab_path} still contains /metadata")
            mgr = fstab.flags(fields[4])
            if mount_point == "/data":
                if "fileencryption=ice" not in mgr:
                    raise BuildError(f"{fstab_path} does not use fileencryption=ice")
                if any(
                    item.startswith(("metadata_encryption=", "keydirectory="))
                    for item in mgr
                ):
                    raise BuildError(f"{fstab_path} still has metadata encryption")
            if mount_point in PERSIST_MOUNTS:
                if "ro" not in fstab.flags(fields[3]):
                    raise BuildError(f"{fstab_path} does not mount {mount_point} ro")
                if "check" in mgr or "formattable" in mgr:
                    raise BuildError(f"{fstab_path} still checks {mount_point}")

    for path, _mode in ext4.walk_files(vendor, "/etc/init"):
        if not path.endswith(".rc"):
            continue
        text = ext4.debugfs(vendor, f"cat {path}").decode("utf-8", "replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            tokens = stripped.split()
            if tokens[0] in (
                "restorecon",
                "restorecon_recursive",
                "mkdir",
                "chown",
                "chmod",
            ) and vendor_init.touches_persist(tokens[1:]):
                raise BuildError(f"vendor:{path} still writes to persist: {stripped}")

    for name, image in images.items():
        if ext4.debugfs_exists(image, UPDATER_DIR):
            raise BuildError(f"{name}:{UPDATER_DIR} still exists")
        for path in UPDATER_FILES:
            if ext4.debugfs_exists(image, path):
                raise BuildError(f"{name}:{path} still exists")

    system = images["system"]
    build_prop = ext4.find_path(system, ("/system/build.prop", "/build.prop"))
    if build_prop is None:
        raise BuildError("system build.prop disappeared")
    props = ext4.debugfs(system, f"cat {build_prop}").decode("utf-8", "replace")
    for key, value in DEBUG_ADB_PROPS:
        if debug_adb.prop_value(props, key) != value:
            raise BuildError(f"{build_prop} does not set {key}={value}")

    configfs = ext4.find_path(system, DEBUG_ADB_CONFIGFS_RC)
    if configfs is None:
        raise BuildError("init.usb.configfs.rc disappeared")
    rc_path = f"{posixpath.dirname(posixpath.dirname(configfs))}/{DEBUG_ADB_RC_NAME}"
    if not ext4.debugfs_exists(system, rc_path):
        raise BuildError(f"{rc_path} was not created")

    for image in images.values():
        ext4.assert_clean(image)


def build(rom_zip: Path, workdir: Path, artifact_dir: Path, *, keep_work: bool) -> None:
    check_dependencies()
    if not rom_zip.is_file():
        raise BuildError(f"ROM zip not found: {rom_zip}")

    workdir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    images = {name: workdir / f"{name}.img" for name in PARTITIONS}
    for image in images.values():
        image.unlink(missing_ok=True)

    log(f"unpacking {rom_zip.name}")
    with zipfile.ZipFile(rom_zip) as archive:
        for name in PARTITIONS:
            log(f"extracting {name}")
            sdat.extract_partition(archive, name, images[name])

    # Archive before patching.
    stock = artifact_dir / STOCK_ARCHIVE
    artifacts.make_stock_archive(workdir, stock)

    for image in images.values():
        ext4.unshare_blocks(image)

    log("patching vendor fstab and persist init scripts")
    fstab.patch_image(images["vendor"])
    vendor_init.patch_image(images["vendor"])
    log("removing the LineageOS Updater")
    updater.remove(images)
    log("enabling early-boot ADB")
    debug_adb.patch(images)

    verify(images)

    date = os.environ.get("BUILD_DATE") or run(
        ["date", "-u", "+%Y%m%d"]
    ).stdout.decode().strip()
    dsu = artifact_dir / f"{DSU_PREFIX}-{date}-dsu.zip"
    artifacts.pack_dsu(workdir, dsu)
    artifacts.write_checksums(stock, dsu, artifact_dir / "SHA256SUMS.txt")

    print()
    print("================ build summary ================")
    print(f"ROM:     {rom_zip}")
    print(f"stock:   {stock} ({human_size(stock.stat().st_size)})")
    print(f"DSU:     {dsu} ({human_size(dsu.stat().st_size)})")
    print(f"images:  {', '.join(f'{name}.img' for name in PARTITIONS)}")
    print("ADB:     enabled at boot (authorization-free)")
    print("==============================================")

    if not keep_work:
        log("removing raw images (set KEEP_WORK=1 to keep them)")
        for image in images.values():
            image.unlink(missing_ok=True)
        try:
            workdir.rmdir()
        except OSError:
            pass
