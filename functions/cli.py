"""Command-line interface."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import rom
from .common import BuildError
from .pipeline import build


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Build a sweet LineageOS DSU package.",
    )
    parser.add_argument(
        "rom",
        nargs="?",
        help="local zip or http(s) URL; omit to query the LineageOS API",
    )
    parser.add_argument(
        "--version",
        default=os.environ.get("LINEAGE_VERSION", ""),
        help="LineageOS series for the API, e.g. 23.2 (default: newest)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("out/cache"),
        help="download cache (default: out/cache)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="API timeout in seconds")
    parser.add_argument("--quiet", action="store_true", help="hide download progress")
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help="print the resolved ROM and exit",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path("out/work"),
        help="scratch directory for the raw images (default: out/work)",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("artifacts"),
        help="output directory (default: artifacts)",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        default=os.environ.get("KEEP_WORK") == "1",
        help="keep the raw images after the build",
    )
    args = parser.parse_args(argv)

    source = args.rom or os.environ.get("ROM_ZIP") or os.environ.get("ROM_URL")
    quiet = args.quiet or bool(os.environ.get("CI"))

    try:
        resolved = rom.resolve(
            source,
            version=args.version,
            cache_dir=args.cache_dir,
            timeout=args.timeout,
            quiet=quiet,
            download=not args.resolve_only,
        )
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"ROM:    {resolved.filename}")
    print(f"source: {resolved.source}")
    if resolved.url:
        print(f"url:    {resolved.url}")
    print(f"sha256: {resolved.sha256}")
    if resolved.date:
        print(f"date:   {resolved.date}")
    print(f"path:   {resolved.path}")

    if args.resolve_only:
        return 0

    try:
        build(
            resolved.path,
            args.workdir,
            args.artifacts,
            keep_work=args.keep_work,
        )
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
