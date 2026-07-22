import logging
from scrapers import ScraperRegistry
from config_manager import load_config
from translations import translations

ALLOWED_PROXY_DOMAINS = ScraperRegistry.get_all_proxy_domains()

def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None, library_type="Manga", is_forced_id=False, forced_provider="AUTO"):
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])

    master_data = {}
    used_providers = []
    base_provider_set = False
    
    accumulated_ids = {'anilist_id': None, 'mal_id': None, 'mangabaka_id': None}
    accumulated_links = set()
    
    def has_useful_data(d):
        return bool(d.get('summary') or d.get('genres') or d.get('cover_url') or d.get('staff') or d.get('year'))

    for p in providers_list:
        scraper = ScraperRegistry.get(p)
        if not scraper:
            continue
            
        if library_type not in scraper.supported_types and "Manga" not in scraper.supported_types:
            if is_forced_id and forced_provider == p:
                msg = t.get('log_scraper_type_bypass', "⚠️ [Scraper {0}] Forçage du type '{1}'")
                logging.warning(msg.format(p, library_type))
            else:
                continue
                
        # =========================================================
        # --- LOGIQUE CHIRURGICALE (URL, ID ou TITRE) ---
        # =========================================================
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
                # C'est un ID brut (ex: 86865 ou slug).
                # Comme la liste des providers a DÉJÀ été filtrée par app.py pour ne garder 
                # que ceux qui gèrent les IDs, on envoie cet ID à tout le monde !
                provider_query = raw_input
                is_id_search = True
        else:
            provider_query = query
            is_id_search = False
            
        if not provider_query:
            continue
            
        # --- EXÉCUTION DU SCRAPING ---
        try:
            data = scraper.fetch(provider_query, library_type=library_type, is_id=is_id_search)
        except Exception as e:
            logging.error(f"❌ [Scraper {p}] Erreur lors de la récupération pour '{provider_query}': {e}")
            data = None
            
        # --- TRAITEMENT DES RÉSULTATS ---
        if data and has_useful_data(data):
            
            # =========================================================
            # --- VÉRIFICATION INTELLIGENTE (SMART ID MATCHING) ---
            # =========================================================
            # Si on a cherché par ID brut et qu'on est en mode AUTO, on vérifie que le résultat correspond bien à notre manga !
            if is_id_search and forced_provider == 'AUTO' and not str(query).startswith("http"):
                from scrapers.utils import calculate_similarity
                
                # On utilise list() pour créer une copie et ne pas modifier le dict d'origine avec l'append
                fetched_titles = list(data.get('alternative_titles', []))
                if data.get('title'):
                    fetched_titles.append(data['title'])
                    
                match_found = False
                for fetched_title in fetched_titles:
                    if not fetched_title: continue
                    similarity = calculate_similarity(fallback_query, fetched_title)
                    if similarity >= 0.50:  # Seuil de 50%
                        match_found = True
                        logging.info(f"🎯 [Smart ID] Match validé avec {p} (Score: {int(similarity*100)}%) sur '{fetched_title}'")
                        break
                        
                if not match_found:
                    logging.warning(f"⏭️ [Smart ID] L'ID {provider_query} sur {p} renvoie une œuvre différente. On ignore et on teste le suivant.")
                    continue # On rejette ce scraper et on passe au suivant de la cascade !
            
            # ---------------------------------------------------------
            used_providers.append(p)
            
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

    # --- RETOUR FINAL ---
    if base_provider_set:
        for id_key, id_val in accumulated_ids.items():
            if id_val: master_data[id_key] = id_val
        master_data['accumulated_links'] = list(accumulated_links)
        return master_data, used_providers
        
    return None, used_providers