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

    def run_cascade(current_query, is_id_search_forced):
        nonlocal base_provider_set, master_data
        for p in providers_list:
            scraper = ScraperRegistry.get(p)
            if not scraper:
                continue
                
            if library_type not in scraper.supported_types and "Manga" not in scraper.supported_types:
                if forced_provider == p or is_id_search_forced:
                    msg = t.get('log_scraper_type_bypass', "⚠️ [Scraper {0}] Forçage du type '{1}'")
                    logging.warning(msg.format(p, library_type))
                else:
                    continue
                    
            is_id_search = False
            provider_query = current_query
            
            if is_id_search_forced:
                raw_input = current_query 
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
                provider_query = current_query
                is_id_search = False
                
            if not provider_query:
                continue
                
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

    # --- 1ER PASSAGE CLASSIQUE ---
    run_cascade(query, is_forced_id)

    # --- 2ÈME PASSAGE : TITRE DE SECOURS (TRADUCTION) ---
    # Si on n'a rien trouvé + Option cochée + Ce n'est pas un ID forcé
    if not base_provider_set and config.get('TITLE_FALLBACK_TRANSLATION') and not is_forced_id:
        from translator import translate_text
        # On force la traduction en anglais car c'est la langue pivot des API asiatiques
        translated_query = translate_text(query, target_lang="EN")
        
        # On vérifie que la traduction a donné un vrai résultat différent de la requête d'origine
        if translated_query and translated_query.strip().lower() != query.strip().lower():
            msg_fallback = t.get('log_title_fallback', "🔄 [Fallback] Aucun résultat pour '{0}'. Traduction automatique tentée : '{1}'")
            logging.info(msg_fallback.format(query, translated_query))
            
            # On relance exactement la même cascade, mais avec le titre traduit
            run_cascade(translated_query, False)
            
            # Si on a trouvé, on ajoute une petite mention au provider pour que ça se voie dans les logs
            if base_provider_set and '_provider_used' in master_data:
                master_data['_provider_used'] += " (Titre Traduit)"

    if base_provider_set:
        for id_key, id_val in accumulated_ids.items():
            if id_val: master_data[id_key] = id_val
        master_data['accumulated_links'] = list(accumulated_links)
        return master_data, used_providers
        
    return None, used_providers