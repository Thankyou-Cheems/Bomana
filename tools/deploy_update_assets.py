#!/usr/bin/env python3
"""Deploy locally built Bomana update assets to the Tencent update server."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

from bomana.launcher_core import (
    RELEASE_MANIFEST_DEFAULT_KEY_ID,
    verify_release_manifest_signature,
)

CHANNELS = ("Enhanced", "Standard", "Lite")
DEFAULT_HOST = "TencentCloudPublic"
DEFAULT_REMOTE_ROOT = "/opt/stacks/bomana-update"
DEFAULT_PUBLIC_BASE_URL = "https://bomanaupdate.ruikang.wang"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("app", "launcher", "all"),
        default="app",
        help="Asset group to deploy from dist/",
    )
    parser.add_argument(
        "--version",
        default="",
        help="App version for app assets; defaults to bomana/metadata.py __version__.",
    )
    parser.add_argument(
        "--launcher-version",
        default="",
        help="Launcher version; defaults to LAUNCHER_VERSION in launcher.pyw.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH host or config alias.")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT, help="Remote service root.")
    parser.add_argument("--dist", default="dist", help="Local release asset directory.")
    parser.add_argument(
        "--public-base-url",
        default=DEFAULT_PUBLIC_BASE_URL,
        help="Public update service base URL used for endpoint verification.",
    )
    parser.add_argument(
        "--skip-public-verify",
        action="store_true",
        help="Skip public HTTPS endpoint checks after deploying.",
    )
    return parser.parse_args()


def run(cmd: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        input=input_text,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def read_literal(path: Path, name: str) -> str:
    match = re.search(rf'{name}\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"failed to read {name} from {path}")
    return match.group(1).strip()


def required_assets(dist: Path, target: str, app_version: str, launcher_version: str) -> list[Path]:
    assets: list[Path] = []
    if target in {"app", "all"}:
        for channel in CHANNELS:
            assets.extend(
                [
                    dist / f"Bomana_app_{channel}_v{app_version}.zip",
                    dist / f"manifest_{channel}.json",
                    dist / f"checksums_app_{channel}.txt",
                ]
            )
    if target in {"launcher", "all"}:
        assets.extend(
            [
                dist / f"Bomana_launcher_v{launcher_version}.exe",
                dist / "launcher_manifest.json",
                dist / "checksums_launcher.txt",
            ]
        )
    missing = [path for path in assets if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "missing release assets:\n" + "\n".join(f"  - {path}" for path in missing)
        )
    return assets


def public_key_config() -> tuple[str, dict[str, str]]:
    public_key = os.environ.get("BOMANA_RELEASE_ED25519_PUBLIC_KEY", "").strip()
    key_id = os.environ.get(
        "BOMANA_RELEASE_SIGNING_KEY_ID",
        RELEASE_MANIFEST_DEFAULT_KEY_ID,
    ).strip()
    if not public_key:
        raise RuntimeError("BOMANA_RELEASE_ED25519_PUBLIC_KEY is required for release verify")
    if not key_id:
        raise RuntimeError("BOMANA_RELEASE_SIGNING_KEY_ID must not be empty")
    return key_id, {key_id: public_key}


def local_asset_path(dist: Path, asset_name: object, field_name: str) -> Path:
    if not isinstance(asset_name, str) or not asset_name.strip():
        raise RuntimeError(f"{field_name} must be a non-empty filename")
    if "/" in asset_name or "\\" in asset_name:
        raise RuntimeError(f"{field_name} must not contain path separators")
    candidate_name = Path(asset_name)
    if candidate_name.is_absolute() or candidate_name.name != asset_name:
        raise RuntimeError(f"{field_name} must be a filename, got {asset_name!r}")
    dist_root = dist.resolve()
    candidate = (dist / candidate_name).resolve()
    try:
        candidate.relative_to(dist_root)
    except ValueError as exc:
        raise RuntimeError(f"{field_name} escapes dist directory: {asset_name!r}") from exc
    if not candidate.exists():
        raise FileNotFoundError(f"{field_name} asset missing: {candidate}")
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def validate_local_release_assets(
    dist: Path,
    target: str,
    app_version: str,
    launcher_version: str,
) -> None:
    _key_id, public_keys = public_key_config()
    if target in {"app", "all"}:
        for channel in CHANNELS:
            manifest_src = dist / f"manifest_{channel}.json"
            manifest = json.loads(manifest_src.read_text(encoding="utf-8"))
            verify_release_manifest_signature(
                manifest,
                manifest_label=f"{manifest_src.name} ",
                public_keys=public_keys,
                expected_kind="app",
            )
            if manifest.get("app_version") != app_version:
                raise RuntimeError(f"{manifest_src.name} app_version mismatch")
            asset_src = local_asset_path(dist, manifest.get("package_asset"), "package_asset")
            if sha256_file(asset_src) != str(manifest.get("package_sha256", "")).lower():
                raise RuntimeError(f"{asset_src.name} sha256 mismatch")

    if target in {"launcher", "all"}:
        manifest_src = dist / "launcher_manifest.json"
        manifest = json.loads(manifest_src.read_text(encoding="utf-8"))
        verify_release_manifest_signature(
            manifest,
            manifest_label=f"{manifest_src.name} ",
            public_keys=public_keys,
            expected_kind="launcher",
        )
        if manifest.get("launcher_version") != launcher_version:
            raise RuntimeError("launcher version mismatch")
        asset_src = local_asset_path(dist, manifest.get("launcher_asset"), "launcher_asset")
        if sha256_file(asset_src) != str(manifest.get("launcher_sha256", "")).lower():
            raise RuntimeError(f"{asset_src.name} sha256 mismatch")


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def remote_env_command(
    *,
    stage_dir: str,
    remote_root: str,
    target: str,
    app_version: str,
    launcher_version: str,
) -> str:
    env = {
        "STAGE_DIR": stage_dir,
        "REMOTE_ROOT": remote_root,
        "TARGET": target,
        "APP_VERSION": app_version,
        "LAUNCHER_VERSION": launcher_version,
    }
    assignments = " ".join(f"{name}={shell_quote(value)}" for name, value in env.items())
    return f"{assignments} python3 -"


def prepare_remote(host: str, stage_dir: str) -> None:
    quoted_stage = shell_quote(stage_dir)
    run(["ssh", host, f"rm -rf {quoted_stage} && mkdir -p {quoted_stage}"])


def upload_assets(host: str, stage_dir: str, assets: list[Path]) -> None:
    for asset in assets:
        run(["scp", str(asset), f"{host}:{stage_dir}/{asset.name}"])


def deploy_remote(
    *,
    host: str,
    stage_dir: str,
    remote_root: str,
    target: str,
    app_version: str,
    launcher_version: str,
) -> None:
    script = r"""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

