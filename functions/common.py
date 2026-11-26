"""Logging, process, dependency and hashing helpers."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def log(message: str) -> None:
    print(f"==> {message}", file=sys.stderr, flush=True)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr, flush=True)


class BuildError(RuntimeError):
    pass


def run(
    cmd: Sequence[str],
    *,
    allow: Sequence[int] = (0,),
    check: bool = True,
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if check and proc.returncode not in allow:
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        raise BuildError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{detail}")
    return proc


def check_dependencies() -> None:
    missing = [
        tool
        for tool in ("debugfs", "dumpe2fs", "e2fsck", "lz4", "tar")
        if not shutil.which(tool)
    ]
    if importlib.util.find_spec("brotli") is None:
        missing.append("python module 'brotli'")
    if missing:
        raise BuildError(
            "missing dependencies: "
            + ", ".join(missing)
            + "\nOn Debian/Ubuntu: sudo apt install e2fsprogs lz4 python3-brotli"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
