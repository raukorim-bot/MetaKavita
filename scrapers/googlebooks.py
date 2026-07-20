# scrapers/googlebooks.py

import logging
import requests
from scrapers import clean_title
from config_manager import load_config

def scrape_data(search_query, library_type="Book"):
    """
    Scraper de production pour Google Books API (Catégorie Roman / Livre).
    Supporte l'utilisation d'une clé API optionnelle et l'internationalisation dynamique.
    """
    cleaned = clean_title(search_query, library_type=library_type)
    if not cleaned:
        return None

    # Lecture de la configuration globale
    config = load_config()
    api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
    
    # 🌍 Internationalisation : On récupère la langue cible (ex: "FR", "ES", "PT-BR") 
    # et on la convertit au format ISO 639-1 sur deux lettres minuscules (ex: "fr", "es", "pt")
    target_lang_raw = config.get("TARGET_LANG", "FR")
    google_lang = target_lang_raw.lower()[:2]

    print(f"[GoogleBooks] Lancement de la recherche pour : '{cleaned}' (Langue prioritaire: {google_lang})")
    
    url = "https://www.googleapis.com/books/v1/volumes"
    params = {
        "q": cleaned,
        "maxResults": 5,
        "langRestrict": google_lang  # ⬅️ Dynamique : basé sur la configuration de l'utilisateur !
    }
    
    # Injection de la clé de quota si disponible
    if api_key:
        params["key"] = api_key

    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            logging.error(f"[GoogleBooks] Erreur HTTP {response.status_code} lors de la requête.")
            return None
            
        json_data = response.json()
        items = json_data.get("items", [])
        if not items:
            print(f"[GoogleBooks] Aucun résultat trouvé pour la requête : '{cleaned}'")
            return None
            
        book_entry = items[0]
        volume_info = book_entry.get("volumeInfo", {})
        
        # 1. Extraction et sécurisation HTTPS de la couverture
        image_links = volume_info.get("imageLinks", {})
        cover_url = (
            image_links.get("extraLarge") or
            image_links.get("large") or
            image_links.get("medium") or
            image_links.get("small") or
            image_links.get("thumbnail") or
            image_links.get("smallThumbnail")
        )
        if cover_url and cover_url.startswith("http://"):
            cover_url = cover_url.replace("http://", "https://")
            
        # 2. Extraction et validation de l'année de sortie
        published_date = volume_info.get("publishedDate", "")
        year = None
        if published_date:
            year_candidate = published_date[:4]
            if year_candidate.isdigit():
                year = int(year_candidate)
                
        # 3. Extraction de l'auteur principal (Staff d'écriture)
        authors = volume_info.get("authors", [])
        staff = []
        for author in authors:
            staff.append({
                "role": "Story",
                "node": {"name": {"full": author.strip()}}
            })
            
        # 4. Traitement des catégories et thèmes (Genres & Tags)
        categories = volume_info.get("categories", [])
        genres = [cat.strip() for cat in categories if cat.strip()]
        
        tags = ["Books", "GoogleBooks"]
        for genre in genres:
            if genre not in tags:
                tags.append(genre)
                
        # 5. Extraction du résumé
        summary = volume_info.get("description", "").strip()
        
        # 6. Liens de référence
        info_link = volume_info.get("canonicalVolumeLink") or volume_info.get("infoLink")
        
        if not summary and not cover_url:
            print(f"[GoogleBooks] Fiche rejetée car sans résumé ni couverture.")
            return None
            
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
        logging.error(f"[GoogleBooks] Erreur inattendue durant le scraping de '{cleaned}' : {e}")
        return None