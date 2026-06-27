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

from bomana import launcher_install


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

    def test_launcher_target_dir_precheck_uses_probe_rename(self) -> None:
        target = self.base / "BomanaLauncher.exe"

        self.launcher._assert_launcher_target_dir_writable(target)

        self.assertFalse(list(self.base.glob(".bomana_launcher_write_probe*")))

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
        self.assertIn("if ($replaceSucceeded)", script)

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

    def test_rollback_failure_after_previous_move_restores_current_version(self) -> None:
        self.write_current_app("2.0.0")
        self.write_previous_app("1.5.0")
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
            self.launcher._rollback_to_previous_app(self.base)

        self.assertEqual(
            self.launcher._read_local_app_version(self.base / self.launcher.APP_DIR_NAME),
            "2.0.0",
        )
        self.assertEqual(
            self.launcher._read_local_app_version(self.base / self.launcher.APP_PREVIOUS_DIR_NAME),
            "1.5.0",
        )
        self.assertFalse((self.base / self.launcher.UPDATE_LOCK_FILE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
