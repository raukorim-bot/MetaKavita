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

def clean_mangaupdates_text(text: str) -> str:
    if not text: return ""
    cleaned = re.sub(r'\[/?[a-zA-Z0-9=\":._\-]+\]', '', text)
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    return cleaned.strip()

class MangaUpdatesScraper(BaseScraper):
    id = "MANGAUPDATES"
    display_name = "MangaUpdates (Baka-Updates)"
    supported_types = {"Manga"}
    rate_limit = 1.0
    proxy_domains = ["mangaupdates.com", "api.mangaupdates.com", "www.mangaupdates.com"]
    has_direct_id_support = True
    requires_proxy = False

    translations = {
        "fr": {
            "direct_id": "[MangaUpdates] Requête directe par ID : '{0}'",
            "search_title": "[MangaUpdates] Recherche par titre : '{0}'",
            "no_match": "⚠️ [MangaUpdates] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [MangaUpdates] Match validé (ID: {0}, Score: {1}%)",
            "err": "[MangaUpdates] Erreur : {0}",
            "covers_err": "[Covers] Erreur MangaUpdates : {0}"
        },
        "en": {
            "direct_id": "[MangaUpdates] Direct request by ID: '{0}'",
            "search_title": "[MangaUpdates] Title search: '{0}'",
            "no_match": "⚠️ [MangaUpdates] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [MangaUpdates] Match validated (ID: {0}, Score: {1}%)",
            "err": "[MangaUpdates] Error: {0}",
            "covers_err": "[Covers] MangaUpdates error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str): return None
        if "mangaupdates.com" in url:
            match_param = re.search(r'[?&]id=(\d+)', url)
            if match_param: return match_param.group(1)
            
            match_path = re.search(r'/series/([a-zA-Z0-9]+)', url)
            if match_path: return match_path.group(1)
        return None

    def _parse_series_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not record or not isinstance(record, dict): return None

        series_id = record.get("series_id")
        title = record.get("title", "") or ""
        
        alt_titles = []
        for assoc in (record.get("associated") or []):
            if isinstance(assoc, dict) and assoc.get("title"):
                alt_titles.append(assoc["title"])
            elif isinstance(assoc, str):
                alt_titles.append(assoc)

        summary = clean_mangaupdates_text(record.get("description", "") or "")

        cover_url = None
        img_dict = record.get("image")
        if isinstance(img_dict, dict):
            url_dict = img_dict.get("url", {})
            if isinstance(url_dict, dict):
                cover_url = url_dict.get("original") or url_dict.get("thumb")

        year = None
        year_val = record.get("year")
        if year_val and str(year_val).isdigit(): year = int(year_val)

        is_completed = record.get("completed", False)
        status = "FINISHED" if is_completed else "RELEASING"

        type_str = str(record.get("type", "")).upper()
        format_type = "manga"
        if "MANHWA" in type_str or "WEBTOON" in type_str or "MANHUA" in type_str:
            format_type = "webtoon"

        staff = []
        for author in (record.get("authors") or []):
            if isinstance(author, dict):
                a_name = author.get("name")
                a_type = str(author.get("type", "")).lower()
                if a_name:
                    role = "Story" if "author" in a_type or "story" in a_type else "Art"
                    staff.append({"role": role, "node": {"name": {"full": a_name}}})

        genres = []
        for g in (record.get("genres") or []):
            if isinstance(g, dict) and g.get("genre"): genres.append(g["genre"])
            elif isinstance(g, str): genres.append(g)

        tags = ["MangaUpdates"] + genres
        for cat in (record.get("categories") or [])[:10]:
            if isinstance(cat, dict) and cat.get("category"): tags.append(cat["category"])

        site_url = record.get("url") or f"https://www.mangaupdates.com/series.html?id={series_id}"

        return {
            'title': title,
            'alternative_titles': alt_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres[:5] if genres else ["Manga"],
            'tags': tags[:15],
            'year': year,
            'status': status,
            'staff': staff,
            'publisher': None,
            'age_rating': 'safe',
            'format': format_type,
            'url': site_url
        }

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        headers = {
            "User-Agent": "MetaKavita-Fetcher/1.5",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            if is_id:
                logging.info(self.t("direct_id").format(query))
                url = f"https://api.mangaupdates.com/v1/series/{query}"
                res = requests.get(url, headers=headers, timeout=12)
                if res.status_code == 200:
                    return self._parse_series_record(res.json())
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None

            logging.info(self.t("search_title").format(cleaned))
            search_url = "https://api.mangaupdates.com/v1/series/search"
            payload = {"search": cleaned, "perpage": 5, "page": 1}

            res = requests.post(search_url, json=payload, headers=headers, timeout=12)
            if res.status_code != 200: return None

            results = res.json().get("results", []) or []
            if not results: return None

            query_keywords = extract_meaningful_words(cleaned)
            best_match_id = None
            best_score = -1.0

            for item in results:
                record = item.get("record", {}) or {}
                title = record.get("title", "") or ""
                hit_title = item.get("hit_title", "") or ""
                
                titles_to_check = [title] if title else []
                if hit_title and hit_title not in titles_to_check:
                    titles_to_check.append(hit_title)

                for assoc in (record.get("associated") or []):
                    if isinstance(assoc, dict) and assoc.get("title"):
                        titles_to_check.append(assoc["title"])
                    elif isinstance(assoc, str):
                        titles_to_check.append(assoc)

                item_score = 0.0
                for t in titles_to_check:
                    if not t: continue
                    score = calculate_similarity(cleaned, t)
                    if score > item_score: item_score = score

                if item_score <= 0.0: continue

                total_score = item_score

                if query_keywords:
                    record_text = f"{title} {hit_title} " + " ".join([str(a) for a in titles_to_check])
                    record_keywords = extract_meaningful_words(record_text)
                    missing_keywords = query_keywords - record_keywords
                    if missing_keywords:
                        total_score -= (0.25 * len(missing_keywords))

                desc = record.get("description", "") or ""
                if len(desc.strip()) > 30: total_score += 0.10

                if normalize_str(cleaned) in [normalize_str(t) for t in titles_to_check]:
                    total_score += 0.05

                if total_score > best_score:
                    best_score = total_score
                    best_match_id = record.get("series_id")

            if not best_match_id or best_score < 0.50:
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_match_id, int(best_score*100)))

            detail_res = requests.get(f"https://api.mangaupdates.com/v1/series/{best_match_id}", headers=headers, timeout=12)
            if detail_res.status_code == 200:
                return self._parse_series_record(detail_res.json())

            return None

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers

        headers = {
            "User-Agent": "MetaKavita-Fetcher/1.5",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            search_url = "https://api.mangaupdates.com/v1/series/search"
            payload = {"search": cleaned, "perpage": 5, "page": 1}
            res = requests.post(search_url, json=payload, headers=headers, timeout=10)

            if res.status_code == 200:
                results = res.json().get("results", []) or []
                query_keywords = extract_meaningful_words(cleaned)
                scored_candidates = []

                for item in results:
                    record = item.get("record", {}) or {}
                    title = record.get("title", "") or ""
                    hit_title = item.get("hit_title", "") or ""
                    
                    titles_to_check = [title] if title else []
                    if hit_title and hit_title not in titles_to_check:
                        titles_to_check.append(hit_title)

                    for assoc in (record.get("associated") or []):
                        if isinstance(assoc, dict) and assoc.get("title"):
                            titles_to_check.append(assoc["title"])
                        elif isinstance(assoc, str):
                            titles_to_check.append(assoc)

                    item_score = 0.0
                    for t in titles_to_check:
                        if not t: continue
                        score = calculate_similarity(cleaned, t)
                        if score > item_score: item_score = score

                    if item_score <= 0.0: continue

                    total_score = item_score

                    if query_keywords:
                        record_text = f"{title} {hit_title} " + " ".join([str(a) for a in titles_to_check])
                        record_keywords = extract_meaningful_words(record_text)
                        missing_keywords = query_keywords - record_keywords
                        if missing_keywords: total_score -= (0.25 * len(missing_keywords))

                    if total_score >= 0.50:
                        img_dict = record.get("image")
                        if isinstance(img_dict, dict):
                            url_dict = img_dict.get("url", {})
                            if isinstance(url_dict, dict):
                                cover_url = url_dict.get("original") or url_dict.get("thumb")
                                if cover_url:
                                    display_title = hit_title or title or "Inconnu"
                                    scored_candidates.append({
                                        "score": total_score,
                                        "provider": "MangaUpdates",
                                        "title": display_title,
                                        "url": cover_url
                                    })

                scored_candidates.sort(key=lambda x: x["score"], reverse=True)

                for cand in scored_candidates:
                    covers.append({
                        "provider": cand["provider"],
                        "title": cand["title"],
                        "url": cand["url"]
                    })

        except Exception as e:
            logging.error(self.t("covers_err").format(e))

        return covers[:4]