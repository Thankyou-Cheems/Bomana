#!/usr/bin/env python3
"""
War Thunder .blkx bomb parameter extractor.

Input: the extracted .blkx files from the War Thunder datamine repo.
Output: bomana/data/offline_rigidbody_catalog.bin for Bomana.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datamine_utils import (  # noqa: E402
    BOMBGUNS_SUBDIR,
    normalize_datamine_caliber_m,
    require_datamine_dir,
)

from bomana.core.offline_rigidbody_catalog import (  # noqa: E402
    CATALOG_PROFILE_ID,
    CATALOG_SCHEMA_VERSION,
    encode_catalog,
)
from bomana.core.offline_rigidbody_properties import (  # noqa: E402
    OFFLINE_DEFAULT_AOA_DRAG_COEFFICIENT,
    OFFLINE_DEFAULT_AXIAL_COEFFICIENT,
    OFFLINE_DEFAULT_LIFT_AREA_SCALE,
    OFFLINE_DEFAULT_NORMAL_AOA_LIMIT,
    OFFLINE_DEFAULT_NORMAL_COEFFICIENT,
)


class BlkxExtractor:
    """Batch-extract bomb ballistic parameters from .blkx files."""

    GUIDED_OR_GLIDE_KEYWORDS: ClassVar[tuple[str, ...]] = (
        "agm",
        "bgl",
        "gbu",
        "gbu_",
        "gb250",
        "gcs_1",
        "glide",
        "grom",
        "guided",
        "hosbo",
        "jdam",
        "jsow",
        "kab",
        "kggb",
        "laser",
        "lizard",
        "lgb",
        "ljdam",
        "ls_6",
        "paveway",
        "pgb",
        "sdb",
        "spice",
        "tv",
        "umpk",
        "upab",
        "walleye",
        "fx1400",
    )
    HIGH_DRAG_KEYWORDS: ClassVar[tuple[str, ...]] = (
        "air_na",
        "ballute",
        "brp",
        "fab500sh",
        "ofab250sh",
        "parachute",
        "retarded",
        "snakeye",
    )
    HIGH_DRAG_BRAKE_COEFFICIENT_MIN = 10.0

    REQUIRED_PARAMS: ClassVar[list[str]] = [
        "mass",
        "mass_lbs",
        "caliber",
        "length",
        "distFromCmToStab",
        "dragCx",
        "wingAreaMult",
        "CxK",
        "CyK",
        "CyMaxAoA",
        "CxAoA",
        "fluidResistanceMultiplier",
        "fluidRotationResistanceMultiplier",
        "finsAoaHor",
        "finsAoaVer",
        "brakeTime",
        "brakeCxK",
        "brakeArm",
        "visRotationFreqX",
        "stabilityThreshold",
        "stabilityRicochetModifier",
    ]

    BOMB_TYPE_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "high_explosive": ["mk", "hc", "gp", "ldgp"],
        "incendiary": ["zb", "napalm", "incendiary"],
        "anti_tank": ["antitank", "at"],
        "cluster": ["cluster"],
        "heavy_strategic": ["12000lb", "4000lb", "8000lb", "10000lb"],
    }

    def __init__(self, *, verbose: bool = True):
        self.results = []
        self.error_count = 0
        self.no_bomb_files = []
        self.skipped_types = {}
        self.verbose = verbose

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def parse_blkx_content(self, content: str):
        """Remove comments then parse JSON."""
        try:
            content_clean = re.sub(r"//.*?(?=\n|$)", "", content, flags=re.MULTILINE)
            content_clean = re.sub(r"/\*.*?\*/", "", content_clean, flags=re.DOTALL)
            return json.loads(content_clean)
        except json.JSONDecodeError as exc:
            self._log(f"  JSON parse error: {exc}")
            return None

    @staticmethod
    def normalize_filename(mesh_value):
        """Mesh can be string or list; normalize to a string name."""
        if isinstance(mesh_value, list):
            return str(mesh_value[-1]) if mesh_value else "unknown"
        if isinstance(mesh_value, str):
            return mesh_value
        return "unknown"

    def extract_ballistic_params(self, config: dict, *, source_name: str = ""):
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
            raw_caliber = float(extracted["caliber"])
            cal, normalization = normalize_datamine_caliber_m(
                raw_caliber,
                source_name,
                extracted["filename"],
                str(bomb_config.get("bulletName", "")),
            )
            extracted["caliber"] = cal
            if normalization is not None:
                extracted["raw_caliber"] = raw_caliber
                extracted["caliber_normalization"] = normalization
            extracted["cross_section"] = 3.1415926535 * (cal / 2) ** 2

        if all(k in extracted for k in ("mass", "dragCx", "cross_section")):
            extracted["ballistic_coeff"] = extracted["mass"] / (
                extracted["dragCx"] * extracted["cross_section"]
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
            self._log("  JSON parse failed")
            self.error_count += 1
            return

        params = self.extract_ballistic_params(config, source_name=filepath.name)
        if not params:
            self._log("  Missing bomb section or no params extracted")
            self.no_bomb_files.append(filepath.name)
            if isinstance(config, dict) and "rocketGun" in config:
                self.skipped_types[filepath.name] = "rocketGun"
            return

        params["source_file"] = filepath.name
        self.results.append(params)
        self._log(f"  OK: {params['filename'][:40]}")

    def process_directory(self, directory: str):
        """Recursively scan for .blkx files."""
        root = Path(directory)
        print(f"Scanning: {root}")
        files = sorted(root.rglob("*.blkx"))
        print(f"Found {len(files)} .blkx files")

        for idx, fp in enumerate(files, 1):
            self._log(f"[{idx:3d}/{len(files):3d}] {fp.name}")
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
                f"{i + 1:<3} {bomb['filename'][:31]:<32} "
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

    @classmethod
    def _prediction_kind(cls, key: str, bomb: dict) -> str:
        text = " ".join(
            (
                key,
                str(bomb.get("source_file", "") or ""),
                str(bomb.get("filename", "") or ""),
            )
        ).lower()
        if any(keyword in text for keyword in cls.GUIDED_OR_GLIDE_KEYWORDS):
            return "guided_glide"
        try:
            brake_coefficient = float(bomb.get("brakeCxK", 0.0) or 0.0)
        except (TypeError, ValueError):
            brake_coefficient = 0.0
        if (
            brake_coefficient >= cls.HIGH_DRAG_BRAKE_COEFFICIENT_MIN
            or any(keyword in text for keyword in cls.HIGH_DRAG_KEYWORDS)
        ):
            return "high_drag"
        return "freefall"

    def export_offline_catalog(
        self,
        output_file: str = "bomana/data/offline_rigidbody_catalog.bin",
    ):
        """Export a compact runtime catalog without per-record source metadata."""

        catalog_records = {}
        collision_count = 0

        for bomb in self.results:
            if not all(k in bomb for k in ("mass", "caliber", "dragCx")):
                continue

            # Use source file name (stable + unique) as key to avoid mesh collisions.
            stem = Path(bomb.get("source_file", "")).stem or bomb["filename"]
            key = re.sub(r"[^\w-]", "_", stem.lower())
            key = re.sub(r"(_na|_mesh|_bomb)$", "", key)

            if key in catalog_records:
                # Rare fallback if filenames still collide.
                collision_count += 1
                suffix = 2
                new_key = f"{key}_{suffix}"
                while new_key in catalog_records:
                    suffix += 1
                    new_key = f"{key}_{suffix}"
                key = new_key

            source_stem = Path(str(bomb.get("source_file", ""))).stem
            aliases = [source_stem] if source_stem and source_stem != key else []
            diameter = float(bomb["caliber"])
            length = float(bomb.get("length", 4.0 * diameter))
            lift_area_scale = float(
                bomb.get("wingAreaMult", OFFLINE_DEFAULT_LIFT_AREA_SCALE)
            )
            record = {
                "mass_kg": float(bomb["mass"]),
                "diameter_m": diameter,
                "length_m": length,
                "display_drag_reference": float(bomb["dragCx"]),
                "prediction_kind": self._prediction_kind(key, bomb),
                "lift_area_scale": lift_area_scale,
                "stabilizer_lever_m": float(
                    bomb.get("distFromCmToStab", 0.3 * length)
                )
                / lift_area_scale,
                "axial_coefficient": float(
                    bomb.get("CxK", OFFLINE_DEFAULT_AXIAL_COEFFICIENT)
                ),
                "normal_coefficient": float(
                    bomb.get("CyK", OFFLINE_DEFAULT_NORMAL_COEFFICIENT)
                ),
                "normal_aoa_limit": float(
                    bomb.get("CyMaxAoA", OFFLINE_DEFAULT_NORMAL_AOA_LIMIT)
                ),
                "aoa_drag_coefficient": float(
                    bomb.get("CxAoA", OFFLINE_DEFAULT_AOA_DRAG_COEFFICIENT)
                ),
            }
            if aliases:
                record["aliases"] = aliases
            catalog_records[key] = record

        payload = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "profile_id": CATALOG_PROFILE_ID,
            "records": catalog_records,
        }
        destination = Path(output_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encode_catalog(payload))

        print(f"Wrote {len(catalog_records)} bombs to {output_file}")
        if collision_count:
            print(f"  Note: {collision_count} key collisions resolved with suffixes")
        return catalog_records


def main():
    parser = argparse.ArgumentParser(description="War Thunder .blkx bomb parameter extractor")
    parser.add_argument("directory", nargs="?", help="root directory with .blkx files")
    parser.add_argument(
        "--datamine-root",
        help="War-Thunder-Datamine repo root; resolves the bombguns directory automatically",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="bomana/data/offline_rigidbody_catalog.bin",
        help="output file (default: bomana/data/offline_rigidbody_catalog.bin)",
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
    elif args.datamine_root:
        source_root = Path(args.datamine_root).resolve()
        try:
            extractor.process_directory(require_datamine_dir(source_root, BOMBGUNS_SUBDIR))
        except FileNotFoundError as exc:
            print(f"[error] {exc}")
            sys.exit(1)
    elif args.directory:
        extractor.process_directory(args.directory)
    else:
        parser.print_help()
        sys.exit(1)

    if extractor.results:
        if not args.no_report:
            extractor.generate_report()
        extractor.export_offline_catalog(args.output)
    else:
        print("No bomb parameters extracted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
