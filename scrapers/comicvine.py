import logging
import requests
import re
import unicodedata
import difflib
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import (
    PROVIDER_ERROR_AUTH,
    PROVIDER_ERROR_HTTP,
    PROVIDER_ERROR_QUOTA,
    attach_match_score,
    clean_title,
    extract_year_from_title,
    get_match_accept_threshold,
    log_provider_http_error,
    note_provider_error,
    response_is_ok,
    score_candidate,
)
from config_manager import load_config, get_max_tags
from secure_logging import safe_exc_str

PRIMARY_PUBLISHERS = ["dc comics", "marvel", "image", "dark horse", "vertigo", "dargaud", "dupuis", "casterman", "le lombard", "glénat", "delcourt", "urban comics", "hachette", "boom! studios", "dynamite", "idw", "titan books", "fantagraphics"]

FOREIGN_KEYWORDS = ["verlag", "brasil", "novaro", "ediciones", "zinco", "ecc", "vid", "interpresse"]

# --- BARÈME DE SÉLECTION D'UN VOLUME ---
# Le bonus « éditeur majeur » valait 300 points contre 150 pour un titre
# exactement égal : un « Scorpion » de chez Marvel (5 albums) battait donc « Le
# Scorpion » d'Editions Paquet (14 albums), et le résumé, la couverture et les
# crédits d'un comic américain partaient sur une BD française avec un score
# affiché de 95 % — le garde-fou final ne voit rien, il compare deux titres qui
# se ressemblent. Ajouter les éditeurs manquants (Paquet, Soleil, Ankama, Rue de
# Sèvres, Bamboo, Vents d'Ouest…) n'aurait rien réglé : c'est le rapport entre
# les primes qui était faux. Un éditeur connu est un indice de notoriété, pas une
# preuve d'identité — il ne doit jamais renverser une égalité de titre.
EXACT_TITLE_BONUS = 150.0
PRIMARY_PUBLISHER_BONUS = 40.0
# Même raison pour le nombre d'albums : à 1,5 point l'unité, un recueil de mille
# strips valait 1500 points et écrasait tout. Plafonné, il redevient ce qu'il
# doit être — un départage entre candidats par ailleurs équivalents.
ISSUES_COUNT_BONUS_MAX = 30.0
FOREIGN_PUBLISHER_MALUS = 400.0

def normalize_str(s):
    if not s: return ""
    return "".join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn').strip()

def calculate_similarity(s1, s2):
    n1 = normalize_str(s1)
    n2 = normalize_str(s2)
    if not n1 or not n2: return 0.0
    seq_ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if not tokens1 or not tokens2: return seq_ratio
    intersection = tokens1.intersection(tokens2)
    token_ratio = len(intersection) / max(len(tokens1), len(tokens2))
    return 0.6 * seq_ratio + 0.4 * token_ratio

def _year_from_date(value) -> Optional[int]:
    """Année d'une date ComicVine (`cover_date` : "2011-11-01") — ou None."""
    match = re.match(r"\s*(19\d{2}|20\d{2})", str(value or ""))
    return int(match.group(1)) if match else None


def clean_comicvine_html(soup):
    noisy_headers = ["publishers", "collected editions", "collected issues", "other collected editions", "collected hardcovers", "hardcover collections", "trade paperbacks", "issues in this volume", "creators", "non-u.s. editions", "translations"]
    for header in soup.find_all(["h2", "h3", "h4", "p", "div"]):
        header_clean = header.get_text().strip().lower().replace(":", "").strip()
        is_structural = header.name in ["h2", "h3", "h4"] or (header.name in ["p", "div"] and len(header_clean) < 35)
        if is_structural and any(noisy in header_clean for noisy in noisy_headers):
            current = header.next_sibling
            while current:
                next_sibling = current.next_sibling
                if current.name in ["h2", "h3", "h4"]: break
                if current.name in ["ul", "ol", "table", "p", "div", "span"]: current.decompose()
                current = next_sibling
            header.decompose()
    for element in soup.find_all(string=re.compile(r'\d+\s+issues?\s+in\s+this\s+volume', re.IGNORECASE)):
        parent = element.parent
        if parent: parent.decompose()
    return soup


