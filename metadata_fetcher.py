import requests
import re

def clean_title(title):
    title = re.sub(r'\(.*?\)', '', title)
    title = re.sub(r'\[.*?\]', '', title)
    title = re.sub(r'(Vol\.|Tome)\s*\d+', '', title, flags=re.IGNORECASE)
    return title.strip()

def fetch_anilist_extended(title_or_id):
    # On détecte si l'argument est un ID numérique forcé
    is_id = str(title_or_id).isdigit()
    
    if is_id:
        print(f"[Anilist] Requête directe par ID : {title_or_id}")
        query = '''
        query ($id: Int) {
          Media(id: $id, type: MANGA) {
            description(asHtml: false)
            genres
            tags { name }
            startDate { year }
            status
            staff { edges { role node { name { full } } } }
            characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
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
            description(asHtml: false)
            genres
            tags { name }
            startDate { year }
            status
            staff { edges { role node { name { full } } } }
            characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
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
                    'genres': data.get('genres', []),
                    'tags': [t['name'] for t in data.get('tags', [])],
                    'year': data.get('startDate', {}).get('year'),
                    'status': data.get('status'),
                    'staff': data.get('staff', {}).get('edges', []),
                    'characters': data.get('characters', {}).get('edges', [])
                }
    except Exception as e:
        print(f"[Erreur Anilist] {e}")
    return None

def translate_text(text, api_key, target_lang="FR"):
    if not text or not api_key: 
        return text
        
    text = text.replace('<br>', '\n').replace('<i>', '').replace('</i>', '')
    url = "https://api-free.deepl.com/v2/translate"
    headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
    payload = {"text": [text], "target_lang": target_lang}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()['translations'][0]['text']
    except Exception as e:
        print(f"[Erreur API DeepL] {e}")
    
    return text
