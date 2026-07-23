import logging
import re
from typing import Dict, Any, List, Optional
from curl_cffi import requests
from .base import BaseScraper
from .utils import clean_title, calculate_similarity, normalize_str
from config_manager import load_config

# --- OUTILS DE SCORING AVANCÉ ---
STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or", "no", "de", "la", "le", "les", "du", "un", "une", "des"}

def extract_meaningful_words(title: str) -> set:
    normalized = normalize_str(title)
    words = set(re.findall(r'\b\w+\b', normalized))
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}

class HardcoverScraper(BaseScraper):
    id = "HARDCOVER"
    display_name = "Hardcover (Expérimental / GraphQL)"
    supported_types = {"Book", "Comic"}
    rate_limit = 1.2 
    proxy_domains = ["hardcover.app", "api.hardcover.app", "img.hardcover.app"]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = True 

    translations = {
        "fr": {
            "err_missing_key": "❌ Clé API Hardcover manquante. Configurez-la dans les paramètres.",
            "search_title": "🔍 [Hardcover] Recherche Typesense pour '{0}'...",
            "search_isbn": "🔎 [Hardcover] Recherche prioritaire via ISBN Kavita : '{0}'",
            "matched_isbn": "🎯 [Hardcover] Match exact par ISBN Kavita ({0}) sur : '{1}'",
            "direct_id": "🎯 [Hardcover] Requête par ID/Slug : '{0}'",
            "no_match": "⚠️ [Hardcover] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Hardcover] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [Hardcover] Erreur API : {0}",
            "covers_err": "❌ [Covers] Erreur Hardcover : {0}"
        },
        "en": {
            "err_missing_key": "❌ Hardcover API Key missing. Please configure it in settings.",
            "search_title": "🔍 [Hardcover] Typesense search for '{0}'...",
            "search_isbn": "🔎 [Hardcover] Priority search via Kavita ISBN: '{0}'",
            "matched_isbn": "🎯 [Hardcover] Exact match by Kavita ISBN ({0}) on: '{1}'",
            "direct_id": "🎯 [Hardcover] Request by ID/Slug: '{0}'",
            "no_match": "⚠️ [Hardcover] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Hardcover] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [Hardcover] API Error: {0}",
            "covers_err": "❌ [Covers] Hardcover error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "hardcover.app/books/" in url:
            return url.split('/books/')[-1].split('/')[0].split('?')[0]
        return None

    def _parse_graphql_errors(self, data: Dict[str, Any]) -> str:
        errors = data.get("errors")
        if isinstance(errors, list) and len(errors) > 0:
            first_err = errors[0]
            if isinstance(first_err, dict):
                return first_err.get("message", "Erreur GraphQL inconnue")
            return str(first_err)
        elif isinstance(errors, str):
            return errors
        return "Erreur GraphQL inconnue"

    def fetch(self, query: str, library_type: str = "Book", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        config = load_config()
        api_key = config.get("HARDCOVER_API_KEY", "").strip()

        if not api_key:
            logging.error(self.t("err_missing_key"))
            return None

        auth_token = f"Bearer {api_key}" if not api_key.startswith("Bearer") else api_key

        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://hardcover.app",
            "Referer": "https://hardcover.app/"
        }

        graphql_url = "https://api.hardcover.app/v1/graphql"
        session = requests.Session(impersonate="chrome110")

        existing_isbn = existing_metadata.get('isbn') if existing_metadata else None

        try:
            candidate_docs = []

            # 1. TENTATIVE PRIORITAIRE PAR ISBN VIA TYPESENSE
            if existing_isbn and not is_id:
                logging.info(self.t("search_isbn").format(existing_isbn))
                gql_search_isbn = """
                query searchBooks($isbn: String!) {
                  search(query: $isbn, query_type: "Book", per_page: 3, page: 1) {
                      results
                  }
                }
                """
                res_isbn = session.post(graphql_url, json={"query": gql_search_isbn, "variables": {"isbn": existing_isbn}}, headers=headers, timeout=12)
                if res_isbn.status_code == 200:
                    s_data = res_isbn.json()
                    s_node = s_data.get("data", {}).get("search", {})
                    r_node = s_node.get("results", {}) if isinstance(s_node, dict) else {}
                    hits = r_node.get("hits", []) if isinstance(r_node, dict) else []
                    for h in hits:
                        if hits and isinstance(hits[0], dict) and isinstance(hits[0].get("document"), dict):
                            best_match = hits[0]["document"]
                            logging.info(self.t("matched_isbn").format(existing_isbn, best_match.get('title')))

            # 2. RECHERCHE PAR ID / SLUG BRUT
            if not candidate_docs and is_id:
                logging.info(self.t("direct_id").format(query))
                if str(query).isdigit():
                    gql_query = """
                    query getBookById($id: Int!) {
                      books(where: {id: {_eq: $id}}, limit: 1) {
                        id slug title description release_year pages
                        image { url }
                        contributions { author { name } }
                      }
                    }
                    """
                    variables = {"id": int(query)}
                else:
                    gql_query = """
                    query getBookBySlug($slug: String!) {
                      books(where: {slug: {_eq: $slug}}, limit: 1) {
                        id slug title description release_year pages
                        image { url }
                        contributions { author { name } }
                      }
                    }
                    """
                    variables = {"slug": query}
                    
                res = session.post(graphql_url, json={"query": gql_query, "variables": variables}, headers=headers, timeout=12)
                if res.status_code == 200 and "data" in res.json():
                    books = res.json().get("data", {}).get("books", [])
                    if books and isinstance(books, list):
                        return self._build_candidate(books[0])
                return None

            # 3. RECHERCHE TEXTUELLE CLASSIQUE
            if not candidate_docs and not is_id:
                cleaned = clean_title(query, library_type=library_type)
                if not cleaned: return None
                logging.info(self.t("search_title").format(cleaned))

                gql_search = """
                query searchBooks($title: String!) {
                  search(
                      query: $title, 
                      query_type: "Book", 
                      per_page: 5, 
                      page: 1
                  ) {
                      results
                  }
                }
                """
                
                res_search = session.post(graphql_url, json={"query": gql_search, "variables": {"title": cleaned}}, headers=headers, timeout=12)
                if res_search.status_code == 200:
                    search_data = res_search.json()
                    if "errors" not in search_data:
                        search_node = search_data.get("data", {}).get("search", {})
                        results_node = search_node.get("results", {}) if isinstance(search_node, dict) else {}
                        hits = results_node.get("hits", []) if isinstance(results_node, dict) else []
                        if hits and isinstance(hits, list):
                            for h in hits:
                                if isinstance(h, dict) and isinstance(h.get("document"), dict):
                                    candidate_docs.append(h["document"])

            if not candidate_docs:
                return None

            # --- ÉVALUATION DES CANDIDATS VIA LE SCORE CENTRALISÉ ---
            from .utils import score_candidate

            cleaned_query = clean_title(query, library_type=library_type) if not is_id else query
            best_match = None
            best_score = -1.0

            for doc in candidate_docs:
                candidate = self._build_candidate(doc)
                if not candidate or not candidate.get("title"):
                    continue

                # Évaluation avec la matrice unifiée
                score = score_candidate(candidate, cleaned_query, existing_metadata)

                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < 0.60:
                logging.warning(self.t("no_match").format(cleaned_query, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_match.get('title'), int(best_score*100)))
            return best_match

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def _build_candidate(self, b: dict) -> Optional[Dict[str, Any]]:
        """Méthode interne pour transformer un document Hardcover en dictionnaire candidat standardisé."""
        if not b or not isinstance(b, dict): return None

        title = b.get("title", "")
        summary = b.get("description", "")
        year = b.get("release_year")
        
        # Extraction de l'ISBN
        isbn = None
        if b.get("isbn_13"):
            isbn = str(b.get("isbn_13")).replace('-', '').replace(' ', '').strip()
        elif b.get("isbn_10"):
            isbn = str(b.get("isbn_10")).replace('-', '').replace(' ', '').strip()
        elif b.get("isbns") and isinstance(b.get("isbns"), list) and b.get("isbns"):
            isbn = str(b.get("isbns")[0]).replace('-', '').replace(' ', '').strip()

        cover_url = None
        if "image" in b and isinstance(b["image"], dict):
            cover_url = b["image"].get("url")
        elif "image" in b and isinstance(b["image"], str):
            cover_url = b["image"]
            
        staff = []
        author_names = b.get("author_names", [])
        if author_names and isinstance(author_names, list):
            for a_name in author_names:
                if isinstance(a_name, str):
                    staff.append({"role": "Story", "node": {"name": {"full": a_name.strip()}}})
        elif "contributions" in b:
            for contrib in b.get("contributions", []):
                if isinstance(contrib, dict):
                    author_name = contrib.get("author", {}).get("name")
                    if author_name and isinstance(author_name, str):
                        staff.append({"role": "Story", "node": {"name": {"full": author_name.strip()}}})

        unique_staff = []
        seen = set()
        for s in staff:
            full_name = s["node"]["name"]["full"]
            if full_name not in seen:
                seen.add(full_name)
                unique_staff.append(s)

        slug = b.get("slug") or b.get("id")
        alt_titles = b.get("alternative_titles", [])
        if not isinstance(alt_titles, list): alt_titles = []
        
        genres = b.get("genres", [])
        if not isinstance(genres, list): genres = []

        return {
            'title': title,
            'alternative_titles': alt_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres[:5] if genres else ["Fiction"],
            'tags': ["Hardcover"],
            'year': year,
            'status': 'FINISHED',
            'staff': unique_staff,
            'publisher': b.get("publisher"),
            'isbn': isbn,
            'age_rating': 'safe',
            'format': 'book',
            'url': f"https://hardcover.app/books/{slug}" if slug else "https://hardcover.app/"
        }

    def fetch_covers(self, query: str, library_type: str = "Book") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers

        config = load_config()
        api_key = config.get("HARDCOVER_API_KEY", "").strip()
        if not api_key: return covers

        auth_token = f"Bearer {api_key}" if not api_key.startswith("Bearer") else api_key
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
            "Origin": "https://hardcover.app",
            "Referer": "https://hardcover.app/"
        }
        
        session = requests.Session(impersonate="chrome110")
        
        try:
            gql_search = """
            query searchCovers($title: String!) {
              search(
                  query: $title, 
                  query_type: "Book", 
                  per_page: 5, 
                  page: 1
              ) {
                  results
              }
            }
            """
            res_search = session.post("https://api.hardcover.app/v1/graphql", json={"query": gql_search, "variables": {"title": cleaned}}, headers=headers, timeout=10)
            
            if res_search.status_code == 200:
                search_data = res_search.json()
                search_node = search_data.get("data", {}).get("search", {})
                
                results_node = search_node.get("results", {}) if isinstance(search_node, dict) else {}
                hits = results_node.get("hits", []) if isinstance(results_node, dict) else []
                
                if not hits and isinstance(search_node, list) and len(search_node) > 0:
                    results_node = search_node[0].get("results", {})
                    hits = results_node.get("hits", []) if isinstance(results_node, dict) else []
                
                query_keywords = extract_meaningful_words(cleaned)

                for hit in hits:
                    if isinstance(hit, dict):
                        doc = hit.get("document")
                        if isinstance(doc, dict):
                            title = doc.get("title", "Inconnu")
                            alt_titles = doc.get("alternative_titles", [])
                            titles_to_check = [title]
                            if isinstance(alt_titles, list): titles_to_check.extend(alt_titles)

                            # SCORING DES COUVERTURES
                            item_score = 0.0
                            for t in titles_to_check:
                                if not t or not isinstance(t, str): continue
                                score = calculate_similarity(cleaned, t)
                                if score > item_score: item_score = score

                            if query_keywords:
                                combined_text = " ".join([str(t) for t in titles_to_check if t])
                                item_words = extract_meaningful_words(combined_text)
                                missing = query_keywords - item_words
                                if missing: item_score -= (0.25 * len(missing))

                            if item_score >= 0.45:
                                c_url = None
                                if "image" in doc and isinstance(doc["image"], dict):
                                    c_url = doc["image"].get("url")
                                elif "image" in doc and isinstance(doc["image"], str):
                                    c_url = doc["image"]
                                    
                                if c_url:
                                    covers.append({
                                        "provider": "Hardcover",
                                        "title": title,
                                        "url": c_url
                                    })
        except Exception as e:
            logging.error(self.t("covers_err").format(e))

        return covers[:4]