import logging
import time
import requests
import re
import unicodedata
import difflib
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import clean_title
from config_manager import load_config

PRIMARY_PUBLISHERS = ["dc comics", "marvel", "image", "dark horse", "vertigo", "dargaud", "dupuis", "casterman", "le lombard", "glénat", "delcourt", "urban comics", "hachette", "boom! studios", "dynamite", "idw", "titan books", "fantagraphics"]

FOREIGN_KEYWORDS = ["verlag", "brasil", "novaro", "ediciones", "zinco", "ecc", "vid", "interpresse"]

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

class ComicVineScraper(BaseScraper):
    id = "COMICVINE"
    display_name = "ComicVine (Ultime BD/Comics)"
    supported_types = {"Comic"}
    rate_limit = 1.2
    proxy_domains = ["comicvine.gamespot.com", "gamespot.com"]
    has_direct_id_support = True
    requires_proxy = True
    needs_api_key = True
    
    translations = {
        "fr": {
            "err_missing": "❌ Clé API ComicVine manquante. Veuillez la configurer dans les paramètres.",
            "direct_id": "🎯 [ComicVine] Requête directe par ID : '{0}'",
            "search_vol": "🔍 [ComicVine] Recherche de Volume pour '{0}'...",
            "err_search": "[ComicVine] Erreur recherche : {0}"
        },
        "en": {
            "err_missing": "❌ ComicVine API Key is missing. Please configure it in settings.",
            "direct_id": "🎯 [ComicVine] Direct request by ID: '{0}'",
            "search_vol": "🔍 [ComicVine] Volume Search for '{0}'...",
            "err_search": "[ComicVine] Search error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "comicvine.gamespot.com" in url:
            match = re.search(r'(40[05]0-\d+)', url)
            if match:
                return match.group(1)
        return None

    def _evaluate_volume_candidates(self, volume_results: list, query_base: str) -> Optional[dict]:
        if not volume_results: return None
        
        norm_query = normalize_str(query_base)
        candidates = []

        for vol in volume_results:
            vol_title = vol.get("name", "")
            sim = calculate_similarity(vol_title, query_base)
            
            if sim >= 0.65:
                issues_cnt = vol.get("count_of_issues", 0) or 0
                pub_dict = vol.get("publisher") or {}
                pub_name = str(pub_dict.get("name", "") if isinstance(pub_dict, dict) else "").lower()
                
                score = (sim * 100.0) + (issues_cnt * 1.5)
                
                if normalize_str(vol_title) == norm_query:
                    score += 150.0
                    
                if any(op in pub_name for op in PRIMARY_PUBLISHERS):
                    score += 300.0
                    
                if any(fk in pub_name for fk in FOREIGN_KEYWORDS):
                    score -= 400.0

                candidates.append((score, vol))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return None

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
                res_v = requests.get(url_volumes, params=params_vol, headers=headers, timeout=12)
                if res_v.status_code == 200:
                    vol_results = res_v.json().get("results", [])
                    matched_volume = self._evaluate_volume_candidates(vol_results, cleaned_query)
            except Exception as e:
                logging.error(self.t("err_search").format(e))

            # 🎯 PASSE 2 : Si pas de résultat et présence d'un deux-points, recherche sans le sous-titre
            if not matched_volume and ":" in cleaned_query:
                base_q = cleaned_query.split(":")[0].strip()
                params_vol["filter"] = f"name:{base_q}"
                try:
                    res_v = requests.get(url_volumes, params=params_vol, headers=headers, timeout=12)
                    if res_v.status_code == 200:
                        vol_results = res_v.json().get("results", [])
                        matched_volume = self._evaluate_volume_candidates(vol_results, base_q)
                except Exception: pass

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
                    res_s = requests.get(url_search, params=params_search, headers=headers, timeout=12)
                    if res_s.status_code == 200:
                        s_results = res_s.json().get("results", [])
                        matched_volume = self._evaluate_volume_candidates(s_results, cleaned_query)
                except Exception as e:
                    logging.error(self.t("err_search").format(e))

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
                    "field_list": "id,name,issue_number,description,deck,image,volume,person_credits"
                }
                time.sleep(1.0)
                try:
                    res_issue = requests.get(url_search, params=issue_params, headers=headers, timeout=12)
                    if res_issue.status_code == 200:
                        res_issue_json = res_issue.json()
                        if res_issue_json.get("status_code") == 1:
                            issue_results = res_issue_json.get("results", [])
                            if issue_results:
                                matched_issue = issue_results[0]
                                issue_id = matched_issue.get("id")
                                issue_name = matched_issue.get("name") or f"Issue #{matched_issue.get('issue_number')}"
                                parent_vol = matched_issue.get("volume")
                                if isinstance(parent_vol, dict):
                                    volume_id = parent_vol.get("id")
                                    volume_name = parent_vol.get("name")
                except Exception: pass

        if not volume_id and not issue_id: 
            return None

        # Récupération détaillée de l'Issue si présente
        if issue_id:
            time.sleep(1.0)
            try:
                issue_res = requests.get(
                    f"https://comicvine.gamespot.com/api/issue/4000-{issue_id}/", 
                    params={"api_key": api_key, "format": "json", "field_list": "id,name,description,deck,image,person_credits,volume"}, 
                    headers=headers, timeout=15
                )
                if issue_res.status_code == 200:
                    issue_detail = issue_res.json().get("results", {})
                    if issue_detail and isinstance(issue_detail, dict):
                        raw_issue_desc = issue_detail.get("description") or issue_detail.get("deck") or ""
                        if raw_issue_desc:
                            soup_issue = BeautifulSoup(raw_issue_desc, "html.parser")
                            issue_summary = clean_comicvine_html(soup_issue).get_text().strip()
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
            except Exception: pass

        volume_summary = ""
        volume_cover = None
        publisher_name = None
        year = None
        tags = ["Comics", "ComicVine"]
        site_url = f"https://comicvine.gamespot.com/volume/4050-{volume_id}/" if volume_id else ""
        
        if volume_id:
            time.sleep(1.0)
            try:
                detail_res = requests.get(
                    f"https://comicvine.gamespot.com/api/volume/4050-{volume_id}/", 
                    params={"api_key": api_key, "format": "json", "field_list": "id,name,deck,description,image,start_year,publisher,first_issue,site_detail_url"}, 
                    headers=headers, timeout=15
                )
                if detail_res.status_code == 200:
                    volume_detail = detail_res.json().get("results", {})
                    if volume_detail and isinstance(volume_detail, dict):
                        if not volume_name: volume_name = volume_detail.get("name")
                            
                        raw_vol_desc = volume_detail.get("description") or volume_detail.get("deck") or ""
                        if raw_vol_desc:
                            soup_vol = BeautifulSoup(raw_vol_desc, "html.parser")
                            soup_vol = clean_comicvine_html(soup_vol)
                            for br in soup_vol.find_all("br"): br.replace_with("\n")
                            for block in soup_vol.find_all(["p", "div", "h2", "h3", "h4"]): block.append("\n\n")
                            volume_summary = re.sub(r'\n{3,}', '\n\n', soup_vol.get_text()).strip()
                            
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
                            time.sleep(1.0)
                            try:
                                f_res = requests.get(
                                    f"https://comicvine.gamespot.com/api/issue/4000-{first_issue_id}/", 
                                    params={"api_key": api_key, "format": "json", "field_list": "description,deck,person_credits"}, 
                                    headers=headers, timeout=10
                                )
                                if f_res.status_code == 200:
                                    f_detail = f_res.json().get("results", {})
                                    if isinstance(f_detail, dict):
                                        # Résumé enrichi via Tome #1
                                        if len(volume_summary) < 150:
                                            f_desc = f_detail.get("description") or f_detail.get("deck") or ""
                                            if f_desc:
                                                f_soup = BeautifulSoup(f_desc, "html.parser")
                                                issue_1_text = clean_comicvine_html(f_soup).get_text().strip()
                                                if issue_1_text:
                                                    volume_summary = f"{volume_summary}\n\n📖 [Synopsis] : {issue_1_text}".strip()

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
                            except Exception: pass

            except Exception: pass

        final_cover = issue_cover if issue_cover else volume_cover
        final_summary = ""
        if issue_summary: final_summary += f"📖 [Album : {issue_name}]\n{issue_summary}\n\n"
        if volume_summary: final_summary += f"📚 [Série : {volume_name}]\n{volume_summary}"
            
        if not final_summary.strip() and not final_cover: 
            return None
            
        final_title = volume_name if volume_name else issue_name
            
        return {
            'title': final_title,
            'alternative_titles': [],
            'summary': final_summary.strip(),
            'cover_url': final_cover,
            'genres': ["Comic Book"],
            'tags': tags[:15],
            'year': year,
            'status': "FINISHED",
            'staff': staff_credits, 
            'publisher': publisher_name,
            'age_rating': "safe",
            'format': "comic",
            'url': site_url
        }

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
            res = requests.get(url, params=params, headers=headers, timeout=10)
            if res.status_code == 200:
                for v in res.json().get('results', []):
                    img_dict = v.get('image') or {}
                    cover_url = img_dict.get('original_url') or img_dict.get('super_url')
                    if cover_url: covers.append({"provider": "ComicVine (Série)", "title": v.get('name', 'Inconnu'), "url": cover_url})
        except Exception: pass
        return covers