import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from launcher import core as launcher_core
from launcher import install_txn as launcher_install
from launcher.terrain_store import TERRAIN_OBJECT_ASSET_PREFIX, TerrainFile, terrain_revision

TEST_SIGNING_PRIVATE_KEY = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"


def load_launcher_module():
    module_name = "launcher_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    loader = importlib.machinery.SourceFileLoader(module_name, "launcher.pyw")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def make_app_zip(
    version: str = "8.1.0",
    *,
    min_launcher_version: str | None = None,
    channel: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    min_launcher_line = (
        f'PORTABLE_MIN_LAUNCHER_VERSION = "{min_launcher_version}"\n'
        if min_launcher_version is not None
        else ""
    )
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Bomana.pyw", "# app entry\n")
        zf.writestr("bomana_version.py", "# shared compatibility boundary\n")
        zf.writestr("bomana/config/__init__.py", f'__version__ = "{version}"\n')
        feature_profile = "ENABLE_CCRP = True\n"
        if channel is not None:
            feature_profile = f'EDITION_CHANNEL = "{channel}"\n' + feature_profile
        zf.writestr("bomana/config/feature_profile.py", feature_profile)
        zf.writestr(
            "bomana/metadata.py",
            f'__version__ = "{version}"\n{min_launcher_line}',
        )
    return buffer.getvalue()


def write_config_package(
    package_dir: Path,
    version: str,
    *,
    sentinel: str | None = None,
    channel: str | None = None,
) -> None:
    config_dir = package_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    sentinel_line = f'SENTINEL = "{sentinel}"\n' if sentinel is not None else ""
    (config_dir / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    feature_profile = "ENABLE_CCRP = True\n"
    if channel is not None:
        feature_profile = f'EDITION_CHANNEL = "{channel}"\n' + feature_profile
    (config_dir / "feature_profile.py").write_text(feature_profile, encoding="utf-8")
    (config_dir / "settings.py").write_text(sentinel_line, encoding="utf-8")
    (package_dir / "metadata.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (package_dir.parent / "bomana_version.py").write_text(
        "# shared compatibility boundary\n",
        encoding="utf-8",
    )


class FakeResponse:
    def __init__(self, body: bytes, headers=None, status: int = 200) -> None:
        self._body = io.BytesIO(body)
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def getcode(self) -> int:
        return self.status


class FakeArtifactAccess:
    def __init__(self, resource: str) -> None:
        self.resource = resource
        self.download_url = f"https://pay.example.test/subscriber-artifacts/{resource}"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer artifact-grant",
            "X-Device-Timestamp": "2026-08-01T12:00:00.000Z",
            "X-Device-Signature": "device-signature",
        }


class LauncherUpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = load_launcher_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_super_bomb_display_name_preserves_enhanced_channel_identity(self) -> None:
        self.assertEqual(
            self.launcher._normalize_channel("超级爆弹版"),
            "Enhanced",
        )
        self.assertEqual(
            self.launcher._channel_display_name("Enhanced"),
            "超级爆弹版",
        )

    def test_terrain_status_copy_covers_installed_update_and_unused_states(self) -> None:
        installed = self.launcher._terrain_status_copy(
            "Enhanced",
            local_state="ready",
            local_revision="a" * 64,
            remote_revision="a" * 64,
            map_count=67,
            total_size_bytes=118 * 1024 * 1024,
        )
        self.assertEqual(installed[0], "已是最新")
        self.assertIn("67 张地图", installed[1])
        self.assertIn("rev aaaaaaaaaaaa", installed[1])

        update = self.launcher._terrain_status_copy(
            "Enhanced",
            local_state="ready",
            local_revision="a" * 64,
            remote_revision="b" * 64,
            map_count=67,
            total_size_bytes=118 * 1024 * 1024,
            update_available=True,
            download_size=4 * 1024 * 1024,
        )
        self.assertEqual(update[0], "可更新")
        self.assertIn("aaaaaaaaaaaa → bbbbbbbbbbbb", update[1])
        self.assertIn("差量", update[1])

        unused = self.launcher._terrain_status_copy(
            "Standard",
            local_state="missing",
        )
        self.assertEqual(unused, ("未使用", "Standard / Lite 不安装离线地图包。", "muted"))

    def test_local_zip_import_uses_streaming_file_installer(self) -> None:
        source = Path("launcher.pyw").read_text(encoding="utf-8")

        self.assertIn("install_txn.install_zip_package_from_file(", source)
        self.assertNotIn("package_bytes = zip_file.read_bytes()", source)

    def write_current_app(self, version: str = "8.0.0") -> None:
        app_dir = self.base / self.launcher.APP_DIR_NAME
        (app_dir / "bomana").mkdir(parents=True)
        (app_dir / "Bomana.pyw").write_text("# app entry\n", encoding="utf-8")
        write_config_package(app_dir / "bomana", version)

    def write_previous_app(self, version: str = "8.0.0") -> None:
        previous_dir = self.base / self.launcher.APP_PREVIOUS_DIR_NAME
        (previous_dir / "bomana").mkdir(parents=True)
        (previous_dir / "Bomana.pyw").write_text("# previous app entry\n", encoding="utf-8")
        write_config_package(previous_dir / "bomana", version)

    def signed_manifest(self, manifest: dict) -> dict:
        manifest = dict(manifest)
        manifest["schema_version"] = 2
        channel = str(manifest.get("channel", "Enhanced"))
        version = str(manifest.get("app_version", "0.0.0")).strip()
        manifest.setdefault("changelog_asset", f"CHANGELOG_{channel}_v{version}.md")
        manifest.setdefault("changelog_sha256", "c" * 64)
        return launcher_core.sign_release_manifest(
            manifest,
            TEST_SIGNING_PRIVATE_KEY,
            key_id="test-key",
        )

    def trusted_release_key_patch(self):
        public_key = launcher_core.ed25519_public_key_from_private_key(TEST_SIGNING_PRIVATE_KEY)
        return patch.dict(
            launcher_core.RELEASE_MANIFEST_PUBLIC_KEYS,
            {"test-key": public_key},
            clear=True,
        )

    def signed_terrain_manifest(self, contents: dict[str, bytes]) -> dict:
        files = tuple(
            TerrainFile(
                path=name,
                asset=(
                    f"{TERRAIN_OBJECT_ASSET_PREFIX}{hashlib.sha256(data).hexdigest()}"
                    f"{Path(name).suffix}"
                ),
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            )
            for name, data in sorted(contents.items())
        )
        payload = {
            "schema_version": 1,
            "terrain_pack_id": "terrain-v1",
            "terrain_revision": terrain_revision("terrain-v1", 1, files),
            "map_count": 1,
            "total_size_bytes": sum(len(data) for data in contents.values()),
            "files": [
                {
                    "path": item.path,
                    "asset": item.asset,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in files
            ],
        }
        signed = launcher_core.sign_release_manifest(
            payload,
            TEST_SIGNING_PRIVATE_KEY,
            key_id="test-key",
        )
        signed["source_name"] = "test-terrain"
        signed["object_base_urls"] = (
            "https://primary.invalid/objects/",
            "https://github.invalid/objects/",
        )
        return signed

    def test_github_app_manifest_requires_release_signature(self) -> None:
        release = {
            "tag_name": "v2.0.0",
            "assets": [
                {
                    "name": "manifest_Enhanced.json",
                    "browser_download_url": "https://example.invalid/manifest.json",
                },
                {
                    "name": "Bomana_app_Enhanced_v2.0.0.zip",
                    "browser_download_url": "https://example.invalid/app.zip",
                    "size": 10,
                },
                {
                    "name": "CHANGELOG_Enhanced_v8.1.0.md",
                    "browser_download_url": "https://example.invalid/changelog.md",
                },
            ],
        }
        manifest = {
            "schema_version": 1,
            "channel": "Enhanced",
            "app_version": "8.1.0",
            "min_launcher_version": "3.0.0",
            "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
            "package_asset": "Bomana_app_Enhanced_v2.0.0.zip",
            "package_sha256": "a" * 64,
        }

        with (
            patch.object(self.launcher, "_fetch_json", return_value=manifest),
            self.assertRaisesRegex(RuntimeError, "缺少发布签名"),
        ):
            self.launcher._manifest_from_github_release(release, "Enhanced")

    def test_github_app_manifest_accepts_signed_release_manifest(self) -> None:
        release = {
            "tag_name": "v2.0.0",
            "assets": [
                {
                    "name": "manifest_Enhanced.json",
                    "browser_download_url": "https://example.invalid/manifest.json",
                },
                {
                    "name": "Bomana_app_Enhanced_v2.0.0.zip",
                    "browser_download_url": "https://example.invalid/app.zip",
                    "size": 10,
                },
                {
                    "name": "CHANGELOG_Enhanced_v8.1.0.md",
                    "browser_download_url": "https://example.invalid/changelog.md",
                },
            ],
        }
        manifest = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Enhanced",
                "app_version": "8.1.0",
                "min_launcher_version": "3.0.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "package_asset": "Bomana_app_Enhanced_v2.0.0.zip",
                "package_sha256": "a" * 64,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_json", return_value=manifest),
        ):
            parsed = self.launcher._manifest_from_github_release(release, "Enhanced")

        self.assertEqual(parsed["remote_version"], "8.1.0")
        self.assertEqual(parsed["package_sha256"], "a" * 64)
        self.assertEqual(parsed["package_url"], "https://example.invalid/app.zip")
        self.assertEqual(parsed["changelog_url"], "https://example.invalid/changelog.md")

    def test_subscriber_manifest_uses_exact_grant_without_public_url(self) -> None:
        signed = self.signed_manifest(
            {
                "channel": "Enhanced",
                "app_version": "8.1.0",
                "min_launcher_version": "3.3.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "package_asset": "Bomana_app_Enhanced_v8.1.0.zip",
                "package_sha256": "a" * 64,
            }
        )
        requested: list[str] = []

        def provider(resource: str) -> FakeArtifactAccess:
            requested.append(resource)
            return FakeArtifactAccess(resource)

        with (
            self.trusted_release_key_patch(),
            patch.object(
                self.launcher,
                "_fetch_bytes",
                return_value=json.dumps(signed).encode("utf-8"),
            ) as fetch,
        ):
            parsed = self.launcher._fetch_manifest_from_subscriber(provider)

        self.assertEqual(
            requested,
            [self.launcher._subscriber_artifacts.APP_MANIFEST_RESOURCE],
        )
        self.assertNotIn("package_url", parsed)
        self.assertEqual(
            parsed["package_resource"],
            "releases/enhanced/Bomana_app_Enhanced_v8.1.0.zip",
        )
        self.assertEqual(
            parsed["changelog_resource"],
            "releases/enhanced/CHANGELOG_Enhanced_v8.1.0.md",
        )
        self.assertEqual(
            fetch.call_args.kwargs["headers"]["Authorization"],
            "Bearer artifact-grant",
        )
        self.assertEqual(fetch.call_args.kwargs["max_bytes"], 1024 * 1024)
        self.assertFalse(fetch.call_args.kwargs["allow_redirects"])

    def test_enhanced_manifest_resolution_fails_without_subscriber_provider(self) -> None:
        service = self.launcher.UpdateService(self.base, "Enhanced", {})

        with self.assertRaisesRegex(RuntimeError, "必须通过 CheemsPay"):
            service.resolve_app_manifest()

    def test_enhanced_package_download_resolves_a_fresh_exact_grant(self) -> None:
        requested: list[str] = []

        def provider(resource: str) -> FakeArtifactAccess:
            requested.append(resource)
            return FakeArtifactAccess(resource)

        service = self.launcher.UpdateService(
            self.base,
            "Enhanced",
            {},
            subscriber_artifact_provider=provider,
        )
        manifest = {
            "package_resource": "releases/enhanced/Bomana_app_Enhanced_v8.1.0.zip",
        }

        with patch.object(
            self.launcher,
            "_download_update_from_manifest",
            return_value=("8.1.0", "CheemsPay"),
        ) as download:
            result = service.download_app_update(manifest)

        self.assertEqual(result, ("8.1.0", "CheemsPay"))
        self.assertEqual(requested, [manifest["package_resource"]])
        resolved_manifest = download.call_args.args[1]
        self.assertEqual(
            resolved_manifest["package_url"],
            "https://pay.example.test/subscriber-artifacts/"
            "releases/enhanced/Bomana_app_Enhanced_v8.1.0.zip",
        )
        self.assertEqual(
            download.call_args.kwargs["download_headers"]["Authorization"],
            "Bearer artifact-grant",
        )
        self.assertFalse(download.call_args.kwargs["allow_redirects"])

    def test_verified_manifest_version_is_not_whitespace_normalized(self) -> None:
        release = {
            "tag_name": "v8.1.0",
            "assets": [
                {
                    "name": "manifest_Enhanced.json",
                    "browser_download_url": "https://example.invalid/manifest.json",
                },
                {
                    "name": "Bomana_app_Enhanced_v8.1.0.zip",
                    "browser_download_url": "https://example.invalid/app.zip",
                    "size": 10,
                },
            ],
        }
        manifest = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Enhanced",
                "app_version": " 8.1.0",
                "min_launcher_version": "3.0.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "package_asset": "Bomana_app_Enhanced_v8.1.0.zip",
                "package_sha256": "a" * 64,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_json", return_value=manifest),
            self.assertRaisesRegex(RuntimeError, "应用版本格式无效"),
        ):
            self.launcher._manifest_from_github_release(release, "Enhanced")

    def test_github_app_manifest_rejects_signed_wrong_channel_manifest(self) -> None:
        release = {
            "tag_name": "v2.0.0",
            "assets": [
                {
                    "name": "manifest_Enhanced.json",
                    "browser_download_url": "https://example.invalid/manifest.json",
                },
                {
                    "name": "Bomana_app_Lite_v2.0.0.zip",
                    "browser_download_url": "https://example.invalid/app.zip",
                    "size": 10,
                },
            ],
        }
        manifest = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Lite",
                "app_version": "8.1.0",
                "min_launcher_version": "3.0.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "package_asset": "Bomana_app_Lite_v2.0.0.zip",
                "package_sha256": "a" * 64,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_json", return_value=manifest),
            self.assertRaisesRegex(RuntimeError, "通道不匹配"),
        ):
            self.launcher._manifest_from_github_release(release, "Enhanced")

    def test_github_app_manifest_rejects_non_default_entrypoint(self) -> None:
        release = {
            "tag_name": "v2.0.0",
            "assets": [
                {
                    "name": "manifest_Enhanced.json",
                    "browser_download_url": "https://example.invalid/manifest.json",
                },
                {
                    "name": "Bomana_app_Enhanced_v2.0.0.zip",
                    "browser_download_url": "https://example.invalid/app.zip",
                    "size": 10,
                },
            ],
        }
        manifest = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Enhanced",
                "app_version": "8.1.0",
                "min_launcher_version": "3.0.0",
                "entrypoint": "Other.pyw",
                "package_asset": "Bomana_app_Enhanced_v2.0.0.zip",
                "package_sha256": "a" * 64,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_json", return_value=manifest),
            self.assertRaisesRegex(RuntimeError, "入口文件不受支持"),
        ):
            self.launcher._manifest_from_github_release(release, "Enhanced")

    def test_github_launcher_manifest_uses_signed_asset_fields(self) -> None:
        release = {
            "tag_name": "v3.1.0-launcher",
            "assets": [
                {
                    "name": "launcher_manifest.json",
                    "browser_download_url": "https://example.invalid/launcher_manifest.json",
                },
                {
                    "name": "Bomana_launcher_v3.1.0.exe",
                    "browser_download_url": "https://example.invalid/launcher.exe",
                    "size": 456,
                },
            ],
        }
        manifest = self.signed_manifest(
            {
                "schema_version": 1,
                "launcher_version": "3.1.0",
                "launcher_asset": "Bomana_launcher_v3.1.0.exe",
                "launcher_sha256": "b" * 64,
                "launcher_size_bytes": 456,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_json", return_value=manifest),
        ):
            parsed = self.launcher._launcher_manifest_from_github_release(release)

        self.assertEqual(parsed["remote_version"], "3.1.0")
        self.assertEqual(parsed["package_sha256"], "b" * 64)
        self.assertEqual(parsed["package_url"], "https://example.invalid/launcher.exe")

    def test_primary_launcher_manifest_uses_signed_launcher_sha256(self) -> None:
        payload = self.signed_manifest(
            {
                "schema_version": 1,
                "launcher_version": "3.1.0",
                "launcher_asset": "Bomana_launcher_v3.1.0.exe",
                "launcher_sha256": "b" * 64,
                "launcher_size_bytes": 456,
            }
        )
        payload.update(
            {
                "package_url": "/downloads/launcher.exe",
                "package_sha256": "c" * 64,
                "package_size": 123,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_primary_json_payload", return_value=payload),
        ):
            parsed = self.launcher._fetch_launcher_manifest_from_primary(
                {"install_id": "abc"},
            )

        self.assertEqual(parsed["remote_version"], "3.1.0")
        self.assertEqual(parsed["package_sha256"], "b" * 64)
        self.assertEqual(
            parsed["package_url"], "https://bomanaupdate.ruikang.wang/downloads/launcher.exe"
        )

    def test_launcher_manifest_rejects_app_signature_with_launcher_fields(self) -> None:
        release = {
            "tag_name": "v9.9.9-launcher",
            "assets": [
                {
                    "name": "launcher_manifest.json",
                    "browser_download_url": "https://example.invalid/launcher_manifest.json",
                },
                {
                    "name": "Bomana_launcher_v9.9.9.exe",
                    "browser_download_url": "https://example.invalid/launcher.exe",
                    "size": 456,
                },
            ],
        }
        mixed = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Enhanced",
                "app_version": "8.1.0",
                "min_launcher_version": "3.0.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "package_asset": "Bomana_app_Enhanced_v2.0.0.zip",
                "package_sha256": "a" * 64,
            }
        )
        mixed.update(
            {
                "launcher_version": "9.9.9",
                "launcher_asset": "Bomana_launcher_v9.9.9.exe",
                "launcher_sha256": "b" * 64,
                "launcher_size_bytes": 456,
            }
        )

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_json", return_value=mixed),
            self.assertRaisesRegex(RuntimeError, "不能同时包含"),
        ):
            self.launcher._launcher_manifest_from_github_release(release)

        mixed["package_url"] = "/downloads/launcher.exe"
        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_primary_json_payload", return_value=mixed),
            self.assertRaisesRegex(RuntimeError, "不能同时包含"),
        ):
            self.launcher._fetch_launcher_manifest_from_primary({"install_id": "abc"})

    def test_primary_app_manifest_requires_release_signature(self) -> None:
        payload = {
            "app_version": "8.1.0",
            "package_url": "/downloads/app.zip",
            "package_sha256": "a" * 64,
        }

        with (
            patch.object(self.launcher, "_fetch_primary_version_payload", return_value=payload),
            self.assertRaisesRegex(RuntimeError, "缺少发布签名"),
        ):
            self.launcher._fetch_manifest_from_primary(
                "Enhanced",
                "1.0.0",
                {"install_id": "abc"},
            )

    def test_primary_app_manifest_accepts_signed_payload(self) -> None:
        payload = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Enhanced",
                "app_version": "8.1.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "min_launcher_version": "3.0.0",
                "package_asset": "Bomana_app_Enhanced_v2.0.0.zip",
                "package_sha256": "a" * 64,
            }
        )
        payload["package_url"] = "/downloads/app.zip"
        payload["package_size_bytes"] = 123

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_primary_version_payload", return_value=payload),
        ):
            parsed = self.launcher._fetch_manifest_from_primary(
                "Enhanced",
                "1.0.0",
                {"install_id": "abc"},
            )

        self.assertEqual(parsed["remote_version"], "8.1.0")
        self.assertEqual(
            parsed["package_url"], "https://bomanaupdate.ruikang.wang/downloads/app.zip"
        )
        self.assertEqual(parsed["package_sha256"], "a" * 64)
        self.assertEqual(
            parsed["changelog_url"],
            "https://bomanaupdate.ruikang.wang/downloads/CHANGELOG_Enhanced_v8.1.0.md",
        )

    def test_fetch_whats_new_verifies_signed_hash(self) -> None:
        content = b"## [8.1.0]\n\n- verified notes\n"
        service = self.launcher.UpdateService(self.base, "Standard", {})
        manifest = {
            "changelog_url": "https://example.invalid/CHANGELOG_Enhanced_v8.1.0.md",
            "changelog_sha256": hashlib.sha256(content).hexdigest(),
        }

        with patch.object(self.launcher, "_fetch_bytes", return_value=content) as fetch:
            result = service.fetch_whats_new(manifest)

        self.assertEqual(result, content.decode("utf-8"))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], manifest["changelog_url"])
        # Post-install notes fetch must ignore cancel_cb so the UI can leave
        # the downloading state even if a cancel was requested mid-flight.
        self.assertNotIn("cancel_cb", fetch.call_args.kwargs)
        self.assertEqual(
            fetch.call_args.kwargs.get("headers", {}).get("Accept"),
            "text/plain, text/markdown, */*",
        )

        with (
            patch.object(self.launcher, "_fetch_bytes", return_value=b"tampered"),
            self.assertRaisesRegex(RuntimeError, "SHA256"),
        ):
            service.fetch_whats_new(manifest)

    def test_primary_app_manifest_rejects_signed_wrong_channel_payload(self) -> None:
        payload = self.signed_manifest(
            {
                "schema_version": 1,
                "channel": "Lite",
                "app_version": "8.1.0",
                "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
                "min_launcher_version": "3.0.0",
                "package_asset": "Bomana_app_Lite_v2.0.0.zip",
                "package_sha256": "a" * 64,
            }
        )
        payload["package_url"] = "/downloads/app.zip"

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_fetch_primary_version_payload", return_value=payload),
            self.assertRaisesRegex(RuntimeError, "通道不匹配"),
        ):
            self.launcher._fetch_manifest_from_primary(
                "Enhanced",
                "1.0.0",
                {"install_id": "abc"},
            )

    def test_check_reports_launcher_requirement_and_fetches_missing_size(self) -> None:
        service = self.launcher.UpdateService(self.base, "Enhanced", {"install_id": "abc"})
        app_manifest = {
            "remote_version": "8.1.0",
            "min_launcher_version": "999.0.0",
            "package_url": "https://example.invalid/app.zip",
            "package_sha256": "abc",
            "package_size": "123",
            "source_name": "GitHub",
        }
        launcher_manifest = {
            "remote_version": "3.5.0",
            "package_url": "https://example.invalid/launcher.exe",
            "package_sha256": "def",
            "package_size": "",
            "source_name": "GitHub",
        }

        with (
            patch.object(service, "resolve_app_manifest", return_value=("8.0.0", app_manifest)),
            patch.object(
                service,
                "resolve_terrain_manifest",
                side_effect=RuntimeError("terrain offline"),
            ),
            patch.object(service, "resolve_launcher_manifest", return_value=launcher_manifest),
            patch.object(self.launcher, "_fetch_content_length", return_value=456) as fetch_size,
        ):
            info = service.check()

        self.assertTrue(info["update_available"])
        self.assertTrue(info["app_requires_launcher_update"])
        self.assertTrue(info["launcher_update_available"])
        self.assertEqual(info["package_size"], 123)
        self.assertEqual(info["launcher_package_size"], 456)
        fetch_size.assert_called_once_with(
            "https://example.invalid/launcher.exe",
            timeout_sec=self.launcher.NET_TIMEOUT_SEC,
        )

    def test_old_launcher_blocks_new_app_before_package_download(self) -> None:
        manifest = {
            "remote_version": "8.5.0",
            "min_launcher_version": "3.4.0",
            "package_url": "https://example.invalid/app.zip",
            "package_asset": "Bomana_app_Enhanced_v8.5.0.zip",
            "package_sha256": "a" * 64,
            "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
        }

        with (
            patch.object(self.launcher, "LAUNCHER_VERSION", "3.3.2"),
            patch.object(self.launcher, "_download_to_file") as download,
            self.assertRaisesRegex(RuntimeError, "要求 >= v3.4.0"),
        ):
            self.launcher._download_update_from_manifest(self.base, manifest)

        download.assert_not_called()

    def test_check_continues_when_launcher_manifest_check_fails(self) -> None:
        service = self.launcher.UpdateService(self.base, "Enhanced", {"install_id": "abc"})
        app_manifest = {
            "remote_version": "8.1.0",
            "min_launcher_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "https://example.invalid/app.zip",
            "package_sha256": "abc",
            "package_size": "123",
            "source_name": "GitHub",
        }

        with (
            patch.object(service, "resolve_app_manifest", return_value=("8.0.0", app_manifest)),
            patch.object(
                service,
                "resolve_terrain_manifest",
                side_effect=RuntimeError("terrain offline"),
            ),
            patch.object(
                service,
                "resolve_launcher_manifest",
                side_effect=RuntimeError("launcher offline"),
            ),
        ):
            info = service.check()

        self.assertTrue(info["update_available"])
        self.assertFalse(info["app_requires_launcher_update"])
        self.assertFalse(info["launcher_update_available"])
        self.assertEqual(info["launcher_check_warning"], "launcher offline")

    def test_enhanced_check_reports_independent_terrain_delta(self) -> None:
        service = self.launcher.UpdateService(self.base, "Enhanced", {"install_id": "abc"})
        app_manifest = {
            "remote_version": "8.0.0",
            "min_launcher_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "",
            "package_sha256": "abc",
            "package_size": "123",
            "source_name": "GitHub",
        }
        launcher_manifest = {
            "remote_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "",
            "package_sha256": "def",
            "package_size": "456",
            "source_name": "GitHub",
        }
        contents = {
            "index.json": b"index",
            "manifest.json": b"manifest",
            "map.bth": b"terrain-grid",
        }
        terrain_manifest = self.signed_terrain_manifest(contents)

        with (
            self.trusted_release_key_patch(),
            patch.object(service, "resolve_app_manifest", return_value=("8.0.0", app_manifest)),
            patch.object(
                service,
                "resolve_terrain_manifest",
                return_value=terrain_manifest,
            ),
            patch.object(
                service,
                "resolve_launcher_manifest",
                return_value=launcher_manifest,
            ),
        ):
            info = service.check()

        self.assertFalse(info["update_available"])
        self.assertTrue(info["terrain_update_available"])
        self.assertEqual(info["terrain_download_size"], sum(map(len, contents.values())))
        self.assertEqual(info["terrain_reuse_size"], 0)
        self.assertFalse(info["terrain_check_blocking"])

    def test_standard_check_does_not_resolve_terrain_manifest(self) -> None:
        service = self.launcher.UpdateService(self.base, "Standard", {"install_id": "abc"})
        app_manifest = {
            "remote_version": "8.0.0",
            "min_launcher_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "",
            "package_sha256": "abc",
            "package_size": "123",
            "source_name": "GitHub",
        }
        launcher_manifest = {
            "remote_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "",
            "package_sha256": "def",
            "package_size": "456",
            "source_name": "GitHub",
        }

        with (
            patch.object(service, "resolve_app_manifest", return_value=("8.0.0", app_manifest)),
            patch.object(service, "resolve_terrain_manifest") as resolve_terrain,
            patch.object(
                service,
                "resolve_launcher_manifest",
                return_value=launcher_manifest,
            ),
        ):
            info = service.check()

        resolve_terrain.assert_not_called()
        self.assertFalse(info["terrain_update_available"])
        self.assertEqual(info["terrain_download_size"], 0)

    def test_terrain_download_falls_back_per_object_and_then_stays_zero_download(
        self,
    ) -> None:
        contents = {
            "index.json": b"index",
            "manifest.json": b"manifest",
            "map.bth": b"terrain-grid",
        }
        terrain_manifest = self.signed_terrain_manifest(contents)
        by_asset = {item["asset"]: contents[item["path"]] for item in terrain_manifest["files"]}
        urls: list[str] = []

        def fake_download(url, destination, progress_cb=None, **_kwargs):
            urls.append(url)
            asset = url.rsplit("/", 1)[-1]
            data = b"bad" if "primary.invalid" in url else by_asset[asset]
            destination.write_bytes(data)
            if progress_cb:
                progress_cb(len(data), len(data))
            return destination

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_download_to_file", side_effect=fake_download),
        ):
            result = self.launcher._download_terrain_update_from_manifest(
                self.base,
                terrain_manifest,
            )

        self.assertEqual(result.downloaded_objects, 3)
        self.assertEqual(len(urls), 6)
        self.assertTrue(all("primary.invalid" in url for url in urls[0::2]))
        self.assertTrue(all("github.invalid" in url for url in urls[1::2]))

        with (
            self.trusted_release_key_patch(),
            patch.object(
                self.launcher,
                "_download_to_file",
                side_effect=AssertionError("unchanged terrain must not download"),
            ),
        ):
            current = self.launcher._download_terrain_update_from_manifest(
                self.base,
                terrain_manifest,
            )

        self.assertTrue(current.already_current)
        self.assertEqual(current.downloaded_bytes, 0)

    def test_subscriber_terrain_download_grants_each_content_addressed_object(self) -> None:
        contents = {
            "index.json": b"index",
            "manifest.json": b"manifest",
            "map.bth": b"terrain-grid",
        }
        terrain_manifest = self.signed_terrain_manifest(contents)
        terrain_manifest["object_base_urls"] = ()
        by_asset = {item["asset"]: contents[item["path"]] for item in terrain_manifest["files"]}
        requested: list[str] = []
        authorization_headers: list[str] = []

        def provider(resource: str) -> FakeArtifactAccess:
            requested.append(resource)
            return FakeArtifactAccess(resource)

        def fake_download(url, destination, progress_cb=None, headers=None, **_kwargs):
            asset = url.rsplit("/", 1)[-1]
            data = by_asset[asset]
            authorization_headers.append(headers["Authorization"])
            destination.write_bytes(data)
            if progress_cb:
                progress_cb(len(data), len(data))
            return destination

        with (
            self.trusted_release_key_patch(),
            patch.object(self.launcher, "_download_to_file", side_effect=fake_download),
        ):
            result = self.launcher._download_terrain_update_from_manifest(
                self.base,
                terrain_manifest,
                subscriber_artifact_provider=provider,
            )

        self.assertEqual(result.downloaded_objects, 3)
        self.assertEqual(
            set(requested),
            {f"terrain/objects/{asset}" for asset in by_asset},
        )
        self.assertEqual(authorization_headers, ["Bearer artifact-grant"] * 3)

    def test_check_propagates_resolver_failure_without_network_fallback_hiding_it(self) -> None:
        service = self.launcher.UpdateService(self.base, "Enhanced", {"install_id": "abc"})

        with (
            patch.object(service, "resolve_app_manifest", side_effect=RuntimeError("offline")),
            self.assertRaisesRegex(RuntimeError, "offline"),
        ):
            service.check()

    def test_primary_attempt_restores_proxy_mode_after_failures(self) -> None:
        self.launcher._set_use_system_proxy(True)

        def fail_fetch(_timeout_sec):
            raise RuntimeError("network down")

        with self.assertRaisesRegex(RuntimeError, "network down"):
            self.launcher._attempt_primary_request(
                self.base,
                "test request",
                "checking",
                fail_fetch,
            )

        self.assertTrue(self.launcher._USE_SYSTEM_PROXY)

    def test_primary_attempt_uses_thread_local_proxy_mode_without_global_toggle(self) -> None:
        self.launcher._set_use_system_proxy(True)
        attempts = []

        def fetch(_timeout_sec):
            attempts.append(
                (
                    self.launcher._current_use_system_proxy(),
                    self.launcher._USE_SYSTEM_PROXY,
                )
            )
            if len(attempts) < 3:
                raise RuntimeError("network down")
            return {"ok": True}

        result = self.launcher._attempt_primary_request(
            self.base,
            "test request",
            "checking",
            fetch,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            attempts,
            [
                (True, True),
                (True, True),
                (False, True),
            ],
        )
        self.assertTrue(self.launcher._USE_SYSTEM_PROXY)

    def test_state_log_and_result_use_writable_data_root_with_atomic_json(self) -> None:
        data_root = self.base / "data-root"
        with patch.dict(os.environ, {"BOMANA_LAUNCHER_DATA_DIR": str(data_root)}):
            self.launcher._write_state(self.base, {"channel": "Lite"})
            self.launcher._log(self.base, "hello")
            result_path = self.launcher._data_path(
                self.base,
                self.launcher.LAUNCHER_UPDATE_RESULT_FILE_NAME,
            )
            self.launcher._atomic_write_text(
                result_path,
                '{"status":"success","target_version":"9.0.0","message":"ok"}',
            )
            self.launcher._consume_launcher_update_result(self.base)

        self.assertFalse((self.base / self.launcher.STATE_FILE_NAME).exists())
        self.assertEqual(
            json.loads((data_root / self.launcher.STATE_FILE_NAME).read_text(encoding="utf-8")),
            {"channel": "Lite"},
        )
        self.assertIn("hello", (data_root / self.launcher.LOG_FILE_NAME).read_text("utf-8"))
        self.assertFalse(result_path.exists())
        self.assertFalse(list(data_root.glob("*.tmp")))

    def test_corrupt_state_file_is_preserved_and_logged(self) -> None:
        data_root = self.base / "data-root"
        with patch.dict(os.environ, {"BOMANA_LAUNCHER_DATA_DIR": str(data_root)}):
            state_path = data_root / self.launcher.STATE_FILE_NAME
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{bad json", encoding="utf-8")

            self.assertEqual(self.launcher._read_state(self.base), {})

        self.assertEqual(state_path.read_text(encoding="utf-8"), "{bad json")
        log_text = (data_root / self.launcher.LOG_FILE_NAME).read_text(encoding="utf-8")
        self.assertIn("读取", log_text)
        self.assertIn(self.launcher.STATE_FILE_NAME, log_text)

    def test_startup_channel_prefers_saved_channel_over_detected_default(self) -> None:
        data_root = self.base / "data-root"
        with patch.dict(os.environ, {"BOMANA_LAUNCHER_DATA_DIR": str(data_root)}):
            self.launcher._write_state(self.base, {"channel": "Lite"})
            channel = self.launcher._select_startup_channel(self.base, "Enhanced")

        self.assertEqual(channel, "Lite")

    def test_download_to_file_resumes_existing_partial_file(self) -> None:
        dest = self.base / "package.zip"
        part = dest.with_name(f"{dest.name}.part")
        part.write_bytes(b"abc")
        requests = []
        progress = []

        def fake_open(req, timeout, use_system_proxy=None):
            requests.append((req, timeout, use_system_proxy))
            return FakeResponse(
                b"def",
                headers={"Content-Range": "bytes 3-5/6", "Content-Length": "3"},
                status=206,
            )

        with patch.object(self.launcher, "_open_url", side_effect=fake_open):
            self.launcher._download_to_file(
                "https://example.invalid/package.zip",
                dest,
                progress_cb=lambda done, total: progress.append((done, total)),
            )

        self.assertEqual(dest.read_bytes(), b"abcdef")
        self.assertFalse(part.exists())
        self.assertEqual(requests[0][0].headers["Range"], "bytes=3-")
        self.assertEqual(progress[-1], (6, 6))

    def test_download_to_file_rejects_declared_size_above_limit_before_write(self) -> None:
        dest = self.base / "terrain-object.bin"
        response = FakeResponse(
            b"abcdef",
            headers={"Content-Length": "6"},
        )

        with (
            patch.object(self.launcher, "_open_url", return_value=response),
            self.assertRaisesRegex(RuntimeError, "超过允许大小"),
        ):
            self.launcher._download_to_file(
                "https://example.invalid/terrain-object.bin",
                dest,
                max_bytes=3,
            )

        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_name(f"{dest.name}.part").exists())

    def test_download_to_file_stops_undeclared_body_before_exceeding_limit(self) -> None:
        dest = self.base / "terrain-object.bin"

        with (
            patch.object(
                self.launcher,
                "_open_url",
                return_value=FakeResponse(b"abcdef"),
            ),
            self.assertRaisesRegex(RuntimeError, "超过允许大小"),
        ):
            self.launcher._download_to_file(
                "https://example.invalid/terrain-object.bin",
                dest,
                max_bytes=3,
            )

        part = dest.with_name(f"{dest.name}.part")
        self.assertFalse(dest.exists())
        self.assertTrue(part.exists())
        self.assertLessEqual(part.stat().st_size, 3)

    def test_download_dir_falls_back_when_user_downloads_is_not_writable(self) -> None:
        user_downloads = self.base / "readonly-downloads"
        data_root = self.base / "data-root"
        fallback_downloads = data_root / self.launcher.DOWNLOAD_DIR_NAME

        def can_write(path: Path) -> bool:
            return path == fallback_downloads

        with (
            patch.object(self.launcher, "_user_downloads_dir", return_value=user_downloads),
            patch.object(self.launcher, "_launcher_data_root", return_value=data_root),
            patch.object(self.launcher, "_can_write_dir", side_effect=can_write),
        ):
            download_dir = self.launcher._launcher_download_dir(self.base)

        self.assertEqual(download_dir, fallback_downloads)

    def test_app_install_preflight_runs_before_download(self) -> None:
        manifest = {
            "remote_version": "8.1.0",
            "min_launcher_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "https://example.invalid/app.zip",
            "package_asset": "Bomana_app_Enhanced_v8.1.0.zip",
            "package_sha256": "a" * 64,
            "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
        }

        with (
            patch.object(
                self.launcher,
                "_assert_app_install_dir_writable",
                side_effect=RuntimeError("当前启动器目录不可写"),
            ),
            patch.object(self.launcher, "_download_to_file") as download,
            self.assertRaisesRegex(RuntimeError, "当前启动器目录不可写"),
        ):
            self.launcher._download_update_from_manifest(self.base, manifest)

        download.assert_not_called()

    def test_download_app_update_preserves_verified_package_in_download_dir(self) -> None:
        package_bytes = make_app_zip("8.1.0")
        package_sha = self.launcher._sha256_bytes(package_bytes)
        download_dir = self.base / "visible-downloads"
        manifest = {
            "remote_version": "8.1.0",
            "min_launcher_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "https://example.invalid/app.zip",
            "package_asset": "Bomana_app_Enhanced_v8.1.0.zip",
            "package_sha256": package_sha,
            "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
            "source_name": "GitHub",
        }
        statuses = []

        def fake_open(_req, timeout, use_system_proxy=None):
            return FakeResponse(package_bytes, headers={"Content-Length": str(len(package_bytes))})

        with (
            patch.dict(os.environ, {self.launcher.DOWNLOAD_DIR_ENV_NAME: str(download_dir)}),
            patch.object(self.launcher, "_open_url", side_effect=fake_open),
        ):
            final_version, _source = self.launcher._download_update_from_manifest(
                self.base,
                manifest,
                status_cb=lambda *args: statuses.append(args),
            )

        self.assertEqual(final_version, "8.1.0")
        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.1.0",
        )
        cached = list(download_dir.glob("Bomana_app_*"))
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].read_bytes(), package_bytes)
        self.assertTrue(any(str(cached[0]) in event[1] for event in statuses))

    def test_download_app_hash_mismatch_preserves_existing_app_and_removes_bad_file(self) -> None:
        self.write_current_app("8.0.0")
        package_bytes = make_app_zip("8.1.0")
        download_dir = self.base / "visible-downloads"
        manifest = {
            "remote_version": "8.1.0",
            "min_launcher_version": self.launcher.LAUNCHER_VERSION,
            "package_url": "https://example.invalid/app.zip",
            "package_asset": "Bomana_app_Enhanced_v8.1.0.zip",
            "package_sha256": "0" * 64,
            "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
        }

        def fake_open(_req, timeout, use_system_proxy=None):
            return FakeResponse(package_bytes, headers={"Content-Length": str(len(package_bytes))})

        with (
            patch.dict(os.environ, {self.launcher.DOWNLOAD_DIR_ENV_NAME: str(download_dir)}),
            patch.object(self.launcher, "_open_url", side_effect=fake_open),
            self.assertRaisesRegex(RuntimeError, "SHA256 校验失败"),
        ):
            self.launcher._download_update_from_manifest(self.base, manifest)

        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.0.0",
        )
        self.assertFalse(list(download_dir.glob("Bomana_app_*")))

    def test_launcher_target_dir_precheck_uses_probe_rename(self) -> None:
        target = self.base / "BomanaLauncher.exe"

        self.launcher._assert_launcher_target_dir_writable(target)

        self.assertFalse(list(self.base.glob(".bomana_launcher_write_probe*")))

    def test_launcher_updater_uses_system_powershell_path_and_safe_cwd(self) -> None:
        script_path = self.base / "staging" / "bomana_update_launcher_apply.ps1"
        script_path.parent.mkdir()
        script_path.write_text("# updater\n", encoding="utf-8")
        system_powershell = (
            self.base / "Windows" / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        system_powershell.parent.mkdir(parents=True)
        system_powershell.write_bytes(b"powershell")
        popen_calls = []

        def fake_popen(args, **kwargs):
            popen_calls.append((args, kwargs))
            return object()

        with (
            patch.object(
                self.launcher,
                "_system_windows_powershell_exe",
                return_value=system_powershell,
            ),
            patch.object(self.launcher.subprocess, "Popen", side_effect=fake_popen),
        ):
            self.launcher._launch_updater_script(script_path)

        self.assertEqual(len(popen_calls), 1)
        args, kwargs = popen_calls[0]
        self.assertEqual(args[0], str(system_powershell))
        self.assertNotEqual(args[0], "powershell.exe")
        self.assertEqual(kwargs["cwd"], str(system_powershell.parent))
        self.assertNotEqual(kwargs["cwd"], str(script_path.parent))
        self.assertIn("-File", args)
        self.assertIn(str(script_path), args)

    def test_launcher_self_update_uses_data_root_result_and_rollback_script(self) -> None:
        data_root = self.base / "data-root"
        target = self.base / "BomanaLauncher.exe"
        target.write_bytes(b"old")
        launched = []

        with (
            patch.dict(os.environ, {"BOMANA_LAUNCHER_DATA_DIR": str(data_root)}),
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(target)),
            patch.object(
                self.launcher,
                "_launch_updater_script",
                side_effect=lambda script_path: launched.append(Path(script_path)),
            ),
        ):
            self.launcher._stage_launcher_self_update(self.base, b"new", "3.0.0")

        self.assertEqual(len(launched), 1)
        script = launched[0].read_text(encoding="utf-8")
        result_path = data_root / self.launcher.LAUNCHER_UPDATE_RESULT_FILE_NAME
        self.assertIn(json.dumps(str(result_path)), script)
        self.assertIn("$replacement", script)
        self.assertIn("$expectedSha256", script)
        self.assertIn("Assert-FileSha256 $staged $expectedSha256", script)
        self.assertIn("Assert-FileSha256 $replacement $expectedSha256", script)
        self.assertIn("Copy-Item -LiteralPath $staged -Destination $replacement -Force", script)
        self.assertIn("Move-Item -LiteralPath $backup -Destination $target", script)
        self.assertIn("新版启动器文件保留在", script)
        self.assertIn("Start-Process -FilePath $target -WorkingDirectory", script)
        self.assertIn("-PassThru", script)
        self.assertIn("$restartSucceeded", script)
        self.assertIn("if ($replaceSucceeded -and $restartSucceeded)", script)

    def test_launcher_self_update_script_preserves_unicode_paths(self) -> None:
        unicode_root = self.base / "中文路径"
        data_root = unicode_root / "数据"
        work_dir = unicode_root / "临时更新"
        target = unicode_root / "Bomana启动器.exe"
        work_dir.mkdir(parents=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"old")
        launched = []

        with (
            patch.dict(os.environ, {"BOMANA_LAUNCHER_DATA_DIR": str(data_root)}),
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(target)),
            patch.object(self.launcher.tempfile, "mkdtemp", return_value=str(work_dir)),
            patch.object(
                self.launcher,
                "_launch_updater_script",
                side_effect=lambda script_path: launched.append(Path(script_path)),
            ),
        ):
            self.launcher._stage_launcher_self_update(self.base, b"new", "3.0.0")

        script = launched[0].read_text(encoding="utf-8-sig")
        self.assertIn("中文路径", script)
        self.assertIn("Bomana启动器.exe", script)
        self.assertNotIn("\\u", script)

    def test_online_install_rejects_signed_staged_version_mismatch_before_swap(self) -> None:
        self.write_current_app("8.0.0")
        package_bytes = make_app_zip("8.2.0")
        package_sha = self.launcher._sha256_bytes(package_bytes)
        manifest = {
            "remote_version": "8.1.0",
            "min_launcher_version": "3.0.0",
            "package_url": "https://example.invalid/app.zip",
            "package_asset": "Bomana_app_Enhanced_v8.1.0.zip",
            "package_sha256": package_sha,
            "entrypoint": self.launcher.DEFAULT_ENTRYPOINT,
        }

        def fake_open(_req, timeout, use_system_proxy=None):
            return FakeResponse(package_bytes, headers={"Content-Length": str(len(package_bytes))})

        with (
            patch.object(self.launcher, "_open_url", side_effect=fake_open),
            self.assertRaisesRegex(RuntimeError, "签名清单版本与暂存包版本不匹配"),
        ):
            self.launcher._download_update_from_manifest(self.base, manifest)

        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.0.0",
        )
        self.assertFalse((self.base / self.launcher.APP_PREVIOUS_DIR_NAME).exists())

    def test_local_import_rejects_below_floor_before_preserving_current_app(self) -> None:
        self.write_current_app("8.0.0")
        package_bytes = make_app_zip("7.99.99")

        with self.assertRaisesRegex(RuntimeError, "暂存应用版本过旧"):
            launcher_install.install_zip_package(
                self.base,
                package_bytes,
                expected_sha256="",
                entrypoint=self.launcher.DEFAULT_ENTRYPOINT,
            )

        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.0.0",
        )
        self.assertFalse((self.base / self.launcher.APP_PREVIOUS_DIR_NAME).exists())

    def test_rollback_rejects_incompatible_previous_slot_before_swap(self) -> None:
        self.write_current_app("8.1.0")
        self.write_previous_app("7.99.99")

        with self.assertRaisesRegex(RuntimeError, "回退应用版本过旧"):
            launcher_install.rollback_to_previous_app(self.base)

        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.1.0",
        )
        self.assertEqual(
            launcher_install.read_local_app_version(
                self.base / self.launcher.APP_PREVIOUS_DIR_NAME
            ),
            "7.99.99",
        )

    def test_recovery_rejects_incompatible_new_candidate_without_promotion(self) -> None:
        new_dir = self.base / "app_new"
        (new_dir / "bomana").mkdir(parents=True)
        (new_dir / "Bomana.pyw").write_text("# app entry\n", encoding="utf-8")
        write_config_package(new_dir / "bomana", "not-a-version")
        logs = []

        steps = launcher_install.InstallTransaction.recover_incomplete(
            self.base,
            log_cb=lambda _base, message: logs.append(message),
        )

        self.assertEqual(steps, [])
        self.assertTrue(new_dir.exists())
        self.assertFalse((self.base / self.launcher.APP_DIR_NAME).exists())
        self.assertIn("格式无效", logs[-1])

    def test_recovery_prevalidates_all_slots_before_restoring_valid_backup(self) -> None:
        backup_dir = self.base / self.launcher.APP_BACKUP_DIR_NAME
        (backup_dir / "bomana").mkdir(parents=True)
        (backup_dir / "Bomana.pyw").write_text("# backup\n", encoding="utf-8")
        write_config_package(backup_dir / "bomana", "8.1.0")
        backup_marker = backup_dir / "backup-marker.txt"
        backup_marker.write_text("preserve backup", encoding="utf-8")

        new_dir = self.base / "app_new"
        (new_dir / "bomana").mkdir(parents=True)
        (new_dir / "Bomana.pyw").write_text("# staged\n", encoding="utf-8")
        write_config_package(new_dir / "bomana", "not-a-version")
        new_marker = new_dir / "new-marker.txt"
        new_marker.write_text("preserve staged", encoding="utf-8")
        logs = []

        steps = launcher_install.InstallTransaction.recover_incomplete(
            self.base,
            log_cb=lambda _base, message: logs.append(message),
        )

        self.assertEqual(steps, [])
        self.assertFalse((self.base / self.launcher.APP_DIR_NAME).exists())
        self.assertEqual(launcher_install.read_local_app_version(backup_dir), "8.1.0")
        self.assertEqual(backup_marker.read_text(encoding="utf-8"), "preserve backup")
        self.assertEqual(new_marker.read_text(encoding="utf-8"), "preserve staged")
        self.assertIn("格式无效", logs[-1])

    def test_recovery_prevalidates_dangling_slot_before_replacing_previous(self) -> None:
        self.write_current_app("8.2.0")
        self.write_previous_app("8.0.0")
        backup_dir = self.base / self.launcher.APP_BACKUP_DIR_NAME
        (backup_dir / "bomana").mkdir(parents=True)
        write_config_package(backup_dir / "bomana", "8.1.0")
        dangling_new = self.base / "app_new"
        real_lexists = launcher_install.os.path.lexists

        with patch.object(
            launcher_install.os.path,
            "lexists",
            side_effect=lambda path: Path(path) == dangling_new or real_lexists(path),
        ):
            steps = launcher_install.InstallTransaction.recover_incomplete(self.base)

        self.assertEqual(steps, [])
        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.2.0",
        )
        self.assertEqual(launcher_install.read_local_app_version(backup_dir), "8.1.0")
        self.assertEqual(
            launcher_install.read_local_app_version(
                self.base / self.launcher.APP_PREVIOUS_DIR_NAME
            ),
            "8.0.0",
        )

    def test_recovery_preserves_slots_when_current_identity_is_below_floor(self) -> None:
        self.write_current_app("7.99.99")
        self.write_previous_app("8.2.0")
        backup_dir = self.base / self.launcher.APP_BACKUP_DIR_NAME
        (backup_dir / "bomana").mkdir(parents=True)
        (backup_dir / "Bomana.pyw").write_text("# backup\n", encoding="utf-8")
        write_config_package(backup_dir / "bomana", "8.1.0")

        steps = launcher_install.InstallTransaction.recover_incomplete(self.base)

        self.assertEqual(steps, [])
        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "7.99.99",
        )
        self.assertEqual(launcher_install.read_local_app_version(backup_dir), "8.1.0")
        self.assertEqual(
            launcher_install.read_local_app_version(
                self.base / self.launcher.APP_PREVIOUS_DIR_NAME
            ),
            "8.2.0",
        )

    def test_candidate_metadata_is_parsed_as_data_without_execution(self) -> None:
        app_dir = self.base / "candidate"
        metadata_dir = app_dir / "bomana"
        metadata_dir.mkdir(parents=True)
        sentinel = self.base / "executed.txt"
        (metadata_dir / "metadata.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            '__version__ = "8.0.0"\n'
            'PORTABLE_MIN_LAUNCHER_VERSION = "3.3.0"\n',
            encoding="utf-8",
        )

        self.assertEqual(launcher_install.read_app_version_identity(app_dir), "8.0.0")
        self.assertEqual(
            launcher_install.read_app_min_launcher_version_identity(app_dir),
            "3.3.0",
        )
        self.assertFalse(sentinel.exists())

    def test_local_zip_rejects_app_requiring_newer_launcher(self) -> None:
        self.write_current_app("8.0.0")
        package_bytes = make_app_zip("8.5.0", min_launcher_version="3.5.0")

        with self.assertRaisesRegex(RuntimeError, "当前启动器版本过旧"):
            launcher_install.install_zip_package(
                self.base,
                package_bytes,
                self.launcher._sha256_bytes(package_bytes),
                self.launcher.DEFAULT_ENTRYPOINT,
            )

        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.0.0",
        )

    def test_channel_slots_keep_app_versions_and_rollbacks_independent(self) -> None:
        standard_zip = make_app_zip("8.1.0", channel="Standard")
        standard_new_zip = make_app_zip("8.2.0", channel="Standard")
        lite_zip = make_app_zip("8.7.0", channel="Lite")

        launcher_install.install_zip_package(
            self.base,
            standard_zip,
            self.launcher._sha256_bytes(standard_zip),
            self.launcher.DEFAULT_ENTRYPOINT,
            channel="Standard",
        )
        launcher_install.install_zip_package(
            self.base,
            lite_zip,
            self.launcher._sha256_bytes(lite_zip),
            self.launcher.DEFAULT_ENTRYPOINT,
            channel="Lite",
        )
        launcher_install.install_zip_package(
            self.base,
            standard_new_zip,
            self.launcher._sha256_bytes(standard_new_zip),
            self.launcher.DEFAULT_ENTRYPOINT,
            channel="Standard",
        )

        self.assertEqual(
            launcher_install.read_local_app_version(
                launcher_install.app_slot_dir(self.base, "Standard")
            ),
            "8.2.0",
        )
        self.assertEqual(
            launcher_install.read_local_app_version(
                launcher_install.previous_app_slot_dir(self.base, "Standard")
            ),
            "8.1.0",
        )
        self.assertEqual(
            launcher_install.read_local_app_version(
                launcher_install.app_slot_dir(self.base, "Lite")
            ),
            "8.7.0",
        )
        self.assertFalse(launcher_install.app_slot_dir(self.base, "Enhanced").exists())

        final_version, preserved = launcher_install.rollback_to_previous_app(
            self.base,
            channel="Standard",
        )
        self.assertEqual((final_version, preserved), ("8.1.0", "8.2.0"))
        self.assertEqual(
            launcher_install.read_local_app_version(
                launcher_install.app_slot_dir(self.base, "Lite")
            ),
            "8.7.0",
        )

    def test_channel_slot_rejects_package_from_another_edition(self) -> None:
        package_bytes = make_app_zip("8.7.0", channel="Lite")

        with self.assertRaisesRegex(RuntimeError, "应用包通道不匹配"):
            launcher_install.install_zip_package(
                self.base,
                package_bytes,
                self.launcher._sha256_bytes(package_bytes),
                self.launcher.DEFAULT_ENTRYPOINT,
                channel="Standard",
            )

        self.assertFalse(launcher_install.app_slot_dir(self.base, "Standard").exists())

    def test_legacy_channel_marker_is_migrated_to_its_slot(self) -> None:
        legacy = self.base / launcher_install.APP_DIR_NAME
        write_config_package(legacy / "bomana", "8.7.0", channel="Lite")
        (legacy / "Bomana.pyw").write_text("# legacy\n", encoding="utf-8")

        steps = launcher_install.migrate_legacy_slots(self.base)

        self.assertEqual(steps, ["migrate_current_Lite"])
        self.assertFalse(legacy.exists())
        self.assertEqual(
            launcher_install.read_local_app_version(
                launcher_install.app_slot_dir(self.base, "Lite")
            ),
            "8.7.0",
        )

    def test_fresh_lock_blocks_install_and_preserves_existing_app(self) -> None:
        self.write_current_app("8.0.0")
        package_bytes = make_app_zip("8.1.0")
        package_sha = self.launcher._sha256_bytes(package_bytes)
        lock_path = self.base / self.launcher.UPDATE_LOCK_FILE_NAME
        lock_path.write_text("pid=1\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "另一个更新任务"):
            launcher_install.install_zip_package(
                self.base,
                package_bytes,
                package_sha,
                self.launcher.DEFAULT_ENTRYPOINT,
            )

        self.assertEqual(
            (
                self.base / self.launcher.APP_DIR_NAME / "bomana" / "config" / "__init__.py"
            ).read_text(encoding="utf-8"),
            '__version__ = "8.0.0"\n',
        )

    def test_install_zip_rejects_package_missing_metadata(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("Bomana.pyw", "# app entry\n")
            zf.writestr("bomana/config/__init__.py", '__version__ = "8.1.0"\n')
        package_bytes = buffer.getvalue()
        package_sha = self.launcher._sha256_bytes(package_bytes)

        with self.assertRaisesRegex(RuntimeError, "metadata.py"):
            launcher_install.install_zip_package(
                self.base,
                package_bytes,
                package_sha,
                self.launcher.DEFAULT_ENTRYPOINT,
            )

        self.assertFalse(self.launcher._is_local_app_ready(self.base))

    def test_recover_incomplete_install_restores_backup_and_removes_stale_lock(self) -> None:
        backup_dir = self.base / self.launcher.APP_BACKUP_DIR_NAME
        (backup_dir / "bomana").mkdir(parents=True)
        (backup_dir / "Bomana.pyw").write_text("# app entry\n", encoding="utf-8")
        write_config_package(backup_dir / "bomana", "8.0.0")
        lock_path = self.base / self.launcher.UPDATE_LOCK_FILE_NAME
        lock_path.write_text("pid=1\n", encoding="utf-8")
        stale_time = time.time() - self.launcher.UPDATE_LOCK_STALE_SEC - 10
        os.utime(lock_path, (stale_time, stale_time))

        steps = launcher_install.InstallTransaction.recover_incomplete(self.base)

        self.assertIn("restore_backup", steps)
        self.assertIn("cleanup_stale_lock", steps)
        self.assertFalse(lock_path.exists())
        self.assertTrue((self.base / self.launcher.APP_DIR_NAME / "Bomana.pyw").exists())

    def test_rollback_to_previous_app_swaps_current_and_previous_versions(self) -> None:
        self.write_current_app("8.1.0")
        self.write_previous_app("8.0.0")
        status_events = []

        final_version, preserved_version = launcher_install.rollback_to_previous_app(
            self.base,
            status_cb=lambda *args: status_events.append(args),
        )

        self.assertEqual(final_version, "8.0.0")
        self.assertEqual(preserved_version, "8.1.0")
        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.0.0",
        )
        self.assertEqual(
            launcher_install.read_local_app_version(
                self.base / self.launcher.APP_PREVIOUS_DIR_NAME
            ),
            "8.1.0",
        )
        self.assertTrue(status_events)
        self.assertFalse((self.base / self.launcher.UPDATE_LOCK_FILE_NAME).exists())

    def test_rollback_failure_after_previous_move_restores_current_version(self) -> None:
        self.write_current_app("8.1.0")
        self.write_previous_app("8.0.0")
        real_replace = os.replace
        replace_calls = []

        def fail_third_replace(src, dst) -> None:
            replace_calls.append((Path(src).name, Path(dst).name))
            if len(replace_calls) == 3:
                raise OSError("third move failed")
            real_replace(src, dst)

        with (
            patch.object(launcher_install.os, "replace", side_effect=fail_third_replace),
            self.assertRaisesRegex(OSError, "third move failed"),
        ):
            launcher_install.rollback_to_previous_app(self.base)

        self.assertEqual(
            launcher_install.read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "8.1.0",
        )
        self.assertEqual(
            launcher_install.read_local_app_version(
                self.base / self.launcher.APP_PREVIOUS_DIR_NAME
            ),
            "8.0.0",
        )
        self.assertFalse((self.base / self.launcher.UPDATE_LOCK_FILE_NAME).exists())

    def test_launch_app_prefers_installed_bomana_over_frozen_importer(self) -> None:
        app_dir = self.base / self.launcher.APP_DIR_NAME
        package_dir = app_dir / "bomana"
        package_dir.mkdir(parents=True)
        (package_dir / "data" / "terrain-v1").mkdir(parents=True)
        (app_dir / "Bomana.pyw").write_text(
            "from pathlib import Path\n"
            "from bomana.config.settings import SENTINEL\n"
            "Path('result.txt').write_text(SENTINEL, encoding='utf-8')\n",
            encoding="utf-8",
        )
        write_config_package(package_dir, "8.0.0", sentinel="app")

        class FrozenBomanaLoader:
            def create_module(self, _spec):
                return None

            def exec_module(self, module) -> None:
                if module.__name__ == "bomana" or module.__name__ == "bomana.config":
                    module.__path__ = []
                elif module.__name__ == "bomana.config.settings":
                    module.SENTINEL = "frozen"

        class FrozenBomanaFinder:
            def find_spec(self, fullname, _path=None, _target=None):
                if fullname == "bomana":
                    return importlib.machinery.ModuleSpec(
                        fullname,
                        FrozenBomanaLoader(),
                        is_package=True,
                    )
                if fullname == "bomana.config":
                    return importlib.machinery.ModuleSpec(fullname, FrozenBomanaLoader())
                if fullname == "bomana.config.settings":
                    return importlib.machinery.ModuleSpec(fullname, FrozenBomanaLoader())
                return None

        finder = FrozenBomanaFinder()
        old_cwd = Path.cwd()
        old_path = list(sys.path)
        old_channel = os.environ.get("BOMANA_CHANNEL")
        old_runtime_root = os.environ.get("BOMANA_RUNTIME_ROOT")
        old_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == "bomana_version" or name == "bomana" or name.startswith("bomana.")
        }
        sys.meta_path.insert(0, finder)
        try:
            self.launcher._launch_app(self.base, "Enhanced")
            self.assertEqual((app_dir / "result.txt").read_text(encoding="utf-8"), "app")
        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path
            if finder in sys.meta_path:
                sys.meta_path.remove(finder)
            for name in tuple(sys.modules):
                if name == "bomana_version" or name == "bomana" or name.startswith("bomana."):
                    sys.modules.pop(name, None)
            sys.modules.update(old_modules)
            if old_channel is None:
                os.environ.pop("BOMANA_CHANNEL", None)
            else:
                os.environ["BOMANA_CHANNEL"] = old_channel
            if old_runtime_root is None:
                os.environ.pop("BOMANA_RUNTIME_ROOT", None)
            else:
                os.environ["BOMANA_RUNTIME_ROOT"] = old_runtime_root


if __name__ == "__main__":
    unittest.main()
