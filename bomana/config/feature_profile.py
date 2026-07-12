"""Build-variant feature switches.

Source runs default to the Enhanced feature profile. Portable build scripts patch
this file temporarily for Standard and Lite artifacts, then restore it.
"""

ENABLE_CCRP = True
ENABLE_ZONES = True
ENABLE_AIRFIELDS = True
ENABLE_FUEL = True
ENABLE_CHECKLIST = True
ENABLE_ADVANCED_SETTINGS = True
# Web Cockpit modules/assets are packaged only when this is True (Enhanced).
ENABLE_WEB_DASHBOARD = True

FEATURE_FLAG_NAMES = (
    "ENABLE_CCRP",
    "ENABLE_ZONES",
    "ENABLE_AIRFIELDS",
    "ENABLE_FUEL",
    "ENABLE_CHECKLIST",
    "ENABLE_ADVANCED_SETTINGS",
    "ENABLE_WEB_DASHBOARD",
)

__all__ = [
    "ENABLE_ADVANCED_SETTINGS",
    "ENABLE_AIRFIELDS",
    "ENABLE_CCRP",
    "ENABLE_CHECKLIST",
    "ENABLE_FUEL",
    "ENABLE_WEB_DASHBOARD",
    "ENABLE_ZONES",
    "FEATURE_FLAG_NAMES",
]
