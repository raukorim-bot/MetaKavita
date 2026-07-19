import requests
import logging
from scrapers.anilist import fetch_anilist_extended
from scrapers.nautiljon import fetch_nautiljon
from scrapers.mangabaka import fetch_mangabaka
from config_manager import load_config
from translations import translations

# --- LE REGISTRE DES PROVIDERS ---
PROVIDERS_MAP = {
    "MANGABAKA": fetch_mangabaka,
    "NAUTILJON": fetch_nautiljon,
    "ANILIST": fetch_anilist_extended
}

# Liste blanche dynamique pour la sécurité du Proxy d'images (SSRF)
ALLOWED_PROXY_DOMAINS = [
    "mangabaka.org",
    "nautiljon.com",
    "anilist.co",
    "mangadex.org" # (En prévision)
]

def fetch_metadata(query, providers_list, smart_fusion=False):
    master_data = None
    used_providers = []
    
    # 1. Le scraper a-t-il ramené des données VRAIMENT utiles ? (Anti-fantôme)
    def has_useful_data(d):
        return bool(d.get('summary') or d.get('genres') or d.get('cover_url') or d.get('staff') or d.get('year'))

    # 2. Le dictionnaire est-il parfait à 100% ?
    def is_complete(d):
        return bool(d.get('summary') and d.get('genres') and d.get('cover_url') and d.get('year') and d.get('staff'))

    for p in providers_list:
        fetch_func = PROVIDERS_MAP.get(p)
        if not fetch_func:
            continue
            
        data = fetch_func(query)
        
        # NOUVEAU : On ignore les résultats si la page trouvée est vide de métadonnées
        if data and has_useful_data(data):
            used_providers.append(p)
            
            if not master_data:
                # Il devient la Base
                master_data = data
                master_data['_provider_used'] = p
                if not smart_fusion or is_complete(master_data):
                    break
            else:
                # Il sert pour la Fusion
                filled_something = False
                for key, value in data.items():
                    if not master_data.get(key) and value:
                        master_data[key] = value
                        filled_something = True
                
                if filled_something:
                    master_data['_fusion_providers'] = master_data.get('_fusion_providers', []) + [p]
                
                if is_complete(master_data):
                    break

    return master_data, used_providers

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