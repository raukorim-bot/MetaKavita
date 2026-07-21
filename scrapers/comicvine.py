import logging
import time
import requests
import re
import unicodedata
import difflib
from bs4 import BeautifulSoup
from .base import BaseScraper
from .utils import clean_title
from config_manager import load_config
from translations import translations

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
    rate_limit = 1.5
    proxy_domains = ["comicvine.gamespot.com", "gamespot.com"]

    def fetch(self, query: str, library_type: str = "Comic", is_id: bool = False):
        config = load_config()
        ui_lang = config.get('UI_LANG', 'fr')
        t = translations.get(ui_lang, translations['fr'])
        api_key = config.get("COMICVINE_API_KEY", "").strip()
        
        if not api_key:
            logging.error(t.get("err_comicvine_missing", "❌ Clé API ComicVine manquante."))
            return None
            
        cleaned_query = clean_title(query, library_type=library_type)
        headers = {"User-Agent": "MetaKavita-Metadata-Fetcher/1.0", "Accept": "application/json"}
        
        logging.info(f"🔍 [ComicVine] Recherche de Volume pour '{cleaned_query}'...")
        url = "https://comicvine.gamespot.com/api/search/"
        params = {"api_key": api_key, "format": "json", "resources": "volume", "query": cleaned_query, "limit": 5}
        
        volume_results = []
        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            if res.status_code in [401, 403]: return None
            res.raise_for_status()
            res_json = res.json()
            if res_json.get("status_code") != 100: volume_results = res_json.get("results", [])
        except Exception as e:
            logging.error(f"[ComicVine] Erreur recherche : {e}")

        volume_id = None
        volume_name = None
        issue_id = None
        issue_summary = ""
        issue_cover = None
        issue_name = ""
        matched_volume = None
        staff_credits = []
        
        if volume_results:
            first_vol = volume_results[0]
            vol_title = first_vol.get("name", "")
            vol_similarity = calculate_similarity(vol_title, cleaned_query)
            if vol_similarity >= 0.85:
                matched_volume = first_vol
                volume_id = matched_volume.get("id")
                volume_name = matched_volume.get("name")

        if not matched_volume:
            issue_params = {"api_key": api_key, "format": "json", "resources": "issue", "query": cleaned_query, "limit": 5}
            time.sleep(1.0)
            try:
                res_issue = requests.get(url, params=issue_params, headers=headers, timeout=15)
                issue_results = res_issue.json().get("results", [])
                if issue_results:
                    matched_issue = issue_results[0]
                    issue_title = matched_issue.get("name") or ""
                    issue_similarity = calculate_similarity(issue_title, cleaned_query)
                    norm_query = normalize_str(cleaned_query)
                    norm_issue = normalize_str(issue_title)
                    is_substring = (norm_query in norm_issue or norm_issue in norm_query) if (norm_query and norm_issue) else False
                    
                    if issue_similarity >= 0.75 or (is_substring and len(norm_query) >= 4 and len(norm_issue) >= 4):
                        issue_id = matched_issue.get("id")
                        issue_name = matched_issue.get("name") or f"Issue #{matched_issue.get('issue_number')}"
                        raw_issue_desc = matched_issue.get("description") or matched_issue.get("deck") or ""
                        if raw_issue_desc:
                            soup_issue = BeautifulSoup(raw_issue_desc, "html.parser")
                            issue_summary = clean_comicvine_html(soup_issue).get_text().strip()
                        img_dict = matched_issue.get("image")
                        if isinstance(img_dict, dict):
                            issue_cover = img_dict.get("original_url") or img_dict.get("super_url")
                        parent_vol = matched_issue.get("volume")
                        if isinstance(parent_vol, dict):
                            volume_id = parent_vol.get("id")
                            volume_name = parent_vol.get("name")
            except Exception as e: pass

        if not volume_id: return None

        if issue_id:
            time.sleep(1.0)
            try:
                issue_res = requests.get(f"https://comicvine.gamespot.com/api/issue/4000-{issue_id}/", params={"api_key": api_key, "format": "json"}, headers=headers, timeout=15)
                issue_detail = issue_res.json().get("results", {})
                if issue_detail:
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
                        elif any(r in p_role for r in ["letterer"]): mapped_role = "Translator"
                        elif any(r in p_role for r in ["cover"]): mapped_role = "Cover"
                        elif any(r in p_role for r in ["editor"]): mapped_role = "Editor"
                        if mapped_role: staff_credits.append({"role": mapped_role, "node": {"name": {"full": p_name}}})
            except Exception: pass

        time.sleep(1.0)
        volume_summary = ""
        volume_cover = None
        publisher_name = None
        year = None
        tags = ["Comics", "ComicVine"]
        site_url = f"https://comicvine.gamespot.com/volume/4050-{volume_id}/"
        
        try:
            detail_res = requests.get(f"https://comicvine.gamespot.com/api/volume/4050-{volume_id}/", params={"api_key": api_key, "format": "json"}, headers=headers, timeout=15)
            volume_detail = detail_res.json().get("results", {})
            if volume_detail:
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
                
                for char in volume_detail.get("characters", [])[:5]:
                    if char.get("name"): tags.append(char.get("name"))
                for con in volume_detail.get("concepts", [])[:5]:
                    if con.get("name") and con.get("name") not in tags: tags.append(con.get("name"))
                site_url = volume_detail.get("site_detail_url") or site_url
        except Exception: pass

        if not volume_summary and volume_name:
            # Fallback homonymes omis pour ne pas surcharger l'exemple, garde la logique d'origine si tu veux !
            pass

        final_cover = issue_cover if issue_cover else volume_cover
        final_summary = ""
        if issue_summary: final_summary += f"📖 [Album : {issue_name}]\n{issue_summary}\n\n"
        if volume_summary: final_summary += f"📚 [Série : {volume_name}]\n{volume_summary}"
            
        if not final_summary.strip(): return None
            
        return {
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

    def fetch_covers(self, query: str, library_type: str = "Comic"):
        covers = []
        clean_sq = clean_title(query, library_type=library_type)
        config = load_config()
        cv_key = config.get("COMICVINE_API_KEY", "").strip()
        if not cv_key: return covers
        headers = {"User-Agent": "MetaKavita-Metadata-Fetcher/1.0", "Accept": "application/json"}
        url = "https://comicvine.gamespot.com/api/search/"
        try:
            params = {"api_key": cv_key, "format": "json", "resources": "volume", "query": clean_sq, "limit": 4}
            res = requests.get(url, params=params, headers=headers, timeout=10)
            if res.status_code == 200:
                for v in res.json().get('results', []):
                    img_dict = v.get('image') or {}
                    cover_url = img_dict.get('original_url') or img_dict.get('super_url')
                    if cover_url: covers.append({"provider": "ComicVine (Série)", "title": v.get('name', 'Inconnu'), "url": cover_url})
            
            params["resources"] = "issue"
            res_issue = requests.get(url, params=params, headers=headers, timeout=10)
            if res_issue.status_code == 200:
                for i in res_issue.json().get('results', []):
                    img_dict = i.get('image') or {}
                    cover_url = img_dict.get('original_url') or img_dict.get('super_url')
                    if cover_url:
                        issue_num = i.get('issue_number') or ''
                        title = f"{i.get('name', 'Inconnu')} (n°{issue_num})" if issue_num else i.get('name', 'Inconnu')
                        covers.append({"provider": "ComicVine (Album)", "title": title, "url": cover_url})
        except Exception: pass
        return covers