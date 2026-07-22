import logging
import requests
import urllib.parse
from .base import BaseScraper
from .utils import clean_title, calculate_similarity, normalize_str
from config_manager import load_config
from typing import Optional

class GoogleBooksScraper(BaseScraper):
    id = "GOOGLEBOOKS"
    display_name = "Google Books"
    supported_types = {"Book", "Comic"}
    rate_limit = 1.0
    proxy_domains = ["books.google.com"]
    has_direct_id_support = True

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "books.google." in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'id' in qs:
                return qs['id'][0]
        return None

    def fetch(self, query: str, library_type: str = "Book", is_id: bool = False):
        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        google_lang = config.get("TARGET_LANG", "FR").lower()[:2]

        try:
            if is_id:
                logging.info(f"[GoogleBooks] Requête directe par ID : '{query}'")
                url = f"https://www.googleapis.com/books/v1/volumes/{query}"
                params = {}
                if api_key: params["key"] = api_key
                
                response = requests.get(url, params=params, timeout=15)
                if response.status_code != 200: return None
                
                volume_info = response.json().get("volumeInfo", {})
                if not volume_info: return None
                
            else:
                # --- LOGIQUE DE RECHERCHE CLASSIQUE ---
                cleaned = clean_title(query, library_type=library_type)
                if not cleaned: return None
                
                logging.info(f"[GoogleBooks] Lancement de la recherche pour : '{cleaned}'")
                url = "https://www.googleapis.com/books/v1/volumes"
                
                # Étape A : Recherche ciblée sur le titre (jusqu'à 10 résultats)
                params = {
                    "q": f'intitle:"{cleaned}"',
                    "maxResults": 10,
                    "orderBy": "relevance"
                }
                if google_lang: params["langRestrict"] = google_lang
                if api_key: params["key"] = api_key

                response = requests.get(url, params=params, timeout=15)
                items = response.json().get("items", []) if response.status_code == 200 else []
                
                # Étape B : Repli si la recherche intitle: est trop stricte
                if not items:
                    params["q"] = cleaned
                    response = requests.get(url, params=params, timeout=15)
                    if response.status_code == 200:
                        items = response.json().get("items", [])

                if not items: 
                    return None
                    
                # --- ÉTAPE C : SÉLECTION INTELLIGENTE ET STABLE ---
                best_match = None
                best_score = -1.0

                for item in items:
                    info = item.get("volumeInfo", {})
                    title = info.get("title", "")
                    subtitle = info.get("subtitle", "")
                    full_title = f"{title} {subtitle}".strip() if subtitle else title
                    
                    if not title: continue
                        
                    # Calcul de la ressemblance avec le nom de la série
                    score = calculate_similarity(cleaned, full_title)
                    
                    # Bonus d'ancrage pour le Tome 1 / Band 1 (évite de sauter entre les tomes)
                    norm_title = normalize_str(full_title)
                    is_vol1 = any(tag in norm_title for tag in [" 1", " 01", "band 1", "vol 1", "volume 1", "tome 1", "book 1", "#1"])
                    if is_vol1:
                        score += 0.12

                    if score > best_score:
                        best_score = score
                        best_match = info

                # Sécurité : Si le score reste trop bas (< 50%), on rejette pour laisser passer le scraper suivant
                if not best_match or best_score < 0.50:
                    logging.warning(f"⚠️ [GoogleBooks] Aucun volume pertinent trouvé pour '{cleaned}' (Meilleur score : {int(best_score*100)}%)")
                    return None

                volume_info = best_match
                logging.info(f"🎯 [GoogleBooks] Volume retenu : '{volume_info.get('title')}' (Score: {int(best_score*100)}%)")

            # --- EXTRACTION DES MÉTADONNÉES ---
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
                'age_rating': 'safe',
                'format': 'book',
                'url': info_link,
                'links': [info_link] if info_link else []
            }
        except Exception as e:
            logging.error(f"[GoogleBooks] Erreur : {e}")
            return None

    def fetch_covers(self, query: str, library_type: str = "Book"):
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