"""Protected local persistence for the Bomana subscription session."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

_STORE_SCHEMA_VERSION = 1
_MAX_PROTECTED_BYTES = 256 * 1024
_DPAPI_UI_FORBIDDEN = 0x1
_DPAPI_ENTROPY = b"Bomana/CheemsPay subscription store/v1"


@dataclass(frozen=True)
class StoredSubscriptionSession:
    private_seed: bytes = field(repr=False)
    access_token: str = field(default="", repr=False)
    device_id: str = ""
    receipt_token: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if len(self.private_seed) != 32:
            raise ValueError("subscription device seed must contain exactly 32 bytes")


class DataProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class SubscriptionSessionStore(Protocol):
    def load(self) -> StoredSubscriptionSession | None: ...

    def save(self, session: StoredSubscriptionSession) -> None: ...

    def clear(self) -> None: ...


class FileSubscriptionSessionStore:
    """Atomic file store whose contents are protected by an injected adapter."""

    def __init__(self, path: Path, protector: DataProtector) -> None:
        self.path = path
        self.protector = protector

    def load(self) -> StoredSubscriptionSession | None:
        try:
            ciphertext = self.path.read_bytes()
        except FileNotFoundError:
            return None
        if not ciphertext or len(ciphertext) > _MAX_PROTECTED_BYTES:
            raise RuntimeError("subscription session store is invalid")
        plaintext = self.protector.unprotect(ciphertext)
        if len(plaintext) > _MAX_PROTECTED_BYTES:
            raise RuntimeError("subscription session payload is too large")
        try:
            payload = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("subscription session payload is invalid") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != _STORE_SCHEMA_VERSION:
            raise RuntimeError("subscription session schema is unsupported")
        try:
            private_seed = _base64url_decode(payload["private_seed"])
            access_token = _optional_string(payload, "access_token")
            device_id = _optional_string(payload, "device_id")
            receipt_token = _optional_string(payload, "receipt_token")
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("subscription session fields are invalid") from exc
        return StoredSubscriptionSession(
            private_seed=private_seed,
            access_token=access_token,
            device_id=device_id,
            receipt_token=receipt_token,
        )

    def save(self, session: StoredSubscriptionSession) -> None:
        payload = {
            "schema_version": _STORE_SCHEMA_VERSION,
            "private_seed": _base64url_encode(session.private_seed),
            "access_token": session.access_token,
            "device_id": session.device_id,
            "receipt_token": session.receipt_token,
        }
        plaintext = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        ciphertext = self.protector.protect(plaintext)
        if not ciphertext or len(ciphertext) > _MAX_PROTECTED_BYTES:
            raise RuntimeError("protected subscription session is invalid")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(ciphertext)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass
class InMemorySubscriptionSessionStore:
    """Non-persistent adapter for tests and source demos."""

    session: StoredSubscriptionSession | None = None

    def load(self) -> StoredSubscriptionSession | None:
        return self.session

    def save(self, session: StoredSubscriptionSession) -> None:
        self.session = session

    def clear(self) -> None:
        self.session = None


class WindowsDpapiProtector:
    """Current-user Windows DPAPI adapter; ciphertext cannot roam between users."""

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def __init__(self, *, entropy: bytes = _DPAPI_ENTROPY) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI is unavailable on this platform")
        self.entropy = bytes(entropy)
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_pointer = ctypes.POINTER(self._DataBlob)
        self._crypt32.CryptProtectData.argtypes = [
            blob_pointer,
            ctypes.c_wchar_p,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            blob_pointer,
            ctypes.POINTER(ctypes.c_wchar_p),
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def protect(self, plaintext: bytes) -> bytes:
        return self._transform(plaintext, protect=True)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return self._transform(ciphertext, protect=False)

    def _transform(self, value: bytes, *, protect: bool) -> bytes:
        input_blob, input_buffer = self._blob(value)
        entropy_blob, entropy_buffer = self._blob(self.entropy)
        output_blob = self._DataBlob()
        _keep_alive = (input_buffer, entropy_buffer)
        if protect:
            success = self._crypt32.CryptProtectData(
                ctypes.byref(input_blob),
                "Bomana CheemsPay subscription",
                ctypes.byref(entropy_blob),
                None,
                None,
                _DPAPI_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        else:
            success = self._crypt32.CryptUnprotectData(
                ctypes.byref(input_blob),
                None,
                ctypes.byref(entropy_blob),
                None,
                None,
                _DPAPI_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)

    def _blob(self, value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(value)
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        return self._DataBlob(len(value), pointer), buffer


def default_subscription_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Bomana" / "subscription-session.dat"


def create_default_subscription_store() -> FileSubscriptionSessionStore:
    return FileSubscriptionSessionStore(
        default_subscription_store_path(),
        WindowsDpapiProtector(),
    )


def _optional_string(payload: dict[str, object], name: str) -> str:
    value = payload.get(name, "")
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("base64url value is empty")
    padded = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded, altchars=b"-_", validate=True)


__all__ = [
    "DataProtector",
    "FileSubscriptionSessionStore",
    "InMemorySubscriptionSessionStore",
    "StoredSubscriptionSession",
    "SubscriptionSessionStore",
    "WindowsDpapiProtector",
    "create_default_subscription_store",
    "default_subscription_store_path",
]
