import logging
import requests
import re
import time
from typing import Dict, Any, List, Optional
from .base import BaseScraper
from .utils import clean_title, calculate_similarity, normalize_str

STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or", "no", "de", "la", "le", "les", "du", "un", "une", "des"}

def extract_meaningful_words(title: str) -> set:
    normalized = normalize_str(title)
    words = set(re.findall(r'\b\w+\b', normalized))
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}

def extract_description(data: Dict[str, Any]) -> str:
    desc = data.get("description")
    if isinstance(desc, dict):
        return str(desc.get("value", "") or "")
    elif isinstance(desc, str):
        return desc
    return ""

def safe_get_request(url: str, params: dict = None, headers: dict = None, timeout: int = 12) -> Optional[requests.Response]:
    try:
        res = requests.get(url, params=params, headers=headers, timeout=timeout)
        if res.status_code == 429:
            logging.warning("⚠️ [OpenLibrary] Limite de requêtes atteinte (HTTP 429). Pause de sécurité de 5 secondes...")
            time.sleep(5.0)
            res = requests.get(url, params=params, headers=headers, timeout=timeout)
        return res
    except Exception as e:
        logging.error(f"[OpenLibrary Request] Erreur : {e}")
        return None

def is_google_disclaimer_cover(doc_summary: dict, work_data: dict) -> bool:
    ia_list = doc_summary.get("ia") or work_data.get("ia") or []
    if isinstance(ia_list, str): ia_list = [ia_list]
    for ia_id in ia_list:
        if "goog" in str(ia_id).lower():
            return True
    return False

def fetch_real_cover_from_google(title: str, headers: dict) -> Optional[str]:
    try:
        gb_res = requests.get("https://www.googleapis.com/books/v1/volumes", params={"q": title, "maxResults": 1}, headers=headers, timeout=5)
        if gb_res.status_code == 200:
            items = gb_res.json().get("items", [])
            if items:
                img_links = items[0].get("volumeInfo", {}).get("imageLinks", {})
                c_url = img_links.get("extraLarge") or img_links.get("large") or img_links.get("medium") or img_links.get("thumbnail")
                if c_url:
                    if c_url.startswith("http://"): c_url = c_url.replace("http://", "https://")
                    return c_url
    except Exception as e:
        logging.error(f"[Google Cover Fallback] Erreur : {e}")
    return None

