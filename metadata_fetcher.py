import logging
import time
from scrapers import ScraperRegistry
from config_manager import load_config
from translations import translations

ALLOWED_PROXY_DOMAINS = ScraperRegistry.get_all_proxy_domains()

# 🎯 DÉCTIONNAIRE D'HORODATAGE GLOBAL (Mémoire des derniers appels par scraper)
LAST_REQUEST_TIMES = {}

def throttle_provider(scraper):
    """
    Attend uniquement le temps strictement nécessaire pour respecter le rate_limit 
    du scraper ciblé. Si l'API était inactive, délai = 0.0s !
    """
    now = time.time()
    last_call = LAST_REQUEST_TIMES.get(scraper.id, 0.0)
    elapsed = now - last_call
    required_delay = getattr(scraper, 'rate_limit', 1.0)
    
    if elapsed < required_delay:
        sleep_needed = required_delay - elapsed
        time.sleep(sleep_needed)
        
    LAST_REQUEST_TIMES[scraper.id] = time.time()

def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None, library_type="Manga", is_forced_id=False, forced_provider="AUTO", existing_metadata=None):
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])

    master_data = {}
    used_providers = []
    base_provider_set = False
    
    accumulated_ids = {'anilist_id': None, 'mal_id': None, 'mangabaka_id': None}
    accumulated_links = set()
    
    current_existing = existing_metadata.copy() if existing_metadata else {}

    def has_useful_data(d):
        return bool(d.get('summary') or d.get('genres') or d.get('cover_url') or d.get('staff') or d.get('year'))

    for p in providers_list:
        scraper = ScraperRegistry.get(p)
        if not scraper:
            continue
            
        if library_type not in scraper.supported_types and "Manga" not in scraper.supported_types:
            if forced_provider == p or is_forced_id:
                msg = t.get('log_scraper_type_bypass', "⚠️ [Scraper {0}] Forçage du type '{1}'")
                logging.warning(msg.format(p, library_type))
            else:
                continue
                
        is_id_search = False
        provider_query = query
        
        if is_forced_id:
            raw_input = query 
            if str(raw_input).startswith("http://") or str(raw_input).startswith("https://"):
                extracted_id = scraper.extract_id_from_url(raw_input)
                if extracted_id:
                    provider_query = extracted_id
                    is_id_search = True
                else:
                    msg_skip = t.get('log_url_not_recognized', "⏭️ [Scraper {0}] URL non reconnue, on passe.")
                    logging.info(msg_skip.format(p))
                    continue
            else:
                provider_query = raw_input
                is_id_search = True
        else:
            provider_query = query
            is_id_search = False
            
        if not provider_query:
            continue
            
        # ⚡ REGULATION DYNAMIQUE : On n'attend QUE si l'API de CE scraper a été appelée trop récemment !
        throttle_provider(scraper)

        try:
            data = scraper.fetch(provider_query, library_type=library_type, is_id=is_id_search, existing_metadata=current_existing)
        except Exception as e:
            logging.error(f"❌ [Scraper {p}] Erreur lors de la récupération pour '{provider_query}': {e}")
            data = None
            
        if data and has_useful_data(data):
            used_providers.append(p)
            
            if data.get('isbn') and not current_existing.get('isbn'):
                current_existing['isbn'] = data['isbn']
            if data.get('staff') and not current_existing.get('authors'):
                current_existing['authors'] = [s['node']['name']['full'] for s in data['staff'] if isinstance(s, dict) and s.get('node', {}).get('name', {}).get('full')]

            for id_key in ['anilist_id', 'mal_id', 'mangabaka_id']:
                if data.get(id_key) and not accumulated_ids[id_key]:
                    accumulated_ids[id_key] = data[id_key]
                    
            if data.get('url'): 
                accumulated_links.add(data['url'])
            if data.get('links'):
                for link in data['links']:
                    if link: accumulated_links.add(link)
            if data.get('external_links'):
                for link_obj in data['external_links']:
                    if isinstance(link_obj, dict) and link_obj.get('url'):
                        accumulated_links.add(link_obj['url'])
                    elif isinstance(link_obj, str):
                        accumulated_links.add(link_obj)

            if not base_provider_set:
                master_data = data.copy()
                master_data['_provider_used'] = p
                base_provider_set = True
            else:
                if smart_fusion:
                    filled_something = False
                    for key, value in data.items():
                        if key in ['_provider_used', '_fusion_providers', 'anilist_id', 'mal_id', 'mangabaka_id', 'links', 'external_links', 'url']:
                            continue
                        if not master_data.get(key) and value:
                            master_data[key] = value
                            filled_something = True
                    
                    if filled_something:
                        master_data['_fusion_providers'] = master_data.get('_fusion_providers', []) + [p]

    if base_provider_set:
        for id_key, id_val in accumulated_ids.items():
            if id_val: master_data[id_key] = id_val
        master_data['accumulated_links'] = list(accumulated_links)
        return master_data, used_providers
        
    return None, used_providers