"""Drop persist writes from vendor init scripts."""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

from . import ext4
from .common import BuildError, log
from .config import PERSIST_MOUNTS


def touches_persist(tokens: Sequence[str]) -> bool:
    for token in tokens:
        for mount in PERSIST_MOUNTS:
            if token == mount or token.startswith(mount + "/"):
                return True
    return False


def patch_text(text: str) -> Tuple[str, bool]:
    output: List[str] = []
    changed = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output.append(line)
            continue
        tokens = stripped.split()
        command = tokens[0]

        if command in ("restorecon", "restorecon_recursive") and touches_persist(
            tokens[1:]
        ):
            changed = True
            continue
        if command in ("mkdir", "chown", "chmod") and touches_persist(tokens[1:]):
            changed = True
            continue

        if command == "mount" and len(tokens) >= 4 and tokens[3] in PERSIST_MOUNTS:
            if "ro" not in tokens[4:] and "rw" not in tokens[4:]:
                indent = line[: len(line) - len(line.lstrip())]
                line = indent + " ".join(tokens[:4] + ["ro"] + tokens[4:])
                changed = True

        output.append(line)

    result = "\n".join(output)
    if text.endswith("\n"):
        result += "\n"
    return result, changed


def patch_image(image: Path) -> None:
    if not ext4.debugfs_exists(image, "/etc/init"):
        raise BuildError("vendor image has no /etc/init")
    for path, _mode in ext4.walk_files(image, "/etc/init"):
        if not path.endswith(".rc"):
            continue
        original = ext4.debugfs(image, f"cat {path}")
        patched, changed = patch_text(original.decode("utf-8", "replace"))
        if changed:
            ext4.debugfs_replace(image, path, patched.encode("utf-8"))
            log(f"vendor:{path}: persist is read-only")
