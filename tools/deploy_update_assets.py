#!/usr/bin/env python3
"""Deploy locally built Bomana update assets to the Tencent update server."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.editions import PUBLIC_CHANNELS  # noqa: E402
from launcher.core import (  # noqa: E402
    RELEASE_MANIFEST_DEFAULT_KEY_ID,
    verify_release_manifest_signature,
)

DEFAULT_HOST = "TencentCloudPublic"
DEFAULT_REMOTE_ROOT = "/opt/stacks/bomana-update"
DEFAULT_PUBLIC_BASE_URL = "https://bomanaupdate.ruikang.wang"
EDGEONE_UPDATE_HOST = "bomanaupdate.ruikang.wang"
EDGEONE_REQUEST_ID_HEADER = "EO-LOG-UUID"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("app", "launcher", "all"),
        default="app",
        help="Public asset group to deploy from dist/.",
    )
    parser.add_argument(
        "--version",
        default="",
        help="App version for app assets; defaults to bomana/metadata.py __version__.",
    )
    parser.add_argument(
        "--launcher-version",
        default="",
        help="Launcher version; defaults to LAUNCHER_VERSION in launcher/metadata.py.",
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
        for channel in PUBLIC_CHANNELS:
            assets.extend(
                [
                    dist / f"Bomana_app_{channel}_v{app_version}.zip",
                    dist / f"manifest_{channel}.json",
                    dist / f"CHANGELOG_{channel}_v{app_version}.md",
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
    try:
        if len(base64.b64decode(public_key, validate=True)) != 32:
            raise ValueError
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError("BOMANA_RELEASE_ED25519_PUBLIC_KEY must decode to 32 bytes") from exc
    public_keys = {key_id: public_key}
    raw_legacy = os.environ.get("BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON", "").strip()
    if not raw_legacy:
        return key_id, public_keys
    try:
        legacy = json.loads(raw_legacy)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON must contain a JSON object"
        ) from exc
    if not isinstance(legacy, dict):
        raise RuntimeError("BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON must contain a JSON object")
    for legacy_id, legacy_key in sorted(legacy.items(), key=lambda item: str(item[0])):
        if not isinstance(legacy_id, str) or not legacy_id.strip():
            raise RuntimeError("BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON contains an empty key id")
        if not isinstance(legacy_key, str) or not legacy_key.strip():
            raise RuntimeError(
                f"BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON contains an empty public key for {legacy_id!r}"
            )
        normalized_id = legacy_id.strip()
        normalized_key = legacy_key.strip()
        if normalized_id == key_id:
            raise RuntimeError(
                "BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON must not replace the active signing key id"
            )
        try:
            if len(base64.b64decode(normalized_key, validate=True)) != 32:
                raise ValueError
        except (ValueError, binascii.Error) as exc:
            raise RuntimeError(
                f"BOMANA_RELEASE_LEGACY_PUBLIC_KEYS_JSON contains an invalid public key for {normalized_id!r}"
            ) from exc
        public_keys[normalized_id] = normalized_key
    return key_id, public_keys


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


def require_edgeone_public_url(url: str, *, label: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != EDGEONE_UPDATE_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise RuntimeError(f"{label} must use the EdgeOne update host: {value}")
    return value


def require_edgeone_public_base(public_base_url: str) -> str:
    value = require_edgeone_public_url(public_base_url, label="public base URL")
    parsed = urlparse(value)
    if parsed.path not in ("", "/") or parsed.params or parsed.query:
        raise RuntimeError(f"public base URL must be the EdgeOne origin root: {value}")
    return value.rstrip("/")


def _response_header(response: object, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return str(value).strip()
    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        value = getheader(name)
        if value is not None:
            return str(value).strip()
    return ""


def require_edgeone_response(response: object, *, requested_url: str) -> None:
    geturl = getattr(response, "geturl", None)
    final_url = str(geturl() if callable(geturl) else requested_url).strip()
    require_edgeone_public_url(final_url, label="public response URL")
    request_id = _response_header(response, EDGEONE_REQUEST_ID_HEADER)
    if not request_id:
        raise RuntimeError(
            f"public response did not traverse EdgeOne "
            f"({EDGEONE_REQUEST_ID_HEADER} missing): {requested_url}"
        )


def validate_local_release_assets(
    dist: Path,
    target: str,
    app_version: str,
    launcher_version: str,
) -> None:
    _key_id, public_keys = public_key_config()
    if target in {"app", "all"}:
        for channel in PUBLIC_CHANNELS:
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
            changelog_src = local_asset_path(
                dist, manifest.get("changelog_asset"), "changelog_asset"
            )
            if sha256_file(changelog_src) != str(manifest.get("changelog_sha256", "")).lower():
                raise RuntimeError(f"{changelog_src.name} sha256 mismatch")

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
channels = __BOMANA_CHANNELS__

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

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
manifest_dir.mkdir(parents=True, exist_ok=True)
download_dir.mkdir(parents=True, exist_ok=True)
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
        changelog_src = stage_asset_path(
            stage_dir, manifest["changelog_asset"], "changelog_asset"
        )
        asset_sha = sha256_file(asset_src)
        if asset_sha != manifest["package_sha256"]:
            raise SystemExit(f"{asset_src.name} sha256 mismatch")
        changelog_sha = sha256_file(changelog_src)
        if changelog_sha != manifest["changelog_sha256"]:
            raise SystemExit(f"{changelog_src.name} sha256 mismatch")
        if manifest["app_version"] != app_version:
            raise SystemExit(f"{manifest_src.name} app_version mismatch")

        shutil.copy2(asset_src, download_dir / asset_src.name)
        shutil.copy2(changelog_src, download_dir / changelog_src.name)
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
    asset_sha = sha256_file(asset_src)
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
    script = script.replace("__BOMANA_CHANNELS__", repr(PUBLIC_CHANNELS))
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
    *,
    host: str,
    public_base_url: str,
    target: str,
    app_version: str,
    launcher_version: str,
    require_edgeone: bool = True,
) -> None:
    _key_id, public_keys = public_key_config()
    resolved_public_base = (
        require_edgeone_public_base(public_base_url)
        if require_edgeone
        else public_base_url.rstrip("/")
    )

    def public_asset_url(package_url: object) -> str:
        raw = str(package_url or "").strip()
        if not raw:
            raise RuntimeError("public payload missing package_url")
        resolved = urljoin(f"{resolved_public_base}/", raw.lstrip("/"))
        if require_edgeone:
            require_edgeone_public_url(resolved, label="public asset URL")
        return resolved

    def sha256_url(url: str) -> str:
        if require_edgeone:
            require_edgeone_public_url(url, label="public asset URL")
        digest = hashlib.sha256()
        with urlopen(url, timeout=60) as response:
            if require_edgeone:
                require_edgeone_response(response, requested_url=url)
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
        if require_edgeone:
            require_edgeone_public_url(url, label=f"{label} URL")
        with urlopen(url, timeout=20) as response:
            if require_edgeone:
                require_edgeone_response(response, requested_url=url)
            payload = json.loads(response.read().decode("utf-8"))
        verify_release_manifest_signature(
            payload,
            manifest_label=f"{label} ",
            public_keys=public_keys,
            expected_kind=expected_kind,
        )
        if str(payload.get(field, "")) != expected:
            raise RuntimeError(f"{label} {field} mismatch: {payload}")
        return payload

    if target in {"app", "all"}:
        for channel in PUBLIC_CHANNELS:
            url = (
                f"{resolved_public_base}/api/v1/version"
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
            package_url = public_asset_url(payload.get("package_url"))
            changelog_url = urljoin(package_url, str(payload["changelog_asset"]))
            if sha256_url(changelog_url) != str(payload["changelog_sha256"]).lower():
                raise RuntimeError(
                    f"app_{channel} public changelog sha256 mismatch: {changelog_url}"
                )
            print(
                "verified_app=",
                payload["app_version"],
                payload["package_sha256"][:12],
                payload["manifest_signature"]["key_id"],
            )
    if target in {"launcher", "all"}:
        url = f"{resolved_public_base}/api/v1/launcher?launcher_version=0.0.0"
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
        root / "launcher" / "metadata.py", "LAUNCHER_VERSION"
    )
    if not args.skip_public_verify:
        require_edgeone_public_base(args.public_base_url)
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
