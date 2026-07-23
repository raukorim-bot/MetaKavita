import logging
import requests
import urllib.parse
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import clean_title, score_candidate
from config_manager import load_config

class GoogleBooksScraper(BaseScraper):
    id = "GOOGLEBOOKS"
    display_name = "Google Books"
    supported_types = {"Book", "Comic"}
    rate_limit = 1.0
    proxy_domains = ["books.google.com"]
    has_direct_id_support = True
    needs_api_key = True
    
    translations = {
        "fr": {
            "direct_id": "[GoogleBooks] Requête directe par ID : '{0}'",
            "search_start": "[GoogleBooks] Lancement de la recherche pour : '{0}'",
            "search_isbn": "[GoogleBooks] Recherche prioritaire via ISBN Kavita : '{0}'",
            "matched_isbn": "🎯 [GoogleBooks] Match exact par ISBN ({0}) sur : '{1}'",
            "no_match": "⚠️ [GoogleBooks] Aucun volume pertinent trouvé pour '{0}' (Meilleur score : {1}%)",
            "matched": "🎯 [GoogleBooks] Volume retenu : '{0}' (Score: {1}%)",
            "err": "[GoogleBooks] Erreur : {0}"
        },
        "en": {
            "direct_id": "[GoogleBooks] Direct request by ID: '{0}'",
            "search_start": "[GoogleBooks] Starting search for: '{0}'",
            "search_isbn": "[GoogleBooks] Priority search via Kavita ISBN: '{0}'",
            "matched_isbn": "🎯 [GoogleBooks] Exact ISBN match ({0}) on: '{1}'",
            "no_match": "⚠️ [GoogleBooks] No relevant volume found for '{0}' (Best score: {1}%)",
            "matched": "🎯 [GoogleBooks] Selected volume: '{0}' (Score: {1}%)",
            "err": "[GoogleBooks] Error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "books.google." in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'id' in qs:
                return qs['id'][0]
        return None

    def fetch(self, query: str, library_type: str = "Book", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        google_lang = config.get("TARGET_LANG", "FR").lower()[:2]

        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                url = f"https://www.googleapis.com/books/v1/volumes/{query}"
                params = {"key": api_key} if api_key else {}
                res = requests.get(url, params=params, timeout=15)
                if res.status_code == 200:
                    item = res.json()
                    return self._build_candidate(item.get("volumeInfo", {}), item.get("id"))
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None
            
            logging.info(self.t("search_start").format(cleaned))
            url = "https://www.googleapis.com/books/v1/volumes"
            ex_isbn = existing_metadata.get('isbn') if existing_metadata else None

            items = []

            if ex_isbn:
                logging.info(self.t("search_isbn").format(ex_isbn))
                p_isbn = {"q": f"isbn:{ex_isbn}"}
                if api_key: p_isbn["key"] = api_key
                res = requests.get(url, params=p_isbn, timeout=12)
                if res.status_code == 200:
                    items = res.json().get("items", [])
                    if items:
                        vol_info = items[0].get("volumeInfo", {})
                        logging.info(self.t("matched_isbn").format(ex_isbn, vol_info.get('title')))

            if not items:
                params = {"q": cleaned, "maxResults": 10, "orderBy": "relevance"}
                if google_lang: params["langRestrict"] = google_lang
                if api_key: params["key"] = api_key
                res = requests.get(url, params=params, timeout=12)
                if res.status_code == 200:
                    items = res.json().get("items", [])

            if not items:
                params = {"q": cleaned, "maxResults": 10, "orderBy": "relevance"}
                if api_key: params["key"] = api_key
                res = requests.get(url, params=params, timeout=12)
                if res.status_code == 200:
                    items = res.json().get("items", [])

            if not items: 
                logging.warning(self.t("no_match").format(cleaned, 0))
                return None

            best_match = None
            best_score = -1.0

            for item in items:
                vol_info = item.get("volumeInfo", {})
                candidate = self._build_candidate(vol_info, item.get("id"))
                if not candidate or not candidate.get('title'):
                    continue

                score = score_candidate(candidate, cleaned, existing_metadata)

                # 🎯 BONUS ANTI-RÉSUMÉ VIDE : Favorise les fiches avec vrai résumé
                if candidate.get('summary') and len(candidate.get('summary')) > 30:
                    score += 0.10

                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < 0.50:
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_match.get('title'), int(best_score*100)))
            return best_match

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def _build_candidate(self, volume_info: dict, vol_id: str = None) -> Optional[Dict[str, Any]]:
        if not volume_info: return None

        isbn = None
        for ident in volume_info.get("industryIdentifiers", []):
            if ident.get("type") in ["ISBN_13", "ISBN_10"]:
                isbn = str(ident.get("identifier")).replace('-', '').replace(' ', '').strip()
                break

        image_links = volume_info.get("imageLinks", {})
        cover_url = image_links.get("extraLarge") or image_links.get("large") or image_links.get("medium") or image_links.get("thumbnail")
        if cover_url and cover_url.startswith("http://"): 
            cover_url = cover_url.replace("http://", "https://")

        year = None
        published_date = volume_info.get("publishedDate", "")
        if published_date and published_date[:4].isdigit(): 
            year = int(published_date[:4])

        staff = [{"role": "Story", "node": {"name": {"full": author.strip()}}} for author in volume_info.get("authors", [])]
        genres = [cat.strip() for cat in volume_info.get("categories", []) if cat.strip()]
        tags = ["Books", "GoogleBooks"] + [g for g in genres if g not in ["Books", "GoogleBooks"]]
        
        summary = volume_info.get("description", "").strip()
        info_link = volume_info.get("canonicalVolumeLink") or volume_info.get("infoLink")
        
        fetched_title = volume_info.get("title", "")
        subtitle = volume_info.get("subtitle", "")
        alt_titles = [subtitle] if subtitle else []

        return {
            'title': fetched_title,
            'alternative_titles': alt_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres,
            'tags': tags[:15],
            'year': year,
            'status': 'FINISHED',
            'staff': staff,
            'publisher': volume_info.get("publisher"),
            'isbn': isbn,
            'age_rating': 'safe',
            'format': 'book',
            'url': info_link,
            'links': [info_link] if info_link else []
        }

    def fetch_covers(self, query: str, library_type: str = "Book") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        url = "https://www.googleapis.com/books/v1/volumes"
        params = {"q": cleaned, "maxResults": 4}
        if api_key: params["key"] = api_key
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("items", []):
                    vol = item.get("volumeInfo", {})
                    img = vol.get("imageLinks", {})
                    cover_url = img.get("extraLarge") or img.get("large") or img.get("thumbnail")
                    if cover_url:
                        if cover_url.startswith("http://"): cover_url = cover_url.replace("http://", "https://")
                        title = vol.get("title", "Inconnu")
                        covers.append({"provider": "GoogleBooks", "title": title, "url": cover_url})
        except Exception: pass
        return covers