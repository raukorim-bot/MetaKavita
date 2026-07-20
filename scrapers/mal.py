# scrapers/mal.py
import requests
import logging
from scrapers import clean_title

def fetch_mal(title_or_id, library_type="Manga", is_id=False):
    try:
        if is_id:
            logging.info(f"[MAL/Jikan] Requête directe par ID : {title_or_id}")
            url = f"https://api.jikan.moe/v4/manga/{title_or_id}"
            res = requests.get(url, timeout=10)
        else:
            clean = clean_title(title_or_id, library_type=library_type)
            logging.info(f"[MAL/Jikan] Recherche par titre : '{clean}'")
            url = "https://api.jikan.moe/v4/manga"
            res = requests.get(url, params={"q": clean, "limit": 1}, timeout=10)
            
        if res.status_code != 200:
            logging.warning(f"[MAL/Jikan] Erreur API (Code {res.status_code})")
            return None
            
        json_res = res.json()
        
        # Gestion de la réponse (Liste vs Objet unique)
        if 'data' not in json_res or not json_res['data']:
            return None
            
        data = json_res['data'][0] if isinstance(json_res['data'], list) else json_res['data']
            
        # Mappage du statut
        raw_status = data.get('status', '').lower()
        status = "RELEASING"
        if "finished" in raw_status: status = "FINISHED"
        elif "hiatus" in raw_status: status = "HIATUS"
        elif "discontinued" in raw_status: status = "CANCELLED"
        
        # Fusion des thèmes et démographies dans les tags
        tags = [t.get('name') for t in data.get('themes', [])]
        for demo in data.get('demographics', []):
            tags.append(demo.get('name'))
            
        # Auteurs (MAL mixe souvent Scénario et Dessin dans "authors")
        staff = []
        for author in data.get('authors', []):
            staff.append({"role": "Story", "node": {"name": {"full": author.get('name')}}})
            staff.append({"role": "Art", "node": {"name": {"full": author.get('name')}}})
            
        # Éditeur (Serializations)
        publisher = None
        serializations = data.get('serializations', [])
        if serializations:
            publisher = serializations[0].get('name')
            
        # Année
        year = None
        published = data.get('published', {})
        if published and published.get('prop', {}).get('from', {}).get('year'):
            year = published['prop']['from']['year']
            
        # Format
        format_type = None
        mal_type = str(data.get('type', '')).lower()
        if 'manhwa' in mal_type or 'webtoon' in mal_type:
            format_type = 'webtoon'
        elif 'manga' in mal_type:
            format_type = 'manga'
        
        return {
            'summary': data.get('synopsis', ''),
            'cover_url': data.get('images', {}).get('jpg', {}).get('large_image_url'),
            'genres': [g.get('name') for g in data.get('genres', [])],
            'tags': tags[:15],
            'year': year,
            'status': status,
            'staff': staff,
            'publisher': publisher,
            'age_rating': 'safe', # Par défaut
            'format': format_type,
            'url': data.get('url'),
            'mal_id': data.get('mal_id')
        }
        
    except Exception as e:
        logging.error(f"[Erreur MAL/Jikan] {e}")
        return None