"""Resolve and download a LineageOS build for sweet."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlsplit

from .common import BuildError, log, sha256
from .config import DEVICE

API = "https://download.lineageos.org/api/v2/devices/{device}/builds"
USER_AGENT = "rom2dsu/2.0"


@dataclass
class Rom:
    path: Path
    source: str
    filename: str
    url: str = ""
    sha256: str = ""
    date: str = ""
    size: int = 0


def _fetch_builds(device: str, timeout: int) -> List[Dict[str, Any]]:
    url = API.format(device=device)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BuildError(f"cannot query {url}: {exc}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BuildError(f"{url} did not return JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("builds", [])
    if not isinstance(data, list):
        raise BuildError("unexpected LineageOS API response (expected a list)")
    return [item for item in data if isinstance(item, dict)]


def _zip_file(build: Dict[str, Any], version: str) -> Optional[Dict[str, Any]]:
    files = build.get("files")
    if not isinstance(files, list):
        return None
    candidates: List[Dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("filename") or "")
        url = str(entry.get("url") or "")
        if not name.endswith(".zip") or not url:
            continue
        if version and version not in name:
            continue
        candidates.append(entry)
    if not candidates:
        return None
    # Prefer the versioned zip.
    candidates.sort(key=lambda e: ("lineage-" not in str(e.get("filename")), str(e.get("filename"))))
    return candidates[0]


def latest(device: str, version: str, timeout: int) -> Dict[str, Any]:
    builds = _fetch_builds(device, timeout)
    found: List[tuple[int, Dict[str, Any], Dict[str, Any]]] = []
    for build in builds:
        entry = _zip_file(build, version)
        if entry is None:
            continue
        try:
            stamp = int(build.get("datetime") or 0)
        except (TypeError, ValueError):
            stamp = 0
        found.append((stamp, build, entry))
    if not found:
        suffix = f" matching version {version!r}" if version else ""
        raise BuildError(f"no LineageOS zip found for {device}{suffix}")
    _stamp, build, entry = max(found, key=lambda item: item[0])
    result = {
        "device": device,
        "date": build.get("date") or entry.get("date") or "",
        "datetime": int(build.get("datetime") or 0),
        "type": entry.get("type") or build.get("type") or "",
        "filename": entry.get("filename") or "",
        "url": entry.get("url") or "",
        "sha256": entry.get("sha256") or "",
        "sha1": entry.get("sha1") or "",
        "size": int(entry.get("size") or 0),
    }
    if not result["filename"] or not result["url"] or not result["sha256"]:
        raise BuildError("LineageOS API returned an incomplete zip record")
    return result


def _download(url: str, destination: Path, expected_sha: str, quiet: bool) -> None:
    if shutil.which("curl") is None:
        raise BuildError("curl is required to download the ROM")

    if destination.is_file() and expected_sha and sha256(destination) == expected_sha:
        log(f"cached ROM is complete: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    if destination.is_file() and not expected_sha:
        destination.unlink()

    cmd = [
        "curl",
        "-fL",
        "--retry",
        "5",
        "--retry-all-errors",
        "--retry-delay",
        "5",
        "--connect-timeout",
        "30",
    ]
    if quiet:
        cmd.append("--no-progress-meter")
    if part.exists():
        cmd.append("--continue-at")
        cmd.append("-")
    cmd.extend(["-o", str(part), url])

    log(f"downloading {url}")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise BuildError(f"download failed ({proc.returncode}): {url}")

    if expected_sha:
        actual = sha256(part)
        if actual != expected_sha:
            part.unlink(missing_ok=True)
            raise BuildError(
                f"sha256 mismatch for {destination.name} (expected {expected_sha}, got {actual})"
            )
    part.replace(destination)


def _local(path: Path) -> Rom:
    if not path.is_file():
        raise BuildError(f"ROM zip not found: {path}")
    if path.stat().st_size == 0:
        raise BuildError(f"ROM zip is empty: {path}")
    return Rom(
        path=path,
        source="local",
        filename=path.name,
        sha256=sha256(path),
        size=path.stat().st_size,
    )


def resolve(
    source: Optional[str],
    *,
    version: str = "",
    cache_dir: Path = Path("out/cache"),
    timeout: int = 30,
    quiet: bool = False,
    download: bool = True,
) -> Rom:
    """Return a ROM; download it unless ``download`` is false."""
    if source:
        if source.startswith(("http://", "https://")):
            filename = unquote(Path(urlsplit(source).path).name) or "lineage-sweet.zip"
            destination = cache_dir / filename
            if download:
                _download(source, destination, "", quiet)
            return Rom(
                path=destination,
                source="url",
                filename=filename,
                url=source,
                sha256=sha256(destination) if destination.is_file() else "",
                size=destination.stat().st_size if destination.is_file() else 0,
            )
        return _local(Path(source).expanduser().resolve())

    log(f"querying the LineageOS API for {DEVICE}" + (f" (version {version})" if version else ""))
    build = latest(DEVICE, version, timeout)
    log(f"latest build: {build['filename']} ({build['date']})")
    destination = cache_dir / build["filename"]
    if download:
        _download(build["url"], destination, build["sha256"], quiet)
    return Rom(
        path=destination,
        source="lineage-api",
        filename=build["filename"],
        url=build["url"],
        sha256=build["sha256"],
        date=build["date"],
        size=build["size"] or (destination.stat().st_size if destination.is_file() else 0),
    )
