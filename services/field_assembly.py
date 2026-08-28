"""
Assembleur de champs (C86 / C88) : constantes + lecture d'une carte MR.

Zéro HTTP, zéro load_config.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence

# Complétion manuelle (C86) : un gagnant par champ, ou une union de listes.
# Les clés UI (`cover`) se distinguent parfois de la clé data (`cover_url`).
FIELD_PICK_KEYS = (
    "title",
    "cover",
    "year",
    "status",
    "format",
    "publisher",
    "age_rating",
    "localized_name",
    "summary",
    "genres",
    "tags",
    "staff",
)
AUTO_FIELD_PICK_KEYS = tuple(k for k in FIELD_PICK_KEYS if k not in ("title", "format"))
LIST_FIELD_PICKS = frozenset({"genres", "tags", "staff"})
FIELD_DATA_KEY = {
    "title": "title",
    "cover": "cover_url",
    "year": "year",
    "status": "status",
    "format": "format",
    "publisher": "publisher",
    "age_rating": "age_rating",
    "localized_name": "localized_name",
    "summary": "summary",
    "genres": "genres",
    "tags": "tags",
    "staff": "staff",
}
STAFF_ROLE_KEYS = (
    "staff",
    "writers",
    "pencillers",
    "colorists",
    "editors",
    "inkers",
    "letterers",
    "cover_artists",
)
IDENTITY_KEYS = (
    "anilist_id",
    "mal_id",
    "mangabaka_id",
    "isbn",
    "url",
    "links",
    "external_links",
)
_USEFUL_CONTENT_KEYS = ("summary", "genres", "cover_url", "staff", "year")


def normalize_field_picks(
    raw: Any,
    *,
    merge_fields: bool,
    known_providers: Optional[Sequence[str]] = None,
) -> Dict[str, List[str]]:
    """Valide le payload UI : clés connues, listes de providers, scalaires à 1."""
    if not isinstance(raw, dict):
        return {}
    allowed = set(known_providers) if known_providers is not None else None
    out: Dict[str, List[str]] = {}
    for key, val in raw.items():
        if key not in FIELD_PICK_KEYS:
            continue
        if isinstance(val, str):
            providers = [val.strip()] if val.strip() else []
        elif isinstance(val, (list, tuple)):
            providers = [str(p).strip() for p in val if p and str(p).strip()]
        else:
            continue
        if allowed is not None:
            providers = [p for p in providers if p in allowed]
        seen: set = set()
        uniq: List[str] = []
        for provider in providers:
            if provider in seen:
                continue
            seen.add(provider)
            uniq.append(provider)
        if not uniq:
            continue
        if not (merge_fields and key in LIST_FIELD_PICKS):
            uniq = uniq[:1]
        out[key] = uniq
    return out


def _card_data(card: dict) -> dict:
    data = card.get("data") if isinstance(card.get("data"), dict) else {}
    return data


def _raw_field(card: dict, data_key: str) -> Any:
    """Valeur brute du blob `data`, sinon le champ top-level de la carte UI."""
    data = _card_data(card)
    if data_key in data and data[data_key] not in (None, "", []):
        return copy.deepcopy(data[data_key])
    top = card.get(data_key)
    if top not in (None, "", []):
        return copy.deepcopy(top)
    return None


def _list_field_items(card: dict, data_key: str) -> list:
    """Items d'une liste à concaténer — aucun dédoublonnage (C86)."""
    data = _card_data(card)
    raw = data.get(data_key)
    if raw in (None, "", False):
        raw = card.get(data_key)
    if raw in (None, "", False):
        return []
    if isinstance(raw, list):
        return copy.deepcopy(raw)
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, str):
        return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    return [copy.deepcopy(raw)]


def _copy_staff_payload(card: dict) -> Dict[str, Any]:
    """Staff brut (edges ou labels) + seaux de rôles si c'est tout ce que la carte a."""
    data = _card_data(card)
    if isinstance(data.get("staff"), list) and data["staff"]:
        return {"staff": copy.deepcopy(data["staff"])}
    out: Dict[str, Any] = {}
    for key in STAFF_ROLE_KEYS:
        if data.get(key):
            out[key] = copy.deepcopy(data[key])
    if out:
        return out
    top = card.get("staff")
    if isinstance(top, list) and top:
        return {"staff": copy.deepcopy(top)}
    return {}


def _staff_from_blob(blob: dict) -> Dict[str, Any]:
    if isinstance(blob.get("staff"), list) and blob["staff"]:
        return {"staff": copy.deepcopy(blob["staff"])}
    out: Dict[str, Any] = {}
    for key in STAFF_ROLE_KEYS:
        if blob.get(key):
            out[key] = copy.deepcopy(blob[key])
    return out


class ProviderFieldSource:
    """Vue normalisée d'un fournisseur. Ni carte UI ni fetch HTTP."""

    def __init__(
        self,
        blob: dict,
        *,
        card: Optional[dict] = None,
        provider_id: Optional[str] = None,
    ):
        self._blob = blob if isinstance(blob, dict) else {}
        self._card = card if isinstance(card, dict) else None
        self.provider_id = provider_id or ""

    def blob(self) -> dict:
        return copy.deepcopy(self._blob)

    def get(self, field_key: str) -> Any:
        """Valeur UI ; staff via staff_payload()."""
        if field_key == "staff":
            payload = self.staff_payload()
            if not payload:
                return None
            if payload.get("staff") not in (None, "", []):
                return copy.deepcopy(payload["staff"])
            return payload
        data_key = FIELD_DATA_KEY.get(field_key, field_key)
        if self._card is not None:
            value = _raw_field(self._card, data_key)
            if value is None and field_key == "localized_name":
                value = self._card.get("localized_name")
            return value
        val = self._blob.get(data_key)
        if val in (None, "", []):
            return None
        return copy.deepcopy(val)

    def list_items(self, field_key: str) -> list:
        data_key = FIELD_DATA_KEY.get(field_key, field_key)
        if self._card is not None:
            return _list_field_items(self._card, data_key)
        raw = self._blob.get(data_key)
        if raw in (None, "", False):
            return []
        if isinstance(raw, list):
            return copy.deepcopy(raw)
        if isinstance(raw, tuple):
            return list(raw)
        if isinstance(raw, str):
            return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
        return [copy.deepcopy(raw)]

    def staff_payload(self) -> dict:
        if self._card is not None:
            return _copy_staff_payload(self._card)
        return _staff_from_blob(self._blob)


