import requests
import logging
import unicodedata
import difflib
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

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False):
        clean = clean_title(query, library_type=library_type)
        logging.info(f"[Kitsu] Recherche par titre : '{clean}'")
        url = "https://kitsu.io/api/edge/manga"
        params = {"filter[text]": clean, "page[limit]": 5, "include": "categories"}

        try:
            headers = {"Accept": "application/vnd.api+json"}
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

            return {
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
            logging.error(f"[Erreur Kitsu] {e}")
            return None

    def fetch_covers(self, query: str):
        covers = []
        clean_sq = clean_title(query)
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
            logging.error(f"[Covers] Erreur Kitsu : {e}")
        return covers