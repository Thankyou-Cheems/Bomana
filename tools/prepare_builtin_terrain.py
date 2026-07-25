#!/usr/bin/env python3
"""Prepare Bomana's pinned terrain source pack for an independent release."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.terrain_release import (  # noqa: E402
    DEFAULT_TERRAIN_PACK_DIR,
    TerrainReleaseError,
    extract_terrain_archive,
    load_terrain_release_spec,
    sanitize_terrain_pack_metadata,
    validate_terrain_archive,
    validate_terrain_pack,
)

ARCHIVE_ENV = "BOMANA_TERRAIN_ARCHIVE"
ARCHIVE_URL_ENV = "BOMANA_TERRAIN_ARCHIVE_URL"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_TERRAIN_PACK_DIR),
        help="Extracted terrain-v1 directory used by tools/build_terrain_release.py.",
    )
    parser.add_argument(
        "--archive",
        default="",
        help=f"Existing pinned archive; defaults to ${ARCHIVE_ENV} when set.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help=(
            "Pinned archive URL to try before release-spec fallbacks. "
            f"${ARCHIVE_URL_ENV} is also honored."
        ),
    )
    return parser.parse_args()


def download_archive(urls: list[str], destination: Path) -> str:
    errors: list[str] = []
    for url in urls:
        try:
            print(f"terrain_download={url}", flush=True)
            request = Request(url, headers={"User-Agent": "BomanaTerrainBuild/1"})
            with urlopen(request, timeout=60) as response, destination.open("wb") as file_obj:
                shutil.copyfileobj(response, file_obj, length=1024 * 1024)
            return url
        except (OSError, TimeoutError, URLError) as exc:
            errors.append(f"{url}: {exc}")
            destination.unlink(missing_ok=True)
    raise TerrainReleaseError("all terrain archive downloads failed:\n" + "\n".join(errors))


def main() -> int:
    args = parse_args()
    spec = load_terrain_release_spec()
    output_dir = Path(args.output).expanduser().resolve()
    if output_dir.exists():
        sanitize_terrain_pack_metadata(output_dir, spec)
        summary = validate_terrain_pack(output_dir, spec)
        print(f"terrain_ready={summary}", flush=True)
        return 0

    configured_archive = str(args.archive or os.environ.get(ARCHIVE_ENV, "")).strip()
    if configured_archive:
        archive_path = Path(configured_archive).expanduser().resolve()
        validate_terrain_archive(archive_path, spec)
        summary = extract_terrain_archive(archive_path, output_dir, spec)
        print(f"terrain_ready={summary}", flush=True)
        return 0

    env_url = os.environ.get(ARCHIVE_URL_ENV, "").strip()
    urls = [*args.url]
    if env_url:
        urls.insert(0, env_url)
    urls.extend(url for url in spec.download_urls if url not in urls)
    with tempfile.TemporaryDirectory(prefix="bomana_terrain_download_") as temp_dir:
        archive_path = Path(temp_dir) / spec.archive_asset
        source = download_archive(urls, archive_path)
        validate_terrain_archive(archive_path, spec)
        summary = extract_terrain_archive(archive_path, output_dir, spec)
    print(f"terrain_source={source}", flush=True)
    print(f"terrain_ready={summary}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TerrainReleaseError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from None
