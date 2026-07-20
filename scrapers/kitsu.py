# scrapers/kitsu.py
import requests
import logging
import unicodedata
import difflib
from scrapers import clean_title

def normalize_str(s):
    if not s: return ""
    return "".join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn').strip()

def fetch_kitsu(title_or_id, library_type="Manga"):
    clean = clean_title(title_or_id, library_type=library_type)
    logging.info(f"[Kitsu] Recherche par titre : '{clean}'")

    # On demande jusqu'à 5 résultats pour pouvoir filtrer
    url = "https://kitsu.io/api/edge/manga"
    params = {
        "filter[text]": clean,
        "page[limit]": 5,
        "include": "categories"
    }

    try:
        headers = {"Accept": "application/vnd.api+json"}
        res = requests.get(url, params=params, headers=headers, timeout=10)
        
        if res.status_code != 200:
            logging.warning(f"[Kitsu] Erreur API (Code {res.status_code})")
            return None

        json_res = res.json()
        data_list = json_res.get('data', [])

        if not data_list:
            return None

        # --- FILTRE ANTI FAUX-POSITIFS ---
        norm_query = normalize_str(clean)
        best_match = None
        
        for manga in data_list:
            attrs = manga.get('attributes', {})
            
            # On récupère tous les titres connus pour cette œuvre (Romaji, Anglais, Japonais...)
            titles_to_check = [attrs.get('canonicalTitle', '')]
            if isinstance(attrs.get('titles'), dict):
                titles_to_check.extend(attrs['titles'].values())
                
            for t in titles_to_check:
                norm_t = normalize_str(str(t))
                if not norm_t: continue
                
                # 1. Sous-chaîne exacte (ex: la requête "Naruto" est dans "Naruto Shippuden")
                is_substring = (norm_query in norm_t or norm_t in norm_query) if (len(norm_query) >= 3 and len(norm_t) >= 3) else False
                
                # 2. Similarité globale (ratio difflib > 80%)
                ratio = difflib.SequenceMatcher(None, norm_query, norm_t).ratio()
                
                if is_substring or ratio >= 0.80:
                    best_match = manga
                    break # On a trouvé notre bonheur, on sort de la boucle des titres
                    
            if best_match:
                break # On sort de la boucle des résultats

        if not best_match:
            logging.warning(f"[Kitsu] ⚠️ Faux positif écarté pour '{clean}' (Aucun résultat suffisamment proche).")
            return None
            
        # Si on est ici, on a une vraie correspondance !
        attrs = best_match.get('attributes', {})

        # Mappage du statut
        raw_status = attrs.get('status', '')
        status = "RELEASING"
        if raw_status == "finished": status = "FINISHED"
        elif raw_status in ["tba", "unreleased", "hiatus"]: status = "HIATUS"
        elif raw_status == "cancelled": status = "CANCELLED"

        # Année
        year = None
        start_date = attrs.get('startDate')
        if start_date:
            year = int(start_date[:4])

        # Format
        format_type = None
        manga_type = attrs.get('mangaType', '').lower()
        if manga_type in ['manhwa', 'manhua', 'webtoon']:
            format_type = 'webtoon'
        elif manga_type == 'manga':
            format_type = 'manga'

        # Classification d'âge
        age_rating = "safe"
        raw_age = attrs.get('ageRating', '')
        if raw_age in ['R', 'R18']: age_rating = "pornographic"
        elif raw_age == 'PG': age_rating = "suggestive"

        # Tags (extraits des 'included')
        tags = []
        included = json_res.get('included', [])
        for item in included:
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