def source_from_card(card: dict) -> ProviderFieldSource:
    """Vue `data` + fallback top-level (comme `_raw_field`)."""
    if not isinstance(card, dict):
        card = {}
    provider_id = card.get("provider")
    return ProviderFieldSource(
        _card_data(card) or {},
        card=card,
        provider_id=str(provider_id) if provider_id else "",
    )


def source_from_scraper_data(
    data: dict, *, provider_id: Optional[str] = None
) -> ProviderFieldSource:
    """Vue blob scraper (pas de fallback carte)."""
    blob = data if isinstance(data, dict) else {}
    return ProviderFieldSource(blob, card=None, provider_id=provider_id or "")


def assemble_field_picks(
    base: Optional[ProviderFieldSource],
    by_provider: Dict[str, ProviderFieldSource],
    field_picks: Any,
    *,
    merge_fields: bool = False,
    base_provider: Optional[str] = None,
) -> Optional[dict]:
    """Un champ = une source. `None` si la base est inconnue."""
    if base is None:
        return None
    master = base.blob()
    if not isinstance(master, dict):
        master = {}
    if not base_provider:
        base_provider = base.provider_id or master.get("_provider_used") or ""
    master["_provider_used"] = base_provider

    picks = normalize_field_picks(
        field_picks,
        merge_fields=merge_fields,
        known_providers=list(by_provider.keys()),
    )
    fusion: List[str] = []

    def _note(providers: Sequence[str]) -> None:
        for provider in providers:
            if provider and provider != base_provider and provider not in fusion:
                fusion.append(provider)

    for field, providers in picks.items():
        sources = [by_provider[p] for p in providers if p in by_provider]
        if not sources:
            continue
        data_key = FIELD_DATA_KEY[field]
        if field == "staff":
            if merge_fields and len(sources) > 1:
                combined: list = []
                for src in sources:
                    payload = src.staff_payload()
                    combined.extend(payload.get("staff") or src.list_items("staff"))
                for key in STAFF_ROLE_KEYS:
                    master.pop(key, None)
                master["staff"] = combined
            else:
                payload = sources[0].staff_payload()
                if not payload:
                    continue
                for key in STAFF_ROLE_KEYS:
                    master.pop(key, None)
                master.update(payload)
            _note(providers)
            continue
        if field in LIST_FIELD_PICKS and merge_fields and len(sources) > 1:
            combined = []
            for src in sources:
                combined.extend(src.list_items(field))
            master[data_key] = combined
            _note(providers)
            continue
        value = sources[0].get(field)
        if value is None:
            continue
        master[data_key] = value
        if field == "localized_name":
            titles = sources[0].get("titles")
            if titles is not None:
                master["titles"] = titles
        _note(providers)

    master["_fusion_providers"] = fusion
    return master


def apply_field_picks(
    base_provider: str,
    by_provider: Dict[str, dict],
    field_picks: Any,
    merge_fields: bool = False,
) -> Optional[dict]:
    """
    Assemble un payload à partir des cases par champ (complétion manuelle).

    Le master est la base. Chaque champ listé dans `field_picks` est remplacé
    par le gagnant (scalaire / exclusif) ou concaténé (listes + merge_fields).
    Un champ absent des picks reste celui du master. Pas de hole-fill Source.
    """
    if base_provider not in by_provider:
        return None
    sources = {
        pid: source_from_card(card)
        for pid, card in by_provider.items()
        if isinstance(card, dict)
    }
    return assemble_field_picks(
        sources.get(base_provider),
        sources,
        field_picks,
        merge_fields=merge_fields,
        base_provider=base_provider,
    )


def _identity_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _blob_useful(blob: Any) -> bool:
    if not isinstance(blob, dict):
        return False
    return any(blob.get(key) not in (None, "", [], {}) for key in _USEFUL_CONTENT_KEYS)


def absorb_identity(target: dict, blobs) -> dict:
    """Copie IDENTITY_KEYS seulement si vides sur `target`. Jamais le contenu."""
    if not isinstance(target, dict):
        return target
    for blob in blobs or []:
        if not isinstance(blob, dict):
            continue
        for key in IDENTITY_KEYS:
            if not _identity_empty(target.get(key)):
                continue
            incoming = blob.get(key)
            if _identity_empty(incoming):
                continue
            target[key] = copy.deepcopy(incoming)
    return target


def pick_assembly_base(
    default_id: Optional[str],
    default_blob: Optional[dict],
    by_provider: Optional[dict],
    override_order,
) -> Optional[ProviderFieldSource]:
    """Default s'il est utile, sinon premier override utile. `None` si tout vide."""
    if _blob_useful(default_blob):
        return source_from_scraper_data(default_blob, provider_id=default_id or "")
    for pid in override_order or []:
        item = (by_provider or {}).get(pid)
        if isinstance(item, ProviderFieldSource):
            if _blob_useful(item.blob()):
                return item
            continue
        if _blob_useful(item):
            return source_from_scraper_data(item, provider_id=pid)
    return None
