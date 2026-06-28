"""Pure launcher helpers shared by the portable launcher UI and tests."""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOWNLOAD_SOURCE_MODE_AUTO = ""
DOWNLOAD_SOURCE_MODE_PRIMARY = "primary"
DOWNLOAD_SOURCE_MODE_GITHUB = "github"
DOWNLOAD_SOURCE_CHOICES = (
    (DOWNLOAD_SOURCE_MODE_AUTO, "自动（沿用现有逻辑）"),
    (DOWNLOAD_SOURCE_MODE_PRIMARY, "腾讯云"),
    (DOWNLOAD_SOURCE_MODE_GITHUB, "GitHub"),
)
DOWNLOAD_SOURCE_DETAILS = {
    DOWNLOAD_SOURCE_MODE_AUTO: "默认：优先腾讯云，失败或缺少下载包时再回退 GitHub。",
    DOWNLOAD_SOURCE_MODE_PRIMARY: "仅使用腾讯云更新服务。检查或下载失败时不再自动回退 GitHub。",
    DOWNLOAD_SOURCE_MODE_GITHUB: "仅使用 GitHub Releases。适合手动排查国内更新链路问题。",
}
DOWNLOAD_SOURCE_LABEL_TO_MODE = {label: mode for mode, label in DOWNLOAD_SOURCE_CHOICES}
DOWNLOAD_SOURCE_MODE_TO_LABEL = dict(DOWNLOAD_SOURCE_CHOICES)
LAUNCHER_ASSET_PREFIX = "Bomana_launcher_v"
RELEASE_MANIFEST_SIGNATURE_FIELD = "manifest_signature"
RELEASE_MANIFEST_SIGNATURE_ALGORITHM = "ed25519"
RELEASE_MANIFEST_DEFAULT_KEY_ID = "bomana-release-2026-06"
try:
    _RELEASE_KEYS_MODULE = importlib.import_module("bomana.release_public_keys")
    _PINNED_RELEASE_KEYS = getattr(_RELEASE_KEYS_MODULE, "RELEASE_MANIFEST_PUBLIC_KEYS", {})
except ImportError:
    _PINNED_RELEASE_KEYS = {}
RELEASE_MANIFEST_PUBLIC_KEYS: dict[str, str] = dict(_PINNED_RELEASE_KEYS)

_ED25519_Q = 2**255 - 19
_ED25519_L = 2**252 + 27742317777372353535851937790883648493
_ED25519_D = -121665 * pow(121666, _ED25519_Q - 2, _ED25519_Q) % _ED25519_Q
_ED25519_I = pow(2, (_ED25519_Q - 1) // 4, _ED25519_Q)
_ED25519_B: tuple[int, int] | None = None


@dataclass
class LaunchDecision:
    action: str  # "launch" | "exit"
    final_version: str
    warning: str = ""


def normalize_download_source_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("", "auto", "default"):
        return DOWNLOAD_SOURCE_MODE_AUTO
    if raw in ("primary", "tencent", "cn", "domestic"):
        return DOWNLOAD_SOURCE_MODE_PRIMARY
    if raw in ("github", "gh"):
        return DOWNLOAD_SOURCE_MODE_GITHUB
    return DOWNLOAD_SOURCE_MODE_AUTO


def download_source_label(mode: str) -> str:
    normalized = normalize_download_source_mode(mode)
    return DOWNLOAD_SOURCE_MODE_TO_LABEL.get(
        normalized,
        DOWNLOAD_SOURCE_MODE_TO_LABEL[DOWNLOAD_SOURCE_MODE_AUTO],
    )


def format_size_text(num_bytes: int | None) -> str:
    if num_bytes is None or num_bytes < 0:
        return "未知"
    if num_bytes >= 1073741824:
        return f"{num_bytes / 1073741824:.2f} GB"
    if num_bytes >= 1048576:
        return f"{num_bytes / 1048576:.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?\s*$")


def extract_version_tuple(version: str) -> tuple[int, ...]:
    text = str(version or "").strip()
    match = _VERSION_RE.match(text)
    if match:
        return tuple(int(part) for part in match.groups(default="0"))
    nums = re.findall(r"\d+", text.split("-", 1)[0].split("+", 1)[0])
    if not nums:
        return (0,)
    return tuple(int(x) for x in nums)


