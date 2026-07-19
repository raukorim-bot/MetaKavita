# metadata_fetcher.py

import requests
import logging
from scrapers.anilist import fetch_anilist_extended
from scrapers.nautiljon import fetch_nautiljon
from scrapers.mangabaka import fetch_mangabaka
from config_manager import load_config
from translations import translations

PROVIDERS_MAP = {
    "MANGABAKA": fetch_mangabaka,
    "NAUTILJON": fetch_nautiljon,
    "ANILIST": fetch_anilist_extended
}

ALLOWED_PROXY_DOMAINS = [
    "mangabaka.org",
    "nautiljon.com",
    "anilist.co",
    "mangadex.org"
]

def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None):
    master_data = {}
    used_providers = []
    base_provider_set = False
    
    # Structures d'accumulation globale des identités
    accumulated_ids = {
        'anilist_id': None,
        'mal_id': None,
        'mangabaka_id': None
    }
    accumulated_links = set()
    
    def has_useful_data(d):
        return bool(d.get('summary') or d.get('genres') or d.get('cover_url') or d.get('staff') or d.get('year'))

    for p in providers_list:
        fetch_func = PROVIDERS_MAP.get(p)
        if not fetch_func:
            continue
            
        # Résolution de la requête selon le type d'identifiant et de fournisseur
        is_id = str(query).isdigit()
        if is_id:
            # Si c'est un ID, seul le scraper AniList peut l'utiliser directement.
            # Les autres basculent sur le titre d'origine.
            provider_query = query if p == "ANILIST" else fallback_query
        else:
            provider_query = query
            
        if not provider_query:
            continue
            
        try:
            data = fetch_func(provider_query)
        except Exception as e:
            logging.error(f"❌ [Scraper {p}] Erreur lors de la récupération pour '{provider_query}': {e}")
            data = None
            
        if data and has_useful_data(data):
            used_providers.append(p)
            
            # 1. Accumulation des identifiants uniques
            for id_key in ['anilist_id', 'mal_id', 'mangabaka_id']:
                if data.get(id_key) and not accumulated_ids[id_key]:
                    accumulated_ids[id_key] = data[id_key]
                    
            # 2. Accumulation de tous les liens web uniques
            if data.get('url'):
                accumulated_links.add(data['url'])
                
            # Liens explicites de la clé 'links' (ex: MangaBaka)
            if data.get('links'):
                for link in data['links']:
                    if link:
                        accumulated_links.add(link)
                        
            # Liens explicites d'AniList
            if data.get('external_links'):
                for link_obj in data['external_links']:
                    if isinstance(link_obj, dict) and link_obj.get('url'):
                        accumulated_links.add(link_obj['url'])
                    elif isinstance(link_obj, str):
                        accumulated_links.add(link_obj)

            # 3. Fusion et attribution des données de fiches standards
            if not base_provider_set:
                master_data = data.copy()
                master_data['_provider_used'] = p
                base_provider_set = True
            else:
                if smart_fusion:
                    filled_something = False
                    for key, value in data.items():
                        # On ignore les champs d'identités gérés par l'accumulateur global
                        if key in ['_provider_used', '_fusion_providers', 'anilist_id', 'mal_id', 'mangabaka_id', 'links', 'external_links', 'url']:
                            continue
                        if not master_data.get(key) and value:
                            master_data[key] = value
                            filled_something = True
                    
                    if filled_something:
                        master_data['_fusion_providers'] = master_data.get('_fusion_providers', []) + [p]

    # Injection des identifiants et des liens accumulés dans le résultat final
    if base_provider_set:
        for id_key, id_val in accumulated_ids.items():
            if id_val:
                master_data[id_key] = id_val
        master_data['accumulated_links'] = list(accumulated_links)
        return master_data, used_providers
        
    return None, used_providers


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