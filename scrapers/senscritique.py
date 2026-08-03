"""SensCritique — métadonnées via Apollo GraphQL (pas d'API key)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    extract_volume_number,
    get_match_accept_threshold,
    score_candidate,
)

_APOLLO = "https://apollo.senscritique.com/"
_BASE = "https://www.senscritique.com"
_NON_ISBN = re.compile(r"[^0-9Xx]")

# Préfixes d'URL SC → type MetaKavita
_BOOK_PREFIXES = ("/livre/",)
_COMIC_PREFIXES = ("/bd/", "/manga/")
_REJECT_PREFIXES = (
    "/film/",
    "/serie/",
    "/jeuvideo/",
    "/album/",
    "/morceau/",
    "/spectacle/",
)

_SEARCH_QUERY = """
query SearchProductExplorer($query: String, $offset: Int, $limit: Int, $sortBy: SearchProductExplorerSort) {
  searchProductExplorer(
    query: $query
    filters: []
    sortBy: $sortBy
    offset: $offset
    limit: $limit
  ) {
    items {
      id
      title
      originalTitle
      category
      url
      yearOfProduction
      rating
      medias { picture }
      genresInfos { label }
      authors { name }
      directors { name }
    }
  }
}
"""

_PRODUCT_QUERY = """
query Product($id: Int!) {
  product(id: $id) {
    id
    title
    originalTitle
    category
    url
    yearOfProduction
    dateRelease
    frenchReleaseDate
    rating
    synopsis
    isbn
    alternativeTitles
    medias { picture }
    genresInfos { label }
    countries { name }
    authors { name }
    directors { name }
    publishers { name }
  }
}
"""


def _normalize_isbn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = _NON_ISBN.sub("", str(raw)).upper()
    if len(cleaned) in (10, 13):
        return cleaned
    return None


def _upgrade_cover(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    # /media/.../300/file.jpg → 1000 (testé live)
    return re.sub(r"/(\d{2,4})/([^/]+)$", r"/1000/\2", url, count=1)


def _path_from_url(url: Optional[str]) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return urlparse(url).path or ""
    return url if url.startswith("/") else f"/{url}"


def _media_kind(url: Optional[str], category: Optional[str] = None) -> Optional[str]:
    """Retourne 'Book', 'Comic' ou None selon l'URL / catégorie SC.

    None = hors scope MetaKavita (film, série, album…) ou indéterminé.
    """
    path = _path_from_url(url).lower()
    for p in _REJECT_PREFIXES:
        if path.startswith(p):
            return None
    for p in _BOOK_PREFIXES:
        if path.startswith(p):
            return "Book"
    for p in _COMIC_PREFIXES:
        if path.startswith(p):
            return "Comic"
    cat = (category or "").lower()
    if any(x in cat for x in ("film", "série", "serie", "téléfilm", "telefilm", "album", "musique", "jeu")):
        return None
    if "bd" in cat or "manga" in cat or "comics" in cat:
        return "Comic"
    if "livre" in cat or cat == "book":
        return "Book"
    return None


def _allowed_kinds(library_type: str) -> Set[str]:
    if library_type == "ComicFlexible":
        return {"Book", "Comic"}
    if library_type == "Comic":
        return {"Comic"}
    if library_type == "Book":
        return {"Book"}
    # Manga / autres : on ne force rien de SC (SC manga est rare / mélangé films)
    return set()


def _rank_hits_for_query(hits: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Préfère tome 1 / titres ancrés sur la requête (ex. Tintin → Soviets, pas Tibet)."""
    q = (query or "").strip().casefold()
    if not q or not hits:
        return hits

    def key(hit: Dict[str, Any]) -> tuple:
        title = (hit.get("title") or "").strip()
        t = title.casefold()
        vol = extract_volume_number(title)
        # tome 1 d'abord, puis sans tome, puis tomes croissants
        if vol == 1:
            vol_rank = 0
        elif vol is None:
            vol_rank = 1
        else:
            vol_rank = 100 + vol
        starts = 0 if t.startswith(q) else 1
        contains = 0 if q in t else 1
        return (vol_rank, starts, contains, len(t))

    return sorted(hits, key=key)


