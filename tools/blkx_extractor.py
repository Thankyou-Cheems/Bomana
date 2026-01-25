#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
War Thunder .blkx bomb parameter extractor.

Input: the extracted .blkx files from the War Thunder datamine repo.
Output: ccrp_bomb_params.json for Bomana.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


class BlkxExtractor:
    """Batch-extract bomb ballistic parameters from .blkx files."""

    REQUIRED_PARAMS = [
        "mass",
        "mass_lbs",
        "caliber",
        "length",
        "distFromCmToStab",
        "dragCx",
        "brakeTime",
        "brakeCxK",
        "brakeArm",
        "visRotationFreqX",
        "stabilityThreshold",
        "stabilityRicochetModifier",
    ]

    BOMB_TYPE_PATTERNS = {
        "high_explosive": ["mk", "hc", "gp", "ldgp"],
        "incendiary": ["zb", "napalm", "incendiary"],
        "anti_tank": ["antitank", "at"],
        "cluster": ["cluster"],
        "heavy_strategic": ["12000lb", "4000lb", "8000lb", "10000lb"],
    }

    def __init__(self):
        self.results = []
        self.error_count = 0
        self.no_bomb_files = []
        self.skipped_types = {}

    def parse_blkx_content(self, content: str):
        """Remove comments then parse JSON."""
        try:
            content_clean = re.sub(r"//.*?(?=\n|$)", "", content, flags=re.MULTILINE)
            content_clean = re.sub(r"/\*.*?\*/", "", content_clean, flags=re.DOTALL)
            return json.loads(content_clean)
        except json.JSONDecodeError as exc:
            print(f"  JSON parse error: {exc}")
            return None

    @staticmethod
    def normalize_filename(mesh_value):
        """Mesh can be string or list; normalize to a string name."""
        if isinstance(mesh_value, list):
            return str(mesh_value[-1]) if mesh_value else "unknown"
        if isinstance(mesh_value, str):
            return mesh_value
        return "unknown"

    def extract_ballistic_params(self, config: dict):
        """Extract ballistic parameters needed by CCRP."""
        if not config or "bomb" not in config:
            return None

        bomb_config = config["bomb"]
        extracted = {}

        mesh_value = config.get("mesh", "unknown")
        extracted["filename"] = self.normalize_filename(mesh_value)
        extracted["preset_cost"] = config.get("preset_cost", 0)

        for param in self.REQUIRED_PARAMS:
            if param in bomb_config:
                extracted[param] = bomb_config[param]

        if "caliber" in extracted:
            cal = extracted["caliber"]
            extracted["cross_section"] = 3.1415926535 * (cal / 2) ** 2

        if all(k in extracted for k in ("mass", "dragCx", "cross_section")):
            extracted["ballistic_coeff"] = (
                extracted["mass"] / (extracted["dragCx"] * extracted["cross_section"])
            )

        extracted["type_tags"] = []
        fn_lower = extracted["filename"].lower()
        for bomb_type, kws in self.BOMB_TYPE_PATTERNS.items():
            if any(kw in fn_lower for kw in kws):
                extracted["type_tags"].append(bomb_type)

        brake_k = extracted.get("brakeCxK", 0)
        extracted["brake_system"] = "active" if brake_k and brake_k > 0 else "none"

        return extracted

    def process_file(self, filepath: Path):
        """Process one .blkx file."""
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            print(f"  Read failed: {exc}")
            self.error_count += 1
            return

        config = self.parse_blkx_content(content)
        if not config:
            print("  JSON parse failed")
            self.error_count += 1
            return

        params = self.extract_ballistic_params(config)
        if not params:
            print("  Missing bomb section or no params extracted")
            self.no_bomb_files.append(filepath.name)
            if isinstance(config, dict):
                if "rocketGun" in config:
                    self.skipped_types[filepath.name] = "rocketGun"
            return

        params["source_file"] = filepath.name
        self.results.append(params)
        print(f"  OK: {params['filename'][:40]}")

    def process_directory(self, directory: str):
        """Recursively scan for .blkx files."""
        root = Path(directory)
        print(f"Scanning: {root}")
        files = sorted(root.rglob("*.blkx"))
        print(f"Found {len(files)} .blkx files")

        for idx, fp in enumerate(files, 1):
            print(f"[{idx:3d}/{len(files):3d}] {fp.name}")
            self.process_file(fp)

        print(f"Valid bomb configs: {len(self.results)}")
        if self.error_count:
            print(f"Failed reads/parses: {self.error_count}")

    def generate_report(self):
        """Console report for sanity checks."""
        if not self.results:
            print("No usable data")
            return

        sorted_results = sorted(
            self.results,
            key=lambda item: item.get("ballistic_coeff", 0),
            reverse=True,
        )

        print("\nTop 30 ballistic coefficient (BC = mass / (dragCx * A))")
        print("-" * 90)
        print(f"{'#':<3} {'file':<32} {'mass':>8} {'drag':>7} {'cal':>6} {'BC*1e6':>9}")
        print("-" * 90)

        for i, bomb in enumerate(sorted_results[:30]):
            mass = bomb.get("mass", 0.0)
            drag = bomb.get("dragCx", 0.0)
            cal = bomb.get("caliber", 0.0)
            bc = bomb.get("ballistic_coeff", 0.0) / 1e6
            print(
                f"{i+1:<3} {bomb['filename'][:31]:<32} "
                f"{mass:>8.1f} {drag:>7.4f} {cal:>6.3f} {bc:>9.3f}"
            )

        complete = sum(
            1 for b in self.results if all(k in b for k in ("mass", "caliber", "dragCx"))
        )
        total = len(self.results)
        print(f"\nComplete (mass+caliber+dragCx): {complete}/{total}")
        if self.no_bomb_files:
            print(f"Non-bomb files skipped: {len(self.no_bomb_files)}")
            if self.skipped_types:
                type_counts = {}
                for t in self.skipped_types.values():
                    type_counts[t] = type_counts.get(t, 0) + 1
                for t, c in sorted(type_counts.items()):
                    print(f"  - {t}: {c}")

    def export_ccrp_params(self, output_file: str = "ccrp_bomb_params.json"):
        """Export BALLISTIC_PARAMS for Bomana (JSON)."""
        ccrp_params = {}
        collision_count = 0

        for bomb in self.results:
            if not all(k in bomb for k in ("mass", "caliber", "dragCx")):
                continue

            # Use source file name (stable + unique) as key to avoid mesh collisions.
            stem = Path(bomb.get("source_file", "")).stem or bomb["filename"]
            key = re.sub(r"[^\w-]", "_", stem.lower())
            key = re.sub(r"(_na|_mesh|_bomb)$", "", key)

            if key in ccrp_params:
                # Rare fallback if filenames still collide.
                collision_count += 1
                suffix = 2
                new_key = f"{key}_{suffix}"
                while new_key in ccrp_params:
                    suffix += 1
                    new_key = f"{key}_{suffix}"
                key = new_key

            ccrp_params[key] = {
                "mass": float(bomb["mass"]),
                "caliber": float(bomb["caliber"]),
                "dragCx": float(bomb["dragCx"]),
                "distFromCmToStab": float(bomb.get("distFromCmToStab", 0.0)),
                "brakeTime": bomb.get("brakeTime", [0.0, 0.0]),
                "brakeCxK": float(bomb.get("brakeCxK", 0.0)),
                "brakeArm": float(bomb.get("brakeArm", 0.0)),
                "stab_enabled": bool(bomb.get("brakeCxK", 0.0) > 0.0),
                "source_file": bomb.get("source_file", ""),
                "mesh": bomb.get("filename", ""),
            }

        payload = {
            "meta": {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "bombs": len(ccrp_params),
                "collisions": collision_count,
                "skipped_non_bomb": len(self.no_bomb_files),
            },
            "ballistic_params": ccrp_params,
        }

        Path(output_file).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"Wrote {len(ccrp_params)} bombs to {output_file}")
        if collision_count:
            print(f"  Note: {collision_count} key collisions resolved with suffixes")
        return ccrp_params


def main():
    parser = argparse.ArgumentParser(
        description="War Thunder .blkx bomb parameter extractor"
    )
    parser.add_argument("directory", nargs="?", help="root directory with .blkx files")
    parser.add_argument(
        "-o",
        "--output",
        default="ccrp_bomb_params.json",
        help="output file (default: ccrp_bomb_params.json)",
    )
    parser.add_argument("--single", help="process a single .blkx file")
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="skip console report",
    )

    args = parser.parse_args()
    extractor = BlkxExtractor()

    if args.single:
        print(f"Processing file: {args.single}")
        extractor.process_file(Path(args.single))
    elif args.directory:
        extractor.process_directory(args.directory)
    else:
        parser.print_help()
        sys.exit(1)

    if extractor.results:
        if not args.no_report:
            extractor.generate_report()
        extractor.export_ccrp_params(args.output)
    else:
        print("No bomb parameters extracted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
