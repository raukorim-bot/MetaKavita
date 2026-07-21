import logging
from scrapers import ScraperRegistry

ALLOWED_PROXY_DOMAINS = ScraperRegistry.get_all_proxy_domains()

def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None, library_type="Manga", is_forced_id=False):
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
            
        # Validation du fallback dynamique : 
        # Si le scraper ne supporte pas la catégorie voulue mais supporte les Mangas, on l'accepte en fallback.
        if library_type not in scraper.supported_types and "Manga" not in scraper.supported_types:
            continue
            
        provider_query = query if (is_forced_id and p == "ANILIST") else fallback_query if is_forced_id else query
        if not provider_query:
            continue
            
        try:
            data = scraper.fetch(provider_query, library_type=library_type, is_id=is_forced_id)
        except Exception as e:
            logging.error(f"❌ [Scraper {p}] Erreur lors de la récupération pour '{provider_query}': {e}")
            data = None
            
        if data and has_useful_data(data):
            used_providers.append(p)
            
            for id_key in ['anilist_id', 'mal_id', 'mangabaka_id']:
                if data.get(id_key) and not accumulated_ids[id_key]:
                    accumulated_ids[id_key] = data[id_key]
                    
            if data.get('url'): accumulated_links.add(data['url'])
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