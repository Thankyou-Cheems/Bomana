"""Install and rollback primitives for the portable launcher."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bomana_version import (
    MIN_SUPPORTED_APP_VERSION,
    MIN_SUPPORTED_LAUNCHER_VERSION,
    require_exact_version,
    require_minimum_version,
)
from launcher.core import (
    RELEASE_MANIFEST_SIGNATURE_FIELD,
    normalize_package_root,
    safe_extract_zip,
    sha256_bytes,
    verify_release_manifest_signature,
)
from launcher.metadata import LAUNCHER_VERSION

APP_DIR_NAME = "app"
APP_PREVIOUS_DIR_NAME = "app_previous"
APP_BACKUP_DIR_NAME = f"{APP_DIR_NAME}_backup"
APP_CHANNELS_DIR_NAME = "app_channels"
APP_CHANNELS = ("Enhanced", "Standard", "Lite")
UPDATE_LOCK_FILE_NAME = ".bomana_update.lock"
UPDATE_LOCK_STALE_SEC = 30 * 60
APP_RUNTIME_FILE_GROUPS = (
    (Path("bomana_version.py"), Path("bomana_version.pyc")),
    (Path("bomana") / "metadata.py", Path("bomana") / "metadata.pyc"),
    (
        Path("bomana") / "config" / "__init__.py",
        Path("bomana") / "config" / "__init__.pyc",
    ),
)
APP_PACKAGE_IDENTITY_PATH = Path("bomana") / "app_identity.json"
APP_PACKAGE_IDENTITY_SCHEMA_VERSION = 1
APP_PACKAGE_IDENTITY_FIELDS = {
    "schema_version",
    "channel",
    "app_version",
    "min_launcher_version",
    "entrypoint",
    "pyc_magic_hex",
}
INSTALLATION_IDENTITY_FILE_NAME = ".bomana_installation_identity.json"
INSTALLATION_IDENTITY_SCHEMA_VERSION = 1
INSTALLATION_IDENTITY_KIND = "managed_app_install"
APP_MANIFEST_IDENTITY_FIELDS = (
    "schema_version",
    "channel",
    "app_version",
    "min_launcher_version",
    "entrypoint",
    "package_asset",
    "package_sha256",
    "changelog_asset",
    "changelog_sha256",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

StatusCallback = Callable[[str, str, float | None, str], None]
CancelCallback = Callable[[], bool]
LogCallback = Callable[[Path, str], None]


def normalize_app_channel(value: object | None) -> str | None:
    """Return one canonical slot name, or ``None`` for the legacy slot."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for channel in APP_CHANNELS:
        if text.casefold() == channel.casefold():
            return channel
    raise ValueError(f"未知应用通道：{value}")


def _slot_root(base: Path, channel: object | None) -> Path:
    canonical = normalize_app_channel(channel)
    if canonical is None:
        return base
    return base / APP_CHANNELS_DIR_NAME / canonical


def app_slot_dir(base: Path, channel: object | None = None) -> Path:
    """Return the active App directory for one channel.

    ``channel=None`` deliberately preserves the pre-3.4 legacy layout for
    local compatibility tests and one-time migration.
    """

    return _slot_root(base, channel) / APP_DIR_NAME


def previous_app_slot_dir(base: Path, channel: object | None = None) -> Path:
    return _slot_root(base, channel) / APP_PREVIOUS_DIR_NAME


def backup_app_slot_dir(base: Path, channel: object | None = None) -> Path:
    return _slot_root(base, channel) / APP_BACKUP_DIR_NAME


def new_app_slot_dir(base: Path, channel: object | None = None) -> Path:
    return _slot_root(base, channel) / f"{APP_DIR_NAME}_new"


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


