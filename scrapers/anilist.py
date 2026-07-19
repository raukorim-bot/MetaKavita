import requests
import re
from scrapers import clean_title

def fetch_anilist_extended(title_or_id):
    is_id = str(title_or_id).isdigit()
    
    if is_id:
        print(f"[Anilist] Requête directe par ID : {title_or_id}")
        query = '''
        query ($id: Int) {
          Media(id: $id, type: MANGA) {
            id
            idMal
            description(asHtml: false)
            coverImage { extraLarge }
            genres
            tags { name }
            startDate { year }
            status
            isAdult
            countryOfOrigin
            staff { edges { role node { name { full } } } }
            characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
            externalLinks { url site }
          }
        }
        '''
        variables = {'id': int(title_or_id)}
    else:
        clean = clean_title(title_or_id)
        print(f"[Anilist] Recherche par titre : '{clean}'")
        query = '''
        query ($search: String) {
          Media(search: $search, type: MANGA) {
            id
            idMal
            description(asHtml: false)
            coverImage { extraLarge }
            genres
            tags { name }
            startDate { year }
            status
            isAdult
            countryOfOrigin
            staff { edges { role node { name { full } } } }
            characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
            externalLinks { url site }
          }
        }
        '''
        variables = {'search': clean}

    try:
        response = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables}, timeout=10)
        if response.status_code == 200:
            data = response.json().get('data', {}).get('Media')
            if data:
                return {
                    'summary': data.get('description', ''),
                    'cover_url': data.get('coverImage', {}).get('extraLarge'),
                    'genres': data.get('genres', []),
                    'tags': [t['name'] for t in data.get('tags', [])],
                    'year': data.get('startDate', {}).get('year'),
                    'status': data.get('status'),
                    'staff': data.get('staff', {}).get('edges', []),
                    'characters': data.get('characters', {}).get('edges', []),
                    'age_rating': 'pornographic' if data.get('isAdult') else 'safe',
                    'format': data.get('countryOfOrigin'),
                    'publisher': None,
                    'anilist_id': data.get('id'),
                    'mal_id': data.get('idMal'),
                    'external_links': [{'url': link['url'], 'site': link['site']} for link in data.get('externalLinks', [])] if data.get('externalLinks') else []
                }
    except Exception as e:
        print(f"[Erreur Anilist] {e}")
    return None