"""Launcher package facade for app install and rollback primitives."""

from __future__ import annotations

from bomana.launcher_install import (
    APP_BACKUP_DIR_NAME,
    APP_DIR_NAME,
    APP_PREVIOUS_DIR_NAME,
    UPDATE_LOCK_FILE_NAME,
    UPDATE_LOCK_STALE_SEC,
    InstallTransaction,
    acquire_update_lock,
    install_zip_package,
    install_zip_package_from_file,
    read_local_app_version,
    release_update_lock,
    rollback_to_previous_app,
    sha256_file,
    validate_app_package_root,
)

__all__ = [
    "APP_BACKUP_DIR_NAME",
    "APP_DIR_NAME",
    "APP_PREVIOUS_DIR_NAME",
    "UPDATE_LOCK_FILE_NAME",
    "UPDATE_LOCK_STALE_SEC",
    "InstallTransaction",
    "acquire_update_lock",
    "install_zip_package",
    "install_zip_package_from_file",
    "read_local_app_version",
    "release_update_lock",
    "rollback_to_previous_app",
    "sha256_file",
    "validate_app_package_root",
]
