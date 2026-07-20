import requests
import logging
import inspect
from scrapers.anilist import fetch_anilist_extended
from scrapers.mangabaka import fetch_mangabaka
from scrapers.kitsu import fetch_kitsu  # <-- Kitsu à la rescousse !
from scrapers.comicvine import scrape_data as fetch_comicvine
from scrapers.googlebooks import scrape_data as fetch_googlebooks
from config_manager import load_config
from translations import translations
from translator import translate_text

PROVIDERS_MAP = {
    "Manga": {
        "MANGABAKA": fetch_mangabaka,
        "KITSU": fetch_kitsu,       # <-- Bye MAL !
        "ANILIST": fetch_anilist_extended
    },
    "Comic": {
        "COMICVINE": fetch_comicvine,
        "GOOGLEBOOKS": fetch_googlebooks,
        "ANILIST": fetch_anilist_extended
    },
    "Book": {
        "GOOGLEBOOKS": fetch_googlebooks,
        "ANILIST": fetch_anilist_extended
    }
}

ALLOWED_PROXY_DOMAINS = [
    "mangabaka.org",
    "anilist.co",
    "mangadex.org",
    "comicvine.gamespot.com",
    "gamespot.com",
    "books.google.com",
    "kitsu.io",         # <-- Kitsu
    "media.kitsu.app",  # <-- Kitsu CDN
    "media.kitsu.io"    # <-- Kitsu CDN
]

def get_scraper_engine(library_type, provider_name):
    """
    Factory Pattern : Retourne la fonction de scraping appropriée pour le type de bibliothèque
    et le nom du fournisseur souhaité. Gère de manière robuste les replis vers la catégorie Manga.
    """
    lib_type = library_type if library_type else "Manga"
    
    # 1. Vérification si la catégorie de bibliothèque existe dans PROVIDERS_MAP, sinon repli sur Manga
    target_lib_type = lib_type if lib_type in PROVIDERS_MAP else "Manga"
    lib_providers = PROVIDERS_MAP[target_lib_type]
    
    # 2. Si le fournisseur est enregistré dans cette catégorie, on le retourne
    if provider_name in lib_providers:
        return lib_providers[provider_name]
        
    # 3. Repli intelligent : Recherche du fournisseur dans la catégorie Manga par défaut
    manga_providers = PROVIDERS_MAP["Manga"]
    if provider_name in manga_providers:
        return manga_providers[provider_name]
        
    # 4. Fallback ultime
    return None

def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None, library_type="Manga", is_forced_id=False):
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
        fetch_func = get_scraper_engine(library_type, p)
        if not fetch_func:
            continue
            
        # Résolution de la requête via le flag is_forced_id passé par app.py
        if is_forced_id:
            # Si c'est un ID, seul le scraper AniList peut l'utiliser directement.
            # Les autres basculent sur le titre d'origine.
            provider_query = query if p == "ANILIST" else fallback_query
        else:
            provider_query = query
            
        if not provider_query:
            continue
            
        try:
            sig = inspect.signature(fetch_func)
            kwargs = {}
            if "library_type" in sig.parameters:
                kwargs["library_type"] = library_type
            if "is_id" in sig.parameters:
                kwargs["is_id"] = is_forced_id
                
            data = fetch_func(provider_query, **kwargs)
            
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
                
            # Liens de la clé 'links' (ex: MangaBaka)
            if data.get('links'):
                for link in data['links']:
                    if link:
                        accumulated_links.add(link)
                        
            # Liens d'AniList
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
        
    return None, used_providers# metadata_fetcher.py