def _is_prerelease(version: str) -> bool:
    release_and_prerelease = str(version or "").strip().split("+", 1)[0]
    return "-" in release_and_prerelease


def version_is_newer(remote: str, local: str) -> bool:
    a = extract_version_tuple(remote)
    b = extract_version_tuple(local)
    n = max(len(a), len(b))
    aa = a + (0,) * (n - len(a))
    bb = b + (0,) * (n - len(b))
    if aa != bb:
        return aa > bb
    return (not _is_prerelease(remote)) and _is_prerelease(local)


def version_is_older(current: str, required: str) -> bool:
    return version_is_newer(required, current)


def format_min_launcher_requirement(required_version: str) -> str:
    ver = str(required_version or "").strip()
    return f"启动器 v{ver}+" if ver else "新版启动器"


def find_asset(assets: list, name: str) -> dict[str, Any] | None:
    for asset in assets:
        if str(asset.get("name", "")).lower() == name.lower():
            return asset
    return None


def normalize_package_root(stage_dir: Path, entrypoint: str) -> Path:
    if (stage_dir / entrypoint).exists():
        return stage_dir
    children = [p for p in stage_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / entrypoint).exists():
        return children[0]
    return stage_dir


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().lower()


def _ed25519_inv(value: int) -> int:
    return pow(value, _ED25519_Q - 2, _ED25519_Q)


def _ed25519_xrecover(y: int) -> int:
    xx = (y * y - 1) * _ed25519_inv(_ED25519_D * y * y + 1)
    x = pow(xx, (_ED25519_Q + 3) // 8, _ED25519_Q)
    if (x * x - xx) % _ED25519_Q != 0:
        x = (x * _ED25519_I) % _ED25519_Q
    if x & 1:
        x = _ED25519_Q - x
    return x


def _ed25519_basepoint() -> tuple[int, int]:
    global _ED25519_B
    if _ED25519_B is None:
        y = 4 * _ed25519_inv(5) % _ED25519_Q
        _ED25519_B = (_ed25519_xrecover(y), y)
    return _ED25519_B


def _ed25519_is_on_curve(point: tuple[int, int]) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - _ED25519_D * x * x * y * y) % _ED25519_Q == 0


def _ed25519_add(
    point_a: tuple[int, int],
    point_b: tuple[int, int],
) -> tuple[int, int]:
    x1, y1 = point_a
    x2, y2 = point_b
    denominator = _ED25519_D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _ed25519_inv(1 + denominator)
    y3 = (y1 * y2 + x1 * x2) * _ed25519_inv(1 - denominator)
    return (x3 % _ED25519_Q, y3 % _ED25519_Q)


