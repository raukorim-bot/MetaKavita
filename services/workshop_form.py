"""Champs de l'atelier : fiche Kavita série + extras chapitre, pour le formulaire.

Les deux cartes n'exposaient que titre alternatif / résumé (série) et
titre / ISBN / date / résumé (tome). L'atelier montre ce que Kavita
détient déjà. L'envoi écrase les champs remplis ; une valeur proposée vide
n'est jamais écrite.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.kavita_chapter_payload import PEOPLE_KEYS

# Champ formulaire -> (clé DTO, verrou, kind)
# kind : text | textarea | csv | select
SERIES_SPECS: Tuple[Tuple[str, str, str, str], ...] = (
    ("localizedName", "localizedName", "localizedNameLocked", "text"),
    ("summary", "summary", "summaryLocked", "textarea"),
    ("releaseYear", "releaseYear", "releaseYearLocked", "text"),
    ("publicationStatus", "publicationStatus", "publicationStatusLocked", "select"),
    ("ageRating", "ageRating", "ageRatingLocked", "select"),
    ("publishers", "publishers", "publisherLocked", "csv"),
    ("genres", "genres", "genresLocked", "csv"),
    ("tags", "tags", "tagsLocked", "csv"),
    ("writers", "writers", "writerLocked", "csv"),
    ("pencillers", "pencillers", "pencillerLocked", "csv"),
    ("coverArtists", "coverArtists", "coverArtistLocked", "csv"),
    ("colorists", "colorists", "coloristLocked", "csv"),
    ("inkers", "inkers", "inkerLocked", "csv"),
    ("letterers", "letterers", "lettererLocked", "csv"),
    ("editors", "editors", "editorLocked", "csv"),
    ("translators", "translators", "translatorLocked", "csv"),
    ("characters", "characters", "characterLocked", "csv"),
    ("imprints", "imprints", "imprintLocked", "csv"),
    ("teams", "teams", "teamLocked", "csv"),
    ("locations", "locations", "locationLocked", "csv"),
    ("webLinks", "webLinks", "", "text"),
    ("language", "language", "languageLocked", "text"),
)

VOLUME_EXTRA_SPECS: Tuple[Tuple[str, str, str, str], ...] = (
    ("language", "language", "languageLocked", "text"),
    ("webLinks", "webLinks", "", "text"),
    ("ageRating", "ageRating", "ageRatingLocked", "select"),
    ("genres", "genres", "genresLocked", "csv"),
    ("tags", "tags", "tagsLocked", "csv"),
    ("writers", "writers", "writerLocked", "csv"),
    ("pencillers", "pencillers", "pencillerLocked", "csv"),
    ("coverArtists", "coverArtists", "coverArtistLocked", "csv"),
    ("translators", "translators", "translatorLocked", "csv"),
)

STATUS_OPTIONS = (
    (0, "workshop_status_releasing"),
    (1, "workshop_status_hiatus"),
    (2, "workshop_status_finished"),
    (3, "workshop_status_cancelled"),
)

AGE_OPTIONS = (
    (0, "workshop_age_unknown"),
    (1, "workshop_age_pending"),
    (2, "workshop_age_early"),
    (3, "workshop_age_everyone"),
    (4, "workshop_age_g"),
    (5, "workshop_age_everyone10"),
    (6, "workshop_age_pg"),
    (7, "workshop_age_kids"),
    (8, "workshop_age_teen"),
    (9, "workshop_age_ma15"),
    (10, "workshop_age_mature"),
    (11, "workshop_age_m"),
    (12, "workshop_age_r18"),
    (13, "workshop_age_adults"),
    (14, "workshop_age_x18"),
)

_PEOPLE_SET = frozenset(PEOPLE_KEYS)
_TITLED_SET = frozenset({"genres", "tags"})
_WIDE = frozenset({"summary", "webLinks", "genres", "tags"})
_MID = frozenset({
    "localizedName",
    "publishers",
    "writers",
    "pencillers",
    "coverArtists",
    "colorists",
    "inkers",
    "letterers",
    "editors",
    "translators",
    "characters",
    "imprints",
    "teams",
    "locations",
})
SERIES_PRIMARY = frozenset({
    "localizedName",
    "summary",
    "releaseYear",
    "publicationStatus",
    "ageRating",
    "publishers",
    "genres",
    "tags",
    "writers",
    "pencillers",
})


def split_csv(text: Any) -> List[str]:
    return [p.strip() for p in str(text or "").replace(";", ",").split(",") if p.strip()]


def join_csv(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    names = []
    for item in raw or []:
        if isinstance(item, dict):
            names.append(str(item.get("name") or item.get("title") or item.get("Name") or item.get("Title") or "").strip())
        else:
            names.append(str(item or "").strip())
    return ", ".join(n for n in names if n)


def unwrap_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, list):
        return raw[0] if raw and isinstance(raw[0], dict) else {}
    return raw if isinstance(raw, dict) else {}


def _field_value(source: dict, dto_key: str, kind: str) -> str:
    raw = source.get(dto_key)
    if kind == "csv":
        return join_csv(raw)
    if kind == "select":
        if dto_key == "ageRating" and raw in (None, "", -1, "-1"):
            return "0"
        if raw in (None, ""):
            return "0"
        return str(int(raw)) if str(raw).lstrip("-").isdigit() else "0"
    if dto_key == "releaseYear":
        try:
            year = int(raw)
        except (TypeError, ValueError):
            return ""
        return str(year) if year else ""
    return str(raw or "").strip()


def lookups(t: dict) -> Dict[str, List[dict]]:
    def opts(pairs):
        return [{"value": str(v), "label": t.get(k, str(v))} for v, k in pairs]

    return {
        "publicationStatus": opts(STATUS_OPTIONS),
        "ageRating": opts(AGE_OPTIONS),
    }


def series_form(series: dict, metadata: dict, t: dict) -> List[Dict[str, Any]]:
    """Champs éditables de la fiche série, dans l'ordre d'affichage."""
    series = series if isinstance(series, dict) else {}
    meta = unwrap_metadata(metadata)
    out = []
    for key, dto_key, lock, kind in SERIES_SPECS:
        source = series if key == "localizedName" else meta
        wide = key in _WIDE
        size = "wide" if wide else ("mid" if key in _MID else "short")
        item = {
            "key": key,
            "label": t.get(f"workshop_series_{key}", key),
            "value": _field_value(source, dto_key, kind),
            "locked": bool(source.get(lock)),
            "kind": kind,
            "wide": wide,
            "size": size,
            "group": "primary" if key in SERIES_PRIMARY else "more",
        }
        if kind == "textarea":
            item["rows"] = 2
        if kind == "select":
            item["options"] = lookups(t).get(key, [])
        out.append(item)
    return out


def chapter_extra_inscribed(chapter: Optional[dict]) -> Dict[str, Any]:
    """Champs chapitre au-delà de titre / ISBN / date / résumé."""
    chap = chapter if isinstance(chapter, dict) else {}
    out: Dict[str, Any] = {}
    for key, dto_key, lock, kind in VOLUME_EXTRA_SPECS:
        out[key] = _field_value(chap, dto_key, kind)
        out[f"{key}_locked"] = bool(chap.get(lock))
    return out


def _should_write(current, proposed, *, force: bool, locked: bool) -> bool:
    if proposed is None:
        return False
    new = str(proposed).strip()
    old = str(current or "").strip()
    if not new or new == old:
        return False
    if locked and not force:
        return False
    if old and not force:
        return False
    return True


def apply_series_edits(
    metadata: dict,
    series: dict,
    form: Sequence[dict],
    edits: dict,
    *,
    force: bool = False,
) -> Tuple[dict, List[str], Optional[str]]:
    """Applique le comblement sur une copie des métadonnées. Rend (meta, écrits, localizedName|None)."""
    meta = dict(unwrap_metadata(metadata))
    by_key = {f["key"]: f for f in form}
    written: List[str] = []
    localized = None
    sid = series.get("id") if isinstance(series, dict) else None
    if sid:
        meta["seriesId"] = int(sid)
    for key, dto_key, lock, kind in SERIES_SPECS:
        field = by_key.get(key) or {}
        proposed = (edits or {}).get(key)
        current_val = field.get("value")
        if key == "ageRating":
            if str(proposed or "").strip() in ("0", "-1"):
                continue
            if str(current_val or "").strip() in ("0", "-1"):
                current_val = ""
        if not _should_write(current_val, proposed, force=force, locked=bool(field.get("locked"))):
            continue
        if key == "localizedName":
            localized = str(proposed).strip()
            written.append(key)
            continue
        if kind == "csv":
            names = split_csv(proposed)
            if not names:
                continue
            if dto_key in _TITLED_SET:
                meta[dto_key] = [{"id": 0, "title": n} for n in names]
            else:
                meta[dto_key] = [{"id": 0, "name": n} for n in names]
        elif key == "releaseYear":
            try:
                year = int(str(proposed).strip())
            except (TypeError, ValueError):
                continue
            if not 1000 <= year <= 2100:
                continue
            meta["releaseYear"] = year
        elif kind == "select":
            try:
                meta[dto_key] = int(str(proposed).strip())
            except (TypeError, ValueError):
                continue
        else:
            meta[dto_key] = str(proposed).strip()
        if lock:
            meta[lock] = True
        written.append(key)
    return meta, written, localized


def form_chapter_changes(edits: dict, current: dict, *, force: bool = False) -> Dict[str, Any]:
    """Extras atelier (langue, liens, âge, genres, tags, crédits) pour `build_update_chapter_dto`."""
    chap = current if isinstance(current, dict) else {}
    out: Dict[str, Any] = {}
    people: Dict[str, List[str]] = {}
    for key, dto_key, lock, kind in VOLUME_EXTRA_SPECS:
        proposed = (edits or {}).get(key)
        current_val = _field_value(chap, dto_key, kind)
        if key == "ageRating":
            if str(proposed or "").strip() in ("0", "-1"):
                continue
            if str(current_val or "").strip() in ("0", "-1"):
                current_val = ""
        if not _should_write(current_val, proposed, force=force, locked=bool(chap.get(lock))):
            continue
        if dto_key in _PEOPLE_SET:
            names = split_csv(proposed)
            if not names:
                continue
            people[dto_key] = names
            continue
        if kind == "csv":
            names = split_csv(proposed)
            if not names:
                continue
            out[dto_key] = names
        elif kind == "select":
            try:
                out[dto_key] = int(str(proposed).strip())
            except (TypeError, ValueError):
                continue
        else:
            out[dto_key] = str(proposed).strip()
    if people:
        out["people"] = people
    return out


# Jetons Manual Review (`ALL_TARGETED_FIELDS`) → clés du formulaire atelier.
_ACTIVE_TO_SERIES_KEYS = {
    "summary": ("summary",),
    "year": ("releaseYear",),
    "status": ("publicationStatus",),
    "genres": ("genres",),
    "tags": ("tags", "characters"),
    "publisher": ("publishers", "imprints"),
    "age": ("ageRating",),
    "staff": (
        "writers",
        "pencillers",
        "coverArtists",
        "colorists",
        "inkers",
        "letterers",
        "editors",
        "translators",
        "teams",
        "locations",
    ),
    "alt_titles": ("localizedName",),
    "weblinks": ("webLinks",),
    "language": ("language",),
}


def series_edits_from_built(built: dict, active_fields) -> Tuple[Dict[str, str], str]:
    """Mappe un `build_kavita_payload` vers les inputs de la fiche atelier.

    Une valeur vide n'est pas renvoyée : le formulaire garde ce que Kavita
    montrait déjà, et l'envoi n'écrit jamais un vide.
    """
    meta = unwrap_metadata((built or {}).get("metadata"))
    allowed = set()
    for token, keys in _ACTIVE_TO_SERIES_KEYS.items():
        if token in (active_fields or []):
            allowed.update(keys)
    edits: Dict[str, str] = {}
    for key, dto_key, _lock, kind in SERIES_SPECS:
        if key not in allowed:
            continue
        if key == "localizedName":
            val = str((built or {}).get("localized_name") or "").strip()
        else:
            val = _field_value(meta, dto_key, kind)
        if key == "ageRating" and str(val).strip() in ("0", "-1"):
            continue
        if not str(val or "").strip():
            continue
        edits[key] = val
    cover = ""
    if "cover" in (active_fields or []):
        cover = str((built or {}).get("cover_url") or "").strip()
    return edits, cover