stage_dir = Path(__import__("os").environ["STAGE_DIR"])
remote_root = Path(__import__("os").environ["REMOTE_ROOT"])
target = __import__("os").environ["TARGET"]
app_version = __import__("os").environ["APP_VERSION"]
launcher_version = __import__("os").environ["LAUNCHER_VERSION"]
channels = ("Enhanced", "Standard", "Lite")

def stage_asset_path(stage_dir: Path, asset_name: object, field_name: str) -> Path:
    if not isinstance(asset_name, str) or not asset_name.strip():
        raise SystemExit(f"{field_name} must be a non-empty filename")
    if "/" in asset_name or "\\" in asset_name:
        raise SystemExit(f"{field_name} must not contain path separators")
    candidate_name = Path(asset_name)
    if candidate_name.is_absolute() or candidate_name.name != asset_name:
        raise SystemExit(f"{field_name} must be a filename, got {asset_name!r}")
    stage_root = stage_dir.resolve()
    candidate = (stage_dir / candidate_name).resolve()
    try:
        candidate.relative_to(stage_root)
    except ValueError as exc:
        raise SystemExit(f"{field_name} escapes stage directory: {asset_name!r}") from exc
    return candidate

def require_manifest_signature(manifest: dict, manifest_name: str) -> None:
    signature = manifest.get("manifest_signature")
    if not isinstance(signature, dict):
        raise SystemExit(f"{manifest_name} missing manifest_signature")
    if signature.get("algorithm") != "ed25519":
        raise SystemExit(f"{manifest_name} has unsupported manifest_signature algorithm")
    if not signature.get("key_id") or not signature.get("signature"):
        raise SystemExit(f"{manifest_name} has incomplete manifest_signature")