def _ed25519_scalarmult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    if scalar == 0:
        return (0, 1)
    partial = _ed25519_scalarmult(point, scalar // 2)
    partial = _ed25519_add(partial, partial)
    if scalar & 1:
        partial = _ed25519_add(partial, point)
    return partial


def _ed25519_encodeint(value: int) -> bytes:
    return value.to_bytes(32, "little")


def _ed25519_decodeint(data: bytes) -> int:
    return int.from_bytes(data, "little")


def _ed25519_encodepoint(point: tuple[int, int]) -> bytes:
    x, y = point
    bits = bytearray(_ed25519_encodeint(y))
    bits[31] |= (x & 1) << 7
    return bytes(bits)


def _ed25519_decodepoint(data: bytes) -> tuple[int, int]:
    if len(data) != 32:
        raise ValueError("Ed25519 point must be 32 bytes")
    y = _ed25519_decodeint(data) & ((1 << 255) - 1)
    x = _ed25519_xrecover(y)
    if bool(x & 1) != bool(data[31] & 0x80):
        x = _ED25519_Q - x
    point = (x, y)
    if not _ed25519_is_on_curve(point):
        raise ValueError("Ed25519 point is not on curve")
    return point


def _ed25519_hash_mod_l(*parts: bytes) -> int:
    h = hashlib.sha512()
    for part in parts:
        h.update(part)
    return int.from_bytes(h.digest(), "little") % _ED25519_L


def _ed25519_secret_scalar(seed: bytes) -> tuple[int, bytes]:
    digest = bytearray(hashlib.sha512(seed).digest())
    digest[0] &= 248
    digest[31] &= 63
    digest[31] |= 64
    return int.from_bytes(digest[:32], "little"), bytes(digest[32:])


def _decode_base64_bytes(value: str, *, label: str, expected_len: int) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError(f"{label}为空")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except binascii.Error as exc:
        raise RuntimeError(f"{label}不是有效 Base64") from exc
    if len(decoded) != expected_len:
        raise RuntimeError(f"{label}长度必须为 {expected_len} 字节")
    return decoded


def _decode_ed25519_private_seed(value: str) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("Ed25519 私钥为空")
    if len(raw) in (64, 128) and re.fullmatch(r"[0-9a-fA-F]+", raw):
        try:
            decoded = bytes.fromhex(raw)
        except ValueError as exc:
            raise RuntimeError("Ed25519 私钥必须是 32 字节 seed 的 Base64 或 hex") from exc
    else:
        try:
            decoded = base64.b64decode(raw, validate=True)
        except binascii.Error as exc:
            raise RuntimeError("Ed25519 私钥必须是 32 字节 seed 的 Base64 或 hex") from exc
    if len(decoded) == 64:
        decoded = decoded[:32]
    if len(decoded) != 32:
        raise RuntimeError("Ed25519 私钥必须是 32 字节 seed")
    return decoded


def ed25519_public_key_from_private_key(private_key: str) -> str:
    seed = _decode_ed25519_private_seed(private_key)
    scalar, _prefix = _ed25519_secret_scalar(seed)
    public_key = _ed25519_encodepoint(_ed25519_scalarmult(_ed25519_basepoint(), scalar))
    return base64.b64encode(public_key).decode("ascii")


def ed25519_sign(message: bytes, private_key: str) -> bytes:
    seed = _decode_ed25519_private_seed(private_key)
    scalar, prefix = _ed25519_secret_scalar(seed)
    public_key = base64.b64decode(ed25519_public_key_from_private_key(private_key), validate=True)
    r = _ed25519_hash_mod_l(prefix, message)
    encoded_r = _ed25519_encodepoint(_ed25519_scalarmult(_ed25519_basepoint(), r))
    h = _ed25519_hash_mod_l(encoded_r, public_key, message)
    s = (r + h * scalar) % _ED25519_L
    return encoded_r + _ed25519_encodeint(s)


def ed25519_verify(message: bytes, signature: bytes, public_key: bytes) -> bool:
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        r = _ed25519_decodepoint(signature[:32])
        a = _ed25519_decodepoint(public_key)
    except ValueError:
        return False
    s = _ed25519_decodeint(signature[32:])
    if s >= _ED25519_L:
        return False
    h = _ed25519_hash_mod_l(signature[:32], public_key, message)
    left = _ed25519_scalarmult(_ed25519_basepoint(), s)
    right = _ed25519_add(r, _ed25519_scalarmult(a, h))
    return left == right


def _without_manifest_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_manifest_signature(item)
            for key, item in value.items()
            if key != RELEASE_MANIFEST_SIGNATURE_FIELD
        }
    if isinstance(value, list):
        return [_without_manifest_signature(item) for item in value]
    return value


_APP_MANIFEST_SIGNATURE_FIELDS = (
    "schema_version",
    "channel",
    "app_version",
    "min_launcher_version",
    "entrypoint",
    "package_asset",
    "package_sha256",
)
_LAUNCHER_MANIFEST_SIGNATURE_FIELDS = (
    "schema_version",
    "launcher_version",
    "launcher_asset",
    "launcher_sha256",
    "launcher_size_bytes",
)


