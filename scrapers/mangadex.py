import logging
import requests
import re
from typing import Dict, Any, List, Optional
from .base import BaseScraper
from .utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)
from config_manager import load_config, get_max_tags

_UUID_RE = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)


class MangaDexScraper(BaseScraper):
    id = "MANGADEX"
    is_core = True
    display_name = "MangaDex (API)"
    supported_types = {"Manga"}
    scopes = {"series", "volume"}
    # 1.1.0 : couvertures de tome (issue #27).
    # 1.2.0 : la pagination des couvertures s'espaçait avec un `time.sleep` posé
    # entre deux pages, qui ne couvrait ni la recherche ni la fiche de série ; la
    # cadence est maintenant portée par chaque requête, et les refus de l'API
    # (429, 5xx) sont journalisés au lieu de rendre un index vide en silence. La
    # montée de version est ce qui autorise l'image à remplacer la copie déjà
    # installée sous data/.
    version = "1.2.0"
    rate_limit = 0.25  # ~4.5/s: 10% under MangaDex global ~5 req/s
    proxy_domains = ["mangadex.org", "uploads.mangadex.org", "api.mangadex.org"]
    has_direct_id_support = True
    requires_proxy = True
    uses_unified_scoring = True
    proxy_referer = "https://mangadex.org/"

    translations = {
        "fr": {
            "direct_uuid": "[MangaDex] Requête directe par UUID : '{0}'",
            "search_title": "[MangaDex] Recherche par titre : '{0}'",
            "no_match": "⚠️ [MangaDex] Aucun résultat pertinent trouvé pour '{0}'",
            "matched": "🎯 [MangaDex] Match validé (Score pondéré: {0}%)",
            "err": "[MangaDex] Erreur : {0}",
            "covers_err": "[Covers] Erreur MangaDex : {0}",
            "index_err": "[MangaDex] Couvertures par tome — erreur : {0}"
        },
        "en": {
            "direct_uuid": "[MangaDex] Direct request by UUID: '{0}'",
            "search_title": "[MangaDex] Title search: '{0}'",
            "no_match": "⚠️ [MangaDex] No relevant result found for '{0}'",
            "matched": "🎯 [MangaDex] Match validated (Weighted score: {0}%)",
            "err": "[MangaDex] Error: {0}",
            "covers_err": "[Covers] MangaDex error: {0}",
            "index_err": "[MangaDex] Per-volume covers failed: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "mangadex.org" in url:
            match = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', url)
            if match:
                return match.group(1)
        return None

    def _build_candidate(self, manga_data: dict, target_lang: str) -> Optional[Dict[str, Any]]:
        """Construit un candidat standardisé complet (titre + staff + résumé...) à partir
        d'un objet manga MangaDex. Utilisée à la fois pour le résultat direct par UUID et pour
        CHAQUE résultat de recherche : le staff (auteur/artiste) est déjà inclus dans la réponse
        de recherche grâce à `includes[]=author,artist`, donc construire le candidat complet ici
        ne coûte aucune requête HTTP supplémentaire — condition nécessaire pour pouvoir évaluer
        chaque candidat avec `score_candidate()` (et sa protection anti-homonyme par auteur).
        """
        attrs = manga_data.get("attributes", {})
        manga_id = manga_data.get("id")

        main_titles = list(attrs.get("title", {}).values())
        primary_title = main_titles[0] if main_titles else ""
        if not primary_title:
            return None

        titles = []
        alt_titles = []
        for lang_key, title_val in (attrs.get("title") or {}).items():
            if title_val:
                titles.append({"lang": lang_key, "value": title_val})
                if title_val not in alt_titles:
                    alt_titles.append(title_val)
        for alt_dict in attrs.get("altTitles", []):
            if not isinstance(alt_dict, dict):
                continue
            for lang_key, alt_val in alt_dict.items():
                if alt_val and alt_val not in alt_titles:
                    alt_titles.append(alt_val)
                    titles.append({"lang": lang_key, "value": alt_val})

        descriptions = attrs.get("description", {})
        summary = descriptions.get(target_lang) or descriptions.get("fr") or descriptions.get("en")
        if not summary and descriptions:
            summary = next(iter(descriptions.values()))

        year = attrs.get("year")
        raw_status = attrs.get("status", "").lower()
        status = "RELEASING"
        if raw_status == "completed": status = "FINISHED"
        elif raw_status == "hiatus": status = "HIATUS"
        elif raw_status == "cancelled": status = "CANCELLED"

        # BF56: contentRating MangaDex est autoritatif ; absent → ne pas inventer safe.
        raw_rating = (attrs.get("contentRating") or "").lower()
        age_rating = ""
        if raw_rating in ("safe",):
            age_rating = "safe"
        elif raw_rating in ("erotica", "pornographic"):
            age_rating = "pornographic"
        elif raw_rating == "suggestive":
            age_rating = "suggestive"

        orig_lang = str(attrs.get("originalLanguage", "")).lower()
        format_type = "manga"
        if orig_lang in ["ko", "zh"]: format_type = "webtoon"

        tags = ["MangaDex"]
        for tag_obj in attrs.get("tags") or []:
            t_name = (tag_obj.get("attributes") or {}).get("name") or {}
            tag_str = t_name.get("en") or t_name.get(target_lang)
            if tag_str and tag_str not in tags:
                tags.append(tag_str)

        staff = []
        cover_url = None

        for rel in manga_data.get("relationships", []):
            rel_type = rel.get("type")
            rel_attrs = rel.get("attributes", {})
            if rel_type == "author" and rel_attrs.get("name"):
                staff.append({"role": "Story", "node": {"name": {"full": rel_attrs.get("name")}}})
            elif rel_type == "artist" and rel_attrs.get("name"):
                staff.append({"role": "Art", "node": {"name": {"full": rel_attrs.get("name")}}})
            elif rel_type == "cover_art" and rel_attrs.get("fileName"):
                cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{rel_attrs.get('fileName')}"

        links = attrs.get("links", {})
        anilist_id = links.get("al") if links.get("al") and str(links.get("al")).isdigit() else None
        mal_id = links.get("mal") if links.get("mal") and str(links.get("mal")).isdigit() else None

        return {
            'title': primary_title,
            'alternative_titles': alt_titles,
            'titles': titles,
            'summary': summary or "",
            'cover_url': cover_url,
            'genres': ["Manga"],
            'tags': tags[:get_max_tags()],
            'year': year,
            'status': status,
            'staff': staff,
            'publisher': None,
            'age_rating': age_rating,
            'format': format_type,
            'anilist_id': anilist_id,
            'mal_id': mal_id,
            'url': f"https://mangadex.org/title/{manga_id}"
        }

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        config = load_config()
        target_lang = config.get("TARGET_LANG", "FR").lower()[:2]
        base_url = "https://api.mangadex.org/manga"
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5"}

        try:
            common_includes = [("includes[]", "author"), ("includes[]", "artist"), ("includes[]", "cover_art")]

            if is_id:
                logging.info(self.t("direct_uuid").format(query))
                url = f"{base_url}/{query}"
                res = self._http_get(requests, url, params=common_includes, headers=headers, timeout=12)
                if not response_is_ok(self, res, context="fiche par UUID"): return None
                manga_data = res.json().get("data")
                return attach_match_score(self._build_candidate(manga_data, target_lang), 1.0) if manga_data else None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None

            logging.info(self.t("search_title").format(cleaned))
            params = [
                ("title", cleaned),
                ("limit", "5"),
                ("order[relevance]", "desc"),
                ("contentRating[]", "safe"),
                ("contentRating[]", "suggestive"),
                ("contentRating[]", "erotica"),
                ("contentRating[]", "pornographic")
            ] + common_includes

            res = self._http_get(requests, base_url, params=params, headers=headers, timeout=12)
            if not response_is_ok(self, res, context="recherche par titre"): return None

            items = res.json().get("data", [])
            if not items: return None

            best_match = None
            best_score = -1.0

            for item in items:
                candidate = self._build_candidate(item, target_lang)
                if not candidate: continue

                # Évaluation avec la matrice unifiée (titre + auteur/artiste + anti-homonyme).
                score = score_candidate(candidate, cleaned, existing_metadata)

                # Pénalité spécifique MangaDex : un "oneshot" (histoire courte isolée, souvent
                # au titre identique à la série mère) ne doit pas remplacer la série multi-tomes
                # réellement recherchée, sauf si l'utilisateur cherche explicitement un oneshot.
                # Ce signal n'existe pas dans score_candidate(), il reste donc un ajustement local.
                attrs = item.get("attributes") or {}
                tag_names = [
                    str(((t.get("attributes") or {}).get("name") or {}).get("en") or "").lower()
                    for t in attrs.get("tags") or []
                ]
                main_titles = list((attrs.get("title") or {}).values())
                is_oneshot = "oneshot" in tag_names or any("oneshot" in str(t).lower() for t in main_titles)
                if is_oneshot and "oneshot" not in cleaned.lower():
                    score -= 0.20

                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < get_match_accept_threshold():
                logging.warning(self.t("no_match").format(cleaned))
                return None

            logging.info(self.t("matched").format(int(best_score*100)))
            return attach_match_score(best_match, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    #: Nombre de pages de couvertures lues au plus. Cent couvertures par page,
    #: et le filtre de langue en écarte déjà l'essentiel : trois pages couvrent
    #: One Piece et ses cent tomes sans laisser la porte ouverte à une série
    #: pathologique qui tirerait vingt appels.
    COVER_PAGES_MAX = 3

    def _resolve_manga_uuid(self, query: str, series_id: Optional[str]) -> Optional[str]:
        """UUID MangaDex de la série, par identifiant forcé ou par recherche."""
        raw = str(series_id or "").strip()
        if raw:
            uuid = self.extract_id_from_url(raw) if raw.startswith("http") else raw
            if uuid and _UUID_RE.fullmatch(uuid):
                return uuid
        # Pas d'identifiant utilisable : on repasse par `fetch`, et donc par le
        # score d'appariement. Une recherche brute rendrait le premier résultat
        # venu, ce qui suffirait à coller les couvertures d'une autre série.
        candidate = self.fetch(query, library_type="Manga")
        return self.extract_id_from_url((candidate or {}).get("url") or "")

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Manga",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """`{numéro de tome: couverture}` — le seul apport de MangaDex par tome.

        MangaDex ne publie ni résumé ni ISBN par tome : ses métadonnées sont
        celles de la série. Il tient en revanche la couverture de chaque tome,
        dans chaque langue d'édition, et c'est exactement ce qui manque à un
        manga scanné : Kavita affiche sinon une vignette découpée dans la
        première page, souvent une page de garde noire.

        Un appel couvre toute la série, contre un appel par tome ailleurs.
        """
        config = load_config()
        target = str(config.get("TARGET_LANG", "FR")).lower()[:2]
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5"}

        try:
            manga_id = self._resolve_manga_uuid(query, series_id)
            if not manga_id:
                return None

            # Une série populaire a des couvertures dans trente langues. Les
            # filtrer côté serveur évite de payer la pagination pour des
            # éditions qu'on écarterait de toute façon.
            locales = list(dict.fromkeys([target, "ja", "en"]))
            found: Dict[str, Dict[str, Any]] = {}
            offset = 0
            for _page in range(self.COVER_PAGES_MAX):
                params = [("manga[]", manga_id), ("limit", "100"),
                          ("offset", str(offset)), ("order[volume]", "asc")]
                params += [("locales[]", loc) for loc in locales]
                res = self._http_get(
                    requests, "https://api.mangadex.org/cover", params=params,
                    headers=headers, timeout=15
                )
                if not response_is_ok(self, res, context="couvertures des tomes"):
                    break
                body = res.json() or {}
                items = body.get("data") or []
                for item in items:
                    attrs = item.get("attributes") or {}
                    volume = str(attrs.get("volume") or "").strip()
                    file_name = attrs.get("fileName")
                    if not volume or not file_name:
                        continue
                    locale = str(attrs.get("locale") or "").lower()
                    rank = locales.index(locale) if locale in locales else len(locales)
                    # Deux éditions du même tome : la langue demandée l'emporte,
                    # l'édition d'origine ensuite.
                    if volume in found and found[volume]["rank"] <= rank:
                        continue
                    found[volume] = {
                        "rank": rank,
                        "cover_url": f"https://uploads.mangadex.org/covers/{manga_id}/{file_name}",
                    }
                offset += len(items)
                if len(items) < 100 or offset >= int(body.get("total") or 0):
                    break
                # Plus de pause explicite entre deux pages : `_http_get` garantit
                # désormais le `rate_limit` requête par requête.

            index = {vol: {"cover_url": data["cover_url"]} for vol, data in found.items()}
            return index or None
        except Exception as e:
            logging.error(self.t("index_err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5"}
        
        try:
            res_manga = self._http_get(
                requests,
                "https://api.mangadex.org/manga",
                params={"title": cleaned, "limit": 2, "includes[]": "cover_art"},
                headers=headers,
                timeout=10
            )

            if response_is_ok(self, res_manga, context="couvertures"):
                manga_list = res_manga.json().get("data", [])
                
                for manga in manga_list:
                    m_id = manga.get("id")
                    title_dict = (manga.get("attributes") or {}).get("title") or {}
                    title = list(title_dict.values())[0] if title_dict else "Inconnu"
                    
                    for rel in manga.get("relationships") or []:
                        fn = (rel.get("attributes") or {}).get("fileName")
                        if rel.get("type") == "cover_art" and fn:
                            covers.append({
                                "provider": "MangaDex",
                                "title": title,
                                "url": f"https://uploads.mangadex.org/covers/{m_id}/{fn}"
                            })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
            
        return covers