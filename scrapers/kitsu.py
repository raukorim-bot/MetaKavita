import requests
import logging
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)
from config_manager import get_max_tags


class KitsuScraper(BaseScraper):
    id = "KITSU"
    is_core = True
    display_name = "Kitsu (JSON:API)"
    supported_types = {"Manga"}
    rate_limit = 1.5
    # 1.1.0 : la cadence s'applique désormais à chaque requête et non à la seule
    # première d'un `fetch()`, et un refus de l'API (429, 5xx) est journalisé au
    # lieu de se confondre avec « aucun résultat ». La montée de version est ce
    # qui autorise l'image à remplacer la copie 1.0.x déjà installée sous data/.
    version = "1.1.0"
    proxy_domains = ["kitsu.io", "media.kitsu.app", "media.kitsu.io"]
    has_direct_id_support = True
    uses_unified_scoring = True

    translations = {
        "fr": {
            "direct_id": "[Kitsu] Requête directe par ID/Slug : '{0}'",
            "search_title": "[Kitsu] Recherche par titre : '{0}'",
            "err": "[Erreur Kitsu] {0}",
            "covers_err": "[Covers] Erreur Kitsu : {0}"
        },
        "en": {
            "direct_id": "[Kitsu] Direct request by ID/Slug: '{0}'",
            "search_title": "[Kitsu] Title search: '{0}'",
            "err": "[Kitsu Error] {0}",
            "covers_err": "[Covers] Kitsu error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "kitsu.io/manga/" in url or "kitsu.app/manga/" in url:
            return url.split('/manga/')[-1].split('/')[0].split('?')[0]
        return None

    def _build_candidate(self, manga: dict, included: Optional[List] = None) -> Optional[Dict[str, Any]]:
        if not manga or not isinstance(manga, dict):
            return None
        attrs = manga.get('attributes', {}) or {}

        raw_status = attrs.get('status', '')
        status = "RELEASING"
        if raw_status == "finished":
            status = "FINISHED"
        elif raw_status in ["tba", "unreleased", "hiatus"]:
            status = "HIATUS"
        elif raw_status == "cancelled":
            status = "CANCELLED"

        year = None
        if attrs.get('startDate'):
            try:
                year = int(attrs.get('startDate')[:4])
            except (TypeError, ValueError):
                year = None

        format_type = None
        manga_type = (attrs.get('mangaType') or '').lower()
        if manga_type in ['manhwa', 'manhua', 'webtoon']:
            format_type = 'webtoon'
        elif manga_type == 'manga':
            format_type = 'manga'

        # BF56/BF80: emit only for known Kitsu ageRating tokens (G/PG/R/R18).
        # R = mature/17+ (violence, themes) ≠ R18 (explicit). Do not collapse
        # both to pornographic — that wrote X18+ onto mainstream series (#29).
        # ageRatingGuide is free-text and often null; it is not required to emit.
        age_rating = ""
        raw_age = (attrs.get("ageRating") or "").strip().upper()
        if raw_age == "R18":
            age_rating = "pornographic"
        elif raw_age == "R":
            age_rating = "mature"
        elif raw_age == "PG":
            age_rating = "suggestive"
        elif raw_age == "G":
            age_rating = "safe"

        tags = []
        for item in (included or []):
            if item.get('type') == 'categories':
                title = (item.get('attributes') or {}).get('title')
                if title:
                    tags.append(title)

        poster = attrs.get('posterImage') or {}
        cover_url = None
        if isinstance(poster, dict):
            cover_url = poster.get('original') or poster.get('large')

        alt_titles = []
        titles = []
        if isinstance(attrs.get('titles'), dict):
            for lang_key, t_val in attrs.get('titles').items():
                if not t_val:
                    continue
                alt_titles.append(t_val)
                # Kitsu: en_jp ≈ romaji, ja_jp ≈ native
                titles.append({"lang": lang_key, "value": t_val})

        return {
            'title': attrs.get('canonicalTitle', '') or '',
            'alternative_titles': alt_titles,
            'titles': titles,
            'summary': attrs.get('synopsis', '') or '',
            'cover_url': cover_url,
            'genres': [],
            'tags': tags[:get_max_tags()],
            'year': year,
            'status': status,
            'staff': [],
            'publisher': None,
            'age_rating': age_rating,
            'format': format_type,
            'url': f"https://kitsu.io/manga/{manga.get('id')}"
        }

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        headers = {"Accept": "application/vnd.api+json"}

        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                if str(query).isdigit():
                    url = f"https://kitsu.io/api/edge/manga/{query}"
                    params = {"include": "categories"}
                else:
                    url = "https://kitsu.io/api/edge/manga"
                    params = {"filter[slug]": query, "include": "categories"}

                res = self._http_get(requests, url, params=params, headers=headers, timeout=10)
                if not response_is_ok(self, res, context="fiche par identifiant"):
                    return None

                json_res = res.json()
                if isinstance(json_res.get('data'), list):
                    if not json_res['data']:
                        return None
                    best_match = json_res['data'][0]
                else:
                    best_match = json_res.get('data')

                if not best_match:
                    return None
                candidate = self._build_candidate(best_match, json_res.get('included', []))
                return attach_match_score(candidate, 1.0) if candidate else None

            clean = clean_title(query, library_type=library_type)
            logging.info(self.t("search_title").format(clean))
            url = "https://kitsu.io/api/edge/manga"
            params = {"filter[text]": clean, "page[limit]": 5, "include": "categories"}

            res = self._http_get(requests, url, params=params, headers=headers, timeout=10)
            if not response_is_ok(self, res, context="recherche par titre"):
                return None

            json_res = res.json()
            data_list = json_res.get('data', [])
            if not data_list:
                return None

            included = json_res.get('included', [])
            best_candidate = None
            best_score = -1.0

            for manga in data_list:
                candidate = self._build_candidate(manga, included)
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
        covers = []
        clean_sq = clean_title(query, library_type=library_type)
        try:
            url = "https://kitsu.io/api/edge/manga"
            params = {"filter[text]": clean_sq, "page[limit]": 4}
            headers = {"Accept": "application/vnd.api+json"}
            res = self._http_get(requests, url, params=params, headers=headers, timeout=10)
            if response_is_ok(self, res, context="couvertures"):
                results = res.json().get('data', [])
                for m in results:
                    attrs = m.get('attributes') or {}
                    poster = attrs.get('posterImage') or {}
                    cover_url = poster.get('original') or poster.get('large')
                    if cover_url:
                        title = attrs.get('canonicalTitle') or 'Inconnu'
                        covers.append({"provider": "Kitsu", "title": title, "url": cover_url})
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers
