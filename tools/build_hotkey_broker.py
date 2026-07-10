#!/usr/bin/env python3
"""Build Bomana's native hotkey broker and its fixed-path installer."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROKER_MANIFEST = ROOT / "native" / "hotkey_broker" / "Cargo.toml"
SETUP_MANIFEST = ROOT / "native" / "hotkey_broker_setup" / "Cargo.toml"
BROKER_NAME = "BomanaHotkeyBroker.exe"
SETUP_NAME = "BomanaHotkeyBrokerSetup.exe"
PFX_B64_ENV = "BOMANA_AUTHENTICODE_PFX_B64"
PFX_PASSWORD_ENV = "BOMANA_AUTHENTICODE_PFX_PASSWORD"
SIGNTOOL_ENV = "BOMANA_SIGNTOOL_PATH"
TIMESTAMP_URL_ENV = "BOMANA_AUTHENTICODE_TIMESTAMP_URL"
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("dev", "release"),
        default="dev",
        help="dev builds unsigned local artifacts; release requires Authenticode",
    )
    parser.add_argument(
        "--output",
        default="",
        help="output directory (defaults to build/hotkey-broker-dev or dist)",
    )
    return parser.parse_args()


def run_checked(arguments: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, cwd=ROOT, env=env, check=True)


def cargo_build(manifest: Path, *, extra_env: dict[str, str] | None = None) -> Path:
    environment = os.environ.copy()
    if extra_env:
        environment.update(extra_env)
    run_checked(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            str(manifest),
        ],
        env=environment,
    )
    executable = manifest.parent / "target" / "release" / f"{manifest.parent.name}.exe"
    expected_name = BROKER_NAME if manifest == BROKER_MANIFEST else SETUP_NAME
    executable = executable.with_name(expected_name)
    if not executable.is_file():
        raise RuntimeError(f"Cargo did not produce {expected_name}: {executable}")
    return executable


def find_signtool() -> str:
    configured = os.environ.get(SIGNTOOL_ENV, "").strip()
    candidate = configured or shutil.which("signtool.exe") or shutil.which("signtool")
    if not candidate and os.name == "nt":
        kits_root = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        candidates = sorted(
            kits_root.glob("Windows Kits/10/bin/*/x64/signtool.exe"),
            reverse=True,
        )
        candidate = str(candidates[0]) if candidates else ""
    if not candidate:
        raise RuntimeError(
            f"release broker build requires signtool.exe; set {SIGNTOOL_ENV} if needed"
        )
    return str(Path(candidate).resolve())


def release_certificate_context() -> tuple[bytes, str]:
    encoded = os.environ.get(PFX_B64_ENV, "").strip()
    password = os.environ.get(PFX_PASSWORD_ENV, "")
    if not encoded:
        raise RuntimeError(f"{PFX_B64_ENV} is required for release broker builds")
    if not password:
        raise RuntimeError(f"{PFX_PASSWORD_ENV} is required for release broker builds")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError(f"{PFX_B64_ENV} is not valid base64") from exc
    if len(payload) < 128:
        raise RuntimeError(f"{PFX_B64_ENV} does not contain a valid certificate payload")
    return payload, password


def authenticode_sign(path: Path, *, signtool: str, pfx: Path, password: str) -> None:
    timestamp_url = os.environ.get(TIMESTAMP_URL_ENV, DEFAULT_TIMESTAMP_URL).strip()
    if not timestamp_url:
        raise RuntimeError(f"{TIMESTAMP_URL_ENV} must not be empty")
    run_checked(
        [
            signtool,
            "sign",
            "/fd",
            "SHA256",
            "/td",
            "SHA256",
            "/tr",
            timestamp_url,
            "/f",
            str(pfx),
            "/p",
            password,
            str(path),
        ]
    )
    run_checked([signtool, "verify", "/pa", "/all", str(path)])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(mode: str, output: Path) -> tuple[Path, Path, Path]:
    release = mode == "release"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bomana-hotkey-broker-") as temporary:
        staging = Path(temporary)
        broker_source = cargo_build(BROKER_MANIFEST)
        broker_staged = staging / BROKER_NAME
        shutil.copy2(broker_source, broker_staged)

        signtool = ""
        password = ""
        pfx_path = staging / "authenticode.pfx"
        if release:
            payload, password = release_certificate_context()
            pfx_path.write_bytes(payload)
            signtool = find_signtool()
            authenticode_sign(broker_staged, signtool=signtool, pfx=pfx_path, password=password)

        setup_source = cargo_build(
            SETUP_MANIFEST,
            extra_env={"BOMANA_BROKER_PAYLOAD": str(broker_staged.resolve())},
        )
        setup_staged = staging / SETUP_NAME
        shutil.copy2(setup_source, setup_staged)
        if release:
            authenticode_sign(setup_staged, signtool=signtool, pfx=pfx_path, password=password)

        broker_output = output / BROKER_NAME
        setup_output = output / SETUP_NAME
        checksums_output = output / "checksums_hotkey_broker.txt"
        shutil.copy2(broker_staged, broker_output)
        shutil.copy2(setup_staged, setup_output)
        checksums_output.write_text(
            f"{sha256_file(broker_output)}  {BROKER_NAME}\n"
            f"{sha256_file(setup_output)}  {SETUP_NAME}\n",
            encoding="utf-8",
        )
    return broker_output, setup_output, checksums_output


def main() -> None:
    args = parse_args()
    default_output = ROOT / ("dist" if args.mode == "release" else "build/hotkey-broker-dev")
    output = Path(args.output).resolve() if args.output else default_output
    artifacts = build(args.mode, output)
    for artifact in artifacts:
        print(artifact)


if __name__ == "__main__":
    main()