def _manifest_signature_core(manifest: dict[str, Any]) -> dict[str, Any]:
    unsigned_manifest = _without_manifest_signature(manifest)
    if "app_version" in unsigned_manifest:
        fields = _APP_MANIFEST_SIGNATURE_FIELDS
        label = "应用发布清单"
    elif "launcher_version" in unsigned_manifest:
        fields = _LAUNCHER_MANIFEST_SIGNATURE_FIELDS
        label = "启动器发布清单"
    else:
        raise RuntimeError("发布清单缺少可签名的版本字段")

    missing = [field for field in fields if field not in unsigned_manifest]
    if missing:
        raise RuntimeError(f"{label}缺少签名字段: {', '.join(missing)}")
    return {field: unsigned_manifest[field] for field in fields}


def manifest_signature_payload(manifest: dict[str, Any]) -> bytes:
    unsigned_manifest = _manifest_signature_core(manifest)
    payload = json.dumps(
        unsigned_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload.encode("utf-8")


def sign_release_manifest(
    manifest: dict[str, Any],
    private_key: str,
    *,
    key_id: str = RELEASE_MANIFEST_DEFAULT_KEY_ID,
) -> dict[str, Any]:
    key = str(key_id or "").strip()
    if not key:
        raise RuntimeError("发布签名 key_id 不能为空")
    signed = dict(_without_manifest_signature(manifest))
    signature = ed25519_sign(manifest_signature_payload(signed), private_key)
    signed[RELEASE_MANIFEST_SIGNATURE_FIELD] = {
        "algorithm": RELEASE_MANIFEST_SIGNATURE_ALGORITHM,
        "key_id": key,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return signed


def verify_release_manifest_signature(
    manifest: dict[str, Any],
    *,
    manifest_label: str = "更新清单",
    public_keys: dict[str, str] | None = None,
) -> None:
    signature_info = manifest.get(RELEASE_MANIFEST_SIGNATURE_FIELD)
    if not isinstance(signature_info, dict):
        raise RuntimeError(f"{manifest_label}缺少发布签名")

    algorithm = str(signature_info.get("algorithm", "")).strip().lower()
    key_id = str(signature_info.get("key_id", "")).strip()
    signature_text = str(signature_info.get("signature", "")).strip()
    if algorithm != RELEASE_MANIFEST_SIGNATURE_ALGORITHM:
        raise RuntimeError(f"{manifest_label}发布签名算法不支持")
    if not key_id:
        raise RuntimeError(f"{manifest_label}发布签名缺少 key_id")

    pinned_keys = RELEASE_MANIFEST_PUBLIC_KEYS if public_keys is None else public_keys
    public_key_text = str(pinned_keys.get(key_id, "")).strip()
    if not public_key_text:
        raise RuntimeError(f"{manifest_label}发布签名 key_id 未被当前启动器信任")

    public_key = _decode_base64_bytes(public_key_text, label="Ed25519 公钥", expected_len=32)
    signature = _decode_base64_bytes(signature_text, label="Ed25519 签名", expected_len=64)
    if not ed25519_verify(manifest_signature_payload(manifest), signature, public_key):
        raise RuntimeError(f"{manifest_label}发布签名校验失败")


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = (target_dir / member.filename).resolve()
            if target_root not in [member_path, *list(member_path.parents)]:
                raise RuntimeError("应用包包含非法路径")
        zf.extractall(target_dir)


def require_remote_checksum(checksum_value: str, *, artifact_label: str) -> str:
    checksum = str(checksum_value or "").strip().lower()
    if not checksum:
        raise RuntimeError(f"{artifact_label}缺少 SHA256 校验值")
    return checksum


def join_base_url_path(base_url: str, path: str) -> str:
    if not path:
        return base_url
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url}{path}"


def parse_launcher_version_from_asset_name(asset_name: str) -> str:
    name = asset_name.strip()
    suffix = ".exe"
    if not name.lower().startswith(LAUNCHER_ASSET_PREFIX.lower()):
        return ""
    if not name.lower().endswith(suffix):
        return ""
    return name[len(LAUNCHER_ASSET_PREFIX) : -len(suffix)].strip()


def find_launcher_asset(assets: list) -> dict[str, Any] | None:
    for asset in assets:
        name = str(asset.get("name", "")).strip()
        if parse_launcher_version_from_asset_name(name):
            return asset
    return None
