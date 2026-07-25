#!/usr/bin/env python3
"""Deploy the local docs/ site as a static mirror on the Tencent EdgeOne host.

Design constraints
------------------
- Push only files that already exist on the maintainer workstation.
- The remote host must never pull from GitHub (outbound GitHub is blocked).
- Download links target bomanaupdate.ruikang.wang so EdgeOne CDN can accelerate
  binary distribution; the canonical static site is bomana.ruikang.wang.
- The browser reads the same-origin download-catalog.json generated here, so a
  site-host migration does not require update-API CORS or change Launcher URLs.

Typical usage::

    uv run python tools/deploy_pages_mirror.py
    uv run python tools/deploy_pages_mirror.py --skip-catalog-refresh
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

DEFAULT_HOST = "TencentCloudPublic"
DEFAULT_REMOTE_DIR = "/opt/Website/bomana"
DEFAULT_PUBLIC_BASE_URL = "https://bomana.ruikang.wang"
DEFAULT_CDN_BASE = "https://bomanaupdate.ruikang.wang"
CHANNELS = ("Enhanced", "Standard", "Lite")

# Top-level names under docs/ that must never ship to the public mirror.
EXCLUDE_TOP_LEVEL = {
    ".git",
    ".DS_Store",
    "Thumbs.db",
    # Internal docs stay on GitHub; the product landing page is enough.
    "specs",
    "adr",
    "changes",
    "guides",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "PITFALLS.md",
    "RELEASE_NOTES.md",
    "PRIVACY.md",
    "QUICKSTART.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH host / config alias.")
    parser.add_argument(
        "--remote-dir",
        default=DEFAULT_REMOTE_DIR,
        help="Absolute path on the remote host for the static site root.",
    )
    parser.add_argument(
        "--public-base-url",
        default=DEFAULT_PUBLIC_BASE_URL,
        help="Public HTTPS base used for post-deploy verification.",
    )
    parser.add_argument(
        "--cdn-base",
        default=DEFAULT_CDN_BASE,
        help="EdgeOne update CDN base for catalog refresh and download links.",
    )
    parser.add_argument(
        "--skip-catalog-refresh",
        action="store_true",
        help="Do not rewrite docs/download-catalog.json from the live CDN API.",
    )
    parser.add_argument(
        "--skip-public-verify",
        action="store_true",
        help="Skip HTTPS checks against the public EdgeOne URL.",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def http_json(url: str, timeout: float = 20.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_status(url: str, timeout: float = 20.0) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def refresh_download_catalog(cdn_base: str, catalog_path: Path) -> dict:
    """Rebuild catalog from CDN API on the maintainer machine (not on the server)."""
    launcher = http_json(f"{cdn_base.rstrip('/')}/api/v1/launcher")
    channels: dict[str, dict[str, str]] = {}
    for channel in CHANNELS:
        body = http_json(f"{cdn_base.rstrip('/')}/api/v1/version?channel={channel}")
        channels[channel] = {
            "app_version": str(body.get("app_version") or ""),
            "package_url": str(body.get("package_url") or ""),
            "asset": str(body.get("package_asset") or ""),
            "sha256": str(body.get("package_sha256") or ""),
        }

    catalog = {
        "schema_version": 1,
        "primary_source": "TencentCloud",
        "cdn_base": cdn_base.rstrip("/"),
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "launcher": {
            "version": str(launcher.get("launcher_version") or launcher.get("version") or ""),
            "package_url": str(launcher.get("package_url") or ""),
            "asset": str(launcher.get("launcher_asset") or launcher.get("package_asset") or ""),
            "sha256": str(launcher.get("launcher_sha256") or launcher.get("package_sha256") or ""),
        },
        "channels": channels,
        "github_releases_url": "https://github.com/Thankyou-Cheems/Bomana/releases",
        "notes": (
            "Primary downloads use EdgeOne CDN. Refreshed on the maintainer "
            "workstation; the mirror host never fetches GitHub."
        ),
    }
    if not catalog["launcher"]["package_url"]:
        raise RuntimeError("CDN launcher API returned empty package_url")

    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "catalog_refreshed=",
        catalog["launcher"]["version"],
        catalog["channels"].get("Enhanced", {}).get("app_version"),
        flush=True,
    )
    return catalog


def should_skip(path: Path, docs: Path) -> bool:
    rel_parts = path.relative_to(docs).parts
    if not rel_parts:
        return False
    return rel_parts[0] in EXCLUDE_TOP_LEVEL


def stage_site(docs: Path, stage: Path) -> None:
    """Copy publishable site files into a clean staging directory."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    for path in docs.rglob("*"):
        if path.is_dir() or should_skip(path, docs):
            continue
        rel = path.relative_to(docs)
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    required = [
        stage / "index.html",
        stage / "styles.css",
        stage / "site.js",
        stage / "download-catalog.json",
        stage / "assets" / "shots" / "nav-hud.png",
        stage / "assets" / "shots" / "nav-precision.png",
        stage / "assets" / "shots" / "ccrp-compact.png",
        stage / "assets" / "shots" / "web-cockpit-desktop.png",
    ]
    missing = [str(path.relative_to(stage)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required site files:\n  - " + "\n  - ".join(missing))


def deploy_stage(host: str, remote_dir: str, stage: Path) -> None:
    remote_stage = f"/tmp/bomana-pages-stage-{int(time.time())}"
    run(["ssh", host, f"rm -rf {remote_stage} && mkdir -p {remote_stage}"])
    run(["scp", "-r", f"{stage}/.", f"{host}:{remote_stage}/"])

    # Keep the remote script POSIX-friendly: some hosts map `bash` to a shell
    # without `pipefail`, and Windows stdin may carry CRLF.
    script = "\n".join(
        [
            "set -eu",
            f"REMOTE_DIR={json.dumps(remote_dir)}",
            f"STAGE={json.dumps(remote_stage)}",
            'mkdir -p "$REMOTE_DIR"',
            "if command -v rsync >/dev/null 2>&1; then",
            '  rsync -a --delete "$STAGE"/ "$REMOTE_DIR"/',
            "else",
            '  find "$REMOTE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +',
            '  cp -a "$STAGE"/. "$REMOTE_DIR"/',
            "fi",
            "if id lighthouse >/dev/null 2>&1; then",
            '  chown -R lighthouse:lighthouse "$REMOTE_DIR"',
            "fi",
            'find "$REMOTE_DIR" -type d -exec chmod 755 {} +',
            'find "$REMOTE_DIR" -type f -exec chmod 644 {} +',
            'rm -rf "$STAGE"',
            'echo "deployed_to=$REMOTE_DIR"',
            'test -f "$REMOTE_DIR/index.html"',
            'test -f "$REMOTE_DIR/download-catalog.json"',
            'test -f "$REMOTE_DIR/assets/shots/nav-hud.png"',
            'test -f "$REMOTE_DIR/assets/shots/nav-precision.png"',
            'test -f "$REMOTE_DIR/assets/shots/ccrp-compact.png"',
            "",
        ]
    )
    print("+ ssh", host, "bash -s <<deploy_pages_mirror", flush=True)
    subprocess.run(
        ["ssh", host, "bash", "-s"],
        input=script.encode("utf-8"),
        check=True,
    )


def verify_public(public_base: str, cdn_base: str) -> None:
    base = public_base.rstrip("/")
    checks = [
        f"{base}/",
        f"{base}/index.html",
        f"{base}/styles.css",
        f"{base}/site.js",
        f"{base}/download-catalog.json",
        f"{base}/assets/shots/web-cockpit-desktop.png",
        f"{base}/assets/shots/nav-hud.png",
        f"{base}/assets/shots/nav-precision.png",
        f"{base}/assets/shots/ccrp-compact.png",
        f"{cdn_base.rstrip('/')}/api/v1/launcher",
    ]
    for url in checks:
        status = http_status(url)
        print(f"verify {status} {url}", flush=True)
        if status >= 400:
            raise RuntimeError(f"public verify failed: {status} {url}")


def main() -> int:
    args = parse_args()
    if not DOCS.is_dir():
        raise SystemExit(f"docs directory missing: {DOCS}")

    catalog_path = DOCS / "download-catalog.json"
    if not args.skip_catalog_refresh:
        refresh_download_catalog(args.cdn_base, catalog_path)
    elif not catalog_path.is_file():
        raise SystemExit("download-catalog.json missing; omit --skip-catalog-refresh")

    with tempfile.TemporaryDirectory(prefix="bomana-pages-") as tmp:
        stage = Path(tmp) / "site"
        stage_site(DOCS, stage)
        deploy_stage(args.host, args.remote_dir, stage)

    if not args.skip_public_verify:
        # EdgeOne may need a moment after origin update.
        time.sleep(1.5)
        verify_public(args.public_base_url, args.cdn_base)

    print("public_url=", args.public_base_url.rstrip("/") + "/", flush=True)
    print("cdn_base=", args.cdn_base.rstrip("/"), flush=True)
    print("ok", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"command failed with exit {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
