import requests
import logging
from scrapers.anilist import fetch_anilist_extended
from scrapers.nautiljon import fetch_nautiljon
from scrapers.mangabaka import fetch_mangabaka # <-- NOUVEAU
from config_manager import load_config
from translations import translations

def fetch_metadata(query, provider="ANILIST"):
    if provider == "NAUTILJON":
        return fetch_nautiljon(query)
    elif provider == "MANGABAKA": # <-- NOUVEAU
        return fetch_mangabaka(query)
    else:
        return fetch_anilist_extended(query)


def translate_text(text, api_key, target_lang="FR"):
    if not text or not api_key: 
        return text
        
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    
    text = text.replace('<br>', '\n').replace('<i>', '').replace('</i>', '')
    url = "https://api-free.deepl.com/v2/translate"
    headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
    payload = {"text": [text], "target_lang": target_lang}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()['translations'][0]['text']
        
        elif response.status_code == 403:
            logging.error(t.get('log_deepl_403'))
        elif response.status_code == 456:
            logging.error(t.get('log_deepl_456'))
        else:
            logging.warning(t.get('log_deepl_fail').format(response.status_code, response.text))
            
    except requests.exceptions.Timeout:
        logging.warning(t.get('log_deepl_timeout'))
    except Exception as e:
        logging.error(t.get('log_deepl_crash').format(e))
    
    return text