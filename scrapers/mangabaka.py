import requests
from scrapers import clean_title

# scrapers/mangabaka.py

def fetch_mangabaka(title_or_id, library_type="Manga", is_id=False):
    base_url = "https://api.mangabaka.org/v2/series"
    search_url = "https://api.mangabaka.org/v2/series/search"
    
    try:
        if is_id:
            print(f"[MangaBaka V2] Requête directe par ID : {title_or_id}")
            res = requests.get(f"{base_url}/{title_or_id}", timeout=10)
            if res.status_code != 200:
                return None
            json_res = res.json()
            data = json_res.get('data') if 'data' in json_res else json_res
        else:
            clean = clean_title(title_or_id)
            print(f"[MangaBaka V2] Recherche par titre : '{clean}'")
            res = requests.get(search_url, params={"q": clean}, timeout=10)
            if res.status_code != 200:
                return None
                
            json_res = res.json()
            results = json_res.get('data') if 'data' in json_res else json_res
            
            if isinstance(results, list) and len(results) > 0:
                data = results[0]
            elif isinstance(results, dict):
                data = results
            else:
                return None

        if not data:
            return None

        cover_url = None
        cover_data = data.get('cover')
        if isinstance(cover_data, dict):
            cover_url = cover_data.get('raw') or cover_data.get('original') or cover_data.get('large')
        elif isinstance(cover_data, str):
            cover_url = cover_data

        staff = []
        for author in data.get('authors', []):
            if isinstance(author, dict): author = author.get('name', '')
            if author: staff.append({"role": "Story", "node": {"name": {"full": author}}})
            
        for artist in data.get('artists', []):
            if isinstance(artist, dict): artist = artist.get('name', '')
            if artist: staff.append({"role": "Art", "node": {"name": {"full": artist}}})

        year = None
        published = data.get('published', {})
        if isinstance(published, dict) and published.get('start_date'):
            year = int(str(published['start_date'])[:4])

        alt_titles = []
        for t in data.get('titles', []):
            if isinstance(t, dict) and t.get('title'):
                alt_titles.append(t['title'])

        # --- NOUVEAU : Récupération des ID externes de MangaBaka ---
        mb_sources = data.get('source', {})
        anilist_id = None
        mal_id = None
        if isinstance(mb_sources, dict):
            anilist_id = mb_sources.get('anilist', {}).get('id')
            mal_id = mb_sources.get('mal', {}).get('id')
            
        links = data.get('links') or []

        # --- NOUVEAU : Déduction du format (Manga vs Webtoon) ---
        format_type = None
        
        # Sécurisation absolue : on force une liste vide si l'API renvoie 'null'
        tags_list = data.get('tags') or []
        genres_list = data.get('genres') or []
        
        try:
            # 1. Vérifier si MangaBaka donne le type explicitement
            mb_type = str(data.get('type', '')).upper()
            if 'MANHWA' in mb_type or 'WEBTOON' in mb_type:
                format_type = 'webtoon'
            elif 'MANGA' in mb_type:
                format_type = 'manga'
                
            # 2. Chercher dans les tags ET les genres s'il n'a rien trouvé
            if not format_type:
                # On extrait proprement, que l'API nous donne des chaînes ou des dictionnaires
                tags_str = " ".join([str(t.get('name', t)) if isinstance(t, dict) else str(t) for t in tags_list]).upper()
                genres_str = " ".join([str(g) for g in genres_list]).upper()
                
                if "MANHWA" in tags_str or "WEBTOON" in tags_str or "MANHWA" in genres_str or "WEBTOON" in genres_str:
                    format_type = "webtoon"
        except Exception:
            pass # Si la déduction échoue, on l'ignore silencieusement sans tuer la fiche !

        return {
            'summary': data.get('description', ''),
            'cover_url': cover_url,
            'genres': genres_list,
            'tags': tags_list[:15],
            'year': year,
            'status': str(data.get('status')).upper() if data.get('status') else None,
            'staff': staff,
            'characters': [],
            'alternative_titles': alt_titles,
            'mangabaka_id': data.get('id'),
            'anilist_id': anilist_id,
            'mal_id': mal_id,
            'links': links,
            'format': format_type
        }

    except Exception as e:
        # On remplace le print par un logging pour voir l'erreur dans l'UI au cas où ça arrive encore !
        import logging
        logging.error(f"[Erreur MangaBaka V2] {e}")
        return None