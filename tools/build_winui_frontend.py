#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build WinUI3 frontend and export runtime files for portable app packaging."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default="winui/Bomana.WinUI3/Bomana.WinUI3.csproj",
        help="WinUI csproj path",
    )
    parser.add_argument(
        "--configuration",
        default="Release",
        choices=("Debug", "Release"),
        help="Build configuration",
    )
    parser.add_argument(
        "--platform",
        default="x64",
        choices=("x86", "x64", "ARM64"),
        help="WinUI platform target",
    )
    parser.add_argument(
        "--output",
        default="winui/dist",
        help="Export folder containing Bomana.WinUI3.exe and dependencies",
    )
    return parser.parse_args()


def find_runtime_dir(project_dir: Path, platform: str, configuration: str) -> Path:
    base = project_dir / "bin" / platform / configuration
    if not base.exists():
        raise RuntimeError(f"Build output not found: {base}")

    hits = []
    for exe in base.rglob("Bomana.WinUI3.exe"):
        try:
            hits.append((exe.stat().st_mtime, exe.parent))
        except OSError:
            continue
    if not hits:
        raise RuntimeError("No Bomana.WinUI3.exe found in build output")

    hits.sort(key=lambda x: x[0], reverse=True)
    return hits[0][1]


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    project = (root / args.project).resolve()
    if not project.exists():
        raise RuntimeError(f"WinUI project not found: {project}")

    cmd = [
        "dotnet",
        "build",
        str(project),
        "-c",
        args.configuration,
        "-p:Platform={}".format(args.platform),
    ]
    subprocess.run(cmd, check=True, cwd=root)

    runtime_dir = find_runtime_dir(project.parent, args.platform, args.configuration)
    out_dir = (root / args.output).resolve()

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    shutil.copytree(runtime_dir, out_dir)

    print(f"[OK] WinUI runtime exported to: {out_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[ERR] {e}")
        raise
