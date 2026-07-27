"""
Mapping Wikidata entity JSON → dict candidat MetaKavita.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

from config_manager import get_max_genres

# Types d'instance (P31 / sous-classes via SPARQL P279*)
TYPE_QIDS: Dict[str, Set[str]] = {
    "Manga": {
        "Q8274",      # manga
        "Q562214",    # manhwa
        "Q754669",    # manhua
        "Q21198342",  # manga series
        "Q184245",    # comic strip (parfois manga)
    },
    "Comic": {
        "Q1004",       # comics
        "Q1760610",    # comic book
        "Q14406742",   # comic book series
        "Q747374",     # graphic novel
        "Q725377",     # bande dessinée
    },
    "Book": {
        "Q7725634",    # literary work
        "Q571",        # book
        "Q47461344",   # written work
        "Q8261",       # novel
        "Q49084",      # short story
    },
}

# Propriétés
P_INSTANCE = "P31"
P_PUB_DATE = "P577"
P_AUTHOR = "P50"
P_ILLUSTRATOR = "P110"
P_CREATOR = "P170"
P_PUBLISHER = "P123"
P_ISBN13 = "P212"
P_ISBN10 = "P957"
P_IMAGE = "P18"
P_ANILIST = "P8729"
P_MAL = "P4087"
P_MU = "P11176"
P_KITSU = "P11494"


def normalize_qid(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = str(raw).strip()
    m = re.search(r"(?:^|[^\d])Q(\d+)\b", text, flags=re.I)
    if m:
        return f"Q{m.group(1)}"
    if text.isdigit():
        return f"Q{text}"
    if re.fullmatch(r"Q\d+", text, flags=re.I):
        return text.upper()
    return None


def commons_file_url(filename: str) -> str:
    """URL stable Special:FilePath (redirige vers upload.wikimedia.org)."""
    name = filename.replace(" ", "_")
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}"


def _claim_values(entity: dict, prop: str) -> List[Any]:
    claims = (entity.get("claims") or {}).get(prop) or []
    out = []
    for claim in claims:
        snak = (claim.get("mainsnak") or {})
        if snak.get("snaktype") != "value":
            continue
        dv = snak.get("datavalue") or {}
        out.append(dv.get("value"))
    return out


def _entity_ids_from_claims(entity: dict, prop: str) -> List[str]:
    ids = []
    for val in _claim_values(entity, prop):
        if isinstance(val, dict) and val.get("id"):
            ids.append(val["id"])
    return ids


def _year_from_time(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        time_str = value.get("time") or ""
    else:
        time_str = str(value or "")
    m = re.match(r"[+-]?(\d{4})", time_str)
    if not m:
        return None
    try:
        year = int(m.group(1))
    except ValueError:
        return None
    return year if 1000 <= year <= 2100 else None


def extract_instance_qids(entity: dict) -> Set[str]:
    return set(_entity_ids_from_claims(entity, P_INSTANCE))


def entity_matches_library_type(entity: dict, library_type: str) -> bool:
    allowed = set()
    if library_type == "ComicFlexible":
        allowed |= TYPE_QIDS["Comic"] | TYPE_QIDS["Manga"]
    else:
        allowed |= TYPE_QIDS.get(library_type, set())
        # Book cascade sometimes hits manga novels — keep Book set only
    if not allowed:
        return True
    return bool(extract_instance_qids(entity) & allowed)


def labels_map(entity: dict) -> Dict[str, str]:
    out = {}
    for lang, blob in (entity.get("labels") or {}).items():
        if isinstance(blob, dict) and blob.get("value"):
            out[lang] = blob["value"]
    return out


def aliases_list(entity: dict) -> List[str]:
    out = []
    for lang, items in (entity.get("aliases") or {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("value"):
                out.append(item["value"])
    return out


def description_text(entity: dict, prefer_langs: Optional[List[str]] = None) -> str:
    prefer = prefer_langs or ["en", "fr", "ja", "de", "es"]
    descs = entity.get("descriptions") or {}
    for lang in prefer:
        blob = descs.get(lang)
        if isinstance(blob, dict) and blob.get("value"):
            return blob["value"]
    for blob in descs.values():
        if isinstance(blob, dict) and blob.get("value"):
            return blob["value"]
    return ""


def pick_title(labels: Dict[str, str], prefer_langs: Optional[List[str]] = None) -> str:
    prefer = prefer_langs or ["en", "fr", "ja", "ja-ro", "de"]
    for lang in prefer:
        if labels.get(lang):
            return labels[lang]
    return next(iter(labels.values()), "")


def build_titles_struct(labels: Dict[str, str]) -> List[Dict[str, str]]:
    titles = []
    seen = set()
    for lang, value in labels.items():
        key = value.strip().lower()
        if not value or key in seen:
            continue
        seen.add(key)
        titles.append({"lang": lang, "value": value})
    return titles


def resolve_cover_url(entity: dict) -> Optional[str]:
    for val in _claim_values(entity, P_IMAGE):
        if isinstance(val, str) and val.strip():
            return commons_file_url(val.strip())
    return None


def first_string_claim(entity: dict, prop: str) -> Optional[str]:
    for val in _claim_values(entity, prop):
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def entity_to_candidate(
    entity: dict,
    label_lookup: Optional[Dict[str, str]] = None,
    library_type: str = "Manga",
) -> Optional[Dict[str, Any]]:
    """
    Convertit un objet entity Wikidata (wbgetentities / EntityData) en candidat MetaKavita.
    `label_lookup` : {Qid: label} pour résoudre auteurs / éditeurs.
    """
    if not entity or entity.get("missing") is not None:
        return None

    qid = entity.get("id") or ""
    labels = labels_map(entity)
    title = pick_title(labels)
    if not title:
        return None

    lookup = label_lookup or {}
    alt = list(dict.fromkeys([title] + list(labels.values()) + aliases_list(entity)))

    years = [_year_from_time(v) for v in _claim_values(entity, P_PUB_DATE)]
    year = next((y for y in years if y), None)

    staff = []
    for prop, role in (
        (P_AUTHOR, "Story"),
        (P_ILLUSTRATOR, "Art"),
        (P_CREATOR, "Story"),
    ):
        for person_qid in _entity_ids_from_claims(entity, prop):
            name = lookup.get(person_qid) or person_qid
            staff.append({"role": role, "node": {"name": {"full": name}}})

    publisher = None
    pub_ids = _entity_ids_from_claims(entity, P_PUBLISHER)
    if pub_ids:
        publisher = lookup.get(pub_ids[0]) or pub_ids[0]

    isbn = first_string_claim(entity, P_ISBN13) or first_string_claim(entity, P_ISBN10)
    if isbn:
        isbn = re.sub(r"[^0-9Xx]", "", isbn)

    anilist_id = first_string_claim(entity, P_ANILIST)
    mal_id = first_string_claim(entity, P_MAL)
    # numeric coerce
    def _as_int(raw):
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    fmt = "manga"
    if library_type == "Comic":
        fmt = "comic"
    elif library_type == "Book":
        fmt = "book"
    elif library_type == "ComicFlexible":
        inst = extract_instance_qids(entity)
        fmt = "comic" if inst & TYPE_QIDS["Comic"] else "manga"

    genres = []
    # Genres Wikidata peu homogènes — on n'invente pas ; type comme hint léger
    if library_type in ("Manga", "ComicFlexible"):
        genres = ["Manga"]
    elif library_type == "Comic":
        genres = ["Comics"]
    elif library_type == "Book":
        genres = ["Book"]

    external_links = [{"url": f"https://www.wikidata.org/wiki/{qid}", "site": "Wikidata"}]
    mu = first_string_claim(entity, P_MU)
    if mu:
        external_links.append({"url": f"https://www.mangaupdates.com/series.html?id={mu}", "site": "MangaUpdates"})
    kitsu = first_string_claim(entity, P_KITSU)
    if kitsu:
        external_links.append({"url": f"https://kitsu.io/manga/{kitsu}", "site": "Kitsu"})

    return {
        "title": title,
        "alternative_titles": alt,
        "titles": build_titles_struct(labels),
        "summary": description_text(entity),
        "cover_url": resolve_cover_url(entity),
        "genres": genres[: get_max_genres()],
        "tags": [],
        "year": year,
        "status": None,
        "staff": staff,
        "characters": [],
        "age_rating": "safe",
        "format": fmt,
        "publisher": publisher,
        "isbn": isbn or None,
        "anilist_id": _as_int(anilist_id),
        "mal_id": _as_int(mal_id),
        "url": f"https://www.wikidata.org/wiki/{qid}",
        "wikidata_id": qid,
        "external_links": external_links,
    }
