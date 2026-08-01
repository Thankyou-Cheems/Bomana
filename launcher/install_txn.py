"""Install and rollback primitives for the portable launcher."""

from __future__ import annotations

import ast
import hashlib
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from bomana_version import (
    MIN_SUPPORTED_APP_VERSION,
    MIN_SUPPORTED_LAUNCHER_VERSION,
    require_exact_version,
    require_minimum_version,
)
from launcher.core import normalize_package_root, safe_extract_zip, sha256_bytes
from launcher.metadata import LAUNCHER_VERSION

APP_DIR_NAME = "app"
APP_PREVIOUS_DIR_NAME = "app_previous"
APP_BACKUP_DIR_NAME = f"{APP_DIR_NAME}_backup"
UPDATE_LOCK_FILE_NAME = ".bomana_update.lock"
UPDATE_LOCK_STALE_SEC = 30 * 60
APP_REQUIRED_FILES = (
    Path("Bomana.pyw"),
    Path("bomana_version.py"),
    Path("bomana") / "metadata.py",
)
APP_CONFIG_MARKERS = (Path("bomana") / "config" / "__init__.py",)

StatusCallback = Callable[[str, str, float | None, str], None]
CancelCallback = Callable[[], bool]
LogCallback = Callable[[Path, str], None]


def _now_utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_literal_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        module = ast.parse(text, filename=str(path))
        values: list[str] = []
        for statement in module.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "__version__" for target in targets
            ):
                continue
            value = statement.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return ""
            values.append(value.value)
        if len(values) == 1:
            return values[0]
    except Exception:
        return ""
    return ""


def _read_optional_literal_version(path: Path, name: str) -> tuple[bool, str]:
    """Read one optional version assignment without executing candidate code."""

    try:
        text = path.read_text(encoding="utf-8")
        module = ast.parse(text, filename=str(path))
        values: list[str] = []
        found = False
        for statement in module.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
                continue
            found = True
            value = statement.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return True, ""
            values.append(value.value)
        if len(values) == 1:
            return True, values[0]
        if found:
            return True, ""
    except Exception:
        return False, ""
    return False, ""


def read_app_version_identity(app_dir: Path) -> str:
    """Read the candidate's canonical version literal without importing it."""

    return _read_literal_version(app_dir / "bomana" / "metadata.py")


def read_app_min_launcher_version_identity(app_dir: Path) -> str:
    """Read the candidate release floor, preserving legacy App compatibility."""

    found, value = _read_optional_literal_version(
        app_dir / "bomana" / "metadata.py",
        "PORTABLE_MIN_LAUNCHER_VERSION",
    )
    return value if found else MIN_SUPPORTED_LAUNCHER_VERSION


def read_local_app_version(app_dir: Path) -> str:
    return read_app_version_identity(app_dir) or "0.0.0"


def slot_entry_exists(path: Path) -> bool:
    """Return whether a slot entry exists without following a reparse target."""

    return os.path.lexists(path)


def require_compatible_app_version(
    app_dir: Path,
    *,
    expected_version: str | None = None,
    launcher_version: str = LAUNCHER_VERSION,
    identity_name: str = "应用版本",
) -> str:
    """Validate App identity and its declared Launcher release floor."""

    if expected_version is not None:
        require_minimum_version(
            expected_version,
            MIN_SUPPORTED_APP_VERSION,
            identity_name="已验证签名清单应用版本",
        )
    version = require_minimum_version(
        read_app_version_identity(app_dir),
        MIN_SUPPORTED_APP_VERSION,
        identity_name=identity_name,
    )
    min_launcher_version = require_minimum_version(
        read_app_min_launcher_version_identity(app_dir),
        MIN_SUPPORTED_LAUNCHER_VERSION,
        identity_name="应用最低启动器版本",
    )
    require_minimum_version(
        launcher_version,
        min_launcher_version,
        identity_name="当前启动器版本",
    )
    if expected_version is not None:
        require_exact_version(version, expected_version, identity_name=identity_name)
    return version


def validate_app_package_root(app_root: Path, entrypoint: str) -> None:
    required = {Path(entrypoint), *APP_REQUIRED_FILES}
    missing = [
        path.as_posix()
        for path in sorted(required, key=lambda item: item.as_posix())
        if not (app_root / path).is_file()
    ]
    if not any((app_root / path).is_file() for path in APP_CONFIG_MARKERS):
        missing.append("bomana/config/__init__.py")
    if missing:
        raise RuntimeError(f"应用包缺少必要文件: {', '.join(missing)}")


def acquire_update_lock(base: Path) -> Path:
    lock_path = base / UPDATE_LOCK_FILE_NAME
    try:
        if lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age >= UPDATE_LOCK_STALE_SEC:
                lock_path.unlink()
    except Exception:
        pass

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as e:
        raise RuntimeError("检测到另一个更新任务正在进行，请稍后重试。") from e

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}\n")
            f.write(f"utc={_now_utc_iso()}\n")
    except Exception:
        with suppress(Exception):
            lock_path.unlink()
        raise
    return lock_path


def release_update_lock(lock_path: Path | None) -> None:
    if not lock_path:
        return
    with suppress(Exception):
        lock_path.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