def read_app_package_identity(app_dir: Path) -> dict[str, Any] | None:
    """Read the non-executable identity embedded in a sourceless App package."""

    path = app_dir / APP_PACKAGE_IDENTITY_PATH
    try:
        if not path.exists():
            return None
        if path.stat().st_size > 16 * 1024:
            raise RuntimeError("应用包身份文件过大")
        value = json.loads(path.read_text(encoding="utf-8"))
    except RuntimeError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("应用包身份文件无效") from exc
    if not isinstance(value, dict) or set(value) != APP_PACKAGE_IDENTITY_FIELDS:
        raise RuntimeError("应用包身份字段无效")
    if value.get("schema_version") != APP_PACKAGE_IDENTITY_SCHEMA_VERSION:
        raise RuntimeError("应用包身份版本不支持")
    for field in (
        "channel",
        "app_version",
        "min_launcher_version",
        "entrypoint",
        "pyc_magic_hex",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise RuntimeError(f"应用包身份字段无效: {field}")
    return value


def read_app_version_identity(app_dir: Path) -> str:
    """Read the candidate's canonical version literal without importing it."""

    try:
        identity = read_app_package_identity(app_dir)
    except RuntimeError:
        return ""
    if identity is not None:
        return str(identity["app_version"]).strip()
    return _read_literal_version(app_dir / "bomana" / "metadata.py")


def read_app_min_launcher_version_identity(app_dir: Path) -> str:
    """Read the candidate release floor, preserving legacy App compatibility."""

    try:
        identity = read_app_package_identity(app_dir)
    except RuntimeError:
        return ""
    if identity is not None:
        return str(identity["min_launcher_version"]).strip()
    found, value = _read_optional_literal_version(
        app_dir / "bomana" / "metadata.py",
        "PORTABLE_MIN_LAUNCHER_VERSION",
    )
    return value if found else MIN_SUPPORTED_LAUNCHER_VERSION


def read_app_channel_identity(app_dir: Path) -> str:
    """Read the packaged edition marker without importing candidate code."""

    try:
        identity = read_app_package_identity(app_dir)
    except RuntimeError:
        return ""
    if identity is not None:
        try:
            return normalize_app_channel(identity["channel"]) or ""
        except ValueError:
            return ""
    path = app_dir / "bomana" / "config" / "feature_profile.py"
    try:
        if path.stat().st_size > 16 * 1024:
            return ""
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return ""
    values: list[str] = []
    for statement in module.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "EDITION_CHANNEL" for target in targets
        ):
            continue
        value = statement.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return ""
        values.append(value.value)
    if len(values) != 1:
        return ""
    try:
        return normalize_app_channel(values[0]) or ""
    except ValueError:
        return ""


def read_app_entrypoint_identity(app_dir: Path) -> str:
    """Return a sourceless package entrypoint, or empty for legacy source packages."""

    try:
        identity = read_app_package_identity(app_dir)
    except RuntimeError:
        return ""
    return str(identity["entrypoint"]).strip() if identity is not None else ""


def read_local_app_version(app_dir: Path) -> str:
    return read_app_version_identity(app_dir) or "0.0.0"


def require_app_channel(app_dir: Path, expected_channel: object) -> str:
    """Require a staged package's feature profile to match its selected slot."""

    expected = normalize_app_channel(expected_channel)
    if expected is None:
        raise ValueError("应用通道不能为空")
    actual = read_app_channel_identity(app_dir)
    if actual != expected:
        raise RuntimeError(f"应用包通道不匹配：包内 {actual or '未知'}，目标 {expected}")
    return actual


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
    entrypoint_path = Path(entrypoint)
    missing = [] if (app_root / entrypoint_path).is_file() else [entrypoint_path.as_posix()]
    for choices in APP_RUNTIME_FILE_GROUPS:
        if not any((app_root / path).is_file() for path in choices):
            missing.append(" or ".join(path.as_posix() for path in choices))
    identity = read_app_package_identity(app_root)
    if entrypoint_path.suffix == ".pyc" and identity is None:
        missing.append(APP_PACKAGE_IDENTITY_PATH.as_posix())
    if identity is not None and str(identity["entrypoint"]).strip() != entrypoint:
        raise RuntimeError("应用包身份入口与清单不匹配")
    if (
        entrypoint_path.suffix == ".pyc"
        and identity is not None
        and str(identity["pyc_magic_hex"]).strip().lower() != importlib.util.MAGIC_NUMBER.hex()
    ):
        raise RuntimeError("应用包字节码运行时不兼容，请先更新启动器")
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