class OpenLibraryScraper(BaseScraper):
    id = "OPENLIBRARY"
    display_name = "Open Library (Livres/Romans)"
    supported_types = {"Book", "Comic"}
    rate_limit = 2.0
    proxy_domains = ["openlibrary.org", "covers.openlibrary.org", "books.google.com"]
    has_direct_id_support = True
    requires_proxy = False

    translations = {
        "fr": {
            "direct_id": "[OpenLibrary] Requête directe par ID/ISBN : '{0}'",
            "search_start": "[OpenLibrary] Recherche pour : '{0}'",
            "search_isbn": "[OpenLibrary] Recherche prioritaire via ISBN Kavita : '{0}'",
            "matched_isbn": "🎯 [OpenLibrary] Match exact par ISBN Kavita ({0}) !",
            "no_match": "⚠️ [OpenLibrary] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [OpenLibrary] Match validé : '{0}' (Score: {1}%)",
            "err": "[OpenLibrary] Erreur : {0}",
            "covers_err": "[Covers] Erreur OpenLibrary : {0}"
        },
        "en": {
            "direct_id": "[OpenLibrary] Direct ID/ISBN request: '{0}'",
            "search_start": "[OpenLibrary] Search for: '{0}'",
            "search_isbn": "[OpenLibrary] Priority search via Kavita ISBN: '{0}'",
            "matched_isbn": "🎯 [OpenLibrary] Exact match by Kavita ISBN ({0})!",
            "no_match": "⚠️ [OpenLibrary] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [OpenLibrary] Match validated: '{0}' (Score: {1}%)",
            "err": "[OpenLibrary] Error: {0}",
            "covers_err": "[Covers] OpenLibrary error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str): return None
        if "openlibrary.org" in url:
            match_work = re.search(r'/works/(OL\d+W)', url)
            if match_work: return match_work.group(1)
            
            match_book = re.search(r'/books/(OL\d+M)', url)
            if match_book: return match_book.group(1)

            match_isbn = re.search(r'/isbn/(\d+)', url)
            if match_isbn: return match_isbn.group(1)
        return None

    def _parse_work_record(self, work_data: Dict[str, Any], doc_summary: Dict[str, Any], headers: dict) -> Optional[Dict[str, Any]]:
        if not work_data and not doc_summary: return None

        title = work_data.get("title") or doc_summary.get("title") or ""
        subtitle = doc_summary.get("subtitle") or work_data.get("subtitle") or ""
        alt_titles = [subtitle] if subtitle else []

        summary = extract_description(work_data)

        # Extraction de l'ISBN
        isbn = None
        isbns = doc_summary.get("isbn") or work_data.get("isbn") or []
        if isinstance(isbns, list) and isbns:
            isbn = str(isbns[0]).replace('-', '').replace(' ', '').strip()
        elif isinstance(isbns, str):
            isbn = isbns.replace('-', '').replace(' ', '').strip()

        cover_url = None
        if is_google_disclaimer_cover(doc_summary, work_data):
            cover_url = fetch_real_cover_from_google(title, headers)
            
        if not cover_url:
            cover_i = doc_summary.get("cover_i")
            if cover_i and str(cover_i).isdigit():
                cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
            else:
                covers_list = work_data.get("covers") or []
                if covers_list and isinstance(covers_list, list) and isinstance(covers_list[0], int):
                    if covers_list[0] > 0:
                        cover_url = f"https://covers.openlibrary.org/b/id/{covers_list[0]}-L.jpg"

        year = doc_summary.get("first_publish_year")
        if not year:
            created_str = work_data.get("created", {}).get("value", "") if isinstance(work_data.get("created"), dict) else ""
            match_y = re.search(r'\b(19|20)\d{2}\b', created_str)
            if match_y: year = int(match_y.group())

        staff = []
        authors = doc_summary.get("author_name") or []
        if isinstance(authors, str): authors = [authors]
        for author in authors:
            if author and isinstance(author, str) and author.strip():
                staff.append({"role": "Story", "node": {"name": {"full": author.strip()}}})

        publisher = None
        publishers = doc_summary.get("publisher") or []
        if isinstance(publishers, list) and publishers:
            publisher = str(publishers[0])
        elif isinstance(publishers, str):
            publisher = publishers

        subjects = doc_summary.get("subject") or work_data.get("subjects") or []
        if isinstance(subjects, str): subjects = [subjects]
        
        genres = []
        tags = ["OpenLibrary", "Book"]
        for s in subjects:
            if isinstance(s, str) and len(s) > 2:
                s_lower = s.lower()
                if any(ign in s_lower for ign in ["nyt:", "=", "reviewed", "bestseller"]):
                    continue

                clean_s = s.strip().capitalize()
                if len(genres) < 5 and clean_s not in genres:
                    genres.append(clean_s)
                if clean_s not in tags:
                    tags.append(clean_s)

        work_key = work_data.get("key") or doc_summary.get("key") or ""
        site_url = f"https://openlibrary.org{work_key}" if work_key.startswith("/") else f"https://openlibrary.org/works/{work_key}"

        return {
            'title': title,
            'alternative_titles': alt_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres[:5] if genres else ["Fiction"],
            'tags': tags[:15],
            'year': year,
            'status': 'FINISHED',
            'staff': staff,
            'publisher': publisher,
            'isbn': isbn,
            'age_rating': 'safe',
            'format': 'book',
            'url': site_url
        }

    def fetch(self, query: str, library_type: str = "Book", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        headers = {"User-Agent": "MetaKavita-Fetcher/1.5 (contact@metakavita.local)", "Accept": "application/json"}

        existing_isbn = existing_metadata.get('isbn') if existing_metadata else None

        try:
            # 1. TENTATIVE PRIORITAIRE PAR ISBN KAVITA
            if existing_isbn and not is_id:
                logging.info(self.t("search_isbn").format(existing_isbn))
                url = f"https://openlibrary.org/isbn/{existing_isbn}.json"
                res = safe_get_request(url, headers=headers, timeout=12)
                if res and res.status_code == 200:
                    logging.info(self.t("matched_isbn").format(existing_isbn))
                    return self._parse_work_record(res.json(), {}, headers)
                    
            # 2. RECHERCHE PAR ID / WORK / BOOK BRUT
            if is_id:
                endpoint = f"/works/{query}" if not query.startswith("OL") or "W" in query else f"/books/{query}"
                if query.startswith("978") or query.isdigit():
                    endpoint = f"/isbn/{query}"
                
                url = f"https://openlibrary.org{endpoint}.json"
                res = safe_get_request(url, headers=headers, timeout=12)
                if res and res.status_code == 200:
                    return self._parse_work_record(res.json(), {}, headers)
                return None

            # 3. RECHERCHE TEXTUELLE CLASSIQUE ET ÉVALUATION
            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None

            search_url = "https://openlibrary.org/search.json"
            params = {"q": cleaned, "limit": 5}

            res = safe_get_request(search_url, params=params, headers=headers, timeout=12)
            if not res or res.status_code != 200: return None

            docs = res.json().get("docs", []) or []
            if not docs: return None

            from .utils import score_candidate

            best_match = None
            best_score = -1.0

            for doc in docs:
                work_key = doc.get("key")
                w_data = {}
                if work_key:
                    w_res = safe_get_request(f"https://openlibrary.org{work_key}.json", headers=headers, timeout=5)
                    if w_res and w_res.status_code == 200:
                        w_data = w_res.json()

                candidate = self._parse_work_record(w_data, doc, headers)
                if not candidate or not candidate.get("title"):
                    continue

                # Évaluation unifiée
                score = score_candidate(candidate, cleaned, existing_metadata)

                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < 0.60:
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_match.get('title'), int(best_score*100)))
            return best_match

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Book") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers

        headers = {"User-Agent": "MetaKavita-Fetcher/1.5 (contact@metakavita.local)", "Accept": "application/json"}

        try:
            res = safe_get_request("https://openlibrary.org/search.json", params={"q": cleaned, "limit": 5}, headers=headers, timeout=10)
            if res and res.status_code == 200:
                docs = res.json().get("docs", []) or []
                query_keywords = extract_meaningful_words(cleaned)

                for doc in docs:
                    title = doc.get("title", "Inconnu")
                    work_key = doc.get("key")
                    score = calculate_similarity(cleaned, title)
                    
                    if query_keywords:
                        item_words = extract_meaningful_words(title)
                        missing = query_keywords - item_words
                        if missing: score -= (0.25 * len(missing))

                    if score >= 0.40:
                        if is_google_disclaimer_cover(doc, {}):
                            real_c_url = fetch_real_cover_from_google(title, headers)
                            if real_c_url and real_c_url not in [c['url'] for c in covers]:
                                covers.append({
                                    "provider": "OpenLibrary",
                                    "title": title,
                                    "url": real_c_url
                                })
                            elif work_key:
                                w_res = safe_get_request(f"https://openlibrary.org{work_key}.json", headers=headers, timeout=5)
                                if w_res and w_res.status_code == 200:
                                    w_covers = w_res.json().get("covers") or []
                                    for cid in w_covers[1:3]:
                                        if cid and isinstance(cid, int) and cid > 0:
                                            c_url = f"https://covers.openlibrary.org/b/id/{cid}-L.jpg"
                                            if c_url not in [c['url'] for c in covers]:
                                                covers.append({
                                                    "provider": "OpenLibrary",
                                                    "title": title,
                                                    "url": c_url
                                                })
                        else:
                            candidate_cover_ids = []
                            if doc.get("cover_i"): candidate_cover_ids.append(doc["cover_i"])

                            if work_key:
                                w_res = safe_get_request(f"https://openlibrary.org{work_key}.json", headers=headers, timeout=5)
                                if w_res and w_res.status_code == 200:
                                    w_covers = w_res.json().get("covers") or []
                                    for cid in w_covers:
                                        if cid and isinstance(cid, int) and cid > 0 and cid not in candidate_cover_ids:
                                            candidate_cover_ids.append(cid)

                            for idx, cid in enumerate(candidate_cover_ids[:3]):
                                cover_url = f"https://covers.openlibrary.org/b/id/{cid}-L.jpg"
                                if cover_url not in [c['url'] for c in covers]:
                                    covers.append({
                                        "provider": "OpenLibrary",
                                        "title": title,
                                        "url": cover_url
                                    })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))

        return covers[:6]