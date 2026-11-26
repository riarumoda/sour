"""Stock archive, DSU zip and checksums."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

from .common import BuildError, log, sha256
from .config import PARTITIONS, STOCK_ARCHIVE


def make_stock_archive(workdir: Path, output: Path) -> None:
    names = [f"{name}.img" for name in PARTITIONS]
    missing = [name for name in names if not (workdir / name).is_file()]
    if missing:
        raise BuildError(f"cannot create {STOCK_ARCHIVE}; missing {', '.join(missing)}")

    log(f"{STOCK_ARCHIVE}: archiving the untouched images")
    tar_cmd = [
        "tar",
        "--sort=name",
        "--mtime=@0",
        "--owner=0",
        "--group=0",
        "--numeric-owner",
        "-cf",
        "-",
        "-C",
        str(workdir),
        *names,
    ]
    output.unlink(missing_ok=True)
    with output.open("wb") as destination:
        tar = subprocess.Popen(
            tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert tar.stdout is not None
        lz4 = subprocess.Popen(
            ["lz4", "-12", "-"],
            stdin=tar.stdout,
            stdout=destination,
            stderr=subprocess.PIPE,
        )
        tar.stdout.close()
        _, lz4_err = lz4.communicate()
        _, tar_err = tar.communicate()
        if tar.returncode != 0 or lz4.returncode != 0:
            detail = (lz4_err or tar_err or b"").decode("utf-8", "replace").strip()
            raise BuildError(f"{STOCK_ARCHIVE} failed\n{detail}")
    if not output.is_file() or output.stat().st_size == 0:
        raise BuildError(f"{STOCK_ARCHIVE} was not created")


def pack_dsu(workdir: Path, output: Path) -> None:
    log(f"packing {output.name}")
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in PARTITIONS:
            image = workdir / f"{name}.img"
            info = zipfile.ZipInfo(f"{name}.img", date_time=(2009, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with image.open("rb") as source, archive.open(
                info, "w", force_zip64=True
            ) as destination:
                shutil.copyfileobj(source, destination, 4 * 1024 * 1024)


def write_checksums(stock: Path, dsu: Path, output: Path) -> None:
    output.write_text(
        f"{sha256(stock)}  {stock.name}\n{sha256(dsu)}  {dsu.name}\n",
        encoding="utf-8",
    )
