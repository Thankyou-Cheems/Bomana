"""Install and rollback primitives for the portable launcher."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from bomana.launcher_core import normalize_package_root, safe_extract_zip, sha256_bytes

APP_DIR_NAME = "app"
APP_PREVIOUS_DIR_NAME = "app_previous"
APP_BACKUP_DIR_NAME = f"{APP_DIR_NAME}_backup"
UPDATE_LOCK_FILE_NAME = ".bomana_update.lock"
UPDATE_LOCK_STALE_SEC = 30 * 60

StatusCallback = Callable[[str, str, float | None, str], None]
CancelCallback = Callable[[], bool]
LogCallback = Callable[[Path, str], None]


def _now_utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_literal_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            return match.group(1).strip()
    except Exception:
        return ""
    return ""


def read_local_app_version(app_dir: Path) -> str:
    for relative in (
        Path("bomana") / "config.py",
        Path("bomana") / "metadata.py",
    ):
        version = _read_literal_version(app_dir / relative)
        if version:
            return version
    return "0.0.0"


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

    def extract_package(self, package_bytes: bytes, entrypoint: str) -> Path:
        if self.zip_path is None or self.stage_dir is None:
            raise RuntimeError("安装事务未启动")
        self.zip_path.write_bytes(package_bytes)
        return self.extract_package_file(self.zip_path, entrypoint)

    def extract_package_file(self, package_path: Path, entrypoint: str) -> Path:
        if self.zip_path is None or self.stage_dir is None:
            raise RuntimeError("安装事务未启动")
        if package_path != self.zip_path:
            shutil.copyfile(package_path, self.zip_path)
        safe_extract_zip(self.zip_path, self.stage_dir)
        src_root = normalize_package_root(self.stage_dir, entrypoint)
        if not (src_root / entrypoint).exists():
            raise RuntimeError("应用包缺少入口文件 Bomana.pyw")
        return src_root

    def stage_new_app(self, src_root: Path) -> None:
        if self.new_dir.exists():
            shutil.rmtree(self.new_dir, ignore_errors=True)
        shutil.copytree(src_root, self.new_dir)

    def replace_app(self) -> None:
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
) -> None:
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
        src_root = transaction.extract_package(package_bytes, entrypoint)

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        transaction.stage_new_app(src_root)
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
) -> None:
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
        src_root = transaction.extract_package_file(package_path, entrypoint)

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        transaction.stage_new_app(src_root)
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

    current_version = read_local_app_version(app_dir)
    previous_version = read_local_app_version(previous_dir)
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
