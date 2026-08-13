import requests
import logging
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import (
    PROVIDER_ERROR_AUTH,
    PROVIDER_ERROR_HTTP,
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    note_provider_error,
    response_is_ok,
    score_candidate,
)
from config_manager import get_max_genres, get_max_tags

class AnilistScraper(BaseScraper):
    id = "ANILIST"
    is_core = True
    display_name = "AniList (International)"
    # Comic stays: AniList has no COMIC Media type; manhwa/manhua/comics live under MANGA.
    # Book: search still uses type MANGA but candidates are filtered to format NOVEL.
    supported_types = {"Manga", "Comic", "Book"}
    rate_limit = 2.25  # ~27/min: 10% under AniList degraded 30/min (normal 90/min)
    # 1.1.0 : le quota AniList (30/min en mode dégradé) se compte par requête, or
    # la cadence n'était appliquée qu'avant `fetch()` — les trois appels d'une
    # même recherche partaient en rafale et déclenchaient le 429 qui suit. Les
    # refus (429 HTTP, `errors` GraphQL rendus en HTTP 200) sont désormais
    # journalisés au lieu de ressembler à « aucun résultat ». La montée de
    # version est ce qui autorise l'image à remplacer la copie 1.0.x déjà
    # installée sous data/.
    version = "1.1.0"
    proxy_domains = ["anilist.co"]
    has_direct_id_support = True
    uses_unified_scoring = True

    _BOOK_FORMATS = frozenset({"NOVEL"})

    translations = {
        "fr": {
            "req_id": "[Anilist] Requête directe par ID : {0}",
            "req_slug": "[Anilist] Requête directe par Slug : '{0}'",
            "search_title": "[Anilist] Recherche par titre ({0}) : '{1}'",
            "err": "[Erreur Anilist] {0}",
            "covers_err": "[Covers] Erreur AniList : {0}",
            "gql_auth": "🔑 [AniList] Accès refusé ({0}) : {1} — vérifiez la configuration AniList.",
            "gql_err": "⚠️ [AniList] Erreur GraphQL ({0}) : {1}"
        },
        "en": {
            "req_id": "[Anilist] Direct request by ID: {0}",
            "req_slug": "[Anilist] Direct request by Slug: '{0}'",
            "search_title": "[Anilist] Title search ({0}): '{1}'",
            "err": "[AniList Error] {0}",
            "covers_err": "[Covers] AniList error: {0}",
            "gql_auth": "🔑 [AniList] Access denied ({0}): {1} — check the AniList configuration.",
            "gql_err": "⚠️ [AniList] GraphQL error ({0}): {1}"
        }
    }

    #: Fragments qui, dans un message d'erreur GraphQL, désignent un refus
    #: d'authentification plutôt qu'une donnée absente : seule une action de
    #: l'utilisateur peut y remédier, le journal doit donc être en ERROR.
    _AUTH_ERROR_MARKERS = ("jwt", "token", "unauthorized")

    def _graphql_payload(self, res, context: str) -> Optional[Dict[str, Any]]:
        """Corps JSON exploitable, ou None après avoir journalisé la cause.

        GraphQL répond volontiers HTTP 200 avec un bloc `errors` : aucun
        contrôle de code de statut ne l'attrape, et `fetch()` rendait alors
        None sans un seul journal — indiscernable, pour l'utilisateur, d'une
        série inconnue.
        """
        if not response_is_ok(self, res, context=context):
            return None
        body = res.json() or {}
        if not isinstance(body, dict):
            return None
        errors = body.get("errors")
        if isinstance(errors, dict):
            errors = [errors]
        if not errors:
            return body
        detail = "; ".join(str((e or {}).get("message") or e) for e in errors if e)[:300]
        if any(marker in detail.lower() for marker in self._AUTH_ERROR_MARKERS):
            note_provider_error(self.id, PROVIDER_ERROR_AUTH, detail)
            logging.error(self.t("gql_auth").format(context, detail))
        else:
            note_provider_error(self.id, PROVIDER_ERROR_HTTP, detail)
            logging.warning(self.t("gql_err").format(context, detail))
        return None

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "anilist.co/manga/" in url:
            parts = url.split('anilist.co/manga/')[-1].split('/')
            if parts and parts[0].isdigit():
                return parts[0]
        return None    

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if is_id:
            if str(query).isdigit():
                logging.info(self.t("req_id").format(query))
                graphql_query = '''
                query ($id: Int) {
                  Media(id: $id, type: MANGA) {
                    id idMal description(asHtml: false) coverImage { extraLarge } title { romaji english native }
                    format genres tags { name } startDate { year } status isAdult countryOfOrigin
                    staff { edges { role node { name { full } } } }
                    characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
                    externalLinks { url site }
                  }
                }
                '''
                variables = {'id': int(query)}
            else:
                logging.info(self.t("req_slug").format(query))
                graphql_query = '''
                query ($search: String) {
                  Media(search: $search, type: MANGA) {
                    id idMal description(asHtml: false) coverImage { extraLarge } title { romaji english native }
                    format genres tags { name } startDate { year } status isAdult countryOfOrigin
                    staff { edges { role node { name { full } } } }
                    characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
                    externalLinks { url site }
                  }
                }
                '''
                variables = {'search': str(query)}

            try:
                response = self._http_post(requests, 'https://graphql.anilist.co', json={'query': graphql_query, 'variables': variables}, timeout=10)
                payload = self._graphql_payload(response, context="fiche par identifiant")
                if payload:
                    data = (payload.get('data') or {}).get('Media')
                    if data and self._library_allows(data, library_type):
                        return attach_match_score(self._build_candidate(data), 1.0)
            except Exception as e:
                logging.error(self.t("err").format(e))
            return None

        else:
            clean = clean_title(query, library_type=library_type)
            logging.info(self.t("search_title").format(library_type, clean))
            
            graphql_query = '''
            query ($search: String) {
              Page(page: 1, perPage: 5) {
                media(search: $search, type: MANGA) {
                  id idMal description(asHtml: false) coverImage { extraLarge } title { romaji english native }
                  format genres tags { name } startDate { year } status isAdult countryOfOrigin
                  staff { edges { role node { name { full } } } }
                  characters(sort: ROLE, perPage: 15) { edges { role node { name { full } } } }
                  externalLinks { url site }
                }
              }
            }
            '''
            try:
                response = self._http_post(requests, 'https://graphql.anilist.co', json={'query': graphql_query, 'variables': {'search': clean}}, timeout=10)
                payload = self._graphql_payload(response, context="recherche par titre")
                if payload:
                    media_list = ((payload.get('data') or {}).get('Page') or {}).get('media') or []
                    if not media_list: return None

                    best_match = None
                    best_score = -1.0

                    for item in media_list:
                        if not self._library_allows(item, library_type):
                            continue
                        candidate = self._build_candidate(item)
                        if not candidate: continue
                        
                        score = score_candidate(candidate, clean, existing_metadata)
                        if score > best_score:
                            best_score = score
                            best_match = candidate

                    if best_match and best_score >= get_match_accept_threshold():
                        return attach_match_score(best_match, best_score)

            except Exception as e:
                logging.error(self.t("err").format(e))
            return None

    def _library_allows(self, data: dict, library_type: str) -> bool:
        """Book libraries only accept AniList NOVEL format; Manga/Comic keep MANGA type results."""
        lib = (library_type or "Manga").strip()
        if lib != "Book":
            return True
        fmt = str((data or {}).get("format") or "").upper()
        return fmt in self._BOOK_FORMATS

    def _build_candidate(self, data: dict) -> dict:
        title_dict = data.get('title', {}) or {}
        romaji_title = title_dict.get('romaji', '')
        english_title = title_dict.get('english', '')
        native_title = title_dict.get('native', '')
        alt_titles = [t for t in title_dict.values() if t]

        country = str(data.get('countryOfOrigin', '')).upper()
        al_format = str(data.get("format") or "").upper()
        format_type = "manga"
        if al_format == "NOVEL":
            format_type = "book"
        elif country in ["KR", "CN"]:
            format_type = "webtoon"

        from localized_titles import native_lang_from_country
        native_lang = native_lang_from_country(country)
        titles = []
        if romaji_title:
            titles.append({"lang": "ja-ro" if native_lang == "ja" else f"{native_lang}-ro", "value": romaji_title})
        if english_title:
            titles.append({"lang": "en", "value": english_title})
        if native_title:
            titles.append({"lang": native_lang, "value": native_title})

        return {
            'title': romaji_title,
            'alternative_titles': alt_titles,
            'titles': titles,
            'summary': data.get('description', '') or '',
            # `or {}` et non le défaut de `get` : AniList déclare ces champs
            # nullables et renvoie bel et bien `null` sur les fiches pauvres —
            # la clé est alors présente, le défaut ne s'applique pas, et le
            # chaînage écartait la série du fournisseur sur un AttributeError.
            'cover_url': (data.get('coverImage') or {}).get('extraLarge'),
            'genres': (data.get('genres') or [])[:get_max_genres()],
            'tags': [
                t['name']
                for t in (data.get('tags') or [])
                if isinstance(t, dict) and t.get('name')
            ][:get_max_tags()],
            'year': (data.get('startDate') or {}).get('year'),
            'status': data.get('status'),
            'staff': (data.get('staff') or {}).get('edges') or [],
            'characters': (data.get('characters') or {}).get('edges') or [],
            # BF56: isAdult=False n'implique pas Everyone — omettre plutôt qu'inventer safe.
            'age_rating': 'pornographic' if data.get('isAdult') else '',
            'format': format_type,
            'publisher': None,
            'anilist_id': data.get('id'),
            'mal_id': data.get('idMal'),
            'external_links': [{'url': link['url'], 'site': link['site']} for link in data.get('externalLinks', [])] if data.get('externalLinks') else []
        }

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
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
            res = self._http_post(requests, 'https://graphql.anilist.co', json={'query': graphql_query, 'variables': {'search': clean}}, timeout=10)
            payload = self._graphql_payload(res, context="couvertures")
            if payload:
                results = ((payload.get('data') or {}).get('Page') or {}).get('media') or []
                for m in results:
                    if (m.get('coverImage') or {}).get('extraLarge'):
                        covers.append({
                            "provider": "AniList", 
                            "title": (m.get('title') or {}).get('romaji') or 'Inconnu',
                            "url": m['coverImage']['extraLarge']
                        })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers