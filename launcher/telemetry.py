"""Launcher facade for Bomana's shared anonymous daily-active contract.

The implementation lives with the portable App so Standalone Green Lite can
use identical payload, storage, endpoint validation, and failure behavior
without bundling the Launcher.
"""

import json

from bomana.anonymous_dau import (
    DAU_CHANNELS,
    DAU_PATH,
    DEFAULT_UPDATE_BASE_URL,
    INSTALL_SECRET_BYTES,
    INSTALL_SECRET_FILE_NAME,
    REPORT_STAMP_FILE_NAME,
    REQUEST_TIMEOUT_SECONDS,
    SCHEMA_VERSION,
    build_daily_active_payload,
    daily_active_endpoint,
    default_state_dir,
    report_daily_active,
    start_daily_active_report,
)

__all__ = [
    "DAU_CHANNELS",
    "DAU_PATH",
    "DEFAULT_UPDATE_BASE_URL",
    "INSTALL_SECRET_BYTES",
    "INSTALL_SECRET_FILE_NAME",
    "REPORT_STAMP_FILE_NAME",
    "REQUEST_TIMEOUT_SECONDS",
    "SCHEMA_VERSION",
    "json",
    "build_daily_active_payload",
    "daily_active_endpoint",
    "default_state_dir",
    "report_daily_active",
    "start_daily_active_report",
]