def _franchise_score_boost(
    candidate: Dict[str, Any], query: str, base_score: float
) -> float:
    """Boost si la requête (marque / héros) figure dans le titre et que c'est un tome 1."""
    q = (query or "").strip().casefold()
    title = (candidate.get("title") or "").strip()
    if not q or not title or len(q) < 3:
        return base_score
    t = title.casefold()
    if q not in t:
        return base_score
    vol = extract_volume_number(title)
    # Requête sans numéro + candidat tome 1 (ou série sans tome) → ancrage franchise
    if extract_volume_number(query) is None and (vol == 1 or vol is None):
        return min(1.0, max(base_score, 0.72 if vol == 1 else 0.65))
    return base_score


def _extract_numeric_id(value: str) -> Optional[int]:
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    # /livre/slug/97412 ou livre/slug/97412
    m = re.search(r"/(?:livre|bd|manga)/[^/]+/(\d+)/?$", value)
    if m:
        return int(m.group(1))
    m = re.search(r"/(\d+)/?$", value.rstrip("/"))
    if m and ("senscritique.com" in value or value.startswith("/")):
        return int(m.group(1))
    return None


class SensCritiqueScraper(BaseScraper):
    id = "SENSCRITIQUE"
    is_core = True
    display_name = "SensCritique (FR)"
    supported_types = {"Book", "Comic"}
    rate_limit = 2.5  # GraphQL front — anti-ban IP
    proxy_domains = [
        "senscritique.com",
        "www.senscritique.com",
        "media.senscritique.com",
        "apollo.senscritique.com",
    ]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "direct_id": "🎯 [SensCritique] Requête directe id={0}",
            "search_isbn": "🔎 [SensCritique] Recherche (ISBN {0})…",
            "matched_isbn": "🎯 [SensCritique] Match ISBN ({0}) : '{1}'",
            "search_title": "🔍 [SensCritique] Recherche pour '{0}'…",
            "no_match": "⚠️ [SensCritique] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [SensCritique] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [SensCritique] Erreur : {0}",
            "covers_err": "❌ [Covers] Erreur SensCritique : {0}",
            "wrong_type": "⚠️ [SensCritique] Résultat hors type bibliothèque ({0})",
        },
        "en": {
            "direct_id": "🎯 [SensCritique] Direct request id={0}",
            "search_isbn": "🔎 [SensCritique] Search (ISBN {0})…",
            "matched_isbn": "🎯 [SensCritique] ISBN match ({0}): '{1}'",
            "search_title": "🔍 [SensCritique] Searching for '{0}'…",
            "no_match": "⚠️ [SensCritique] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [SensCritique] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [SensCritique] Error: {0}",
            "covers_err": "❌ [Covers] SensCritique error: {0}",
            "wrong_type": "⚠️ [SensCritique] Result outside library type ({0})",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        if "senscritique.com" not in url and not re.match(
            r"^/(?:livre|bd|manga)/", url
        ):
            if url.strip().isdigit():
                return url.strip()
            return None
        pid = _extract_numeric_id(url)
        return str(pid) if pid is not None else None

    def fetch(
        self,
        query: str,
        library_type: str = "Book",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        allowed = _allowed_kinds(library_type)
        if not allowed and not is_id:
            return None

        session = requests.Session()
        try:
            if is_id:
                pid = _extract_numeric_id(query) or (
                    int(query) if str(query).isdigit() else None
                )
                if pid is None:
                    return None
                logging.info(self.t("direct_id").format(pid))
                candidate = self._fetch_product(
                    session, pid, library_type, enforce_type=False
                )
                if candidate:
                    candidate.pop("_isbns", None)
                    return attach_match_score(candidate, 1.0)
                return None

            existing_isbn = _normalize_isbn(
                (existing_metadata or {}).get("isbn") if existing_metadata else None
            )
            cleaned = clean_title(query, library_type=library_type)
            if not cleaned and not existing_isbn:
                return None

            # 1) Passage ISBN : la search SC par EAN seul est souvent vide →
            #    on cherche le titre puis on matche sur product.isbn[]
            search_term = cleaned or existing_isbn
            if existing_isbn:
                logging.info(self.t("search_isbn").format(existing_isbn))
            else:
                logging.info(self.t("search_title").format(cleaned))

            hits = self._search(session, search_term, limit=12)
            hits = [
                h
                for h in hits
                if _media_kind(h.get("url"), h.get("category")) in allowed
            ]
            if not hits and existing_isbn and cleaned and cleaned != existing_isbn:
                hits = self._search(session, cleaned, limit=12)
                hits = [
                    h
                    for h in hits
                    if _media_kind(h.get("url"), h.get("category")) in allowed
                ]

            # BD : la search SC mélange films/jeux et omet souvent le tome 1
            # pour une franchise courte (« Tintin ») → 2e passe « {q} tome 1 ».
            if (
                library_type == "Comic"
                and cleaned
                and extract_volume_number(cleaned) is None
            ):
                vol1_hits = self._search(session, f"{cleaned} tome 1", limit=10)
                vol1_hits = [
                    h
                    for h in vol1_hits
                    if _media_kind(h.get("url"), h.get("category")) in allowed
                ]
                seen = {h.get("id") for h in hits}
                for h in vol1_hits:
                    if h.get("id") not in seen:
                        hits.append(h)
                        seen.add(h.get("id"))

            if not hits:
                return None

            hits = _rank_hits_for_query(hits, cleaned or search_term)

            best_match = None
            best_score = -1.0

            for hit in hits[:8]:
                pid = hit.get("id")
                if not pid:
                    continue
                candidate = self._fetch_product(session, int(pid), library_type)
                if not candidate:
                    # Fallback depuis le hit search (moins riche)
                    candidate = self._candidate_from_search_hit(hit, library_type)
                if not candidate or not candidate.get("title"):
                    continue

                cand_isbns = candidate.pop("_isbns", None) or []
                if existing_isbn and existing_isbn in cand_isbns:
                    logging.info(
                        self.t("matched_isbn").format(
                            existing_isbn, candidate.get("title")
                        )
                    )
                    return attach_match_score(candidate, 1.0)

                score = score_candidate(
                    candidate, cleaned or search_term, existing_metadata
                )
                score = _franchise_score_boost(
                    candidate, cleaned or search_term, score
                )
                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < get_match_accept_threshold():
                logging.warning(
                    self.t("no_match").format(
                        cleaned or search_term, int(max(best_score, 0) * 100)
                    )
                )
                return None

            logging.info(
                self.t("matched").format(best_match.get("title"), int(best_score * 100))
            )
            return attach_match_score(best_match, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_covers(
        self, query: str, library_type: str = "Book"
    ) -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        allowed = _allowed_kinds(library_type)
        if not allowed:
            return covers
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return covers

        session = requests.Session()
        try:
            hits = self._search(session, cleaned, limit=12)
            hits = [
                h
                for h in hits
                if _media_kind(h.get("url"), h.get("category")) in allowed
            ]
            if library_type == "Comic" and extract_volume_number(cleaned) is None:
                vol1_hits = self._search(session, f"{cleaned} tome 1", limit=8)
                vol1_hits = [
                    h
                    for h in vol1_hits
                    if _media_kind(h.get("url"), h.get("category")) in allowed
                ]
                seen = {h.get("id") for h in hits}
                for h in vol1_hits:
                    if h.get("id") not in seen:
                        hits.append(h)
                        seen.add(h.get("id"))
            hits = _rank_hits_for_query(hits, cleaned)
            for hit in hits:
                pic = _upgrade_cover(((hit.get("medias") or {}) or {}).get("picture"))
                title = hit.get("title") or cleaned
                if pic and pic not in [c["url"] for c in covers]:
                    covers.append(
                        {
                            "provider": self.display_name,
                            "title": title,
                            "url": pic,
                        }
                    )
                if len(covers) >= 5:
                    break
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        finally:
            try:
                session.close()
            except Exception:
                pass
        return covers

    # ------------------------------------------------------------------ HTTP

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": _BASE,
            "Referer": f"{_BASE}/",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }

    def _gql(self, session, query: str, variables: dict, operation: Optional[str] = None):
        payload: Dict[str, Any] = {"query": query, "variables": variables}
        if operation:
            payload["operationName"] = operation
        res = session.post(
            _APOLLO,
            json=payload,
            headers=self._headers(),
            impersonate="chrome",
            timeout=20,
        )
        if res.status_code != 200:
            return None
        data = res.json()
        if data.get("errors") and not data.get("data"):
            return None
        return data.get("data")

    def _search(self, session, terms: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        data = self._gql(
            session,
            _SEARCH_QUERY,
            {
                "query": terms,
                "offset": 0,
                "limit": limit,
                "sortBy": "RELEVANCE",
            },
            "SearchProductExplorer",
        )
        if not data:
            return []
        items = (data.get("searchProductExplorer") or {}).get("items") or []
        return [it for it in items if isinstance(it, dict) and it.get("id")]

    def _fetch_product(
        self,
        session,
        product_id: int,
        library_type: str,
        *,
        enforce_type: bool = True,
    ) -> Optional[Dict[str, Any]]:
        data = self._gql(
            session, _PRODUCT_QUERY, {"id": int(product_id)}, "Product"
        )
        if not data or not data.get("product"):
            return None
        return self._build_candidate(
            data["product"], library_type, enforce_type=enforce_type
        )

    # ------------------------------------------------------------------ Build

    def _candidate_from_search_hit(
        self, hit: Dict[str, Any], library_type: str
    ) -> Optional[Dict[str, Any]]:
        return self._build_candidate(hit, library_type)

    def _build_candidate(
        self,
        product: Dict[str, Any],
        library_type: str,
        *,
        enforce_type: bool = True,
    ) -> Optional[Dict[str, Any]]:
        title = (product.get("title") or "").strip()
        if not title:
            return None

        path = product.get("url") or ""
        kind = _media_kind(path, product.get("category"))
        allowed = _allowed_kinds(library_type)

        # Path film/série/etc. → hors scope
        if kind is None and any(
            _path_from_url(path).lower().startswith(p) for p in _REJECT_PREFIXES
        ):
            logging.info(self.t("wrong_type").format(product.get("category") or path))
            return None

        if kind is None:
            # category/url ambigus : pas de fallback silencieux vers Book
            logging.info(self.t("wrong_type").format(product.get("category") or path or "?"))
            return None

        if enforce_type and allowed and kind not in allowed:
            logging.info(self.t("wrong_type").format(kind))
            return None

        authors = []
        for a in product.get("authors") or []:
            name = (a or {}).get("name") if isinstance(a, dict) else None
            if name and name.strip():
                authors.append(name.strip())
        # BD : parfois staff côté directors (rare) — ignorer pour Book
        if not authors and kind == "Comic":
            for a in product.get("directors") or []:
                name = (a or {}).get("name") if isinstance(a, dict) else None
                if name and name.strip():
                    authors.append(name.strip())

        staff = [
            {"role": "Story", "node": {"name": {"full": name}}} for name in authors
        ]

        publishers = product.get("publishers") or []
        publisher = None
        if publishers and isinstance(publishers[0], dict):
            publisher = (publishers[0].get("name") or "").strip() or None

        genres = []
        for g in product.get("genresInfos") or []:
            label = (g or {}).get("label") if isinstance(g, dict) else None
            if label and label.strip():
                genres.append(label.strip())

        tags: List[str] = []
        for c in product.get("countries") or []:
            name = (c or {}).get("name") if isinstance(c, dict) else None
            if name and name.strip():
                tags.append(name.strip())

        year = product.get("yearOfProduction")
        if not isinstance(year, int):
            year = None
            for key in ("frenchReleaseDate", "dateRelease"):
                raw = product.get(key) or ""
                m = re.match(r"^(\d{4})", str(raw))
                if m:
                    y = int(m.group(1))
                    if 1000 <= y <= 2100:
                        year = y
                        break

        isbn_list_raw = product.get("isbn") or []
        if isinstance(isbn_list_raw, str):
            isbn_list_raw = [isbn_list_raw]
        isbns = []
        for raw in isbn_list_raw:
            n = _normalize_isbn(raw)
            if n and n not in isbns:
                isbns.append(n)
        # Préférer ISBN-13 ; si plusieurs, garder le premier 13 puis 10
        isbn = None
        for n in isbns:
            if len(n) == 13:
                isbn = n
                break
        if not isbn and isbns:
            isbn = isbns[0]

        alt = []
        orig = (product.get("originalTitle") or "").strip()
        if orig and orig.casefold() != title.casefold():
            alt.append(orig)
        for t in product.get("alternativeTitles") or []:
            if isinstance(t, str) and t.strip() and t.strip().casefold() != title.casefold():
                if t.strip() not in alt:
                    alt.append(t.strip())

        pid = product.get("id")
        url = path
        if url and not str(url).startswith("http"):
            url = f"{_BASE}{url}"
        elif not url and pid:
            url = f"{_BASE}/livre/x/{pid}"

        cover = _upgrade_cover(((product.get("medias") or {}) or {}).get("picture"))
        fmt = "comic" if kind == "Comic" else "book"

        return {
            "title": title,
            "alternative_titles": alt,
            "summary": (product.get("synopsis") or "").strip(),
            "cover_url": cover,
            "genres": genres[: get_max_genres()] if genres else [kind],
            "tags": tags[: get_max_tags()],
            "year": year,
            # BF59 / BF56 : pas de status / age inventés
            "staff": staff,
            "publisher": publisher,
            "format": fmt,
            "url": url,
            "links": [url] if url else [],
            "isbn": isbn,
            "_isbns": isbns,
        }
