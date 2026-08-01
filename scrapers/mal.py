"""
MyAnimeList officiel (API v2) — remplace l'ancien chemin Jikan (indisponible).

Auth : header `X-MAL-CLIENT-ID` = Client ID de l'app enregistrée sur
https://myanimelist.net/apiconfig (stocké dans `MAL_API_KEY` via le moteur
Zero-Hardcode). Pas d'OAuth utilisateur pour search / details manga.
"""
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from config_manager import get_max_genres, get_max_tags, load_config
from .base import BaseScraper
from .utils import attach_match_score, clean_title, get_match_accept_threshold, score_candidate

API_BASE = "https://api.myanimelist.net/v2"
MANGA_FIELDS = (
    "id,title,main_picture,alternative_titles,start_date,synopsis,"
    "media_type,status,genres,nsfw,num_volumes,num_chapters,"
    "authors{first_name,last_name},serialization{name}"
)

# media_type MAL → familles MetaKavita
_BOOK_MEDIA = {"novel", "light_novel"}
_MANGA_MEDIA = {
    "manga", "one_shot", "doujinshi", "manhwa", "manhua", "oel", "unknown",
}


class MalScraper(BaseScraper):
    id = "MAL"
    display_name = "MyAnimeList (Official API)"
    supported_types = {"Manga", "Book"}
    rate_limit = 1.2
    proxy_domains = ["cdn.myanimelist.net", "myanimelist.net", "api.myanimelist.net"]
    has_direct_id_support = True
    needs_api_key = True
    uses_unified_scoring = True

    translations = {
        "fr": {
            "err_missing": (
                "❌ Client ID MyAnimeList manquant. Créez une app sur "
                "https://myanimelist.net/apiconfig et collez le Client ID "
                "dans MAL_API_KEY (Config)."
            ),
            "direct_id": "[MAL] Requête directe par ID : '{0}'",
            "search_title": "[MAL] Recherche par titre : '{0}'",
            "err": "[MAL] Erreur : {0}",
            "covers_err": "[Covers] Erreur MAL : {0}",
            "http_err": "[MAL] HTTP {0}",
        },
        "en": {
            "err_missing": (
                "❌ MyAnimeList Client ID missing. Register an app at "
                "https://myanimelist.net/apiconfig and paste the Client ID "
                "into MAL_API_KEY (Config)."
            ),
            "direct_id": "[MAL] Direct request by ID: '{0}'",
            "search_title": "[MAL] Title search: '{0}'",
            "err": "[MAL] Error: {0}",
            "covers_err": "[Covers] MAL error: {0}",
            "http_err": "[MAL] HTTP {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        if "myanimelist.net" not in url.lower():
            return None
        match = re.search(r"/manga/(\d+)", url, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _client_id(self) -> str:
        config = load_config()
        return (config.get("MAL_API_KEY") or "").strip()

    def _headers(self, client_id: str) -> Dict[str, str]:
        return {
            "X-MAL-CLIENT-ID": client_id,
            "Accept": "application/json",
            "User-Agent": "MetaKavita/1.6",
        }

    def _get(self, path: str, client_id: str, params: Optional[dict] = None) -> Optional[dict]:
        url = f"{API_BASE}{path}"
        res = requests.get(url, headers=self._headers(client_id), params=params or {}, timeout=12)
        if res.status_code != 200:
            logging.warning(self.t("http_err").format(res.status_code))
            return None
        data = res.json()
        return data if isinstance(data, dict) else None

    @staticmethod
    def _map_status(raw: str) -> str:
        raw = (raw or "").lower()
        if raw == "finished":
            return "FINISHED"
        if raw in ("on_hiatus",):
            return "HIATUS"
        if raw in ("discontinued",):
            return "CANCELLED"
        if raw in ("currently_publishing", "not_yet_published"):
            return "RELEASING"
        return "RELEASING"

    @staticmethod
    def _map_age(nsfw) -> Optional[str]:
        """Map MAL nsfw flag → internal age_rating, or None if unknown/absent.

        BF56: do not invent ``safe`` when the API omitted ``nsfw``. Explicit
        ``white`` still maps to safe (authoritative Everyone signal).
        """
        if nsfw is None:
            return None
        raw = str(nsfw).strip().lower()
        if not raw:
            return None
        if raw == "black":
            return "pornographic"
        if raw == "gray":
            return "suggestive"
        if raw == "white":
            return "safe"
        return None

    @staticmethod
    def _map_format(media_type: str) -> Optional[str]:
        mt = (media_type or "").lower()
        if mt in ("manhwa", "manhua"):
            return "webtoon"
        if mt in ("manga", "one_shot", "doujinshi", "oel"):
            return "manga"
        if mt in _BOOK_MEDIA:
            return None
        return "manga"

    @staticmethod
    def _media_ok(media_type: str, library_type: str) -> bool:
        mt = (media_type or "unknown").lower()
        lib = (library_type or "Manga").strip()
        if lib == "Book":
            return mt in _BOOK_MEDIA or mt == "unknown"
        # Manga (défaut) : tout sauf romans purs
        return mt not in _BOOK_MEDIA

    def _build_candidate(self, node: dict) -> Optional[Dict[str, Any]]:
        if not node or not isinstance(node, dict):
            return None
        manga_id = node.get("id")
        if manga_id is None:
            return None

        title = (node.get("title") or "").strip()
        alts = node.get("alternative_titles") or {}
        alt_titles: List[str] = []
        titles: List[Dict[str, str]] = []
        if title:
            titles.append({"lang": "en", "value": title})

        for syn in alts.get("synonyms") or []:
            if syn and isinstance(syn, str) and syn.strip() and syn.strip() != title:
                alt_titles.append(syn.strip())
        en = alts.get("en")
        if en and isinstance(en, str) and en.strip() and en.strip() != title:
            alt_titles.append(en.strip())
            titles.append({"lang": "en", "value": en.strip()})
        ja = alts.get("ja")
        if ja and isinstance(ja, str) and ja.strip():
            alt_titles.append(ja.strip())
            titles.append({"lang": "ja", "value": ja.strip()})

        year = None
        start = node.get("start_date") or ""
        if isinstance(start, str) and len(start) >= 4 and start[:4].isdigit():
            year = int(start[:4])

        genres = []
        for g in node.get("genres") or []:
            if isinstance(g, dict) and g.get("name"):
                genres.append(g["name"])

        staff = []
        for entry in node.get("authors") or []:
            if not isinstance(entry, dict):
                continue
            person = entry.get("node") or {}
            first = (person.get("first_name") or "").strip()
            last = (person.get("last_name") or "").strip()
            full = f"{first} {last}".strip() or last or first
            if not full:
                continue
            role_raw = (entry.get("role") or "").lower()
            has_story = any(k in role_raw for k in ("story", "author", "writer"))
            has_art = any(k in role_raw for k in ("art", "illustrat"))
            if "story & art" in role_raw or ("story" in role_raw and "art" in role_raw):
                has_story = has_art = True
            if not has_story and not has_art:
                has_story = True
            if has_story:
                staff.append({"role": "Story", "node": {"name": {"full": full}}})
            if has_art:
                staff.append({"role": "Art", "node": {"name": {"full": full}}})

        publisher = None
        for ser in node.get("serialization") or []:
            if isinstance(ser, dict):
                name = (ser.get("node") or {}).get("name")
                if name:
                    publisher = name
                    break

        pic = node.get("main_picture") or {}
        cover_url = None
        if isinstance(pic, dict):
            cover_url = pic.get("large") or pic.get("medium")

        media_type = (node.get("media_type") or "").lower()
        return {
            "title": title,
            "alternative_titles": alt_titles,
            "titles": titles,
            "summary": (node.get("synopsis") or "").strip(),
            "cover_url": cover_url,
            "genres": genres[: get_max_genres()],
            "tags": genres[: get_max_tags()],
            "year": year,
            "status": self._map_status(node.get("status") or ""),
            "staff": staff,
            "publisher": publisher,
            "age_rating": self._map_age(node.get("nsfw")) or "",
            "format": self._map_format(media_type),
            "mal_id": manga_id,
            "url": f"https://myanimelist.net/manga/{manga_id}",
        }

    def fetch(
        self,
        query: str,
        library_type: str = "Manga",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        client_id = self._client_id()
        if not client_id:
            logging.error(self.t("err_missing"))
            return None

        try:
            if is_id:
                mid = str(query).strip()
                if not mid.isdigit():
                    extracted = self.extract_id_from_url(mid)
                    mid = extracted or mid
                if not str(mid).isdigit():
                    return None
                logging.info(self.t("direct_id").format(mid))
                node = self._get(f"/manga/{mid}", client_id, {"fields": MANGA_FIELDS})
                if not node:
                    return None
                if not self._media_ok(node.get("media_type") or "", library_type):
                    return None
                candidate = self._build_candidate(node)
                return attach_match_score(candidate, 1.0) if candidate else None

            clean = clean_title(query, library_type=library_type)
            if len(clean) < 2:
                return None
            logging.info(self.t("search_title").format(clean))
            payload = self._get(
                "/manga",
                client_id,
                {
                    "q": clean[:64],
                    "limit": 5,
                    "nsfw": "true",
                    "fields": MANGA_FIELDS,
                },
            )
            if not payload:
                return None

            best_candidate = None
            best_score = -1.0
            for row in payload.get("data") or []:
                node = row.get("node") if isinstance(row, dict) else None
                if not isinstance(node, dict):
                    continue
                if not self._media_ok(node.get("media_type") or "", library_type):
                    continue
                candidate = self._build_candidate(node)
                if not candidate:
                    continue
                score = score_candidate(candidate, clean, existing_metadata)
                if score > best_score:
                    best_score = score
                    best_candidate = candidate

            if not best_candidate or best_score < get_match_accept_threshold():
                return None
            return attach_match_score(best_candidate, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        client_id = self._client_id()
        if not client_id:
            return covers
        clean = clean_title(query, library_type=library_type)
        try:
            payload = self._get(
                "/manga",
                client_id,
                {
                    "q": clean[:64],
                    "limit": 4,
                    "nsfw": "true",
                    "fields": "id,title,main_picture,media_type",
                },
            )
            if not payload:
                return covers
            for row in payload.get("data") or []:
                node = row.get("node") if isinstance(row, dict) else None
                if not isinstance(node, dict):
                    continue
                if not self._media_ok(node.get("media_type") or "", library_type):
                    continue
                pic = node.get("main_picture") or {}
                url = pic.get("large") or pic.get("medium") if isinstance(pic, dict) else None
                if url:
                    covers.append({
                        "provider": "MyAnimeList",
                        "title": node.get("title") or "MAL",
                        "url": url,
                    })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers
