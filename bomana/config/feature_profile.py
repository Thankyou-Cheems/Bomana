"""Runtime feature projection for the packaged product edition.

Public source runs use Standard. Portable builds render only ``EDITION_CHANNEL``
into the archived copy; they never modify this working-tree file. The private
release closure owns the Enhanced source profile.
"""

from bomana.editions import FEATURE_FLAG_NAMES, feature_flags_for

EDITION_CHANNEL = "Standard"

_FEATURE_FLAGS = feature_flags_for(EDITION_CHANNEL)

ENABLE_CCRP = _FEATURE_FLAGS["ENABLE_CCRP"]
ENABLE_ZONES = _FEATURE_FLAGS["ENABLE_ZONES"]
ENABLE_AIRFIELDS = _FEATURE_FLAGS["ENABLE_AIRFIELDS"]
ENABLE_FUEL = _FEATURE_FLAGS["ENABLE_FUEL"]
ENABLE_CHECKLIST = _FEATURE_FLAGS["ENABLE_CHECKLIST"]
ENABLE_ADVANCED_SETTINGS = _FEATURE_FLAGS["ENABLE_ADVANCED_SETTINGS"]
ENABLE_WEB_DASHBOARD = _FEATURE_FLAGS["ENABLE_WEB_DASHBOARD"]

__all__ = [
    "ENABLE_ADVANCED_SETTINGS",
    "ENABLE_AIRFIELDS",
    "ENABLE_CCRP",
    "ENABLE_CHECKLIST",
    "ENABLE_FUEL",
    "ENABLE_WEB_DASHBOARD",
    "ENABLE_ZONES",
    "EDITION_CHANNEL",
    "FEATURE_FLAG_NAMES",
]
