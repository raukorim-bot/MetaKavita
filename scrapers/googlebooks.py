import logging
import requests
from .base import BaseScraper
from .utils import clean_title
from config_manager import load_config

class GoogleBooksScraper(BaseScraper):
    id = "GOOGLEBOOKS"
    display_name = "Google Books"
    supported_types = {"Book", "Comic"}
    rate_limit = 1.0
    proxy_domains = ["books.google.com"]

    def fetch(self, query: str, library_type: str = "Book", is_id: bool = False):
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return None

        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        google_lang = config.get("TARGET_LANG", "FR").lower()[:2]
        
        logging.info(f"[GoogleBooks] Lancement de la recherche pour : '{cleaned}'")
        url = "https://www.googleapis.com/books/v1/volumes"
        params = {"q": cleaned, "maxResults": 5, "langRestrict": google_lang}
        if api_key: params["key"] = api_key

        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code != 200: return None
            items = response.json().get("items", [])
            if not items: return None
                
            volume_info = items[0].get("volumeInfo", {})
            
            image_links = volume_info.get("imageLinks", {})
            cover_url = image_links.get("extraLarge") or image_links.get("large") or image_links.get("medium") or image_links.get("thumbnail")
            if cover_url and cover_url.startswith("http://"): cover_url = cover_url.replace("http://", "https://")
                
            year = None
            published_date = volume_info.get("publishedDate", "")
            if published_date and published_date[:4].isdigit(): year = int(published_date[:4])
                    
            staff = [{"role": "Story", "node": {"name": {"full": author.strip()}}} for author in volume_info.get("authors", [])]
            
            genres = [cat.strip() for cat in volume_info.get("categories", []) if cat.strip()]
            tags = ["Books", "GoogleBooks"] + [g for g in genres if g not in ["Books", "GoogleBooks"]]
            
            summary = volume_info.get("description", "").strip()
            info_link = volume_info.get("canonicalVolumeLink") or volume_info.get("infoLink")
            
            if not summary and not cover_url: return None
                
            return {
                'summary': summary,
                'cover_url': cover_url,
                'genres': genres,
                'tags': tags[:15],
                'year': year,
                'status': 'FINISHED',
                'staff': staff,
                'publisher': volume_info.get("publisher"),
                'age_rating': 'safe',
                'format': 'book',
                'url': info_link,
                'links': [info_link] if info_link else []
            }
        except Exception as e:
            logging.error(f"[GoogleBooks] Erreur : {e}")
            return None

    def fetch_covers(self, query: str):
        covers = []
        cleaned = clean_title(query)
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