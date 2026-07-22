import requests
import logging
from .base import BaseScraper
from .utils import clean_title
from typing import Optional

class AnilistScraper(BaseScraper):
    id = "ANILIST"
    display_name = "AniList (International)"
    supported_types = {"Manga", "Comic", "Book"}
    rate_limit = 1.0
    proxy_domains = ["anilist.co"]
    has_direct_id_support = True

    def extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrait l'ID (ex: 119161) d'une URL anilist.co"""
        if "anilist.co/manga/" in url:
            # Sépare à partir de 'anilist.co/manga/' et prend le premier bloc numérique
            parts = url.split('anilist.co/manga/')[-1].split('/')
            if parts and parts[0].isdigit():
                return parts[0]
        return None    

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False):
        if is_id:
            # --- GESTION ID vs SLUG ---
            if str(query).isdigit():
                logging.info(f"[Anilist] Requête directe par ID : {query}")
                graphql_query = '''
                query ($id: Int) {
                  Media(id: $id, type: MANGA) {
                    id idMal description(asHtml: false) coverImage { extraLarge } title { romaji english native }
                    genres tags { name } startDate { year } status isAdult countryOfOrigin
                    staff { edges { role node { name { full } } } }
                    characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
                    externalLinks { url site }
                  }
                }
                '''
                variables = {'id': int(query)}
            else:
                logging.info(f"[Anilist] Requête directe par Slug : '{query}'")
                graphql_query = '''
                query ($search: String) {
                  Media(search: $search, type: MANGA) {
                    id idMal description(asHtml: false) coverImage { extraLarge } title { romaji english native }
                    genres tags { name } startDate { year } status isAdult countryOfOrigin
                    staff { edges { role node { name { full } } } }
                    characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
                    externalLinks { url site }
                  }
                }
                '''
                variables = {'search': str(query)}
        else:
            # --- RECHERCHE CLASSIQUE ---
            clean = clean_title(query, library_type=library_type)
            logging.info(f"[Anilist] Recherche par titre ({library_type}) : '{clean}'")
            graphql_query = '''
            query ($search: String) {
              Media(search: $search, type: MANGA) {
                id idMal description(asHtml: false) coverImage { extraLarge } title { romaji english native }
                genres tags { name } startDate { year } status isAdult countryOfOrigin
                staff { edges { role node { name { full } } } }
                characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
                externalLinks { url site }
              }
            }
            '''
            variables = {'search': clean}

        try:
            response = requests.post('https://graphql.anilist.co', json={'query': graphql_query, 'variables': variables}, timeout=10)
            if response.status_code == 200:
                data = response.json().get('data', {}).get('Media')
                if data:
                    return {
                        'title': data.get('title', {}).get('romaji', ''),
                        'alternative_titles': [t for t in data.get('title', {}).values() if t],
                        'summary': data.get('description', ''),
                        'cover_url': data.get('coverImage', {}).get('extraLarge'),
                        'genres': data.get('genres', []),
                        'tags': [t['name'] for t in data.get('tags', [])],
                        'year': data.get('startDate', {}).get('year'),
                        'status': data.get('status'),
                        'staff': data.get('staff', {}).get('edges', []),
                        'characters': data.get('characters', {}).get('edges', []),
                        'age_rating': 'pornographic' if data.get('isAdult') else 'safe',
                        'format': data.get('countryOfOrigin'),
                        'publisher': None,
                        'anilist_id': data.get('id'),
                        'mal_id': data.get('idMal'),
                        'external_links': [{'url': link['url'], 'site': link['site']} for link in data.get('externalLinks', [])] if data.get('externalLinks') else []
                    }
        except Exception as e:
            logging.error(f"[Erreur Anilist] {e}")
        return None

    def fetch_covers(self, query: str, library_type: str = "Manga"):
        covers = []
        clean = clean_title(query, library_type=library_type)
        try:
            graphql_query = '''
            query ($search: String) {
              Page(page: 1, perPage: 4) {
                media(search: $search, type: MANGA) {
                  title { romaji }
                  coverImage { extraLarge }
                }
              }
            }
            '''
            res = requests.post('https://graphql.anilist.co', json={'query': graphql_query, 'variables': {'search': clean}}, timeout=10)
            if res.status_code == 200:
                results = res.json().get('data', {}).get('Page', {}).get('media', [])
                for m in results:
                    if m.get('coverImage', {}).get('extraLarge'):
                        covers.append({
                            "provider": "AniList", 
                            "title": m.get('title', {}).get('romaji', 'Inconnu'),
                            "url": m['coverImage']['extraLarge']
                        })
        except Exception as e:
            logging.error(f"[Covers] Erreur AniList : {e}")
        return covers