def html_to_summary_text(raw_html: str) -> str:
    """HTML ComicVine → texte summary propre (sans labels décoratifs)."""
    if not raw_html:
        return ""
    soup = clean_comicvine_html(BeautifulSoup(raw_html, "html.parser"))
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "h2", "h3", "h4"]):
        block.append("\n\n")
    return re.sub(r"\n{3,}", "\n\n", soup.get_text()).strip()


def compose_summary_parts(*parts: str) -> str:
    """Assemble les blocs texte non vides, sans emoji / balises MetaKavita."""
    cleaned = []
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text).casefold()
        # Nouveau texte déjà entièrement inclus dans un bloc existant → skip.
        if any(key in re.sub(r"\s+", " ", prev).casefold() for prev in cleaned):
            continue
        # Nouveau texte englobe un bloc plus court → remplace le court.
        cleaned = [
            prev
            for prev in cleaned
            if re.sub(r"\s+", " ", prev).casefold() not in key
        ]
        cleaned.append(text)
    return "\n\n".join(cleaned)

class ComicVineScraper(BaseScraper):
    id = "COMICVINE"
    is_core = True
    display_name = "ComicVine (Ultime BD/Comics)"
    supported_types = {"Comic"}
    # `volume` (issue #27) : /api/issues/ ramène cent albums par requête, ce qui
    # met un run de 150 numéros à deux appels au lieu de 150.
    scopes = {"series", "volume"}
    # 1.2.0 : cadence appliquée à chaque requête (et non à la seule première),
    # causes d'erreur API journalisées, barème de sélection rééquilibré. La
    # montée de version est ce qui autorise l'image à remplacer la copie 1.1.x
    # déjà installée sous data/.
    version = "1.2.0"
    rate_limit = 1.2
    # API + CDN image historique ComicVine (pas le domaine parent gamespot.com).
    proxy_domains = ["comicvine.gamespot.com", "static.comicvine.com"]
    has_direct_id_support = True
    requires_proxy = True
    needs_api_key = True
    uses_unified_scoring = True 
    translations = {
        "fr": {
            "display_name": "ComicVine (Ultime BD/Comics)",
            "err_missing": "❌ Clé API ComicVine manquante. Veuillez la configurer dans les paramètres.",
            "direct_id": "🎯 [ComicVine] Requête directe par ID : '{0}'",
            "search_vol": "🔍 [ComicVine] Recherche de Volume pour '{0}'...",
            "err_search": "[ComicVine] Erreur recherche : {0}",
            "err_index": "[ComicVine] Erreur index des albums : {0}",
            "err_index_http": "[ComicVine] Index des albums : code {0}",
            "err_api_key": "🔑 [ComicVine] Clé API refusée (code {0}) — vérifiez la clé dans les paramètres.",
            "err_api_quota": "⏳ [ComicVine] Quota d'appels dépassé (code {0}) — réessayez plus tard.",
            "err_api_status": "⚠️ [ComicVine] Requête refusée par l'API (code {0}) : {1}",
            "cover_provider_series": "ComicVine (Série)",
            "unknown_title": "Inconnu",
        },
        "en": {
            "display_name": "ComicVine (Ultimate Comics)",
            "err_missing": "❌ ComicVine API Key is missing. Please configure it in settings.",
            "direct_id": "🎯 [ComicVine] Direct request by ID: '{0}'",
            "search_vol": "🔍 [ComicVine] Volume Search for '{0}'...",
            "err_search": "[ComicVine] Search error: {0}",
            "err_index": "[ComicVine] Album index error: {0}",
            "err_index_http": "[ComicVine] Album index: code {0}",
            "err_api_key": "🔑 [ComicVine] API key rejected (code {0}) — check the key in settings.",
            "err_api_quota": "⏳ [ComicVine] Rate limit exceeded (code {0}) — try again later.",
            "err_api_status": "⚠️ [ComicVine] Request rejected by the API (code {0}): {1}",
            "cover_provider_series": "ComicVine (Series)",
            "unknown_title": "Unknown",
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "comicvine.gamespot.com" in url:
            match = re.search(r'(40[05]0-\d+)', url)
            if match:
                return match.group(1)
        return None

    #: `status_code` des réponses ComicVine exploitables.
    _API_OK = 1
    #: Causes applicatives ComicVine, rendues **en HTTP 200**.
    _API_ERRORS = {
        100: (PROVIDER_ERROR_AUTH, "Invalid API Key"),
        101: (PROVIDER_ERROR_HTTP, "Object Not Found"),
        102: (PROVIDER_ERROR_HTTP, "Error in URL Format"),
        104: (PROVIDER_ERROR_HTTP, "Filter Error"),
        107: (PROVIDER_ERROR_QUOTA, "Rate Limit Exceeded"),
    }

    def _api_json(self, res, context: str = "") -> Optional[Dict[str, Any]]:
        """Corps JSON d'une réponse ComicVine, ou None **avec la cause dite**.

        ComicVine répond HTTP 200 à une clé révoquée comme à un quota dépassé, en
        plaçant la cause dans `status_code` et une liste `results` vide. Les
        trois passes de recherche voyaient donc zéro candidat, `fetch()` rendait
        None, et l'utilisateur lisait « aucun résultat » sans qu'aucune ligne de
        journal ne mentionne sa clé périmée. Le fichier savait lire ce champ,
        mais à un seul endroit — la passe par album.
        """
        if not response_is_ok(self, res, context=context):
            return None
        try:
            body = res.json()
        except (ValueError, TypeError):
            log_provider_http_error(self, res, context=context)
            return None
        if not isinstance(body, dict):
            return None

        raw_status = body.get("status_code")
        if raw_status is None:
            return body
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            return body
        if status == self._API_OK:
            return body

        kind, label = self._API_ERRORS.get(status, (PROVIDER_ERROR_HTTP, "Unknown API error"))
        detail = str(body.get("error") or label)
        note_provider_error(self.id, kind, f"status_code={status} {detail}")
        if kind == PROVIDER_ERROR_AUTH:
            logging.error(self.t("err_api_key").format(status))
        elif kind == PROVIDER_ERROR_QUOTA:
            logging.warning(self.t("err_api_quota").format(status))
        else:
            logging.warning(self.t("err_api_status").format(status, detail))
        return None

    def _evaluate_volume_candidates(
        self,
        volume_results: list,
        query_base: str,
        year_hint: Optional[int] = None,
        library_type: str = "Comic",
    ) -> Optional[dict]:
        if not volume_results: return None
        
        norm_query = normalize_str(query_base)
        candidates = []
        # Le catalogue ComicVine est celui du comic américain : sa notoriété
        # d'éditeur ne dit rien de la pertinence d'un candidat pour une
        # bibliothèque manga (type forcé depuis metadata_fetcher), où elle ne
        # ferait que remonter des homonymes Marvel / DC.
        publisher_bonus_applies = library_type in ("Comic", "ComicFlexible")

        for vol in volume_results:
            vol_title = vol.get("name", "")
            sim = calculate_similarity(vol_title, query_base)
            
            if sim >= 0.65:
                issues_cnt = vol.get("count_of_issues", 0) or 0
                pub_dict = vol.get("publisher") or {}
                pub_name = str(pub_dict.get("name", "") if isinstance(pub_dict, dict) else "").lower()
                
                score = (sim * 100.0) + min(issues_cnt * 1.5, ISSUES_COUNT_BONUS_MAX)
                
                if normalize_str(vol_title) == norm_query:
                    score += EXACT_TITLE_BONUS
                    
                if publisher_bonus_applies and any(op in pub_name for op in PRIMARY_PUBLISHERS):
                    score += PRIMARY_PUBLISHER_BONUS
                    
                if any(fk in pub_name for fk in FOREIGN_KEYWORDS):
                    score -= FOREIGN_PUBLISHER_MALUS

                # Run year (Kavita Flexible "(YYYY)" / existing_metadata) vs ComicVine start_year.
                if year_hint is not None:
                    start_raw = vol.get("start_year")
                    try:
                        start_year = int(start_raw) if start_raw is not None else None
                    except (TypeError, ValueError):
                        start_year = None
                    if start_year is not None:
                        delta = abs(start_year - int(year_hint))
                        if delta <= 1:
                            score += 200.0
                        elif delta > 5:
                            score -= 100.0

                candidates.append((score, vol))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return None

    def _evaluate_issue_candidates(
        self,
        issue_results: list,
        query_base: str,
        year_hint: Optional[int] = None,
    ) -> Optional[dict]:
        """Retient l'issue la plus proche du titre — et du run — recherché.

        Prendre `issue_results[0]` suffisait à écrire « Batman (1940) » sur un
        « Batman (2011) » : le volume parent de l'issue devient le volume retenu,
        et le score final ne rattrape rien puisqu'il compare des titres
        identiques d'un run à l'autre. `cover_date` situe l'issue dans le temps,
        à défaut l'année portée par le nom du volume parent.
        """
        best = None
        best_score = None
        for issue in issue_results or []:
            if not isinstance(issue, dict):
                continue
            parent = issue.get("volume") if isinstance(issue.get("volume"), dict) else {}
            titles = [issue.get("name") or "", parent.get("name") or ""]
            score = max(
                (calculate_similarity(t, query_base) for t in titles if t),
                default=0.0,
            ) * 100.0

            if year_hint is not None:
                issue_year = (
                    _year_from_date(issue.get("cover_date"))
                    or extract_year_from_title(parent.get("name") or "")
                )
                if issue_year is not None:
                    delta = abs(issue_year - int(year_hint))
                    if delta <= 1:
                        score += 200.0
                    elif delta > 5:
                        score -= 150.0

            # Comparaison stricte : à égalité, l'ordre de pertinence ComicVine
            # reste celui qui décide.
            if best_score is None or score > best_score:
                best_score = score
                best = issue
        return best

    # ===== Index des albums (issue #27) =====

    #: Maximum accepté par ComicVine sur `limit`.
    ISSUES_PAGE_SIZE = 100
    #: Garde-fou : un « volume » ComicVine mal choisi peut contenir des milliers
    #: d'issues (les recueils de strips), et rien n'oblige à tout lire.
    ISSUES_MAX_PAGES = 30

    @staticmethod
    def _volume_id_from_any(raw) -> Optional[str]:
        """Extrait un identifiant de volume d'un ID direct, d'une URL ou d'un nombre.

        Le Champ Magique accepte aussi bien « 4050-12345 » que l'URL de la page
        ComicVine ; les deux doivent mener au même index.
        """
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("4050-"):
            return text.split("-", 1)[1]
        if text.startswith("4000-"):
            # Un identifiant d'album, pas de série : on ne peut pas en tirer
            # l'index sans un appel de plus, que l'appelant fera s'il veut.
            return None
        match = re.search(r"/4050-(\d+)", text)
        if match:
            return match.group(1)
        return text if text.isdigit() else None

    def _resolve_volume_id(
        self,
        query: str,
        library_type: str,
        series_id,
        existing_metadata: Optional[Dict[str, Any]],
        api_key: str,
        headers: dict,
    ) -> Optional[str]:
        """Identifiant ComicVine du run, par ID forcé si possible, par recherche sinon."""
        for candidate in (
            series_id,
            (existing_metadata or {}).get("comicvine_id"),
            (existing_metadata or {}).get("provider_id"),
            (existing_metadata or {}).get("url"),
        ):
            resolved = self._volume_id_from_any(candidate)
            if resolved:
                return resolved

        cleaned_query = clean_title(query, library_type=library_type)
        if not cleaned_query:
            return None
        year_hint = None
        if existing_metadata and existing_metadata.get("year") is not None:
            try:
                year_hint = int(existing_metadata["year"])
            except (TypeError, ValueError):
                year_hint = None
        if year_hint is None:
            year_hint = extract_year_from_title(query)

        try:
            res = self._http_get(
                requests,
                "https://comicvine.gamespot.com/api/volumes/",
                params={
                    "api_key": api_key,
                    "format": "json",
                    "filter": f"name:{cleaned_query}",
                    "limit": 20,
                    "field_list": "id,name,start_year,count_of_issues,publisher",
                },
                headers=headers,
                timeout=12,
            )
            body = self._api_json(res, context="recherche du run")
            if body is None:
                return None
            matched = self._evaluate_volume_candidates(
                body.get("results", []) or [],
                cleaned_query,
                year_hint=year_hint,
                library_type=library_type,
            )
        except Exception as e:
            logging.error(self.t("err_search").format(safe_exc_str(e)))
            return None
        return str(matched.get("id")) if matched and matched.get("id") else None

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Comic",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """`{numéro d'album: payload}` pour toute la série, en un appel par centaine.

        Sans crédits : ComicVine ne les rend pas sur la liste, il faut un appel
        par album. C'est l'objet de `fetch_volume_credits`, laissé à l'option
        `VOLUME_ENRICH_CREDITS`.
        """
        api_key = load_config().get("COMICVINE_API_KEY", "").strip()
        if not api_key:
            logging.error(self.t("err_missing"))
            return None

        headers = {"User-Agent": "MetaKavita-Fetcher/1.5", "Accept": "application/json"}
        volume_id = self._resolve_volume_id(
            query, library_type, series_id, existing_metadata, api_key, headers
        )
        if not volume_id:
            return None

        index: Dict[str, Any] = {}
        offset = 0
        for _page in range(self.ISSUES_MAX_PAGES):
            try:
                res = self._http_get(
                    requests,
                    "https://comicvine.gamespot.com/api/issues/",
                    params={
                        "api_key": api_key,
                        "format": "json",
                        "filter": f"volume:{volume_id}",
                        "sort": "issue_number:asc",
                        "limit": self.ISSUES_PAGE_SIZE,
                        "offset": offset,
                        "field_list": "id,name,issue_number,cover_date,store_date,description,deck,image",
                    },
                    headers=headers,
                    timeout=15,
                )
            except Exception as e:
                logging.error(self.t("err_index").format(safe_exc_str(e)))
                break
            body = self._api_json(res, context="index des albums")
            if body is None:
                break
            results = body.get("results") or []
            for issue in results:
                if not isinstance(issue, dict):
                    continue
                number = issue.get("issue_number")
                if number in (None, ""):
                    continue
                image = issue.get("image") or {}
                payload = {
                    "provider_ref": f"4000-{issue.get('id')}" if issue.get("id") else "",
                    "title": (issue.get("name") or "").strip(),
                    "summary": html_to_summary_text(
                        issue.get("description") or issue.get("deck") or ""
                    ),
                    "release_date": issue.get("cover_date") or issue.get("store_date") or "",
                    "cover_url": image.get("original_url") or image.get("super_url") or "",
                }
                index[str(number)] = {k: v for k, v in payload.items() if v}

            total = body.get("number_of_total_results")
            offset += len(results)
            if not results or (isinstance(total, int) and offset >= total):
                break
            if len(results) < self.ISSUES_PAGE_SIZE:
                break

        return index or None

    def fetch_volume_credits(self, provider_ref: str) -> Optional[Dict[str, List[str]]]:
        """Crédits nominatifs d'un album : un appel réseau, pour un album.

        C'est le seul chemin de la fonctionnalité qui coûte un appel par unité,
        d'où l'interrupteur dédié.
        """
        issue_id = str(provider_ref or "").strip()
        if issue_id.startswith("4000-"):
            issue_id = issue_id.split("-", 1)[1]
        if not issue_id.isdigit():
            return None
        api_key = load_config().get("COMICVINE_API_KEY", "").strip()
        if not api_key:
            return None
        try:
            res = self._http_get(
                requests,
                f"https://comicvine.gamespot.com/api/issue/4000-{issue_id}/",
                params={"api_key": api_key, "format": "json", "field_list": "person_credits"},
                headers={"User-Agent": "MetaKavita-Fetcher/1.5", "Accept": "application/json"},
                timeout=15,
            )
            body = self._api_json(res, context="crédits d'un album")
            if body is None:
                return None
            credits = (body.get("results") or {}).get("person_credits") or []
        except Exception as e:
            logging.debug("ComicVine credits failed: %s", safe_exc_str(e))
            return None

        buckets: Dict[str, List[str]] = {}
        for person in credits:
            if not isinstance(person, dict):
                continue
            name = (person.get("name") or "").strip()
            if not name:
                continue
            role = (person.get("role") or "").lower()
            # Un crédit ComicVine cumule les rôles (« writer, artist ») : chaque
            # rôle reconnu verse dans sa collection Kavita.
            for needles, key in (
                (("writer", "plotter", "scripter"), "writers"),
                (("penciller", "artist"), "pencillers"),
                (("inker",), "inkers"),
                (("colorist",), "colorists"),
                (("letterer",), "letterers"),
                (("editor",), "editors"),
                (("cover",), "coverArtists"),
            ):
                if any(n in role for n in needles):
                    names = buckets.setdefault(key, [])
                    if name not in names:
                        names.append(name)
        return buckets or None

    def fetch(self, query: str, library_type: str = "Comic", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        config = load_config()
        api_key = config.get("COMICVINE_API_KEY", "").strip()
        
        if not api_key:
            logging.error(self.t("err_missing"))
            return None
            
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5", "Accept": "application/json"}
        
        volume_id = None
        volume_name = None
        issue_id = None
        issue_summary = ""
        issue_cover = None
        issue_name = ""
        matched_volume = None
        staff_credits = []

        if is_id:
            logging.info(self.t("direct_id").format(query))
            if str(query).startswith("4050-"):
                volume_id = str(query).split("-")[1]
            elif str(query).startswith("4000-"):
                issue_id = str(query).split("-")[1]
            else:
                volume_id = str(query)
        else:
            cleaned_query = clean_title(query, library_type=library_type)
            year_hint = None
            if existing_metadata and existing_metadata.get("year") is not None:
                try:
                    year_hint = int(existing_metadata["year"])
                except (TypeError, ValueError):
                    year_hint = None
            if year_hint is None:
                year_hint = extract_year_from_title(query)

            logging.info(self.t("search_vol").format(cleaned_query))
            url_volumes = "https://comicvine.gamespot.com/api/volumes/"
            
            # 🎯 PASSE 1 : Recherche avec le titre complet (Essentiel pour 'Y: The Last Man')
            params_vol = {
                "api_key": api_key,
                "format": "json",
                "filter": f"name:{cleaned_query}",
                "limit": 20,
                "field_list": "id,name,start_year,count_of_issues,publisher,deck,description,first_issue,image,site_detail_url"
            }

            try:
                res_v = self._http_get(
                    requests, url_volumes, params=params_vol, headers=headers, timeout=12
                )
                body_v = self._api_json(res_v, context="passe 1 (titre complet)")
                if body_v is not None:
                    matched_volume = self._evaluate_volume_candidates(
                        body_v.get("results", []),
                        cleaned_query,
                        year_hint=year_hint,
                        library_type=library_type,
                    )
            except Exception as e:
                logging.error(self.t("err_search").format(safe_exc_str(e)))

            # 🎯 PASSE 2 : Si pas de résultat et présence d'un deux-points, recherche sans le sous-titre
            if not matched_volume and ":" in cleaned_query:
                base_q = cleaned_query.split(":")[0].strip()
                params_vol["filter"] = f"name:{base_q}"
                try:
                    res_v = self._http_get(
                        requests, url_volumes, params=params_vol, headers=headers, timeout=12
                    )
                    body_v = self._api_json(res_v, context="passe 2 (sans sous-titre)")
                    if body_v is not None:
                        matched_volume = self._evaluate_volume_candidates(
                            body_v.get("results", []),
                            base_q,
                            year_hint=year_hint,
                            library_type=library_type,
                        )
                except Exception as e:
                    logging.debug("ComicVine passe-2 search failed: %s", safe_exc_str(e))

            # 🎯 PASSE 3 : Fallback via /search/
            if not matched_volume:
                url_search = "https://comicvine.gamespot.com/api/search/"
                params_search = {
                    "api_key": api_key,
                    "format": "json",
                    "resources": "volume",
                    "query": cleaned_query,
                    "limit": 20,
                    "field_list": "id,name,start_year,count_of_issues,publisher,deck,description,first_issue,image,site_detail_url"
                }
                try:
                    res_s = self._http_get(
                        requests, url_search, params=params_search, headers=headers, timeout=12
                    )
                    body_s = self._api_json(res_s, context="passe 3 (/search/)")
                    if body_s is not None:
                        matched_volume = self._evaluate_volume_candidates(
                            body_s.get("results", []),
                            cleaned_query,
                            year_hint=year_hint,
                            library_type=library_type,
                        )
                except Exception as e:
                    logging.error(self.t("err_search").format(safe_exc_str(e)))

            if matched_volume:
                volume_id = matched_volume.get("id")
                volume_name = matched_volume.get("name")

            # 🎯 PASSE 4 : Recherche par Issue (Album / Arc)
            if not matched_volume:
                url_search = "https://comicvine.gamespot.com/api/search/"
                issue_params = {
                    "api_key": api_key, 
                    "format": "json", 
                    "resources": "issue", 
                    "query": cleaned_query, 
                    "limit": 5,
                    # cover_date : situe l'issue dans le run (voir _evaluate_issue_candidates).
                    "field_list": "id,name,issue_number,cover_date,description,deck,image,volume,person_credits"
                }
                try:
                    res_issue = self._http_get(
                        requests, url_search, params=issue_params, headers=headers, timeout=12
                    )
                    body_issue = self._api_json(res_issue, context="passe 4 (album)")
                    if body_issue is not None:
                        matched_issue = self._evaluate_issue_candidates(
                            body_issue.get("results", []), cleaned_query, year_hint=year_hint
                        )
                        if matched_issue:
                            issue_id = matched_issue.get("id")
                            issue_name = matched_issue.get("name") or f"Issue #{matched_issue.get('issue_number')}"
                            parent_vol = matched_issue.get("volume")
                            if isinstance(parent_vol, dict):
                                volume_id = parent_vol.get("id")
                                volume_name = parent_vol.get("name")
                except Exception as e:
                    logging.debug("ComicVine issue search failed: %s", safe_exc_str(e))

        if not volume_id and not issue_id: 
            return None

        # Récupération détaillée de l'Issue si présente
        if issue_id:
            try:
                issue_res = self._http_get(
                    requests,
                    f"https://comicvine.gamespot.com/api/issue/4000-{issue_id}/",
                    params={"api_key": api_key, "format": "json", "field_list": "id,name,description,deck,image,person_credits,volume"},
                    headers=headers, timeout=15
                )
                issue_body = self._api_json(issue_res, context="fiche album")
                if issue_body is not None:
                    issue_detail = issue_body.get("results", {})
                    if issue_detail and isinstance(issue_detail, dict):
                        raw_issue_desc = issue_detail.get("description") or issue_detail.get("deck") or ""
                        issue_summary = html_to_summary_text(raw_issue_desc)
                        img_dict = issue_detail.get("image")
                        if isinstance(img_dict, dict): issue_cover = img_dict.get("original_url") or img_dict.get("super_url")
                        
                        for person in issue_detail.get("person_credits", []):
                            p_name = person.get("name")
                            p_role = person.get("role", "").lower()
                            if not p_name: continue
                            mapped_role = None
                            if any(r in p_role for r in ["writer", "plotter", "scripter"]): mapped_role = "Story"
                            elif any(r in p_role for r in ["penciller", "artist"]): mapped_role = "Art"
                            elif any(r in p_role for r in ["colorist"]): mapped_role = "Color"
                            if mapped_role: staff_credits.append({"role": mapped_role, "node": {"name": {"full": p_name}}})
            except Exception as e:
                logging.debug("ComicVine issue detail/staff parse failed: %s", safe_exc_str(e))

        volume_summary = ""
        volume_cover = None
        publisher_name = None
        year = None
        tags = ["Comics", "ComicVine"]
        site_url = f"https://comicvine.gamespot.com/volume/4050-{volume_id}/" if volume_id else ""
        
        if volume_id:
            try:
                detail_res = self._http_get(
                    requests,
                    f"https://comicvine.gamespot.com/api/volume/4050-{volume_id}/",
                    params={"api_key": api_key, "format": "json", "field_list": "id,name,deck,description,image,start_year,publisher,first_issue,site_detail_url"},
                    headers=headers, timeout=15
                )
                detail_body = self._api_json(detail_res, context="fiche du run")
                if detail_body is not None:
                    volume_detail = detail_body.get("results", {})
                    if volume_detail and isinstance(volume_detail, dict):
                        if not volume_name: volume_name = volume_detail.get("name")
                            
                        volume_summary = html_to_summary_text(
                            volume_detail.get("description") or volume_detail.get("deck") or ""
                        )
                            
                        img_dict = volume_detail.get("image")
                        if isinstance(img_dict, dict): volume_cover = img_dict.get("original_url") or img_dict.get("super_url")
                        
                        start_year_str = volume_detail.get("start_year")
                        if start_year_str and str(start_year_str).isdigit(): year = int(start_year_str)
                        
                        pub_dict = volume_detail.get("publisher")
                        if isinstance(pub_dict, dict): publisher_name = pub_dict.get("name")
                        if publisher_name: tags.append(publisher_name)

                        # 🎯 ENRICHISSEMENT ISSUE #1 : Si le résumé du Volume fait < 150 caractères OU si le Staff est vide
                        first_issue = (volume_detail.get("first_issue") or {})
                        first_issue_id = first_issue.get("id")
                        
                        if first_issue_id and (not staff_credits or len(volume_summary) < 150):
                            try:
                                f_res = self._http_get(
                                    requests,
                                    f"https://comicvine.gamespot.com/api/issue/4000-{first_issue_id}/",
                                    params={"api_key": api_key, "format": "json", "field_list": "description,deck,person_credits"},
                                    headers=headers, timeout=10
                                )
                                f_body = self._api_json(f_res, context="premier album du run")
                                if f_body is not None:
                                    f_detail = f_body.get("results", {})
                                    if isinstance(f_detail, dict):
                                        # Résumé enrichi via Tome #1 (texte brut, sans balise)
                                        if len(volume_summary) < 150:
                                            issue_1_text = html_to_summary_text(
                                                f_detail.get("description") or f_detail.get("deck") or ""
                                            )
                                            volume_summary = compose_summary_parts(
                                                volume_summary, issue_1_text
                                            )

                                        # Staff enrichi via Tome #1
                                        if not staff_credits:
                                            for person in f_detail.get("person_credits", []):
                                                p_name = person.get("name")
                                                p_role = person.get("role", "").lower()
                                                if not p_name: continue
                                                mapped_role = None
                                                if any(r in p_role for r in ["writer", "plotter", "scripter"]): mapped_role = "Story"
                                                elif any(r in p_role for r in ["penciller", "artist"]): mapped_role = "Art"
                                                elif any(r in p_role for r in ["colorist"]): mapped_role = "Color"
                                                if mapped_role: staff_credits.append({"role": mapped_role, "node": {"name": {"full": p_name}}})
                            except Exception as e:
                                logging.debug("ComicVine first-issue staff enrich failed: %s", safe_exc_str(e))

            except Exception as e:
                logging.debug("ComicVine volume detail failed: %s", safe_exc_str(e))

        final_cover = issue_cover if issue_cover else volume_cover
        # Volume d'abord (page série Kavita), puis album si distinct — sans emoji/balises.
        final_summary = compose_summary_parts(volume_summary, issue_summary)
            
        if not final_summary.strip() and not final_cover: 
            return None
            
        final_title = volume_name if volume_name else issue_name
            
        candidate = {
            'title': final_title,
            'alternative_titles': [],
            'summary': final_summary,
            'cover_url': final_cover,
            'genres': ["Comic Book"],
            'tags': tags[:get_max_tags()],
            'year': year,
            'staff': staff_credits, 
            'publisher': publisher_name,
            'format': "comic",
            'url': site_url
        }
        if is_id:
            return attach_match_score(candidate, 1.0)
        clean_q = clean_title(query, library_type=library_type) or query
        score = score_candidate(candidate, clean_q, existing_metadata)
        if score < get_match_accept_threshold():
            return None
        return attach_match_score(candidate, score)

    def fetch_covers(self, query: str, library_type: str = "Comic") -> List[Dict[str, str]]:
        covers = []
        clean_sq = clean_title(query, library_type=library_type)
        config = load_config()
        cv_key = config.get("COMICVINE_API_KEY", "").strip()
        if not cv_key: return covers
        headers = {"User-Agent": "MetaKavita-Metadata-Fetcher/1.5", "Accept": "application/json"}
        url = "https://comicvine.gamespot.com/api/volumes/"
        try:
            params = {"api_key": cv_key, "format": "json", "filter": f"name:{clean_sq}", "limit": 4, "field_list": "name,image"}
            res = self._http_get(requests, url, params=params, headers=headers, timeout=10)
            body = self._api_json(res, context="recherche de couvertures")
            if body is not None:
                for v in body.get('results', []):
                    img_dict = v.get('image') or {}
                    cover_url = img_dict.get('original_url') or img_dict.get('super_url')
                    if cover_url:
                        covers.append({
                            "provider": self.t("cover_provider_series"),
                            "title": v.get("name") or self.t("unknown_title"),
                            "url": cover_url,
                        })
        except Exception as e:
            logging.debug("ComicVine cover search failed: %s", safe_exc_str(e))
        return covers