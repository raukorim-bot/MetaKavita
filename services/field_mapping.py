"""C88 — config → plan de mapping (pur : pas de HTTP)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from scrapers import ScraperRegistry
from services.field_assembly import (
    AUTO_FIELD_PICK_KEYS,
    FIELD_DATA_KEY,
    STAFF_ROLE_KEYS,
)

CASCADE = "CASCADE"

# plan_id UI → (library_type, vague Flexible, clés config)
PLAN_SPECS = (
    ("MANGA", "Manga", None, "FIELD_MAPPING_DEFAULT_MANGA", "FIELD_PROVIDER_MAP_MANGA"),
    ("COMIC", "Comic", None, "FIELD_MAPPING_DEFAULT_COMIC", "FIELD_PROVIDER_MAP_COMIC"),
    ("BOOK", "Book", None, "FIELD_MAPPING_DEFAULT_BOOK", "FIELD_PROVIDER_MAP_BOOK"),
    (
        "COMICFLEXIBLE",
        "ComicFlexible",
        "comic",
        "FIELD_MAPPING_DEFAULT_COMICFLEXIBLE",
        "FIELD_PROVIDER_MAP_COMICFLEXIBLE",
    ),
    (
        "COMICFLEXIBLE_MANGA",
        "ComicFlexible",
        "manga",
        "FIELD_MAPPING_DEFAULT_COMICFLEXIBLE_MANGA",
        "FIELD_PROVIDER_MAP_COMICFLEXIBLE_MANGA",
    ),
)
_WAVE_KEYS = {
    (library_type, wave): (default_key, map_key)
    for _plan_id, library_type, wave, default_key, map_key in PLAN_SPECS
}


@dataclass(frozen=True)
class MappingPlan:
    library_type: str
    wave: Optional[str]
    fetch_library_type: str
    default: str
    overrides: Dict[str, str]
    skip_keys: frozenset
    override_providers: tuple
    mapping_noop: bool


def parse_mapping_default(raw: Any) -> str:
    """CASCADE ou id scraper upper ; sinon CASCADE. Jamais AUTO/NONE."""
    if not isinstance(raw, str) or not raw.strip():
        return CASCADE
    val = raw.strip().upper()
    if val in ("AUTO", "NONE", "", "—", "-"):
        return CASCADE
    return val


def parse_provider_map(
    raw: Any,
    *,
    allowed_fields: Sequence[str],
    allowed_providers: Sequence[str],
) -> Dict[str, str]:
    """Une string par champ ; drop title/format ; drop id inconnu / hors allowed."""
    if not isinstance(raw, dict):
        return {}
    allowed_f = set(allowed_fields)
    allowed_p = {str(p).strip().upper() for p in allowed_providers if p}
    out: Dict[str, str] = {}
    for field, provider in raw.items():
        if field in ("title", "format"):
            continue
        if field not in allowed_f:
            continue
        if not isinstance(provider, str) or not provider.strip():
            continue
        pid = provider.strip().upper()
        if pid in (CASCADE, "AUTO", "NONE", "", "—", "-"):
            continue
        if pid not in allowed_p:
            continue
        out[str(field)] = pid
    return out


def skip_keys_for_overrides(overrides: Optional[dict]) -> frozenset:
    keys = set()
    for field in overrides or {}:
        keys.add(FIELD_DATA_KEY.get(field, field))
        if field == "staff":
            keys.update(STAFF_ROLE_KEYS)
        if field == "localized_name":
            keys.add("titles")
    return frozenset(keys)


def wave_fetch_library_type(library_type: Optional[str], flexible_wave=None) -> str:
    """Comic / Manga / Book. Jamais ComicFlexible."""
    lt = (library_type or "").strip()
    if lt == "ComicFlexible":
        if flexible_wave == "manga":
            return "Manga"
        return "Comic"
    if lt in ("Comic", "Manga", "Book"):
        return lt
    return "Manga"


def _scraper_has_key(scraper, config: dict) -> bool:
    if not getattr(scraper, "needs_api_key", False):
        return True
    return bool((config.get(f"{scraper.id}_API_KEY") or "").strip())


def usable_ids_for_fetch_type(config: dict, fetch_library_type: str) -> List[str]:
    lt = wave_fetch_library_type(fetch_library_type)
    if lt == "ComicFlexible":
        lt = "Comic"
    scrapers = ScraperRegistry.get_by_type(lt) or []
    return [s.id for s in scrapers if _scraper_has_key(s, config or {})]


def dropdown_providers(config: dict, fetch_library_type: str) -> List[Dict[str, str]]:
    """Scrapers Comic **ou** Manga **ou** Book, clé API présente. Jamais ComicFlexible."""
    lt = wave_fetch_library_type(fetch_library_type)
    if lt not in ("Comic", "Manga", "Book"):
        lt = "Manga"
    scrapers = ScraperRegistry.get_by_type(lt) or []
    items: List[Dict[str, str]] = []
    for scraper in scrapers:
        if not _scraper_has_key(scraper, config or {}):
            continue
        name = getattr(scraper, "display_name", None) or scraper.id
        try:
            loc = getattr(scraper, "localized_display_name", None)
        except Exception:
            loc = None
        if loc and not callable(loc):
            name = loc
        items.append({"id": scraper.id, "display_name": str(name)})
    return items


def mapping_should_run(config: dict, *, forced_provider, manual_mode) -> bool:
    if not (config or {}).get("FIELD_MAPPING_ENABLED"):
        return False
    if not (config or {}).get("UI_SHOW_FIELD_MAPPING"):
        return False
    fp = (forced_provider or "").strip().upper()
    if fp and fp not in ("AUTO",):
        return False
    if manual_mode:
        return False
    return True


def url_detect_should_pin_provider(config, *, manual_mode) -> bool:
    """Pin URL → scraper exclusif seulement si le mapping Auto ne tourne pas.

    Sinon `forced_provider` passerait à ANILIST/MAL/… et `mapping_should_run`
    ignorerait la carte — y compris pour un Magic Input URL, qui doit au
    contraire nourrir les overrides (IDs croisés / titre du hit).
    """
    return not mapping_should_run(
        config, forced_provider="AUTO", manual_mode=manual_mode
    )


def map_to_field_picks(plan: MappingPlan) -> Dict[str, List[str]]:
    return {field: [provider] for field, provider in plan.overrides.items()}


def resolve_mapping_plan(
    config: dict,
    library_type: str,
    *,
    flexible_wave=None,
) -> MappingPlan:
    lt = (library_type or "Manga").strip() or "Manga"
    wave = flexible_wave if lt == "ComicFlexible" else None
    if lt == "ComicFlexible" and wave not in ("comic", "manga"):
        wave = "comic"
    fetch_lt = wave_fetch_library_type(lt, wave)
    default_key, map_key = _WAVE_KEYS.get(
        (lt, wave),
        ("FIELD_MAPPING_DEFAULT_MANGA", "FIELD_PROVIDER_MAP_MANGA"),
    )
    allowed = usable_ids_for_fetch_type(config or {}, fetch_lt)
    default = parse_mapping_default((config or {}).get(default_key))
    if default != CASCADE and default not in {p.upper() for p in allowed}:
        default = CASCADE
    overrides = parse_provider_map(
        (config or {}).get(map_key, {}),
        allowed_fields=AUTO_FIELD_PICK_KEYS,
        allowed_providers=allowed,
    )
    if default != CASCADE:
        overrides = {f: p for f, p in overrides.items() if p != default}
    skip_keys = skip_keys_for_overrides(overrides)
    override_providers = tuple(dict.fromkeys(overrides.values()))
    mapping_noop = default == CASCADE and not overrides
    return MappingPlan(
        library_type=lt,
        wave=wave,
        fetch_library_type=fetch_lt,
        default=default,
        overrides=overrides,
        skip_keys=skip_keys,
        override_providers=override_providers,
        mapping_noop=mapping_noop,
    )