def _require_sha256(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise RuntimeError(f"{label}不是有效的 SHA256")
    return digest


def _signed_manifest_projection(signed_manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify and retain only App fields covered by the release signature."""

    if not isinstance(signed_manifest, dict):
        raise RuntimeError("安装身份缺少已签名应用清单")
    verify_release_manifest_signature(
        signed_manifest,
        manifest_label="安装身份应用清单",
        expected_kind="app",
    )
    missing = [field for field in APP_MANIFEST_IDENTITY_FIELDS if field not in signed_manifest]
    if missing:
        raise RuntimeError(f"安装身份应用清单缺少签名字段: {', '.join(missing)}")
    signature = signed_manifest.get(RELEASE_MANIFEST_SIGNATURE_FIELD)
    if not isinstance(signature, dict):
        raise RuntimeError("安装身份应用清单缺少发布签名")
    try:
        projection = {field: signed_manifest[field] for field in APP_MANIFEST_IDENTITY_FIELDS}
        projection[RELEASE_MANIFEST_SIGNATURE_FIELD] = dict(signature)
        # JSON round-tripping rejects non-persistent / mutable values before a slot moves.
        return json.loads(json.dumps(projection, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("安装身份应用清单无法持久化") from exc


def build_signed_installation_identity(
    signed_manifest: dict[str, Any],
    *,
    channel: object,
    package_sha256: object,
    entrypoint: object,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Build local metadata anchored to one verified release manifest.

    The local record deliberately carries the original signed manifest rather
    than a Launcher-created signature.  Re-validating it later proves the
    channel, version, entrypoint, package digest, and trusted key identifier.
    """

    expected_channel = normalize_app_channel(channel)
    if expected_channel is None:
        raise ValueError("托管应用安装必须指定通道")
    expected_digest = _require_sha256(package_sha256, label="应用包 SHA256")
    expected_entrypoint = str(entrypoint or "").strip()
    if not expected_entrypoint:
        raise RuntimeError("应用入口文件不能为空")

    manifest = _signed_manifest_projection(signed_manifest)
    manifest_channel = normalize_app_channel(manifest.get("channel"))
    if manifest_channel != expected_channel:
        raise RuntimeError(
            f"签名安装身份通道不匹配：清单 {manifest_channel or '未知'}，目标 {expected_channel}"
        )
    manifest_version = require_minimum_version(
        manifest.get("app_version"),
        MIN_SUPPORTED_APP_VERSION,
        identity_name="签名安装身份应用版本",
    )
    if expected_version is not None:
        require_exact_version(
            manifest_version,
            expected_version,
            identity_name="签名安装身份应用版本",
        )
    manifest_entrypoint = str(manifest.get("entrypoint") or "").strip()
    if manifest_entrypoint != expected_entrypoint:
        raise RuntimeError("签名安装身份入口文件与安装目标不匹配")
    manifest_digest = _require_sha256(
        manifest.get("package_sha256"),
        label="签名安装身份应用包 SHA256",
    )
    if manifest_digest != expected_digest:
        raise RuntimeError("签名安装身份应用包 SHA256 与下载包不匹配")
    signature = manifest[RELEASE_MANIFEST_SIGNATURE_FIELD]
    key_id = str(signature.get("key_id") if isinstance(signature, dict) else "").strip()
    if not key_id:
        raise RuntimeError("签名安装身份缺少 manifest key_id")
    return {
        "schema_version": INSTALLATION_IDENTITY_SCHEMA_VERSION,
        "kind": INSTALLATION_IDENTITY_KIND,
        "channel": expected_channel,
        "app_version": manifest_version,
        "package_sha256": manifest_digest,
        "entrypoint": manifest_entrypoint,
        "manifest_key_id": key_id,
        "signed_manifest": manifest,
    }


def _write_installation_identity(app_dir: Path, identity: dict[str, Any]) -> None:
    destination = app_dir / INSTALLATION_IDENTITY_FILE_NAME
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(str(temporary), str(destination))
    finally:
        temporary.unlink(missing_ok=True)


def read_installation_identity(app_dir: Path) -> dict[str, Any]:
    path = app_dir / INSTALLATION_IDENTITY_FILE_NAME
    try:
        if path.stat().st_size > 128 * 1024:
            raise RuntimeError("安装身份文件过大")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("托管应用缺少签名安装身份") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("托管应用签名安装身份无效") from exc
    if not isinstance(value, dict):
        raise RuntimeError("托管应用签名安装身份格式无效")
    return value


def require_signed_installation_identity(
    app_dir: Path,
    expected_channel: object,
    *,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Require that a managed slot still matches its signed installation record."""

    channel = normalize_app_channel(expected_channel)
    if channel is None:
        raise ValueError("托管应用身份校验必须指定通道")
    identity = read_installation_identity(app_dir)
    if identity.get("schema_version") != INSTALLATION_IDENTITY_SCHEMA_VERSION:
        raise RuntimeError("托管应用签名安装身份版本不支持")
    if identity.get("kind") != INSTALLATION_IDENTITY_KIND:
        raise RuntimeError("托管应用签名安装身份类型无效")
    record_digest = _require_sha256(
        identity.get("package_sha256"),
        label="托管应用签名安装身份 SHA256",
    )
    record_entrypoint = str(identity.get("entrypoint") or "").strip()
    rebuilt = build_signed_installation_identity(
        identity.get("signed_manifest"),
        channel=channel,
        package_sha256=record_digest,
        entrypoint=record_entrypoint,
        expected_version=expected_version,
    )
    for field in (
        "schema_version",
        "kind",
        "channel",
        "app_version",
        "package_sha256",
        "entrypoint",
        "manifest_key_id",
        "signed_manifest",
    ):
        if identity.get(field) != rebuilt[field]:
            raise RuntimeError("托管应用签名安装身份与发布清单不一致")
    validate_app_package_root(app_dir, rebuilt["entrypoint"])
    require_app_channel(app_dir, channel)
    require_compatible_app_version(
        app_dir,
        expected_version=rebuilt["app_version"],
        identity_name="托管应用版本",
    )
    return rebuilt


class InstallTransaction:
    """Own update lock and atomic replacement for one channel slot."""

    def __init__(self, base: Path, channel: object | None = None) -> None:
        self.base = base
        self.channel = normalize_app_channel(channel)
        self.app_dir = app_slot_dir(base, self.channel)
        self.backup_dir = backup_app_slot_dir(base, self.channel)
        self.previous_dir = previous_app_slot_dir(base, self.channel)
        self.new_dir = new_app_slot_dir(base, self.channel)
        self.lock_path: Path | None = None
        self.work_dir: Path | None = None
        self.zip_path: Path | None = None
        self.stage_dir: Path | None = None
        self.validated_new_version: str | None = None
        self.installation_identity: dict[str, Any] | None = None
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
        expected_channel: object | None = None,
    ) -> Path:
        if self.zip_path is None or self.stage_dir is None:
            raise RuntimeError("安装事务未启动")
        self.zip_path.write_bytes(package_bytes)
        return self.extract_package_file(
            self.zip_path,
            entrypoint,
            expected_version=expected_version,
            expected_channel=expected_channel,
        )

    def extract_package_file(
        self,
        package_path: Path,
        entrypoint: str,
        *,
        expected_version: str | None = None,
        expected_channel: object | None = None,
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
        if expected_channel is not None:
            require_app_channel(src_root, expected_channel)
        return src_root

    def stage_new_app(
        self,
        src_root: Path,
        *,
        expected_version: str | None = None,
        expected_channel: object | None = None,
        installation_identity: dict[str, Any] | None = None,
    ) -> None:
        version = require_compatible_app_version(
            src_root,
            expected_version=expected_version,
            identity_name="暂存应用版本",
        )
        if self.new_dir.exists():
            shutil.rmtree(self.new_dir, ignore_errors=True)
        self.new_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_root, self.new_dir)
        if installation_identity is not None:
            _write_installation_identity(self.new_dir, installation_identity)
        self.validated_new_version = require_compatible_app_version(
            self.new_dir,
            expected_version=version,
            identity_name="暂存应用版本",
        )
        if expected_channel is not None:
            require_app_channel(self.new_dir, expected_channel)
            if installation_identity is None:
                raise RuntimeError("托管应用暂存缺少签名安装身份")
            require_signed_installation_identity(
                self.new_dir,
                expected_channel,
                expected_version=self.validated_new_version,
            )
        self.installation_identity = installation_identity

    def replace_app(self) -> None:
        if self.validated_new_version is None:
            raise RuntimeError("暂存应用尚未通过兼容性校验")
        require_compatible_app_version(
            self.new_dir,
            expected_version=self.validated_new_version,
            identity_name="暂存应用版本",
        )
        if self.channel is not None:
            require_signed_installation_identity(
                self.new_dir,
                self.channel,
                expected_version=self.validated_new_version,
            )
        self.app_dir.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.parent.mkdir(parents=True, exist_ok=True)
        self.previous_dir.parent.mkdir(parents=True, exist_ok=True)
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
    def recover_incomplete(
        cls,
        base: Path,
        log_cb: LogCallback | None = None,
        channel: object | None = None,
    ) -> list[str]:
        transaction = cls(base, channel)
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
                    if transaction.channel is not None:
                        require_signed_installation_identity(candidate, transaction.channel)

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

    @classmethod
    def recover_incomplete_all(
        cls,
        base: Path,
        log_cb: LogCallback | None = None,
    ) -> list[str]:
        """Recover legacy and every channel slot before launcher handoff."""

        steps: list[str] = []
        steps.extend(cls.recover_incomplete(base, log_cb=log_cb))
        for channel in APP_CHANNELS:
            steps.extend(cls.recover_incomplete(base, log_cb=log_cb, channel=channel))
        steps.extend(migrate_legacy_slots(base, log_cb=log_cb))
        return steps


def migrate_legacy_slots(
    base: Path,
    *,
    log_cb: LogCallback | None = None,
) -> list[str]:
    """Move pre-3.4 global slots into their channel-specific locations.

    Both legacy candidates are validated before the first rename. If a package
    has no channel marker (old test/source packages), it remains in the legacy
    slot and is resolved by the launcher compatibility fallback; real release
    packages always carry the marker.
    """

    candidates = (
        (base / APP_DIR_NAME, "current", "当前应用版本"),
        (base / APP_PREVIOUS_DIR_NAME, "previous", "保留应用版本"),
    )
    pending: list[tuple[Path, Path, str, str]] = []
    try:
        for source, slot_name, identity_name in candidates:
            if not slot_entry_exists(source):
                continue
            require_compatible_app_version(source, identity_name=identity_name)
            channel = read_app_channel_identity(source)
            if not channel:
                continue
            target = (
                app_slot_dir(base, channel)
                if slot_name == "current"
                else previous_app_slot_dir(base, channel)
            )
            pending.append((source, target, channel, slot_name))
    except Exception as exc:
        if log_cb is not None:
            log_cb(base, f"旧版应用槽位迁移已安全停止：{exc}")
        return []

    steps: list[str] = []
    for source, target, channel, slot_name in pending:
        if slot_entry_exists(target):
            if log_cb is not None:
                log_cb(base, f"通道 {channel} 已存在新槽位，保留旧版 {slot_name} 槽位：{source}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(source), str(target))
        steps.append(f"migrate_{slot_name}_{channel}")
    return steps


def install_zip_package(
    base: Path,
    package_bytes: bytes,
    expected_sha256: str,
    entrypoint: str,
    status_cb: StatusCallback | None = None,
    cancel_cb: CancelCallback | None = None,
    expected_version: str | None = None,
    channel: object | None = None,
    signed_manifest: dict[str, Any] | None = None,
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
    canonical_channel = normalize_app_channel(channel)
    installation_identity = None
    if canonical_channel is not None:
        if signed_manifest is None:
            raise RuntimeError("托管应用安装缺少已签名发布清单")
        installation_identity = build_signed_installation_identity(
            signed_manifest,
            channel=canonical_channel,
            package_sha256=expected,
            entrypoint=entrypoint,
            expected_version=expected_version,
        )
    if cancel_cb and cancel_cb():
        raise RuntimeError("已取消当前操作")

    with InstallTransaction(base, canonical_channel) as transaction:
        if status_cb:
            status_cb("正在安装更新", "正在解压应用包...", 0.86, "info")
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        src_root = transaction.extract_package(
            package_bytes,
            entrypoint,
            expected_version=expected_version,
            expected_channel=canonical_channel,
        )

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        transaction.stage_new_app(
            src_root,
            expected_version=expected_version,
            expected_channel=canonical_channel,
            installation_identity=installation_identity,
        )
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
    channel: object | None = None,
    signed_manifest: dict[str, Any] | None = None,
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
    canonical_channel = normalize_app_channel(channel)
    installation_identity = None
    if canonical_channel is not None:
        if signed_manifest is None:
            raise RuntimeError("托管应用安装缺少已签名发布清单")
        installation_identity = build_signed_installation_identity(
            signed_manifest,
            channel=canonical_channel,
            package_sha256=expected,
            entrypoint=entrypoint,
            expected_version=expected_version,
        )
    if cancel_cb and cancel_cb():
        raise RuntimeError("已取消当前操作")

    with InstallTransaction(base, canonical_channel) as transaction:
        if status_cb:
            status_cb("正在安装更新", "正在解压应用包...", 0.86, "info")
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        src_root = transaction.extract_package_file(
            package_path,
            entrypoint,
            expected_version=expected_version,
            expected_channel=canonical_channel,
        )

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        transaction.stage_new_app(
            src_root,
            expected_version=expected_version,
            expected_channel=canonical_channel,
            installation_identity=installation_identity,
        )
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        transaction.replace_app()


def rollback_to_previous_app(
    base: Path,
    status_cb: StatusCallback | None = None,
    channel: object | None = None,
) -> tuple[str, str]:
    app_dir = app_slot_dir(base, channel)
    previous_dir = previous_app_slot_dir(base, channel)
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
    canonical_channel = normalize_app_channel(channel)
    if canonical_channel is not None:
        require_signed_installation_identity(
            app_dir,
            canonical_channel,
            expected_version=current_version,
        )
        require_signed_installation_identity(
            previous_dir,
            canonical_channel,
            expected_version=previous_version,
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
