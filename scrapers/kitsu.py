import requests
import logging
import unicodedata
import difflib
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import clean_title

def normalize_str(s):
    if not s: return ""
    return "".join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn').strip()

class KitsuScraper(BaseScraper):
    id = "KITSU"
    display_name = "Kitsu (JSON:API)"
    supported_types = {"Manga"}
    rate_limit = 1.5
    proxy_domains = ["kitsu.io", "media.kitsu.app", "media.kitsu.io"]
    has_direct_id_support = True

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
                    
                res = requests.get(url, params=params, headers=headers, timeout=10)
                if res.status_code != 200: return None
                
                json_res = res.json()
                if isinstance(json_res.get('data'), list):
                    if not json_res['data']: return None
                    best_match = json_res['data'][0]
                else:
                    best_match = json_res.get('data')
                    
                if not best_match: return None

            else:
                clean = clean_title(query, library_type=library_type)
                logging.info(self.t("search_title").format(clean))
                url = "https://kitsu.io/api/edge/manga"
                params = {"filter[text]": clean, "page[limit]": 5, "include": "categories"}

                res = requests.get(url, params=params, headers=headers, timeout=10)
                if res.status_code != 200: return None

                json_res = res.json()
                data_list = json_res.get('data', [])
                if not data_list: return None

                norm_query = normalize_str(clean)
                best_match = None
                
                for manga in data_list:
                    attrs = manga.get('attributes', {})
                    titles_to_check = [attrs.get('canonicalTitle', '')]
                    if isinstance(attrs.get('titles'), dict):
                        titles_to_check.extend(attrs['titles'].values())
                        
                    for t in titles_to_check:
                        norm_t = normalize_str(str(t))
                        if not norm_t: continue
                        is_substring = (norm_query in norm_t or norm_t in norm_query) if (len(norm_query) >= 3 and len(norm_t) >= 3) else False
                        ratio = difflib.SequenceMatcher(None, norm_query, norm_t).ratio()
                        
                        if is_substring or ratio >= 0.80:
                            best_match = manga
                            break
                    if best_match: break

                if not best_match: return None
                
            attrs = best_match.get('attributes', {})
            raw_status = attrs.get('status', '')
            status = "RELEASING"
            if raw_status == "finished": status = "FINISHED"
            elif raw_status in ["tba", "unreleased", "hiatus"]: status = "HIATUS"
            elif raw_status == "cancelled": status = "CANCELLED"

            year = None
            if attrs.get('startDate'): year = int(attrs.get('startDate')[:4])

            format_type = None
            manga_type = attrs.get('mangaType', '').lower()
            if manga_type in ['manhwa', 'manhua', 'webtoon']: format_type = 'webtoon'
            elif manga_type == 'manga': format_type = 'manga'

            age_rating = "safe"
            raw_age = attrs.get('ageRating', '')
            if raw_age in ['R', 'R18']: age_rating = "pornographic"
            elif raw_age == 'PG': age_rating = "suggestive"

            tags = []
            for item in json_res.get('included', []):
                if item.get('type') == 'categories':
                    tags.append(item.get('attributes', {}).get('title'))

            cover_url = attrs.get('posterImage', {}).get('original') or attrs.get('posterImage', {}).get('large')

            alt_titles = []
            if isinstance(attrs.get('titles'), dict):
                alt_titles = [t for t in attrs.get('titles').values() if t]

            return {
                'title': attrs.get('canonicalTitle', ''),
                'alternative_titles': alt_titles,
                'summary': attrs.get('synopsis', ''),
                'cover_url': cover_url,
                'genres': [], 
                'tags': tags[:15],
                'year': year,
                'status': status,
                'staff': [], 
                'publisher': None,
                'age_rating': age_rating,
                'format': format_type,
                'url': f"https://kitsu.io/manga/{best_match.get('id')}"
            }
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
            res = requests.get(url, params=params, headers=headers, timeout=10)
            if res.status_code == 200:
                results = res.json().get('data', [])
                for m in results:
                    attrs = m.get('attributes', {})
                    cover_url = attrs.get('posterImage', {}).get('original') or attrs.get('posterImage', {}).get('large')
                    if cover_url:
                        title = attrs.get('canonicalTitle', 'Inconnu')
                        covers.append({"provider": "Kitsu", "title": title, "url": cover_url})
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers