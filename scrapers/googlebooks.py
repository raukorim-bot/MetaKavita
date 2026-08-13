import logging
import requests
import urllib.parse
from typing import Optional, Dict, Any, List
import re
from .base import BaseScraper
from .utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)
from config_manager import load_config, get_max_tags, get_max_genres
from secure_logging import safe_exc_str


#: Formes sous lesquelles un numéro de tome apparaît dans un titre de livre :
#: « Berserk, Vol. 7 », « Naruto T7 », « Monster tome 7 », « One Piece #7 ».
#: Le mot-clé est exigé — sans lui, « Akira 2020 » passerait pour le tome 2020,
#: et « 20th Century Boys » pour le tome 20.
_VOLUME_IN_TITLE = re.compile(
    r'(?:\b(?:vol|volume|tome|tomo|band|deel|t)\.?\s*|#\s*)(\d{1,4})\b', re.I
)
_ACCENTS = str.maketrans("àâäáãçéèêëíìîïñóòôöõúùûüýÿ", "aaaaaceeeeiiiinooooouuuuyy")


def _normalize_for_match(text: str) -> str:
    lowered = str(text or "").lower().translate(_ACCENTS)
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _volume_token(raw) -> Optional[str]:
    """Numéro de tome sous sa forme canonique, ou rien si ce n'en est pas un."""
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if value != value or value <= 0 or value != int(value):
        return None
    return str(int(value))


def _volume_in_title(title: str) -> Optional[str]:
    match = _VOLUME_IN_TITLE.search(str(title or ""))
    return str(int(match.group(1))) if match else None


def _title_matches_series(title: str, series: str) -> bool:
    """Le titre du livre doit contenir celui de la série, mot pour mot.

    Google Books répond volontiers à côté : demander « Berserk 7 » ramène des
    artbooks, des guides de lecture et des tomes d'autres séries du même
    éditeur. Sans cette vérification, chacun d'eux serait écrit sur le tome 7,
    résumé et couverture compris, puis verrouillé.
    """
    haystack = _normalize_for_match(title)
    needle = _normalize_for_match(series)
    if not haystack or not needle:
        return False
    return re.search(rf"(?:^|\s){re.escape(needle)}(?:\s|$)", haystack) is not None


