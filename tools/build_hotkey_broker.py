#!/usr/bin/env python3
"""Build Bomana's zero-install native hotkey broker."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROKER_MANIFEST = ROOT / "native" / "hotkey_broker" / "Cargo.toml"
BROKER_NAME = "BomanaHotkeyBroker.exe"
BROKER_CHECKSUM_NAME = "BomanaHotkeyBroker.sha256"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("dev", "release"),
        default="dev",
        help="select the default output directory; both modes build the same native binary",
    )
    parser.add_argument(
        "--output",
        default="",
        help="output directory (defaults to build/hotkey-broker-dev or build/hotkey-broker-release)",
    )
    return parser.parse_args()


def run_checked(arguments: list[str]) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def cargo_build() -> Path:
    run_checked(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            str(BROKER_MANIFEST),
        ]
    )
    executable = BROKER_MANIFEST.parent / "target" / "release" / BROKER_NAME
    if not executable.is_file():
        raise RuntimeError(f"Cargo did not produce {BROKER_NAME}: {executable}")
    return executable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bomana-hotkey-broker-") as temporary:
        broker_staged = Path(temporary) / BROKER_NAME
        shutil.copy2(cargo_build(), broker_staged)
        broker_output = output / BROKER_NAME
        checksums_output = output / BROKER_CHECKSUM_NAME
        shutil.copy2(broker_staged, broker_output)
        checksums_output.write_text(
            f"{sha256_file(broker_output)}  {BROKER_NAME}\n",
            encoding="ascii",
        )
    return broker_output, checksums_output


def main() -> None:
    args = parse_args()
    suffix = "release" if args.mode == "release" else "dev"
    default_output = ROOT / f"build/hotkey-broker-{suffix}"
    output = Path(args.output).resolve() if args.output else default_output
    for artifact in build(output):
        print(artifact)


if __name__ == "__main__":
    main()
