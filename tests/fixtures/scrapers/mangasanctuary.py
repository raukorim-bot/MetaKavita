"""Manga-Sanctuary — métadonnées manga FR (HTML). Fixture Magasin (T8).

Le scraper live vit dans le dépôt communautaire. Cette copie de test porte
`fetch_volume_index` + `scopes` volume, le contrat que `provides_volume_index`
exige pour entrer dans la cascade des tomes.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    album_number_key,
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    score_candidate,
    select_wanted_album_links,
)

_BASE = "https://www.manga-sanctuary.com"
_MANGA = re.compile(r"^/bdd/manga/(\d+)(?:-[^/?#]*)?/?$", re.I)
_TOME = re.compile(r"(?:tome|vol(?:ume)?)\s*(\d+(?:[.,]\d+)?)", re.I)


class MangaSanctuaryScraper(BaseScraper):
    id = "MANGASANCTUARY"
    display_name = "Manga-Sanctuary"
    supported_types = {"Manga"}
    scopes = {"series", "volume"}
    version = "1.2.0"
    rate_limit = 2.5
    VOLUME_INDEX_MAX = 40
    proxy_domains = ["manga-sanctuary.com", "www.manga-sanctuary.com"]
    has_direct_id_support = True
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "search_title": "🔍 [Manga-Sanctuary] Recherche pour '{0}'…",
            "direct_id": "🎯 [Manga-Sanctuary] id={0}",
            "no_match": "⚠️ [Manga-Sanctuary] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Manga-Sanctuary] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [Manga-Sanctuary] Erreur : {0}",
            "covers_err": "❌ [Covers] Manga-Sanctuary : {0}",
        },
        "en": {
            "search_title": "🔍 [Manga-Sanctuary] Searching for '{0}'…",
            "direct_id": "🎯 [Manga-Sanctuary] id={0}",
            "no_match": "⚠️ [Manga-Sanctuary] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Manga-Sanctuary] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [Manga-Sanctuary] Error: {0}",
            "covers_err": "❌ [Covers] Manga-Sanctuary: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        if url.strip().isdigit():
            return url.strip()
        path = urlparse(url).path if "://" in url else url
        m = _MANGA.match(path if path.startswith("/") else f"/bdd/manga/{path}")
        return m.group(1) if m else None

    def fetch(
        self,
        query: str,
        library_type: str = "Manga",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        session = requests.Session(impersonate="chrome110")
        try:
            if is_id:
                mid = self.extract_id_from_url(query)
                if not mid:
                    return None
                url = query if "manga-sanctuary.com" in query else f"{_BASE}/bdd/manga/{mid}/"
                cand = self._parse_manga(session, url)
                return attach_match_score(cand, 1.0) if cand else None
            cleaned = clean_title(query, library_type=library_type)
            if not cleaned:
                return None
            hits = self._search(session, cleaned)
            best, best_score = None, -1.0
            for hit in hits[:8]:
                cand = self._parse_manga(session, hit["url"])
                if not cand:
                    continue
                score = score_candidate(cand, cleaned, existing_metadata)
                if score > best_score:
                    best_score, best = score, cand
            if not best or best_score < get_match_accept_threshold():
                return None
            return attach_match_score(best, best_score)
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        return []

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Manga",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
        wanted_numbers: Optional[set] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        session = requests.Session(impersonate="chrome110")
        try:
            url = None
            for candidate in (series_id, (existing_metadata or {}).get("url"), query):
                mid = self.extract_id_from_url(str(candidate or ""))
                if mid:
                    url = (
                        str(candidate)
                        if "manga-sanctuary.com" in str(candidate)
                        else f"{_BASE}/bdd/manga/{mid}/"
                    )
                    break
            if not url:
                cleaned = clean_title(query, library_type=library_type)
                hits = self._search(session, cleaned) if cleaned else []
                url = (hits[0] or {}).get("url") if hits else None
            if not url:
                return None
            res = self._http_get(session, url, timeout=25)
            if getattr(res, "status_code", 0) != 200:
                return None
            soup = BeautifulSoup(getattr(res, "text", "") or "", "html.parser")
            links = self._volume_links(soup, url)
            index: Dict[str, Any] = {}
            for link in select_wanted_album_links(
                links, wanted_numbers, self.VOLUME_INDEX_MAX
            ):
                if should_cancel and should_cancel():
                    break
                payload = {
                    "provider_ref": link["url"],
                    "title": link.get("label") or "",
                    "cover_url": link.get("cover_url") or "",
                }
                payload = {k: v for k, v in payload.items() if v}
                if payload:
                    index[link["number"]] = payload
            return index or None
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _search(self, session, terms: str) -> List[dict]:
        res = self._http_post(
            session,
            f"{_BASE}/include/ajax_rechercher_mots.php",
            data={"chaine": terms},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=25,
        )
        if getattr(res, "status_code", 0) != 200 or not (getattr(res, "text", "") or "").strip():
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        hits, seen = [], set()
        for a in soup.select('a[href*="/bdd/manga/"]'):
            href = a.get("href") or ""
            mid = self.extract_id_from_url(href)
            if not mid or mid in seen:
                continue
            title = a.get_text(" ", strip=True)
            title = re.sub(r"\s*\((?:Manga|Manhwa|Manhua)\)\s*$", "", title, flags=re.I).strip()
            if not title:
                continue
            seen.add(mid)
            hits.append({"title": title, "url": urljoin(_BASE, href)})
        return hits

    def _parse_manga(self, session, url: str) -> Optional[Dict[str, Any]]:
        res = self._http_get(session, url, timeout=25)
        if getattr(res, "status_code", 0) != 200:
            return None
        soup = BeautifulSoup(getattr(res, "text", "") or "", "html.parser")
        og_title = soup.select_one('meta[property="og:title"]')
        title = (og_title.get("content") if og_title else "").strip()
        if not title and soup.h1:
            title = soup.h1.get_text(" ", strip=True)
        if not title:
            return None
        title = re.sub(r"\s*[-|]\s*Manga.?Sanctuary.*$", "", title, flags=re.I).strip()
        og_img = soup.select_one('meta[property="og:image"]')
        og_desc = soup.select_one('meta[property="og:description"]')
        return {
            "title": title,
            "alternative_titles": [],
            "summary": (og_desc.get("content") if og_desc else "") or "",
            "cover_url": og_img.get("content") if og_img else None,
            "genres": ["Manga"][: get_max_genres()],
            "tags": [][: get_max_tags()],
            "format": "manga",
            "url": url.split("?")[0],
            "links": [url.split("?")[0]],
        }

    @staticmethod
    def _volume_links(soup, serie_url: str) -> List[dict]:
        found = []
        seen = set()
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            label = a.get_text(" ", strip=True) or (a.get("title") or "")
            match = _TOME.search(label) or _TOME.search(href)
            if not match:
                continue
            number = album_number_key(match.group(1).replace(",", "."))
            if not number:
                continue
            absolute = urljoin(serie_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            img = a.find("img")
            found.append(
                {
                    "url": absolute,
                    "number": number,
                    "label": label,
                    "cover_url": (img.get("src") if img else "") or "",
                }
            )
        return found
