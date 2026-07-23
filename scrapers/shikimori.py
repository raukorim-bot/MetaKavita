import logging
import requests
import re
from typing import Dict, Any, List, Optional
from .base import BaseScraper
from .utils import clean_title, calculate_similarity, normalize_str

STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or", "no", "de", "la", "le", "les", "du", "un", "une", "des"}

def extract_meaningful_words(title: str) -> set:
    normalized = normalize_str(title)
    words = set(re.findall(r'\b\w+\b', normalized))
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}

def clean_shikimori_text(text: str) -> str:
    if not text: return ""
    cleaned = re.sub(r'\[/?[a-zA-Z0-9=\":._\-]+\]', '', text)
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    return cleaned.strip()

def format_author_name(name: str) -> str:
    if not name or not isinstance(name, str): return ""
    if ',' in name:
        parts = name.split(',', 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name.strip()

class ShikimoriScraper(BaseScraper):
    id = "SHIKIMORI"
    display_name = "Shikimori (API JSON)"
    supported_types = {"Manga"}
    rate_limit = 0.5
    proxy_domains = ["shikimori.one", "shikimori.me"]
    has_direct_id_support = True
    requires_proxy = False

    translations = {
        "fr": {
            "direct_id": "[Shikimori] Requête directe par ID : '{0}'",
            "search_title": "[Shikimori] Recherche par titre : '{0}'",
            "no_match": "⚠️ [Shikimori] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Shikimori] Match validé (ID: {0}, Score: {1}%)",
            "err": "[Shikimori] Erreur : {0}",
            "staff_err": "[Shikimori Staff] Erreur : {0}",
            "covers_err": "[Covers] Erreur Shikimori : {0}"
        },
        "en": {
            "direct_id": "[Shikimori] Direct request by ID: '{0}'",
            "search_title": "[Shikimori] Title search: '{0}'",
            "no_match": "⚠️ [Shikimori] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Shikimori] Match validated (ID: {0}, Score: {1}%)",
            "err": "[Shikimori] Error: {0}",
            "staff_err": "[Shikimori Staff] Error: {0}",
            "covers_err": "[Covers] Shikimori error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str): return None
        if "shikimori." in url:
            match = re.search(r'/mangas/([zZ]?\d+)', url)
            if match:
                return match.group(1).lstrip('zZ')
        return None

    def _parse_shikimori_record(self, data: Dict[str, Any], headers: dict) -> Optional[Dict[str, Any]]:
        if not data or not isinstance(data, dict): return None

        manga_id = data.get("id")
        primary_title = data.get("name", "") or ""

        alt_titles = []
        raw_alts = []
        
        if isinstance(data.get("english"), list): raw_alts.extend(data["english"])
        elif isinstance(data.get("english"), str): raw_alts.append(data["english"])
        
        if isinstance(data.get("japanese"), list): raw_alts.extend(data["japanese"])
        elif isinstance(data.get("japanese"), str): raw_alts.append(data["japanese"])

        if isinstance(data.get("synonyms"), list): raw_alts.extend(data["synonyms"])
        elif isinstance(data.get("synonyms"), str): raw_alts.append(data["synonyms"])

        for alt in raw_alts:
            if alt and isinstance(alt, str) and alt.strip():
                clean_alt = alt.strip()
                if clean_alt not in alt_titles and clean_alt != primary_title:
                    alt_titles.append(clean_alt)

        summary = clean_shikimori_text(data.get("description", "") or "")

        cover_url = None
        img_dict = data.get("image")
        if isinstance(img_dict, dict):
            rel_path = img_dict.get("original") or img_dict.get("preview")
            if rel_path:
                cover_url = rel_path if rel_path.startswith("http") else f"https://shikimori.one{rel_path}"

        year = None
        aired_on = data.get("aired_on") or data.get("released_on") or ""
        if aired_on and len(str(aired_on)) >= 4 and str(aired_on)[:4].isdigit():
            year = int(str(aired_on)[:4])

        raw_status = str(data.get("status", "")).lower()
        status = "RELEASING"
        if raw_status in ["released", "finished"]: status = "FINISHED"
        elif raw_status in ["paused", "anons"]: status = "HIATUS"
        elif raw_status in ["discontinued", "cancelled"]: status = "CANCELLED"

        kind = str(data.get("kind", "")).lower()
        format_type = "manga"
        if kind in ["manhwa", "manhua"]: format_type = "webtoon"
        elif kind in ["light_novel", "novel"]: format_type = "book"

        genres = []
        for g in (data.get("genres") or []):
            if isinstance(g, dict) and g.get("name"): genres.append(g["name"])

        tags = ["Shikimori"] + genres

        publisher = None
        publishers_list = data.get("publishers") or []
        if publishers_list and isinstance(publishers_list, list) and isinstance(publishers_list[0], dict):
            publisher = publishers_list[0].get("name")

        staff = []
        try:
            roles_url = f"https://shikimori.one/api/mangas/{manga_id}/roles"
            roles_res = requests.get(roles_url, headers=headers, timeout=5)
            if roles_res.status_code == 200:
                for item in (roles_res.json() or []):
                    if isinstance(item, dict):
                        p_node = item.get("person") or {}
                        raw_name = p_node.get("name") or p_node.get("russian")
                        p_name = format_author_name(raw_name)
                        
                        roles_lower = [str(r).lower() for r in (item.get("roles") or [])]
                        if p_name and roles_lower:
                            has_story = any(k in r for r in roles_lower for k in ["story", "author", "mangaka", "writer"])
                            has_art = any(k in r for r in roles_lower for k in ["art", "artist", "illustration", "draw"])

                            if has_story: staff.append({"role": "Story", "node": {"name": {"full": p_name}}})
                            if has_art: staff.append({"role": "Art", "node": {"name": {"full": p_name}}})
        except Exception as e:
            logging.error(self.t("staff_err").format(e))

        site_url = f"https://shikimori.one{data.get('url')}" if data.get("url") else f"https://shikimori.one/mangas/{manga_id}"

        return {
            'title': primary_title,
            'alternative_titles': alt_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres[:5] if genres else ["Manga"],
            'tags': tags[:15],
            'year': year,
            'status': status,
            'staff': staff,
            'publisher': publisher,
            'age_rating': 'safe',
            'format': format_type,
            'mal_id': manga_id,
            'url': site_url
        }

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5", "Accept": "application/json"}

        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                url = f"https://shikimori.one/api/mangas/{query}"
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200:
                    return self._parse_shikimori_record(res.json(), headers)
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None

            logging.info(self.t("search_title").format(cleaned))
            search_url = "https://shikimori.one/api/mangas"
            params = {"search": cleaned, "limit": 5}

            res = requests.get(search_url, params=params, headers=headers, timeout=10)
            if res.status_code != 200: return None

            items = res.json()
            if not isinstance(items, list) or not items: return None

            query_keywords = extract_meaningful_words(cleaned)
            best_match_detail = None
            best_score = -1.0

            for item in items:
                item_id = item.get("id")
                romaji_name = item.get("name", "")
                
                detail_res = requests.get(f"https://shikimori.one/api/mangas/{item_id}", headers=headers, timeout=10)
                if detail_res.status_code == 200:
                    detail_data = detail_res.json()
                    
                    titles_to_check = [romaji_name]
                    eng = detail_data.get("english")
                    if isinstance(eng, list): titles_to_check.extend(eng)
                    elif isinstance(eng, str): titles_to_check.append(eng)

                    jap = detail_data.get("japanese")
                    if isinstance(jap, list): titles_to_check.extend(jap)
                    elif isinstance(jap, str): titles_to_check.append(jap)

                    syns = detail_data.get("synonyms")
                    if isinstance(syns, list): titles_to_check.extend(syns)

                    item_score = 0.0
                    for t in titles_to_check:
                        if not t: continue
                        score = calculate_similarity(cleaned, str(t))
                        if score > item_score: item_score = score

                    if item_score <= 0.0: continue

                    total_score = item_score
                    if query_keywords:
                        combined_text = " ".join([str(t) for t in titles_to_check if t])
                        item_words = extract_meaningful_words(combined_text)
                        missing = query_keywords - item_words
                        if missing: total_score -= (0.25 * len(missing))

                    if total_score > best_score:
                        best_score = total_score
                        best_match_detail = detail_data

            if not best_match_detail or best_score < 0.45:
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_match_detail.get('id'), int(best_score*100)))
            return self._parse_shikimori_record(best_match_detail, headers)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers

        headers = {"User-Agent": "MetaKavita-Fetcher/1.5", "Accept": "application/json"}

        try:
            res = requests.get("https://shikimori.one/api/mangas", params={"search": cleaned, "limit": 5}, headers=headers, timeout=8)
            if res.status_code == 200:
                items = res.json()
                if isinstance(items, list):
                    query_keywords = extract_meaningful_words(cleaned)

                    for item in items:
                        item_id = item.get("id")
                        romaji_title = item.get("name", "Inconnu")
                        img_dict = item.get("image") or {}
                        rel_path = img_dict.get("original") or img_dict.get("preview")

                        if rel_path:
                            cover_url = rel_path if rel_path.startswith("http") else f"https://shikimori.one{rel_path}"
                            detail_res = requests.get(f"https://shikimori.one/api/mangas/{item_id}", headers=headers, timeout=5)
                            titles_to_check = [romaji_title]
                            display_title = romaji_title

                            if detail_res.status_code == 200:
                                d_data = detail_res.json()
                                eng = d_data.get("english")
                                if isinstance(eng, list) and eng:
                                    titles_to_check.extend(eng)
                                    display_title = eng[0]
                                elif isinstance(eng, str):
                                    titles_to_check.append(eng)
                                    display_title = eng

                                syns = d_data.get("synonyms")
                                if isinstance(syns, list): titles_to_check.extend(syns)

                            score = 0.0
                            for t in titles_to_check:
                                if not t: continue
                                s = calculate_similarity(cleaned, str(t))
                                if s > score: score = s

                            if query_keywords:
                                combined_text = " ".join([str(t) for t in titles_to_check if t])
                                item_words = extract_meaningful_words(combined_text)
                                missing = query_keywords - item_words
                                if missing: score -= (0.25 * len(missing))

                            if score >= 0.45:
                                covers.append({
                                    "provider": "Shikimori",
                                    "title": display_title,
                                    "url": cover_url
                                })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))

        return covers[:4]