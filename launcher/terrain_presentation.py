"""User-facing grouping and selection projection for terrain maps."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from launcher.terrain_map_names import terrain_map_localized_name


@dataclass(frozen=True, slots=True)
class TerrainMapCategory:
    category_id: str
    label: str
    map_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainCategorySelection:
    category_id: str
    label: str
    map_ids: tuple[str, ...]
    selected_count: int
    selection_state: str


_CATEGORY_DEFINITIONS = (
    ("air", "空战地图"),
    ("combined", "空地联合"),
    ("ground", "陆战地图"),
    ("naval", "海战地图"),
    ("unclassified", "旧版/未标注"),
)

# Versioned fallback for legacy catalogs that do not carry category metadata.
# The rules and exceptions reproduce the 2026-08-04 game-data classification
# audit for all 163 known maps. Unknown identifiers deliberately remain
# unclassified instead of being guessed into the old default-air bucket.
_CATEGORY_PREFIX_RULES = (
    ("avg_", "ground"),
    ("avn_", "naval"),
    ("air_", "air"),
    ("arcade_", "air"),
    ("hvg_", "ground"),
    ("hangar_field", "ground"),
)
_CATEGORY_OVERRIDES = {
    "air_ladoga": "unclassified",
    "arcade_asia_4roads": "unclassified",
    "arcade_tabletop_mountain": "unclassified",
    "avg_egypt_sinai": "combined",
    "avg_northern_india": "combined",
    "avn_ice_port": "ground",
    "bulge": "unclassified",
    "dover_strait": "naval",
    "firing_range": "ground",
    "guadalcanal": "naval",
    "hangar_field_halloween": "unclassified",
    "hangar_field_winter": "unclassified",
    "korsun": "unclassified",
    "malta": "naval",
    "midway": "naval",
    "mozdok_winter": "unclassified",
    "port_moresby": "naval",
    "saipan": "naval",
    "stalingrad_w": "unclassified",
    "water": "unclassified",
}
_LEGACY_AIR_MAP_IDS = frozenset(
    {
        "berlin",
        "britain",
        "caribbean_islands",
        "guam",
        "honolulu",
        "hurtgen",
        "iwo_jima",
        "khalkhin_gol",
        "korea",
        "krymsk",
        "kursk",
        "moscow",
        "mozdok",
        "norway",
        "peleliu",
        "ruhr",
        "sector_montmedy",
        "sicily",
        "spain",
        "stalingrad",
        "tunisia",
        "wake_island",
        "zhengzhou",
    }
)

# Bomana is primarily used for full-real air sorties.  Recommend the air and
# air-ground groups on the first visit, but keep the recommendation in the
# presentation module so it never becomes an implicit Terrain Map Selection.
_RECOMMENDED_CATEGORY_IDS = frozenset({"air", "combined"})


def terrain_map_category_id(map_id: object) -> str:
    value = str(map_id or "").strip()
    if value in _CATEGORY_OVERRIDES:
        return _CATEGORY_OVERRIDES[value]
    if value in _LEGACY_AIR_MAP_IDS:
        return "air"
    for prefix, category_id in _CATEGORY_PREFIX_RULES:
        if value.startswith(prefix):
            return category_id
    return "unclassified"


def terrain_map_display_name(map_id: object) -> str:
    value = str(map_id or "").strip()
    for prefix in ("air_", "arcade_", "avg_", "avn_", "hvg_"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value.replace("_", " ").title()


def terrain_map_localized_display_name(
    map_id: object,
    catalog_display_name: object = "",
) -> str:
    """Prefer the signed catalog name, with bundled and ID fallbacks for old catalogs."""

    if isinstance(catalog_display_name, str) and catalog_display_name.strip():
        return catalog_display_name.strip()
    return terrain_map_localized_name(map_id) or terrain_map_display_name(map_id)


def group_terrain_maps(map_ids: Iterable[object]) -> tuple[TerrainMapCategory, ...]:
    unique_ids = {value for raw in map_ids if (value := str(raw or "").strip())}
    grouped: dict[str, list[str]] = {
        category_id: [] for category_id, _label in _CATEGORY_DEFINITIONS
    }
    for map_id in unique_ids:
        grouped[terrain_map_category_id(map_id)].append(map_id)

    categories: list[TerrainMapCategory] = []
    for category_id, label in _CATEGORY_DEFINITIONS:
        values = grouped[category_id]
        if not values:
            continue
        values.sort(
            key=lambda value: (
                terrain_map_localized_display_name(value).casefold(),
                value,
            )
        )
        categories.append(
            TerrainMapCategory(
                category_id=category_id,
                label=label,
                map_ids=tuple(values),
            )
        )
    return tuple(categories)


def recommended_terrain_category_ids(
    categories: Iterable[TerrainMapCategory],
) -> tuple[str, ...]:
    """Return the stable categories recommended for a first-time user."""

    return tuple(
        category.category_id
        for category in categories
        if category.category_id in _RECOMMENDED_CATEGORY_IDS
    )


def recommended_terrain_map_ids(
    categories: Iterable[TerrainMapCategory],
) -> tuple[str, ...]:
    """Return first-visit recommendations without selecting every map."""

    category_values = tuple(categories)
    recommended = set(recommended_terrain_category_ids(category_values))
    return tuple(
        sorted(
            map_id
            for category in category_values
            if category.category_id in recommended
            for map_id in category.map_ids
        )
    )


def initial_terrain_map_selection(
    categories: Iterable[TerrainMapCategory],
    selected_map_ids: Iterable[object],
    *,
    selection_initialized: bool,
) -> tuple[str, ...]:
    """Project persisted selection or a first-visit recommendation.

    An initialized empty selection is intentional and must remain empty.  This
    distinction lets the UI recommend useful groups once without undoing a
    user's explicit "清空" choice on every later open.
    """

    selected = {value for raw in selected_map_ids if (value := str(raw or "").strip())}
    if not selection_initialized:
        selected.update(recommended_terrain_map_ids(categories))
    return tuple(sorted(selected))


def project_category_selection(
    categories: Iterable[TerrainMapCategory],
    selected_map_ids: Iterable[object],
) -> tuple[TerrainCategorySelection, ...]:
    selected = frozenset(str(value or "").strip() for value in selected_map_ids)
    projected: list[TerrainCategorySelection] = []
    for category in categories:
        selected_count = sum(map_id in selected for map_id in category.map_ids)
        if selected_count == 0:
            state = "none"
        elif selected_count == len(category.map_ids):
            state = "all"
        else:
            state = "partial"
        projected.append(
            TerrainCategorySelection(
                category_id=category.category_id,
                label=category.label,
                map_ids=category.map_ids,
                selected_count=selected_count,
                selection_state=state,
            )
        )
    return tuple(projected)


def toggle_category_selection(
    selected_map_ids: Iterable[object],
    category_map_ids: Iterable[object],
) -> tuple[str, ...]:
    selected = {value for raw in selected_map_ids if (value := str(raw or "").strip())}
    category = {value for raw in category_map_ids if (value := str(raw or "").strip())}
    if category and category.issubset(selected):
        selected.difference_update(category)
    else:
        selected.update(category)
    return tuple(sorted(selected))


__all__ = [
    "TerrainCategorySelection",
    "TerrainMapCategory",
    "group_terrain_maps",
    "initial_terrain_map_selection",
    "project_category_selection",
    "recommended_terrain_category_ids",
    "recommended_terrain_map_ids",
    "terrain_map_category_id",
    "terrain_map_display_name",
    "terrain_map_localized_display_name",
    "toggle_category_selection",
]
