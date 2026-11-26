"""Extract sdat partitions from a ROM zip."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

from .common import BuildError
from .config import BLOCK

try:
    import brotli
except ImportError:  # pragma: no cover - reported by check_dependencies()
    brotli = None  # type: ignore[assignment]


class TransferList:
    def __init__(
        self,
        version: int,
        new_blocks: int,
        commands: List[Tuple[str, List[Tuple[int, int]]]],
    ) -> None:
        self.version = version
        self.new_blocks = new_blocks
        self.commands = commands


def parse_ranges(spec: str) -> List[Tuple[int, int]]:
    """Parse ``count,start,end,...`` ranges (end exclusive)."""
    values = [int(item) for item in spec.split(",") if item.strip()]
    if not values:
        raise BuildError("empty block range")
    count = values[0]
    numbers = values[1:]
    if count != len(numbers) or count % 2 != 0:
        raise BuildError(f"invalid block range set: {spec!r}")
    return [
        (numbers[index], numbers[index + 1])
        for index in range(0, count, 2)
    ]


def parse_transfer_list(data: str, name: str) -> TransferList:
    lines = [line.strip() for line in data.splitlines() if line.strip()]
    if len(lines) < 2:
        raise BuildError(f"{name}: transfer list is too short")
    try:
        version = int(lines[0])
        new_blocks = int(lines[1])
    except ValueError as exc:
        raise BuildError(f"{name}: invalid transfer list header") from exc

    index = 2
    if version >= 2:
        if len(lines) < 4:
            raise BuildError(f"{name}: transfer list is missing the stash header")
        index = 4

    commands: List[Tuple[str, List[Tuple[int, int]]]] = []
    for line in lines[index:]:
        parts = line.split()
        if not parts or parts[0][0].isdigit():
            continue
        command = parts[0]
        if command not in ("new", "erase", "zero"):
            raise BuildError(f"{name}: unsupported transfer command {command!r}")
        if len(parts) < 2:
            raise BuildError(f"{name}: command {command!r} has no ranges")
        commands.append((command, parse_ranges(parts[1])))
    return TransferList(version, new_blocks, commands)


class ChunkReader:
    """Read adapter over decompressed chunks."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""

    def read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            try:
                self._buffer += next(self._chunks)
            except StopIteration:
                break
        result, self._buffer = self._buffer[:size], self._buffer[size:]
        if not result:
            raise BuildError("unexpected end of .new.dat data")
        return result


def sdat2img(transfer: TransferList, chunks: Iterable[bytes], output: Path) -> None:
    new_ranges = [
        (start, end)
        for command, ranges in transfer.commands
        if command == "new"
        for start, end in ranges
    ]
    if not new_ranges:
        raise BuildError("transfer list contains no new blocks")
    if any(end < start for start, end in new_ranges):
        raise BuildError("transfer list contains an invalid block range")

    total_blocks = max(transfer.new_blocks, max(end for _start, end in new_ranges))
    reader = ChunkReader(chunks)
    with output.open("wb") as out:
        out.truncate(total_blocks * BLOCK)
        for command, ranges in transfer.commands:
            if command != "new":
                continue
            for start, end in ranges:
                out.seek(start * BLOCK)
                remaining = (end - start) * BLOCK
                while remaining:
                    data = reader.read(min(remaining, 8 * 1024 * 1024))
                    out.write(data)
                    remaining -= len(data)
        out.truncate(total_blocks * BLOCK)


def _brotli_chunks(handle) -> Iterator[bytes]:
    assert brotli is not None
    decompressor = brotli.Decompressor()
    while True:
        raw = handle.read(1024 * 1024)
        if not raw:
            break
        data = decompressor.process(raw)
        if data:
            yield data
    if not decompressor.is_finished():
        raise BuildError("brotli stream ended early")


def extract_partition(archive: zipfile.ZipFile, name: str, destination: Path) -> None:
    names = set(archive.namelist())
    transfer_name = f"{name}.transfer.list"
    if transfer_name not in names:
        raise BuildError(f"ROM zip has no {transfer_name}")
    transfer = parse_transfer_list(archive.read(transfer_name).decode("utf-8"), name)

    compressed = f"{name}.new.dat.br"
    plain = f"{name}.new.dat"
    if compressed in names:
        with archive.open(compressed) as handle:
            sdat2img(transfer, _brotli_chunks(handle), destination)
    elif plain in names:
        with archive.open(plain) as handle:
            sdat2img(
                transfer,
                iter(lambda: handle.read(4 * 1024 * 1024), b""),
                destination,
            )
    else:
        raise BuildError(f"ROM zip has no {compressed} or {plain}")
