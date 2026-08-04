"""HTTP Range transport for independently verified terrain objects.

The Launcher supplies the object base URL from a signed Distribution Descriptor.
This module has no UI, manifest, or activation behavior: it only resumes one
content-addressed object into a caller-owned partial file.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS: Final = 30.0
DOWNLOAD_CHUNK_BYTES: Final = 256 * 1024
CONTENT_RANGE_RE: Final = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")


class TerrainTransportError(RuntimeError):
    """Raised when an object response cannot safely resume or verify."""


class TerrainObject(Protocol):
    """The content-addressed fields needed by the byte transport."""

    asset: str
    sha256: str
    size_bytes: int


class TerrainHttpResponse(Protocol):
    """Minimal streaming response seam for deterministic transport tests."""

    status: int
    headers: Mapping[str, str]

    def iter_bytes(self, chunk_size: int) -> Iterable[bytes]: ...

    def close(self) -> None: ...


TerrainRequest = Callable[[str, Mapping[str, str], float], TerrainHttpResponse]


class _UrllibResponse:
    def __init__(self, response: object) -> None:
        self._response = response
        self.status = int(getattr(response, "status", getattr(response, "code", 0)))
        raw_headers = getattr(response, "headers", {})
        self.headers: Mapping[str, str] = {
            str(key): str(value) for key, value in raw_headers.items()
        }

    def iter_bytes(self, chunk_size: int) -> Iterable[bytes]:
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                return
            yield bytes(chunk)

    def close(self) -> None:
        self._response.close()


def urllib_terrain_request(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> TerrainHttpResponse:
    """Perform one bounded GET while preserving non-2xx HTTP status details."""

    request = Request(url, headers=dict(headers), method="GET")
    try:
        return _UrllibResponse(urlopen(request, timeout=timeout))
    except HTTPError as exc:
        return _UrllibResponse(exc)
    except URLError as exc:
        raise TerrainTransportError(f"terrain object request failed: {exc.reason}") from exc


def terrain_object_url(object_base_url: str, asset: str) -> str:
    """Resolve a safe manifest asset beneath a descriptor-provided HTTPS base."""

    base = str(object_base_url or "").strip()
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise TerrainTransportError("terrain object base URL must be an HTTPS path without a query")
    normalized_asset = str(asset or "").strip()
    candidate = PurePosixPath(normalized_asset)
    if (
        not normalized_asset
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name != normalized_asset
        or normalized_asset in {".", ".."}
        or "\\" in normalized_asset
    ):
        raise TerrainTransportError("terrain object asset must be a safe filename")
    return f"{base.rstrip('/')}/{quote(normalized_asset, safe='._-')}"


def range_headers(resume_from: int) -> dict[str, str]:
    """Render the request headers for a resumable byte offset."""

    if resume_from < 0:
        raise TerrainTransportError("terrain resume offset must not be negative")
    return {"Range": f"bytes={resume_from}-"} if resume_from else {}


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return str(value).strip()
    return ""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _validate_content_range(value: str, *, resume_from: int, expected_size: int) -> None:
    match = CONTENT_RANGE_RE.fullmatch(value)
    if match is None:
        raise TerrainTransportError("terrain range response is missing a valid Content-Range")
    start, end, total = (int(part) for part in match.groups())
    if start != resume_from or end < start or total != expected_size or end >= expected_size:
        raise TerrainTransportError("terrain range response does not match the requested object")


def _validate_content_length(headers: Mapping[str, str], expected_size: int) -> None:
    value = _header(headers, "Content-Length")
    if not value:
        return
    try:
        content_length = int(value)
    except ValueError as exc:
        raise TerrainTransportError("terrain response Content-Length is invalid") from exc
    if content_length != expected_size:
        raise TerrainTransportError("terrain response Content-Length is unexpected")


class TerrainObjectTransport:
    """Callable ObjectFetcher adapter with Range/resume and size/hash checks."""

    def __init__(
        self,
        object_base_url: str,
        *,
        request: TerrainRequest = urllib_terrain_request,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        source_name: str = "",
    ) -> None:
        self.object_base_url = str(object_base_url or "").strip()
        self.request = request
        self.timeout_seconds = float(timeout_seconds)
        self.source_name = str(source_name or "").strip()
        if self.timeout_seconds <= 0:
            raise TerrainTransportError("terrain request timeout must be positive")

    def __call__(
        self,
        item: TerrainObject,
        destination: Path,
        progress_cb: Callable[[int, int | None], None],
    ) -> str:
        return self.fetch(item, destination, progress_cb)

    def fetch(
        self,
        item: TerrainObject,
        destination: Path,
        progress_cb: Callable[[int, int | None], None],
    ) -> str:
        expected_size = int(item.size_bytes)
        if expected_size <= 0:
            raise TerrainTransportError("terrain object size must be positive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        resume_from = self._resume_offset(destination, item, progress_cb)
        if resume_from == expected_size:
            return self._source_label(item)

        url = terrain_object_url(self.object_base_url, item.asset)
        response = self.request(url, range_headers(resume_from), self.timeout_seconds)
        try:
            mode, received = self._response_mode(response, resume_from, expected_size)
            progress_cb(received, expected_size)
            with destination.open(mode) as file_obj:
                for raw_chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                    chunk = bytes(raw_chunk)
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > expected_size:
                        raise TerrainTransportError(
                            "terrain response exceeds its declared object size"
                        )
                    file_obj.write(chunk)
                    progress_cb(received, expected_size)
        finally:
            response.close()
        if received != expected_size:
            raise TerrainTransportError("terrain response ended before the declared object size")
        if _file_sha256(destination) != str(item.sha256).lower():
            raise TerrainTransportError("terrain object SHA-256 verification failed")
        return self._source_label(item)

    def _resume_offset(
        self,
        destination: Path,
        item: TerrainObject,
        progress_cb: Callable[[int, int | None], None],
    ) -> int:
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise TerrainTransportError("terrain partial path must be a regular file")
        if not destination.exists():
            return 0
        size = destination.stat().st_size
        if size > item.size_bytes:
            destination.unlink()
            return 0
        if size == item.size_bytes:
            if _file_sha256(destination) == str(item.sha256).lower():
                progress_cb(size, item.size_bytes)
                return size
            destination.unlink()
            return 0
        return size

    @staticmethod
    def _response_mode(
        response: TerrainHttpResponse,
        resume_from: int,
        expected_size: int,
    ) -> tuple[str, int]:
        if resume_from:
            if response.status == 206:
                _validate_content_range(
                    _header(response.headers, "Content-Range"),
                    resume_from=resume_from,
                    expected_size=expected_size,
                )
                _validate_content_length(response.headers, expected_size - resume_from)
                return "ab", resume_from
            if response.status == 200:
                _validate_content_length(response.headers, expected_size)
                return "wb", 0
            raise TerrainTransportError(f"terrain range request returned HTTP {response.status}")
        if response.status != 200:
            raise TerrainTransportError(f"terrain object request returned HTTP {response.status}")
        _validate_content_length(response.headers, expected_size)
        return "wb", 0

    def _source_label(self, item: TerrainObject) -> str:
        if self.source_name:
            return self.source_name
        return urlsplit(terrain_object_url(self.object_base_url, item.asset)).netloc


__all__ = [
    "CONTENT_RANGE_RE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DOWNLOAD_CHUNK_BYTES",
    "TerrainHttpResponse",
    "TerrainObject",
    "TerrainObjectTransport",
    "TerrainRequest",
    "TerrainTransportError",
    "range_headers",
    "terrain_object_url",
    "urllib_terrain_request",
]