manifest_dir = remote_root / "data" / "manifests"
download_dir = remote_root / "data" / "downloads"
launcher_manifest = remote_root / "data" / "launcher_manifest.json"
backup_dir = Path("/opt/backups/bomana-update") / (
    "release-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
)
backup_dir.mkdir(parents=True, exist_ok=True)

db_path = remote_root / "data" / "stats.db"
if db_path.exists():
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(backup_dir / "stats.db")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    conn = sqlite3.connect(db_path)
    try:
        print("stats_integrity=", conn.execute("pragma integrity_check").fetchone()[0])
        print("events_total=", conn.execute("select count(*) from events").fetchone()[0])
    finally:
        conn.close()

for path in manifest_dir.glob("manifest_*.json"):
    shutil.copy2(path, backup_dir / path.name)
for path in launcher_manifest.parent.glob("launcher_manifest*.json"):
    shutil.copy2(path, backup_dir / path.name)

if target in {"app", "all"}:
    for channel in channels:
        manifest_src = stage_dir / f"manifest_{channel}.json"
        manifest = json.loads(manifest_src.read_text(encoding="utf-8"))
        require_manifest_signature(manifest, manifest_src.name)
        asset_src = stage_asset_path(stage_dir, manifest["package_asset"], "package_asset")
        asset_sha = hashlib.sha256(asset_src.read_bytes()).hexdigest()
        if asset_sha != manifest["package_sha256"]:
            raise SystemExit(f"{asset_src.name} sha256 mismatch")
        if manifest["app_version"] != app_version:
            raise SystemExit(f"{manifest_src.name} app_version mismatch")

        shutil.copy2(asset_src, download_dir / asset_src.name)
        checksum_src = stage_dir / f"checksums_app_{channel}.txt"
        if checksum_src.exists():
            shutil.copy2(checksum_src, download_dir / checksum_src.name)
        versioned_manifest = manifest_dir / f"manifest_{channel}_v{app_version}.json"
        shutil.copy2(manifest_src, versioned_manifest)
        shutil.copy2(manifest_src, manifest_dir / f"manifest_{channel}.json")
        print("deployed_app=", channel, app_version, asset_src.name)

if target in {"launcher", "all"}:
    manifest_src = stage_dir / "launcher_manifest.json"
    manifest = json.loads(manifest_src.read_text(encoding="utf-8"))
    require_manifest_signature(manifest, manifest_src.name)
    asset_src = stage_asset_path(stage_dir, manifest["launcher_asset"], "launcher_asset")
    asset_sha = hashlib.sha256(asset_src.read_bytes()).hexdigest()
    if asset_sha != manifest["launcher_sha256"]:
        raise SystemExit(f"{asset_src.name} sha256 mismatch")
    if manifest["launcher_version"] != launcher_version:
        raise SystemExit("launcher version mismatch")

    shutil.copy2(asset_src, download_dir / asset_src.name)
    checksum_src = stage_dir / "checksums_launcher.txt"
    if checksum_src.exists():
        shutil.copy2(checksum_src, download_dir / checksum_src.name)
    shutil.copy2(manifest_src, launcher_manifest.parent / f"launcher_manifest_v{launcher_version}.json")
    shutil.copy2(manifest_src, launcher_manifest)
    print("deployed_launcher=", launcher_version, asset_src.name)

