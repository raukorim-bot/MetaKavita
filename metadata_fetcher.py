import requests
from scrapers.anilist import fetch_anilist_extended
from scrapers.nautiljon import fetch_nautiljon

def fetch_metadata(query, provider="ANILIST"):
    if provider == "NAUTILJON":
        return fetch_nautiljon(query)
    else:
        return fetch_anilist_extended(query)

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
