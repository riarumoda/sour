"""ext4 helpers built on debugfs and e2fsck."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

from .common import BuildError, log, run


def ext4_features(image: Path) -> List[str]:
    proc = run(["dumpe2fs", "-h", str(image)])
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("Filesystem features:"):
            return line.split(":", 1)[1].split()
    return []


def unshare_blocks(image: Path) -> None:
    """Unshare deduplicated blocks so the image can be patched."""
    if "shared_blocks" not in ext4_features(image):
        return
    log(f"{image.name}: unsharing deduplicated blocks")
    proc = run(
        ["e2fsck", "-fy", "-E", "unshare_blocks", str(image)],
        allow=(0, 1, 2),
        check=False,
    )
    if proc.returncode not in (0, 1, 2):
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")
        raise BuildError(f"{image.name}: could not unshare shared blocks\n{detail}")


def assert_clean(image: Path) -> None:
    proc = run(["e2fsck", "-fn", str(image)], allow=(0,), check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        raise BuildError(f"{image.name}: filesystem check failed\n{detail}")


def debugfs(image: Path, command: str, *, write: bool = False) -> bytes:
    cmd = ["debugfs"]
    if write:
        cmd.append("-w")
    cmd.extend(["-R", command, str(image)])
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        if "File not found" not in detail:
            raise BuildError(f"debugfs {command!r} failed on {image.name}: {detail}")
    return proc.stdout


def debugfs_exists(image: Path, path: str) -> bool:
    proc = subprocess.run(
        ["debugfs", "-R", f"stat {path}", str(image)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return (
        proc.returncode == 0
        and b"File not found" not in proc.stderr
        and bool(proc.stdout)
    )


def find_path(image: Path, candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if debugfs_exists(image, candidate):
            return candidate
    return None


def debugfs_label(image: Path, path: str) -> Optional[str]:
    output = debugfs(image, f"ea_list {path}").decode("utf-8", "replace")
    match = re.search(r'security\.selinux \(\d+\) = "(.*)"', output)
    if not match:
        return None
    value = match.group(1).split("\\000", 1)[0]
    return value or None


def debugfs_ls(image: Path, path: str) -> List[Tuple[str, str]]:
    output = debugfs(image, f"ls -l {path}").decode("utf-8", "replace")
    entries: List[Tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].isdigit():
            continue
        name = parts[-1]
        if name in (".", ".."):
            continue
        entries.append((name, parts[1]))
    return entries


def debugfs_remove_tree(image: Path, path: str) -> None:
    if not debugfs_exists(image, path):
        return
    for name, mode in debugfs_ls(image, path):
        child = f"{path.rstrip('/')}/{name}"
        if mode.startswith("4"):
            debugfs_remove_tree(image, child)
        else:
            debugfs(image, f"rm {child}", write=True)
    debugfs(image, f"rmdir {path}", write=True)


def debugfs_write_file(image: Path, path: str, data: bytes, label: str) -> None:
    """Create/replace a file and restore its SELinux label."""
    with tempfile.NamedTemporaryFile(delete=False, dir=image.parent) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    try:
        if debugfs_exists(image, path):
            debugfs(image, f"rm {path}", write=True)
        debugfs(image, f"write {temp_path} {path}", write=True)
        debugfs(image, f"ea_set {path} security.selinux {label}", write=True)
    finally:
        temp_path.unlink(missing_ok=True)


def debugfs_replace(image: Path, path: str, data: bytes) -> None:
    label = debugfs_label(image, path)
    if label is None:
        raise BuildError(f"{image.name}:{path} has no security.selinux label")
    debugfs_write_file(image, path, data, label)


def walk_files(image: Path, directory: str) -> Iterator[Tuple[str, str]]:
    for name, mode in debugfs_ls(image, directory):
        child = f"{directory.rstrip('/')}/{name}"
        if mode.startswith("4"):
            yield from walk_files(image, child)
        else:
            yield child, mode
