"""Canonical product-edition policy shared by App, Launcher, and release tooling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class EditionAccess(StrEnum):
    """How an edition becomes available to a user."""

    PUBLIC = "public"
    SUBSCRIPTION = "subscription"


class EditionCapability(StrEnum):
    """Product capabilities that vary between editions."""

    TIMER = "timer"
    SPEED = "speed"
    ZONE_NAVIGATION = "zone_navigation"
    AIRFIELD_NAVIGATION = "airfield_navigation"
    FUEL = "fuel"
    CHECKLIST = "checklist"
    ADVANCED_SETTINGS = "advanced_settings"
    WEB_COCKPIT = "web_cockpit"
    STRIKE_PREDICTION = "strike_prediction"


@dataclass(frozen=True, slots=True)
class Edition:
    """One canonical Bomana edition and its stable release identity."""

    channel: str
    display_name: str
    title: str
    description: str
    audience: str
    access: EditionAccess
    capabilities: frozenset[EditionCapability]
    aliases: tuple[str, ...] = ()

    @property
    def requires_subscription(self) -> bool:
        return self.access is EditionAccess.SUBSCRIPTION

    def includes(self, capability: EditionCapability) -> bool:
        return capability in self.capabilities


_CORE_CAPABILITIES = frozenset(
    {
        EditionCapability.TIMER,
        EditionCapability.SPEED,
        EditionCapability.ADVANCED_SETTINGS,
    }
)

SUPER_BOMB_EDITION: Final = Edition(
    channel="Enhanced",
    display_name="超级爆弹版",
    title="超级爆弹版",
    description="拥有深度学习的高精度打击模型与启动器独立维护的地形数据。",
    audience="适合：需要最高精度投弹预测与离线地形参考。",
    access=EditionAccess.SUBSCRIPTION,
    capabilities=_CORE_CAPABILITIES
    | {
        EditionCapability.ZONE_NAVIGATION,
        EditionCapability.AIRFIELD_NAVIGATION,
        EditionCapability.FUEL,
        EditionCapability.CHECKLIST,
        EditionCapability.WEB_COCKPIT,
        EditionCapability.STRIKE_PREDICTION,
    },
    aliases=("enhanced", "增强版", "超级爆弹版"),
)

STANDARD_EDITION: Final = Edition(
    channel="Standard",
    display_name="Standard",
    title="标准版 (稳定轻量)",
    description="包含计时器 + 战区/机场导航 + 燃油管理；不含投弹预测与网页驾驶舱。",
    audience="适合：不需要投弹预测与网页控制台，但需要导航和油量信息。",
    access=EditionAccess.PUBLIC,
    capabilities=_CORE_CAPABILITIES
    | {
        EditionCapability.ZONE_NAVIGATION,
        EditionCapability.AIRFIELD_NAVIGATION,
        EditionCapability.FUEL,
        EditionCapability.CHECKLIST,
    },
    aliases=("standard", "标准版"),
)

LITE_EDITION: Final = Edition(
    channel="Lite",
    display_name="Lite",
    title="精简版 (极简模式)",
    description="仅保留核心复活计时器，不含网页驾驶舱；资源占用最低。",
    audience="适合：只想看计时、追求最小干扰和最低开销。",
    access=EditionAccess.PUBLIC,
    capabilities=_CORE_CAPABILITIES,
    aliases=("lite", "精简版"),
)

EDITIONS: Final = (SUPER_BOMB_EDITION, STANDARD_EDITION, LITE_EDITION)
CHANNELS: Final = tuple(edition.channel for edition in EDITIONS)
PUBLIC_CHANNELS: Final = tuple(
    edition.channel for edition in EDITIONS if edition.access is EditionAccess.PUBLIC
)
SUBSCRIPTION_CHANNELS: Final = tuple(
    edition.channel for edition in EDITIONS if edition.requires_subscription
)

_EDITION_BY_CHANNEL = MappingProxyType({edition.channel: edition for edition in EDITIONS})
_EDITION_BY_ALIAS = MappingProxyType(
    {
        alias.casefold(): edition
        for edition in EDITIONS
        for alias in (edition.channel, edition.display_name, *edition.aliases)
    }
)

CHANNEL_ALIASES: Final = MappingProxyType(
    {alias: edition.channel for alias, edition in _EDITION_BY_ALIAS.items()}
)
CHANNEL_DISPLAY_NAMES: Final = MappingProxyType(
    {edition.channel: edition.display_name for edition in EDITIONS}
)
CHANNEL_DETAILS: Final = MappingProxyType(
    {
        edition.channel: MappingProxyType(
            {
                "title": edition.title,
                "desc": edition.description,
                "who": edition.audience,
            }
        )
        for edition in EDITIONS
    }
)
WEB_COCKPIT_CHANNELS: Final = frozenset(
    edition.channel for edition in EDITIONS if edition.includes(EditionCapability.WEB_COCKPIT)
)

FEATURE_FLAG_CAPABILITIES: Final = MappingProxyType(
    {
        "ENABLE_CCRP": EditionCapability.STRIKE_PREDICTION,
        "ENABLE_ZONES": EditionCapability.ZONE_NAVIGATION,
        "ENABLE_AIRFIELDS": EditionCapability.AIRFIELD_NAVIGATION,
        "ENABLE_FUEL": EditionCapability.FUEL,
        "ENABLE_CHECKLIST": EditionCapability.CHECKLIST,
        "ENABLE_ADVANCED_SETTINGS": EditionCapability.ADVANCED_SETTINGS,
        "ENABLE_WEB_DASHBOARD": EditionCapability.WEB_COCKPIT,
    }
)
FEATURE_FLAG_NAMES: Final = tuple(FEATURE_FLAG_CAPABILITIES)


def find_edition(value: object) -> Edition | None:
    """Resolve a channel, display name, or legacy alias without choosing a fallback."""

    if isinstance(value, Edition):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    return _EDITION_BY_CHANNEL.get(text) or _EDITION_BY_ALIAS.get(text.casefold())


def require_edition(value: object) -> Edition:
    """Resolve an edition or fail closed for an unknown identity."""

    edition = find_edition(value)
    if edition is None:
        raise ValueError(f"unknown Bomana edition: {value!r}")
    return edition


def require_public_edition(value: object) -> Edition:
    """Resolve an edition that belongs to the public release closure."""

    edition = require_edition(value)
    if edition.requires_subscription:
        raise ValueError(
            f"subscriber edition {edition.channel!r} must be built from the private closure"
        )
    return edition


def feature_flags_for(value: object) -> MappingProxyType[str, bool]:
    """Return the complete legacy flag projection for one edition."""

    edition = require_edition(value)
    return MappingProxyType(
        {
            name: edition.includes(capability)
            for name, capability in FEATURE_FLAG_CAPABILITIES.items()
        }
    )


def variant_switch_matrix() -> dict[str, dict[str, str]]:
    """Project edition policy into the existing portable-build format."""

    return {
        edition.channel: {
            name: str(enabled) for name, enabled in feature_flags_for(edition).items()
        }
        for edition in EDITIONS
    }


__all__ = [
    "CHANNELS",
    "CHANNEL_ALIASES",
    "CHANNEL_DETAILS",
    "CHANNEL_DISPLAY_NAMES",
    "EDITIONS",
    "Edition",
    "EditionAccess",
    "EditionCapability",
    "FEATURE_FLAG_NAMES",
    "LITE_EDITION",
    "PUBLIC_CHANNELS",
    "STANDARD_EDITION",
    "SUBSCRIPTION_CHANNELS",
    "SUPER_BOMB_EDITION",
    "WEB_COCKPIT_CHANNELS",
    "feature_flags_for",
    "find_edition",
    "require_edition",
    "require_public_edition",
    "variant_switch_matrix",
]