shutil.rmtree(stage_dir, ignore_errors=True)
print("backup_dir=", backup_dir)
"""
    run(
        [
            "ssh",
            host,
            remote_env_command(
                stage_dir=stage_dir,
                remote_root=remote_root,
                target=target,
                app_version=app_version,
                launcher_version=launcher_version,
            ),
        ],
        input_text=script,
    )


def verify_public(
    *, host: str, public_base_url: str, target: str, app_version: str, launcher_version: str
) -> None:
    _key_id, public_keys = public_key_config()

    def public_asset_url(package_url: object) -> str:
        raw = str(package_url or "").strip()
        if not raw:
            raise RuntimeError("public payload missing package_url")
        return urljoin(f"{public_base_url.rstrip('/')}/", raw.lstrip("/"))

    def sha256_url(url: str) -> str:
        digest = hashlib.sha256()
        with urlopen(url, timeout=60) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest().lower()

    def verify_public_asset(payload: dict, label: str, expected_sha256: str) -> None:
        expected = str(expected_sha256 or "").strip().lower()
        if not expected:
            raise RuntimeError(f"{label} missing signed sha256")
        asset_url = public_asset_url(payload.get("package_url"))
        actual = sha256_url(asset_url)
        if actual != expected:
            raise RuntimeError(f"{label} public asset sha256 mismatch: {asset_url}")

    def verify_signed_payload(
        url: str,
        label: str,
        field: str,
        expected: str,
        *,
        expected_kind: str,
    ) -> dict:
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get(field, "")) != expected:
            raise RuntimeError(f"{label} {field} mismatch: {payload}")
        verify_release_manifest_signature(
            payload,
            manifest_label=f"{label} ",
            public_keys=public_keys,
            expected_kind=expected_kind,
        )
        return payload

    if target in {"app", "all"}:
        for channel in CHANNELS:
            url = (
                f"{public_base_url.rstrip('/')}/api/v1/version"
                f"?channel={channel}&local_version=0.0.0&launcher_version={launcher_version}"
            )
            payload = verify_signed_payload(
                url,
                f"app_{channel}",
                "app_version",
                app_version,
                expected_kind="app",
            )
            verify_public_asset(payload, f"app_{channel}", payload["package_sha256"])
            print(
                "verified_app=",
                payload["app_version"],
                payload["package_sha256"][:12],
                payload["manifest_signature"]["key_id"],
            )
    if target in {"launcher", "all"}:
        url = f"{public_base_url.rstrip('/')}/api/v1/launcher?launcher_version=0.0.0"
        payload = verify_signed_payload(
            url,
            "launcher",
            "launcher_version",
            launcher_version,
            expected_kind="launcher",
        )
        launcher_sha256 = str(payload.get("launcher_sha256", "")).strip().lower()
        package_sha256 = str(payload.get("package_sha256", "")).strip().lower()
        if package_sha256 and package_sha256 != launcher_sha256:
            raise RuntimeError("launcher package_sha256 alias does not match launcher_sha256")
        verify_public_asset(payload, "launcher", launcher_sha256)
        print(
            "verified_launcher=",
            payload["launcher_version"],
            launcher_sha256[:12],
            payload["manifest_signature"]["key_id"],
        )


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    dist = (root / args.dist).resolve()
    if not dist.exists():
        raise FileNotFoundError(f"dist directory not found: {dist}")
    app_version = args.version.strip() or read_literal(
        root / "bomana" / "metadata.py", "__version__"
    )
    launcher_version = args.launcher_version.strip() or read_literal(
        root / "launcher.pyw", "LAUNCHER_VERSION"
    )
    assets = required_assets(dist, args.target, app_version, launcher_version)
    validate_local_release_assets(dist, args.target, app_version, launcher_version)
    stage_dir = f"/tmp/bomana-update-assets-local-{int(time.time())}"

    prepare_remote(args.host, stage_dir)
    upload_assets(args.host, stage_dir, assets)
    deploy_remote(
        host=args.host,
        stage_dir=stage_dir,
        remote_root=args.remote_root,
        target=args.target,
        app_version=app_version,
        launcher_version=launcher_version,
    )
    if not args.skip_public_verify:
        verify_public(
            host=args.host,
            public_base_url=args.public_base_url,
            target=args.target,
            app_version=app_version,
            launcher_version=launcher_version,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
