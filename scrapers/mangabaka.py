import requests
from scrapers.anilist import clean_title

def fetch_mangabaka(title_or_id):
    # La bonne URL de base pour les IDs
    base_url = "https://api.mangabaka.org/v2/series"
    # La bonne URL pour la recherche
    search_url = "https://api.mangabaka.org/v2/series/search"
    
    is_id = str(title_or_id).isdigit()
    
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

        # 1. Extraction de la couverture HD (clé 'raw' selon notre test)
        cover_url = None
        cover_data = data.get('cover')
        if isinstance(cover_data, dict):
            cover_url = cover_data.get('raw') or cover_data.get('original') or cover_data.get('large')
        elif isinstance(cover_data, str):
            cover_url = cover_data

        # 2. Extraction du Staff
        staff = []
        for author in data.get('authors', []):
            if isinstance(author, dict): author = author.get('name', '')
            if author: staff.append({"role": "Story", "node": {"name": {"full": author}}})
            
        for artist in data.get('artists', []):
            if isinstance(artist, dict): artist = artist.get('name', '')
            if artist: staff.append({"role": "Art", "node": {"name": {"full": artist}}})

        # 3. Extraction de l'année depuis 'published'
        year = None
        published = data.get('published', {})
        if isinstance(published, dict) and published.get('start_date'):
            year = int(str(published['start_date'])[:4]) # On prend juste "2018" dans "2018-03-05"

        # 4. Extraction des titres alternatifs
        alt_titles = []
        for t in data.get('titles', []):
            if isinstance(t, dict) and t.get('title'):
                alt_titles.append(t['title'])

        return {
            'summary': data.get('description', ''),
            'cover_url': cover_url,
            'genres': data.get('genres', []),
            'tags': data.get('tags', [])[:15] if data.get('tags') else [],
            'year': year,
            'status': str(data.get('status')).upper() if data.get('status') else None,
            'staff': staff,
            'characters': [],
            'alternative_titles': alt_titles
        }

    except Exception as e:
        print(f"[Erreur MangaBaka V2] {e}")
        return None