def _isbn_query_variants(isbn: str) -> List[str]:
    """ISBN-13 et ISBN-10 : Google indexe parfois un seul des deux (ex. Dune Ace)."""
    clean = re.sub(r"[\s\-]", "", str(isbn or ""))
    if not clean:
        return []
    out = [clean]
    if len(clean) == 13 and clean.startswith("978") and clean.isdigit():
        core = clean[3:12]
        total = sum((10 - i) * int(core[i]) for i in range(9))
        check = (11 - (total % 11)) % 11
        isbn10 = core + ("X" if check == 10 else str(check))
        if isbn10 not in out:
            out.append(isbn10)
    elif len(clean) == 10:
        body = clean[:9]
        if body.isdigit() and (clean[9].isdigit() or clean[9].upper() == "X"):
            core = "978" + body
            total = sum(int(core[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
            check = (10 - (total % 10)) % 10
            isbn13 = core + str(check)
            if isbn13 not in out:
                out.append(isbn13)
    return out


class GoogleBooksScraper(BaseScraper):
    id = "GOOGLEBOOKS"
    is_core = True
    display_name = "Google Books"
    supported_types = {"Book", "Comic"}
    rate_limit = 1.0
    proxy_domains = [
        "books.google.com",
        "books.googleusercontent.com",
        "googleusercontent.com",
    ]
    has_direct_id_support = True
    needs_api_key = True
    uses_unified_scoring = True
    # 1.1.0 : une clé Google révoquée ou son quota journalier épuisé se traduit
    # par un 403 que rien ne journalisait — l'utilisateur lisait « aucun
    # résultat » sans savoir qu'il devait renouveler sa clé. La cadence, elle,
    # ne couvrait que la première des quatre requêtes possibles d'un `fetch()`.
    # La montée de version est ce qui autorise l'image à remplacer la copie
    # 1.0.x déjà installée sous data/.
    version = "1.1.0"

    # Google Books géolocalise la requête via l'IP source pour le endpoint
    # volumes:list. Sur certaines IP (notamment françaises/résidentielles, cas
    # typique d'un serveur auto-hébergé), Google échoue à déterminer le pays
    # de façon fiable et renvoie tantôt `totalItems: 0` sur une requête
    # pourtant valide, tantôt une erreur 503 "Service temporarily unavailable"
    # (backendFailed). Forcer `country` (ISO-3166-1) contourne ce problème
    # documenté côté Google — voir developers.google.com/books/docs/v1/reference/volumes/list
    # et les multiples rapports (Stack Overflow) de "totalItems=0 en France
    # mais OK depuis les US".
    DEFAULT_COUNTRY = "US"
    
    translations = {
        "fr": {
            "direct_id": "[GoogleBooks] Requête directe par ID : '{0}'",
            "search_start": "[GoogleBooks] Lancement de la recherche pour : '{0}'",
            "search_isbn": "[GoogleBooks] Recherche prioritaire via ISBN Kavita : '{0}'",
            "matched_isbn": "🎯 [GoogleBooks] Match exact par ISBN ({0}) sur : '{1}'",
            "no_match": "⚠️ [GoogleBooks] Aucun volume pertinent trouvé pour '{0}' (Meilleur score : {1}%)",
            "matched": "🎯 [GoogleBooks] Volume retenu : '{0}' (Score: {1}%)",
            "volume_matched": "🎯 [GoogleBooks] Tome {0} vérifié : '{1}'",
            "err": "[GoogleBooks] Erreur : {0}"
        },
        "en": {
            "direct_id": "[GoogleBooks] Direct request by ID: '{0}'",
            "search_start": "[GoogleBooks] Starting search for: '{0}'",
            "search_isbn": "[GoogleBooks] Priority search via Kavita ISBN: '{0}'",
            "matched_isbn": "🎯 [GoogleBooks] Exact ISBN match ({0}) on: '{1}'",
            "no_match": "⚠️ [GoogleBooks] No relevant volume found for '{0}' (Best score: {1}%)",
            "matched": "🎯 [GoogleBooks] Selected volume: '{0}' (Score: {1}%)",
            "volume_matched": "🎯 [GoogleBooks] Volume {0} verified: '{1}'",
            "err": "[GoogleBooks] Error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "books.google." in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'id' in qs:
                return qs['id'][0]
        return None

    def fetch(self, query: str, library_type: str = "Book", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        google_lang = config.get("TARGET_LANG", "FR").lower()[:2]

        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                url = f"https://www.googleapis.com/books/v1/volumes/{query}"
                params = {"country": self.DEFAULT_COUNTRY}
                if api_key: params["key"] = api_key
                res = self._http_get(requests, url, params=params, timeout=15)
                if response_is_ok(self, res, context="fiche par identifiant"):
                    item = res.json()
                    return attach_match_score(self._build_candidate(item.get("volumeInfo", {}), item.get("id")), 1.0)
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None
            
            logging.info(self.t("search_start").format(cleaned))
            url = "https://www.googleapis.com/books/v1/volumes"
            ex_isbn = existing_metadata.get('isbn') if existing_metadata else None

            items = []

            if ex_isbn:
                logging.info(self.t("search_isbn").format(ex_isbn))
                for isbn_try in _isbn_query_variants(ex_isbn):
                    p_isbn = {"q": f"isbn:{isbn_try}", "country": self.DEFAULT_COUNTRY}
                    if api_key: p_isbn["key"] = api_key
                    res = self._http_get(requests, url, params=p_isbn, timeout=12)
                    if response_is_ok(self, res, context="recherche par ISBN"):
                        items = res.json().get("items", [])
                        if items:
                            vol_info = items[0].get("volumeInfo", {})
                            logging.info(self.t("matched_isbn").format(isbn_try, vol_info.get('title')))
                            break

            if not items:
                params = {"q": cleaned, "maxResults": 10, "orderBy": "relevance", "country": self.DEFAULT_COUNTRY, "printType": "books"}
                if google_lang: params["langRestrict"] = google_lang
                if api_key: params["key"] = api_key
                res = self._http_get(requests, url, params=params, timeout=12)
                if response_is_ok(self, res, context="recherche par titre (langue cible)"):
                    items = res.json().get("items", [])

            if not items:
                params = {"q": cleaned, "maxResults": 10, "orderBy": "relevance", "country": self.DEFAULT_COUNTRY, "printType": "books"}
                if api_key: params["key"] = api_key
                res = self._http_get(requests, url, params=params, timeout=12)
                if response_is_ok(self, res, context="recherche par titre (toutes langues)"):
                    items = res.json().get("items", [])

            if not items: 
                logging.warning(self.t("no_match").format(cleaned, 0))
                return None

            best_match = None
            best_score = -1.0

            for item in items:
                vol_info = item.get("volumeInfo", {})
                candidate = self._build_candidate(vol_info, item.get("id"))
                if not candidate or not candidate.get('title'):
                    continue

                score = score_candidate(candidate, cleaned, existing_metadata)

                # 🎯 BONUS ANTI-RÉSUMÉ VIDE : Favorise les fiches avec vrai résumé
                if candidate.get('summary') and len(candidate.get('summary')) > 30:
                    score += 0.10

                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < get_match_accept_threshold():
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_match.get('title'), int(best_score*100)))
            return attach_match_score(best_match, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def _build_candidate(self, volume_info: dict, vol_id: str = None) -> Optional[Dict[str, Any]]:
        if not volume_info: return None

        isbn = None
        for ident in volume_info.get("industryIdentifiers", []):
            if ident.get("type") in ["ISBN_13", "ISBN_10"]:
                isbn = str(ident.get("identifier")).replace('-', '').replace(' ', '').strip()
                break

        image_links = volume_info.get("imageLinks", {})
        cover_url = image_links.get("extraLarge") or image_links.get("large") or image_links.get("medium") or image_links.get("thumbnail")
        if cover_url and cover_url.startswith("http://"): 
            cover_url = cover_url.replace("http://", "https://")

        year = None
        published_date = volume_info.get("publishedDate", "")
        if published_date and published_date[:4].isdigit(): 
            year = int(published_date[:4])

        staff = [{"role": "Story", "node": {"name": {"full": author.strip()}}} for author in volume_info.get("authors", [])]
        genres = [cat.strip() for cat in volume_info.get("categories", []) if cat.strip()]
        tags = ["Books", "GoogleBooks"] + [g for g in genres if g not in ["Books", "GoogleBooks"]]
        
        summary = volume_info.get("description", "").strip()
        info_link = volume_info.get("canonicalVolumeLink") or volume_info.get("infoLink")
        
        fetched_title = volume_info.get("title", "")
        subtitle = volume_info.get("subtitle", "")
        alt_titles = [subtitle] if subtitle else []

        # BF56: maturityRating Google est binaire — MATURE → erotica ; sinon omettre
        # (NOT_MATURE n'est pas une preuve « Everyone », ne pas inventer safe).
        age_rating = ""
        if (volume_info.get("maturityRating") or "").upper() == "MATURE":
            age_rating = "erotica"

        return {
            'title': fetched_title,
            'alternative_titles': alt_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres[:get_max_genres()],
            'tags': tags[:get_max_tags()],
            'year': year,
            'staff': staff,
            'publisher': volume_info.get("publisher"),
            'isbn': isbn,
            'age_rating': age_rating,
            'format': 'book',
            'url': info_link,
            'links': [info_link] if info_link else []
        }

    def fetch_volume(
        self,
        query: str,
        volume_number=None,
        library_type: str = "Book",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Métadonnées d'un tome précis, par titre de série et numéro.

        C'est le seul chemin qui donne un titre et un résumé à un manga scanné
        sans ISBN — le cas courant. C'est aussi le plus fragile : une recherche
        « Berserk 7 » rend volontiers un artbook, un guide, une intégrale ou le
        tome 7 d'une autre série chez le même éditeur. Chaque résultat est donc
        revérifié contre le titre **et** contre le numéro avant d'être rendu, et
        on préfère ne rien rendre à rendre un tome plausible.
        """
        number = _volume_token(volume_number)
        if number is None:
            return None
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return None

        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        google_lang = str(config.get("TARGET_LANG", "") or "").lower()[:2]
        params = {
            "q": f'intitle:"{cleaned}" {number}',
            "maxResults": 10,
            "orderBy": "relevance",
            "country": self.DEFAULT_COUNTRY,
            "printType": "books",
        }
        if google_lang:
            params["langRestrict"] = google_lang
        if api_key:
            params["key"] = api_key

        try:
            res = self._http_get(
                requests, "https://www.googleapis.com/books/v1/volumes", params=params, timeout=12
            )
            if not response_is_ok(self, res, context="tome précis d'une série"):
                return None
            for item in (res.json() or {}).get("items", []):
                info = item.get("volumeInfo") or {}
                full = " ".join(
                    part for part in (info.get("title"), info.get("subtitle")) if part
                )
                if not _title_matches_series(full, cleaned):
                    continue
                if _volume_in_title(full) != number:
                    continue
                candidate = self._build_candidate(info, item.get("id"))
                if candidate:
                    logging.info(self.t("volume_matched").format(number, full))
                    return candidate
        except Exception as e:
            logging.debug(self.t("err").format(e))
        return None

    def fetch_covers(self, query: str, library_type: str = "Book") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        config = load_config()
        api_key = config.get("GOOGLEBOOKS_API_KEY", "").strip()
        url = "https://www.googleapis.com/books/v1/volumes"
        params = {"q": cleaned, "maxResults": 4, "country": self.DEFAULT_COUNTRY, "printType": "books"}
        if api_key: params["key"] = api_key
        try:
            res = self._http_get(requests, url, params=params, timeout=10)
            if response_is_ok(self, res, context="couvertures"):
                for item in res.json().get("items", []):
                    vol = item.get("volumeInfo", {})
                    img = vol.get("imageLinks", {})
                    cover_url = img.get("extraLarge") or img.get("large") or img.get("thumbnail")
                    if cover_url:
                        if cover_url.startswith("http://"): cover_url = cover_url.replace("http://", "https://")
                        title = vol.get("title", "Inconnu")
                        covers.append({"provider": "GoogleBooks", "title": title, "url": cover_url})
        except Exception as e:
            logging.debug("GoogleBooks cover search failed: %s", safe_exc_str(e))
        return covers