import requests
import logging
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)
from config_manager import load_config, get_max_tags, get_max_genres
from kavita_constants import normalize_provider_status
from secure_logging import safe_exc_str
from url_allowlist import validate_proxied_image_url

class MangaBakaScraper(BaseScraper):
    id = "MANGABAKA"
    is_core = True
    display_name = "MangaBaka (API / Rapide)"
    supported_types = {"Manga", "Book"}
    rate_limit = 2.25  # ~27/min: 10% under MangaBaka search 30/min
    # 1.1.0 : le quota MangaBaka (30/min) se compte par requête, or la cadence
    # n'était appliquée qu'avant `fetch()` ; et un 429 ou une clé d'accès
    # refusée rendaient « aucun résultat » sans un seul journal. La montée de
    # version est ce qui autorise l'image à remplacer la copie 1.0.x déjà
    # installée sous data/.
    version = "1.1.0"
    # API is on *.mangabaka.org; cover/CDN URLs still come back as *.mangabaka.dev
    # (images.mangabaka.org has no DNS yet). Whitelist both so uploads/proxy work.
    proxy_domains = [
        "mangabaka.org",
        "api.mangabaka.org",
        "images.mangabaka.org",
        "cdn.mangabaka.org",
        "mangabaka.dev",
        "api.mangabaka.dev",
        "images.mangabaka.dev",
        "cdn.mangabaka.dev",
    ]
    has_direct_id_support = True
    uses_unified_scoring = True

    translations = {
        "fr": {
            "display_name": "MangaBaka (API / Rapide)",
            "direct_id": "[MangaBaka V2] Requête directe par ID : {0}",
            "search_title": "[MangaBaka V2] Recherche par titre : '{0}'",
            "err": "[Erreur MangaBaka V2] {0}",
            "covers_err": "[Covers] Erreur MangaBaka V2 : {0}"
        },
        "en": {
            "display_name": "MangaBaka (API / Fast)",
            "direct_id": "[MangaBaka V2] Direct request by ID: {0}",
            "search_title": "[MangaBaka V2] Title search: '{0}'",
            "err": "[MangaBaka V2 Error] {0}",
            "covers_err": "[Covers] MangaBaka V2 error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "mangabaka.org" in url or "mangabaka.dev" in url:
            return url.split('?')[0].rstrip('/').split('/')[-1]
        return None

    def _cover_url_allowed(self, url: Optional[str]) -> bool:
        if not url or not isinstance(url, str):
            return False
        ok, _, _ = validate_proxied_image_url(url.strip(), self.proxy_domains)
        return ok

    def _pick_cover_url(self, cover_data) -> Optional[str]:
        """Pick a cover URL that MetaKavita can download under MangaBaka proxy_domains.

        The API often puts a third-party host in ``raw`` (e.g. s4.anilist.co) while
        still exposing MangaBaka CDN imgproxy variants (x350/x250/x150). Prefer
        native/allowed hosts; fall back to imgproxy; never return an off-allowlist URL.
        """
        if isinstance(cover_data, str):
            url = cover_data.strip()
            return url if self._cover_url_allowed(url) else None
        if not isinstance(cover_data, dict):
            return None
        for key in ("raw", "original", "large", "x350", "x250", "x150"):
            url = cover_data.get(key)
            if isinstance(url, str) and url.strip() and self._cover_url_allowed(url):
                return url.strip()
        return None

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        base_url = "https://api.mangabaka.org/v2/series"
        search_url = "https://api.mangabaka.org/v2/series/search"
        
        # --- Détermination du paramètre Publisher (Local vs Global) ---
        config = load_config()
        pub_pref = "LOCALIZED"
        if existing_metadata and existing_metadata.get('publisher_pref') and existing_metadata.get('publisher_pref') != 'GLOBAL':
            pub_pref = existing_metadata.get('publisher_pref')
        else:
            pub_pref = config.get("PUBLISHER_PREFERENCE", "LOCALIZED")
        
        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                # schema=full : champs sources/tags/genres complets (fix LazyGeniusMan / PR communautaire).
                res = self._http_get(requests, f"{base_url}/{query}", params={"schema": "full"}, timeout=10)
                if not response_is_ok(self, res, context="fiche par identifiant"): return None
                json_res = res.json()
                raw_data = json_res.get('data') if 'data' in json_res else json_res
                return attach_match_score(self._build_candidate(raw_data, pub_pref), 1.0) if raw_data else None

            else:
                clean = clean_title(query, library_type=library_type)
                logging.info(self.t("search_title").format(clean))
                # Filtre `type` MangaBaka : évite qu'une recherche Book/LN tombe sur un manga
                # homonyme (et réciproquement).
                type_mapping = {
                    "Manga": ["manga", "manhwa", "manhua"],
                    "Book": "novel",
                    "Comic": ["manga", "manhwa", "manhua"],
                }
                params = {"q": clean, "schema": "full"}
                mangabaka_type = type_mapping.get(library_type)
                if mangabaka_type is not None:
                    params["type"] = mangabaka_type
                res = self._http_get(requests, search_url, params=params, timeout=10)
                if not response_is_ok(self, res, context="recherche par titre"): return None
                json_res = res.json()
                results = json_res.get('data') if 'data' in json_res else json_res
                
                if not isinstance(results, list) or not results:
                    return None

                best_match = None
                best_score = -1.0

                for item in results:
                    candidate = self._build_candidate(item, pub_pref)
                    if not candidate: continue

                    score = score_candidate(candidate, clean, existing_metadata)
                    if score > best_score:
                        best_score = score
                        best_match = candidate

                if best_match and best_score >= get_match_accept_threshold():
                    return attach_match_score(best_match, best_score)

                return None

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def _build_candidate(self, data: dict, pub_pref: str = "LOCALIZED") -> Optional[dict]:
        if not data or not isinstance(data, dict):
            return None

        cover_url = self._pick_cover_url(data.get('cover'))

        staff = []
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
            anilist_id = mb_sources.get('anilist', {}).get('id') if isinstance(mb_sources.get('anilist'), dict) else None
            # schema=full utilise souvent `my_anime_list` ; l'ancien chemin `mal` est gardé
            # en repli pour rester compatible avec les réponses allégées.
            mal_node = mb_sources.get('my_anime_list') or mb_sources.get('mal') or {}
            mal_id = mal_node.get('id') if isinstance(mal_node, dict) else None

        # schema=full : tags unifiés avec drapeau is_genre. Sinon : clés séparées genres/tags.
        raw_tags = data.get('tags') or []
        if raw_tags and isinstance(raw_tags[0], dict) and 'is_genre' in raw_tags[0]:
            tags_list = [tag.get('name') for tag in raw_tags if isinstance(tag, dict) and tag.get('name') and not tag.get('is_genre')]
            genres_list = [tag.get('name') for tag in raw_tags if isinstance(tag, dict) and tag.get('name') and tag.get('is_genre')]
        else:
            tags_list = []
            for tag in raw_tags:
                if isinstance(tag, dict) and tag.get('name'):
                    tags_list.append(tag['name'])
                elif isinstance(tag, str) and tag.strip():
                    tags_list.append(tag.strip())
            genres_list = []
            for g in (data.get('genres') or []):
                if isinstance(g, dict) and g.get('name'):
                    genres_list.append(g['name'])
                elif isinstance(g, str) and g.strip():
                    genres_list.append(g.strip())

        format_type = None
        try:
            mb_type = str(data.get('type', '')).upper()
            if 'MANHWA' in mb_type or 'WEBTOON' in mb_type: format_type = 'webtoon'
            elif 'NOVEL' in mb_type: format_type = 'book'
            elif 'MANGA' in mb_type: format_type = 'manga'
            if not format_type:
                tags_str = " ".join([str(t) for t in tags_list]).upper()
                genres_str = " ".join([str(g) for g in genres_list]).upper()
                if "MANHWA" in tags_str or "WEBTOON" in tags_str or "MANHWA" in genres_str or "WEBTOON" in genres_str:
                    format_type = "webtoon"
        except Exception as e:
            logging.debug("MangaBaka format_type detection failed: %s", safe_exc_str(e))

        # --- GESTION DE L'ÉDITEUR ---
        publisher = None
        orig_pub = None
        loc_pub = None
        
        publishers_list = data.get("publishers") or []
        for pub in publishers_list:
            if isinstance(pub, dict) and pub.get("name"):
                p_name = pub.get("name").strip()
                p_type = str(pub.get("type", "")).lower()
                
                # Si c'est l'original, on garde le PREMIER trouvé
                if "original" in p_type or "ja" in p_type:
                    if not orig_pub:
                        orig_pub = p_name
                # Sinon, c'est une édition localisée, on garde la PREMIÈRE trouvée
                else:
                    if not loc_pub:
                        loc_pub = p_name
            elif isinstance(pub, str):
                if not orig_pub:
                    orig_pub = pub

        if pub_pref == "ORIGINAL":
            publisher = orig_pub or loc_pub
        else:
            publisher = loc_pub or orig_pub
            
        # Secours absolu : on prend le premier de la liste si nos filtres échouent
        if not publisher and publishers_list and isinstance(publishers_list[0], dict):
            publisher = publishers_list[0].get("name")

        # Normalisation du statut brut MangaBaka ('cancelled', 'completed', 'hiatus',
        # 'releasing', 'unknown', 'upcoming') vers le contrat interne MetaKavita
        # ('RELEASING', 'FINISHED', 'HIATUS', 'CANCELLED'), centralisee dans
        # kavita_constants.py (voir DEVELOPER.md section 11.D). Sans ce mapping,
        # "completed" ne correspondait a aucune cle du mapping de statut attendu
        # par le moteur d'enrichissement, et les series terminees scrapees via
        # MangaBaka restaient silencieusement marquees "En cours" dans Kavita.
        mb_status = normalize_provider_status(data.get('status'))

        links = []
        for link in (data.get('links') or []):
            if isinstance(link, dict) and link.get('url'):
                links.append(link['url'])
            elif isinstance(link, str) and link.strip():
                links.append(link.strip())

        return {
            'title': fetched_title or (alt_titles[0] if alt_titles else ""),
            'summary': data.get('description', '') or '',
            'cover_url': cover_url,
            'genres': genres_list[:get_max_genres()],
            'tags': tags_list[:get_max_tags()],
            'year': year,
            'status': mb_status,
            'staff': staff,
            'characters': [],
            'alternative_titles': alt_titles,
            'publisher': publisher,
            'mangabaka_id': data.get('id'),
            'anilist_id': anilist_id,
            'mal_id': mal_id,
            'links': links,
            'format': format_type
        }
    
    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        clean_sq = clean_title(query, library_type=library_type)
        try:
            type_mapping = {
                "Manga": ["manga", "manhwa", "manhua"],
                "Book": "novel",
                "Comic": ["manga", "manhwa", "manhua"],
            }
            params = {"q": clean_sq, "schema": "full"}
            mangabaka_type = type_mapping.get(library_type)
            if mangabaka_type is not None:
                params["type"] = mangabaka_type
            res = self._http_get(requests, "https://api.mangabaka.org/v2/series/search", params=params, timeout=10)
            if response_is_ok(self, res, context="couvertures"):
                json_res = res.json()
                results = json_res.get('data') if 'data' in json_res else json_res
                if isinstance(results, list):
                    for m in results[:4]:
                        cover_url = self._pick_cover_url(m.get('cover'))
                        if cover_url:
                            title = "Inconnu"
                            titles_list = m.get('titles', [])
                            if titles_list and isinstance(titles_list, list) and isinstance(titles_list[0], dict):
                                title = titles_list[0].get('title', 'Inconnu')
                            covers.append({"provider": "MangaBaka", "title": title, "url": cover_url})
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers