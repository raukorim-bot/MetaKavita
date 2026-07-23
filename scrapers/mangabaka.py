import requests
import logging
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import clean_title, score_candidate

class MangaBakaScraper(BaseScraper):
    id = "MANGABAKA"
    display_name = "MangaBaka (API / Rapide)"
    supported_types = {"Manga"}
    rate_limit = 2.5
    proxy_domains = ["mangabaka.org"]
    has_direct_id_support = True

    translations = {
        "fr": {
            "direct_id": "[MangaBaka V2] Requête directe par ID : {0}",
            "search_title": "[MangaBaka V2] Recherche par titre : '{0}'",
            "err": "[Erreur MangaBaka V2] {0}",
            "covers_err": "[Covers] Erreur MangaBaka V2 : {0}"
        },
        "en": {
            "direct_id": "[MangaBaka V2] Direct request by ID: {0}",
            "search_title": "[MangaBaka V2] Title search: '{0}'",
            "err": "[MangaBaka V2 Error] {0}",
            "covers_err": "[Covers] MangaBaka V2 error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "mangabaka.org" in url:
            return url.split('?')[0].rstrip('/').split('/')[-1]
        return None

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        base_url = "https://api.mangabaka.org/v2/series"
        search_url = "https://api.mangabaka.org/v2/series/search"
        
        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                res = requests.get(f"{base_url}/{query}", timeout=10)
                if res.status_code != 200: return None
                json_res = res.json()
                raw_data = json_res.get('data') if 'data' in json_res else json_res
                return self._build_candidate(raw_data) if raw_data else None

            else:
                clean = clean_title(query, library_type=library_type)
                logging.info(self.t("search_title").format(clean))
                res = requests.get(search_url, params={"q": clean}, timeout=10)
                if res.status_code != 200: return None
                json_res = res.json()
                results = json_res.get('data') if 'data' in json_res else json_res
                
                if not isinstance(results, list) or not results:
                    return None

                best_match = None
                best_score = -1.0

                for item in results:
                    candidate = self._build_candidate(item)
                    if not candidate: continue

                    score = score_candidate(candidate, clean, existing_metadata)
                    if score > best_score:
                        best_score = score
                        best_match = candidate

                if best_match and best_score >= 0.50:
                    return best_match

                return None

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def _build_candidate(self, data: dict) -> Optional[dict]:
        if not data or not isinstance(data, dict):
            return None

        cover_url = None
        cover_data = data.get('cover')
        if isinstance(cover_data, dict):
            cover_url = cover_data.get('raw') or cover_data.get('original') or cover_data.get('large')
        elif isinstance(cover_data, str):
            cover_url = cover_data

        staff = []
        # Sécurisation contre les valeurs 'null' envoyées par l'API MangaBaka
        for author in (data.get('authors') or []):
            if isinstance(author, dict): author = author.get('name', '')
            if author and isinstance(author, str):
                staff.append({"role": "Story", "node": {"name": {"full": author.strip()}}})

        for artist in (data.get('artists') or []):
            if isinstance(artist, dict): artist = artist.get('name', '')
            if artist and isinstance(artist, str):
                staff.append({"role": "Art", "node": {"name": {"full": artist.strip()}}})

        year = None
        published = data.get('published', {})
        if isinstance(published, dict) and published.get('start_date'):
            try:
                year = int(str(published['start_date'])[:4])
            except (ValueError, TypeError):
                pass

        alt_titles = []
        for t in (data.get('titles') or []):
            if isinstance(t, dict) and t.get('title'):
                alt_titles.append(t['title'])
            elif isinstance(t, str) and t.strip():
                alt_titles.append(t.strip())

        fetched_title = data.get('name') or data.get('title') or ""
        if fetched_title and fetched_title not in alt_titles:
            alt_titles.append(fetched_title)

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
            'title': fetched_title or (alt_titles[0] if alt_titles else ""),
            'summary': data.get('description', '') or '',
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

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
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
            logging.error(self.t("covers_err").format(e))
        return covers