#!/usr/bin/env python3
"""Build a DSU package for sweet.

Usage:
    ./build.py                          # newest LineageOS build
    ./build.py --version 23.2           # pin a series
    ./build.py path/to/lineage-sweet.zip
    ./build.py https://download.lineageos.org/...

Requires brotli, e2fsprogs, lz4, tar and curl.

SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from functions.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
