import requests
import logging
from .base import BaseScraper
from .utils import clean_title
from typing import Optional

class MangaBakaScraper(BaseScraper):
    id = "MANGABAKA"
    display_name = "MangaBaka (API / Rapide)"
    supported_types = {"Manga"}
    rate_limit = 2.5
    proxy_domains = ["mangabaka.org"]
    has_direct_id_support = True

    def extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrait l'ID (ex: 2027) d'une URL mangabaka.org"""
        if "mangabaka.org" in url:
            # Enlève les paramètres éventuels ?q=... et prend le dernier élément
            return url.split('?')[0].rstrip('/').split('/')[-1]
        return None

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False):
        base_url = "https://api.mangabaka.org/v2/series"
        search_url = "https://api.mangabaka.org/v2/series/search"
        
        try:
            if is_id:
                logging.info(f"[MangaBaka V2] Requête directe par ID : {query}")
                res = requests.get(f"{base_url}/{query}", timeout=10)
                if res.status_code != 200: return None
                json_res = res.json()
                data = json_res.get('data') if 'data' in json_res else json_res
            else:
                clean = clean_title(query, library_type=library_type)
                logging.info(f"[MangaBaka V2] Recherche par titre : '{clean}'")
                res = requests.get(search_url, params={"q": clean}, timeout=10)
                if res.status_code != 200: return None
                json_res = res.json()
                results = json_res.get('data') if 'data' in json_res else json_res
                
                if isinstance(results, list) and len(results) > 0:
                    data = results[0]
                elif isinstance(results, dict):
                    data = results
                else:
                    return None

            if not data: return None

            cover_url = None
            cover_data = data.get('cover')
            if isinstance(cover_data, dict):
                cover_url = cover_data.get('raw') or cover_data.get('original') or cover_data.get('large')
            elif isinstance(cover_data, str):
                cover_url = cover_data

            staff = []
            for author in data.get('authors', []):
                if isinstance(author, dict): author = author.get('name', '')
                if author: staff.append({"role": "Story", "node": {"name": {"full": author}}})
            for artist in data.get('artists', []):
                if isinstance(artist, dict): artist = artist.get('name', '')
                if artist: staff.append({"role": "Art", "node": {"name": {"full": artist}}})

            year = None
            published = data.get('published', {})
            if isinstance(published, dict) and published.get('start_date'):
                year = int(str(published['start_date'])[:4])

            alt_titles = []
            for t in data.get('titles', []):
                if isinstance(t, dict) and t.get('title'):
                    alt_titles.append(t['title'])
                    
            # NOUVEAU : Récupération du titre principal pour le Smart Match
            fetched_title = data.get('name') or data.get('title')
            if not fetched_title and alt_titles:
                fetched_title = alt_titles[0]

            mb_sources = data.get('source', {})
            anilist_id, mal_id = None, None
            if isinstance(mb_sources, dict):
                anilist_id = mb_sources.get('anilist', {}).get('id')
                mal_id = mb_sources.get('mal', {}).get('id')

            format_type = None
            tags_list = data.get('tags') or []
            genres_list = data.get('genres') or []
            
            try:
                mb_type = str(data.get('type', '')).upper()
                if 'MANHWA' in mb_type or 'WEBTOON' in mb_type: format_type = 'webtoon'
                elif 'MANGA' in mb_type: format_type = 'manga'
                if not format_type:
                    tags_str = " ".join([str(t.get('name', t)) if isinstance(t, dict) else str(t) for t in tags_list]).upper()
                    genres_str = " ".join([str(g) for g in genres_list]).upper()
                    if "MANHWA" in tags_str or "WEBTOON" in tags_str or "MANHWA" in genres_str or "WEBTOON" in genres_str:
                        format_type = "webtoon"
            except Exception: pass

            return {
                'title': fetched_title, # 👈 Ajout capital pour le Smart Match
                'summary': data.get('description', ''),
                'cover_url': cover_url,
                'genres': genres_list,
                'tags': tags_list[:15],
                'year': year,
                'status': str(data.get('status')).upper() if data.get('status') else None,
                'staff': staff,
                'characters': [],
                'alternative_titles': alt_titles,
                'mangabaka_id': data.get('id'),
                'anilist_id': anilist_id,
                'mal_id': mal_id,
                'links': data.get('links') or [],
                'format': format_type
            }
        except Exception as e:
            logging.error(f"[Erreur MangaBaka V2] {e}")
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga"):
        covers = []
        clean_sq = clean_title(query, library_type=library_type)
        try:
            res = requests.get("https://api.mangabaka.org/v2/series/search", params={"q": clean_sq}, timeout=10)
            if res.status_code == 200:
                json_res = res.json()
                results = json_res.get('data') if 'data' in json_res else json_res
                if isinstance(results, list):
                    for m in results[:4]:
                        cover_url = None
                        cover_data = m.get('cover', {})
                        if isinstance(cover_data, dict): cover_url = cover_data.get('raw') or cover_data.get('original')
                        elif isinstance(cover_data, str): cover_url = cover_data
                            
                        if cover_url:
                            title = "Inconnu"
                            titles_list = m.get('titles', [])
                            if titles_list and isinstance(titles_list, list) and isinstance(titles_list[0], dict):
                                title = titles_list[0].get('title', 'Inconnu')
                            covers.append({"provider": "MangaBaka", "title": title, "url": cover_url})
        except Exception as e:
            logging.error(f"[Covers] Erreur MangaBaka V2 : {e}")
        return covers