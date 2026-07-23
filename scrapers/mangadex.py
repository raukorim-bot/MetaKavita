import logging
import requests
import re
from typing import Dict, Any, List, Optional
from .base import BaseScraper
from .utils import clean_title, calculate_similarity, normalize_str
from config_manager import load_config

class MangaDexScraper(BaseScraper):
    id = "MANGADEX"
    display_name = "MangaDex (API)"
    supported_types = {"Manga"}
    rate_limit = 0.5
    proxy_domains = ["mangadex.org", "uploads.mangadex.org", "api.mangadex.org"]
    has_direct_id_support = True
    requires_proxy = True
    proxy_referer = "https://mangadex.org/"

    translations = {
        "fr": {
            "direct_uuid": "[MangaDex] Requête directe par UUID : '{0}'",
            "search_title": "[MangaDex] Recherche par titre : '{0}'",
            "no_match": "⚠️ [MangaDex] Aucun résultat pertinent trouvé pour '{0}'",
            "matched": "🎯 [MangaDex] Match validé (Score pondéré: {0}%)",
            "err": "[MangaDex] Erreur : {0}",
            "covers_err": "[Covers] Erreur MangaDex : {0}"
        },
        "en": {
            "direct_uuid": "[MangaDex] Direct request by UUID: '{0}'",
            "search_title": "[MangaDex] Title search: '{0}'",
            "no_match": "⚠️ [MangaDex] No relevant result found for '{0}'",
            "matched": "🎯 [MangaDex] Match validated (Weighted score: {0}%)",
            "err": "[MangaDex] Error: {0}",
            "covers_err": "[Covers] MangaDex error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "mangadex.org" in url:
            match = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', url)
            if match:
                return match.group(1)
        return None

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        config = load_config()
        target_lang = config.get("TARGET_LANG", "FR").lower()[:2]
        base_url = "https://api.mangadex.org/manga"
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5"}
        manga_data = None

        try:
            common_includes = [("includes[]", "author"), ("includes[]", "artist"), ("includes[]", "cover_art")]

            if is_id:
                logging.info(self.t("direct_uuid").format(query))
                url = f"{base_url}/{query}"
                res = requests.get(url, params=common_includes, headers=headers, timeout=12)
                if res.status_code == 200:
                    manga_data = res.json().get("data")
            else:
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

                res = requests.get(base_url, params=params, headers=headers, timeout=12)
                if res.status_code != 200: return None
                
                items = res.json().get("data", [])
                if not items: return None

                best_match = None
                best_score = -1.0

                for item in items:
                    attrs = item.get("attributes", {})
                    main_titles = list(attrs.get("title", {}).values())
                    titles_to_check = list(main_titles)
                    for alt in attrs.get("altTitles", []):
                        titles_to_check.extend(alt.values())

                    item_title_score = 0.0
                    for t in titles_to_check:
                        if not t: continue
                        score = calculate_similarity(cleaned, t)
                        if score > item_title_score:
                            item_title_score = score

                    if item_title_score <= 0.0: continue

                    total_score = item_title_score

                    tag_names = [str(t.get("attributes", {}).get("name", {}).get("en", "")).lower() for t in attrs.get("tags", [])]
                    is_oneshot = "oneshot" in tag_names or any("oneshot" in str(t).lower() for t in main_titles)

                    if is_oneshot and "oneshot" not in cleaned.lower():
                        total_score -= 0.20

                    descriptions = attrs.get("description", {})
                    if descriptions and any(len(d.strip()) > 30 for d in descriptions.values()):
                        total_score += 0.10

                    if any(normalize_str(cleaned) == normalize_str(mt) for mt in main_titles):
                        total_score += 0.05

                    if total_score > best_score:
                        best_score = total_score
                        best_match = item

                if not best_match or best_score < 0.50:
                    logging.warning(self.t("no_match").format(cleaned))
                    return None

                manga_data = best_match
                logging.info(self.t("matched").format(int(best_score*100)))

            if not manga_data: return None

            attrs = manga_data.get("attributes", {})
            manga_id = manga_data.get("id")

            main_titles = list(attrs.get("title", {}).values())
            primary_title = main_titles[0] if main_titles else ""
            
            alt_titles = []
            for alt_dict in attrs.get("altTitles", []):
                for alt_val in alt_dict.values():
                    if alt_val and alt_val not in alt_titles:
                        alt_titles.append(alt_val)

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

            raw_rating = attrs.get("contentRating", "safe").lower()
            age_rating = "safe"
            if raw_rating in ["erotica", "pornographic"]: age_rating = "pornographic"
            elif raw_rating == "suggestive": age_rating = "suggestive"

            orig_lang = str(attrs.get("originalLanguage", "")).lower()
            format_type = "manga"
            if orig_lang in ["ko", "zh"]: format_type = "webtoon"

            tags = ["MangaDex"]
            for tag_obj in attrs.get("tags", []):
                t_name = tag_obj.get("attributes", {}).get("name", {})
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
                'summary': summary or "",
                'cover_url': cover_url,
                'genres': ["Manga"],
                'tags': tags[:15],
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

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5"}
        
        try:
            res_manga = requests.get(
                "https://api.mangadex.org/manga",
                params={"title": cleaned, "limit": 2, "includes[]": "cover_art"},
                headers=headers,
                timeout=10
            )
            
            if res_manga.status_code == 200:
                manga_list = res_manga.json().get("data", [])
                
                for manga in manga_list:
                    m_id = manga.get("id")
                    title_dict = manga.get("attributes", {}).get("title", {})
                    title = list(title_dict.values())[0] if title_dict else "Inconnu"
                    
                    for rel in manga.get("relationships", []):
                        if rel.get("type") == "cover_art" and rel.get("attributes", {}).get("fileName"):
                            fn = rel.get("attributes", {}).get("fileName")
                            covers.append({
                                "provider": "MangaDex",
                                "title": title,
                                "url": f"https://uploads.mangadex.org/covers/{m_id}/{fn}"
                            })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
            
        return covers