class InstallTransaction:
    """Owns update lock, staging paths, replacement, and rollback cleanup."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.app_dir = base / APP_DIR_NAME
        self.backup_dir = base / APP_BACKUP_DIR_NAME
        self.previous_dir = base / APP_PREVIOUS_DIR_NAME
        self.new_dir = base / f"{APP_DIR_NAME}_new"
        self.lock_path: Path | None = None
        self.work_dir: Path | None = None
        self.zip_path: Path | None = None
        self.stage_dir: Path | None = None
        self.validated_new_version: str | None = None
        self.moved_to_backup = False
        self.replaced_app = False

    def __enter__(self) -> InstallTransaction:
        self.lock_path = acquire_update_lock(self.base)
        self.work_dir = Path(tempfile.mkdtemp(prefix="bomana_update_", dir=str(self.base)))
        self.zip_path = self.work_dir / "app.zip"
        self.stage_dir = self.work_dir / "stage"
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rollback()
        if self.work_dir is not None:
            shutil.rmtree(self.work_dir, ignore_errors=True)
        release_update_lock(self.lock_path)

    def extract_package(
        self,
        package_bytes: bytes,
        entrypoint: str,
        *,
        expected_version: str | None = None,
    ) -> Path:
        if self.zip_path is None or self.stage_dir is None:
            raise RuntimeError("安装事务未启动")
        self.zip_path.write_bytes(package_bytes)
        return self.extract_package_file(
            self.zip_path,
            entrypoint,
            expected_version=expected_version,
        )

    def extract_package_file(
        self,
        package_path: Path,
        entrypoint: str,
        *,
        expected_version: str | None = None,
    ) -> Path:
        if self.zip_path is None or self.stage_dir is None:
            raise RuntimeError("安装事务未启动")
        if package_path != self.zip_path:
            shutil.copyfile(package_path, self.zip_path)
        safe_extract_zip(self.zip_path, self.stage_dir)
        src_root = normalize_package_root(self.stage_dir, entrypoint)
        validate_app_package_root(src_root, entrypoint)
        require_compatible_app_version(
            src_root,
            expected_version=expected_version,
            identity_name="暂存应用版本",
        )
        return src_root

    def stage_new_app(self, src_root: Path, *, expected_version: str | None = None) -> None:
        version = require_compatible_app_version(
            src_root,
            expected_version=expected_version,
            identity_name="暂存应用版本",
        )
        if self.new_dir.exists():
            shutil.rmtree(self.new_dir, ignore_errors=True)
        shutil.copytree(src_root, self.new_dir)
        self.validated_new_version = require_compatible_app_version(
            self.new_dir,
            expected_version=version,
            identity_name="暂存应用版本",
        )

    def replace_app(self) -> None:
        if self.validated_new_version is None:
            raise RuntimeError("暂存应用尚未通过兼容性校验")
        require_compatible_app_version(
            self.new_dir,
            expected_version=self.validated_new_version,
            identity_name="暂存应用版本",
        )
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir, ignore_errors=True)
        if self.app_dir.exists():
            os.replace(str(self.app_dir), str(self.backup_dir))
            self.moved_to_backup = True
        os.replace(str(self.new_dir), str(self.app_dir))
        self.replaced_app = True

        if self.backup_dir.exists():
            if self.previous_dir.exists():
                shutil.rmtree(self.previous_dir, ignore_errors=True)
            os.replace(str(self.backup_dir), str(self.previous_dir))

    def rollback(self) -> None:
        try:
            if self.replaced_app and self.moved_to_backup and self.backup_dir.exists():
                if self.app_dir.exists():
                    shutil.rmtree(self.app_dir, ignore_errors=True)
                os.replace(str(self.backup_dir), str(self.app_dir))
            elif self.moved_to_backup and self.backup_dir.exists() and not self.app_dir.exists():
                os.replace(str(self.backup_dir), str(self.app_dir))
            if self.new_dir.exists():
                shutil.rmtree(self.new_dir, ignore_errors=True)
        except Exception:
            pass

    @classmethod
    def recover_incomplete(cls, base: Path, log_cb: LogCallback | None = None) -> list[str]:
        transaction = cls(base)
        steps: list[str] = []
        try:
            candidates = (
                (transaction.app_dir, "当前应用版本"),
                (transaction.backup_dir, "恢复备份应用版本"),
                (transaction.previous_dir, "保留应用版本"),
                (transaction.new_dir, "恢复暂存应用版本"),
            )
            for candidate, identity_name in candidates:
                if slot_entry_exists(candidate):
                    require_compatible_app_version(
                        candidate,
                        identity_name=identity_name,
                    )

            if (not transaction.app_dir.exists()) and transaction.backup_dir.exists():
                os.replace(str(transaction.backup_dir), str(transaction.app_dir))
                steps.append("restore_backup")

            if transaction.app_dir.exists() and transaction.backup_dir.exists():
                if transaction.previous_dir.exists():
                    shutil.rmtree(transaction.previous_dir, ignore_errors=True)
                os.replace(str(transaction.backup_dir), str(transaction.previous_dir))
                steps.append("promote_backup_to_previous")

            if transaction.new_dir.exists():
                if not transaction.app_dir.exists():
                    os.replace(str(transaction.new_dir), str(transaction.app_dir))
                    steps.append("promote_new")
                else:
                    shutil.rmtree(transaction.new_dir, ignore_errors=True)
                    steps.append("cleanup_new")

            lock_path = base / UPDATE_LOCK_FILE_NAME
            if lock_path.exists():
                age = time.time() - lock_path.stat().st_mtime
                if age >= UPDATE_LOCK_STALE_SEC:
                    lock_path.unlink()
                    steps.append("cleanup_stale_lock")
        except Exception as e:
            if log_cb is not None:
                log_cb(base, f"安装恢复失败：{e}")
            return []
        return steps


def install_zip_package(
    base: Path,
    package_bytes: bytes,
    expected_sha256: str,
    entrypoint: str,
    status_cb: StatusCallback | None = None,
    cancel_cb: CancelCallback | None = None,
    expected_version: str | None = None,
) -> None:
    if expected_version is not None:
        require_minimum_version(
            expected_version,
            MIN_SUPPORTED_APP_VERSION,
            identity_name="已验证签名清单应用版本",
        )
    expected = (expected_sha256 or "").strip().lower()
    actual = sha256_bytes(package_bytes)
    if expected and actual != expected:
        raise RuntimeError("应用包 SHA256 校验失败")
    if cancel_cb and cancel_cb():
        raise RuntimeError("已取消当前操作")

    with InstallTransaction(base) as transaction:
        if status_cb:
            status_cb("正在安装更新", "正在解压应用包...", 0.86, "info")
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        src_root = transaction.extract_package(
            package_bytes,
            entrypoint,
            expected_version=expected_version,
        )

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        transaction.stage_new_app(src_root, expected_version=expected_version)
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        transaction.replace_app()


def install_zip_package_from_file(
    base: Path,
    package_path: Path,
    expected_sha256: str,
    entrypoint: str,
    status_cb: StatusCallback | None = None,
    cancel_cb: CancelCallback | None = None,
    expected_version: str | None = None,
) -> None:
    if expected_version is not None:
        require_minimum_version(
            expected_version,
            MIN_SUPPORTED_APP_VERSION,
            identity_name="已验证签名清单应用版本",
        )
    expected = (expected_sha256 or "").strip().lower()
    actual = sha256_file(package_path)
    if expected and actual != expected:
        raise RuntimeError("应用包 SHA256 校验失败")
    if cancel_cb and cancel_cb():
        raise RuntimeError("已取消当前操作")

    with InstallTransaction(base) as transaction:
        if status_cb:
            status_cb("正在安装更新", "正在解压应用包...", 0.86, "info")
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        src_root = transaction.extract_package_file(
            package_path,
            entrypoint,
            expected_version=expected_version,
        )

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        transaction.stage_new_app(src_root, expected_version=expected_version)
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        transaction.replace_app()


def rollback_to_previous_app(
    base: Path,
    status_cb: StatusCallback | None = None,
) -> tuple[str, str]:
    app_dir = base / APP_DIR_NAME
    previous_dir = base / APP_PREVIOUS_DIR_NAME
    if not app_dir.exists():
        raise RuntimeError("当前没有可用应用，无法执行回退。")
    if not previous_dir.exists():
        raise RuntimeError("未找到可回退的上一版本。")

    current_version = require_compatible_app_version(
        app_dir,
        identity_name="当前应用版本",
    )
    previous_version = require_compatible_app_version(
        previous_dir,
        identity_name="回退应用版本",
    )
    lock_path = acquire_update_lock(base)
    work_dir = Path(tempfile.mkdtemp(prefix="bomana_rollback_", dir=str(base)))
    swap_dir = work_dir / "app_swap"
    moved_current_to_swap = False
    moved_previous_to_app = False
    cleanup_work_dir = True

    try:
        if status_cb:
            status_cb(
                "正在回退版本",
                f"正在切换到上一版本 v{previous_version}...",
                0.55,
                "warning",
            )

        os.replace(str(app_dir), str(swap_dir))
        moved_current_to_swap = True
        os.replace(str(previous_dir), str(app_dir))
        moved_previous_to_app = True
        os.replace(str(swap_dir), str(previous_dir))
        moved_current_to_swap = False

        if status_cb:
            status_cb(
                "回退完成",
                f"已切换到 v{previous_version}，当前保留的上一版本为 v{current_version}。",
                1.0,
                "success",
            )
        return previous_version, current_version
    except Exception:
        with suppress(Exception):
            if moved_previous_to_app and app_dir.exists() and not previous_dir.exists():
                os.replace(str(app_dir), str(previous_dir))
                moved_previous_to_app = False
        with suppress(Exception):
            if moved_current_to_swap and swap_dir.exists() and not app_dir.exists():
                os.replace(str(swap_dir), str(app_dir))
                moved_current_to_swap = False
        if swap_dir.exists():
            cleanup_work_dir = False
        raise
    finally:
        if cleanup_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        release_update_lock(lock_path)
