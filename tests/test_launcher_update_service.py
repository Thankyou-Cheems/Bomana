import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


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


def make_app_zip(version: str = "2.0.0") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Bomana.pyw", "# app entry\n")
        zf.writestr("bomana/config.py", f'__version__ = "{version}"\n')
    return buffer.getvalue()


class LauncherUpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = load_launcher_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_current_app(self, version: str = "1.0.0") -> None:
        app_dir = self.base / self.launcher.APP_DIR_NAME
        (app_dir / "bomana").mkdir(parents=True)
        (app_dir / "Bomana.pyw").write_text("# app entry\n", encoding="utf-8")
        (app_dir / "bomana" / "config.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )

    def write_previous_app(self, version: str = "0.9.0") -> None:
        previous_dir = self.base / self.launcher.APP_PREVIOUS_DIR_NAME
        (previous_dir / "bomana").mkdir(parents=True)
        (previous_dir / "Bomana.pyw").write_text("# previous app entry\n", encoding="utf-8")
        (previous_dir / "bomana" / "config.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )

    def test_check_reports_launcher_requirement_and_fetches_missing_size(self) -> None:
        service = self.launcher.UpdateService(self.base, "Enhanced", {"install_id": "abc"})
        app_manifest = {
            "remote_version": "2.0.0",
            "min_launcher_version": "999.0.0",
            "package_url": "https://example.invalid/app.zip",
            "package_sha256": "abc",
            "package_size": "123",
            "source_name": "GitHub",
        }
        launcher_manifest = {
            "remote_version": "2.1.0",
            "package_url": "https://example.invalid/launcher.exe",
            "package_sha256": "def",
            "package_size": "",
            "source_name": "GitHub",
        }

        with (
            patch.object(service, "resolve_app_manifest", return_value=("1.0.0", app_manifest)),
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

    def test_fresh_lock_blocks_install_and_preserves_existing_app(self) -> None:
        self.write_current_app("1.0.0")
        package_bytes = make_app_zip("2.0.0")
        package_sha = self.launcher._sha256_bytes(package_bytes)
        lock_path = self.base / self.launcher.UPDATE_LOCK_FILE_NAME
        lock_path.write_text("pid=1\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "另一个更新任务"):
            self.launcher._install_zip_package(
                self.base,
                package_bytes,
                package_sha,
                self.launcher.DEFAULT_ENTRYPOINT,
            )

        self.assertEqual(
            (self.base / self.launcher.APP_DIR_NAME / "bomana" / "config.py").read_text(
                encoding="utf-8"
            ),
            '__version__ = "1.0.0"\n',
        )

    def test_recover_incomplete_install_restores_backup_and_removes_stale_lock(self) -> None:
        backup_dir = self.base / self.launcher.APP_BACKUP_DIR_NAME
        (backup_dir / "bomana").mkdir(parents=True)
        (backup_dir / "Bomana.pyw").write_text("# app entry\n", encoding="utf-8")
        (backup_dir / "bomana" / "config.py").write_text(
            '__version__ = "1.0.0"\n',
            encoding="utf-8",
        )
        lock_path = self.base / self.launcher.UPDATE_LOCK_FILE_NAME
        lock_path.write_text("pid=1\n", encoding="utf-8")
        stale_time = time.time() - self.launcher.UPDATE_LOCK_STALE_SEC - 10
        os.utime(lock_path, (stale_time, stale_time))

        steps = self.launcher.InstallTransaction.recover_incomplete(self.base)

        self.assertIn("restore_backup", steps)
        self.assertIn("cleanup_stale_lock", steps)
        self.assertFalse(lock_path.exists())
        self.assertTrue((self.base / self.launcher.APP_DIR_NAME / "Bomana.pyw").exists())

    def test_rollback_to_previous_app_swaps_current_and_previous_versions(self) -> None:
        self.write_current_app("2.0.0")
        self.write_previous_app("1.5.0")
        status_events = []

        final_version, preserved_version = self.launcher._rollback_to_previous_app(
            self.base,
            status_cb=lambda *args: status_events.append(args),
        )

        self.assertEqual(final_version, "1.5.0")
        self.assertEqual(preserved_version, "2.0.0")
        self.assertEqual(
            self.launcher._read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "1.5.0",
        )
        self.assertEqual(
            self.launcher._read_local_app_version(self.base / self.launcher.APP_PREVIOUS_DIR_NAME),
            "2.0.0",
        )
        self.assertTrue(status_events)
        self.assertFalse((self.base / self.launcher.UPDATE_LOCK_FILE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
