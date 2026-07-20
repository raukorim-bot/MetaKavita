# scrapers/comicvine.py

import logging
import time
import requests
import re
import unicodedata
import difflib
from bs4 import BeautifulSoup
from scrapers import clean_title
from config_manager import load_config
from translations import translations

def normalize_str(s):
    """
    Normalise une chaîne de caractères pour les comparaisons strictes.
    """
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn').strip()

def calculate_similarity(s1, s2):
    """
    Calcule un ratio de similarité hybride entre deux chaînes.
    Combine difflib.SequenceMatcher (séquence) et une intersection de tokens (mots-clés).
    """
    n1 = normalize_str(s1)
    n2 = normalize_str(s2)
    if not n1 or not n2:
        return 0.0
        
    # 1. Ratio basé sur la distance de séquence de caractères
    seq_ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    
    # 2. Ratio d'intersection de mots pour gérer le désordre
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if not tokens1 or not tokens2:
        return seq_ratio
        
    intersection = tokens1.intersection(tokens2)
    token_ratio = len(intersection) / max(len(tokens1), len(tokens2))
    
    # Score hybride équilibré
    return 0.6 * seq_ratio + 0.4 * token_ratio

def clean_comicvine_html(soup):
    """
    Prune les sections bruyantes de la description (Publishers, Collected Editions, etc.).
    Supprime les en-têtes correspondants ainsi que leurs listes ou paragraphes associés.
    """
    noisy_headers = [
        "publishers", "collected editions", "collected issues", 
        "other collected editions", "collected hardcovers", 
        "hardcover collections", "trade paperbacks", "issues in this volume",
        "creators", "non-u.s. editions", "translations"
    ]
    
    # 1. Suppression des sections structurelles et de leurs enfants/frères directs
    for header in soup.find_all(["h2", "h3", "h4", "p", "div"]):
        header_text = header.get_text().strip().lower()
        header_clean = header_text.replace(":", "").strip()
        
        # Un titre est considéré comme structurel s'il s'agit d'une balise h2/h3/h4,
        # ou d'un paragraphe/div très court (servant de titre stylisé)
        is_structural = header.name in ["h2", "h3", "h4"] or (header.name in ["p", "div"] and len(header_clean) < 35)
        
        if is_structural and any(noisy in header_clean for noisy in noisy_headers):
            # On supprime en cascade les éléments qui suivent directement (listes, paragraphes d'infos)
            # jusqu'à rencontrer un autre titre majeur ou la fin de l'élément parent
            current = header.next_sibling
            while current:
                next_sibling = current.next_sibling
                if current.name in ["h2", "h3", "h4"]:
                    break
                if current.name in ["ul", "ol", "table", "p", "div", "span"]:
                    current.decompose()
                current = next_sibling
                
            # Décomposition du titre de section lui-même
            header.decompose()
            
    # 2. Suppression des compteurs d'issues résiduels (ex: "41 issues in this volume")
    for element in soup.find_all(string=re.compile(r'\d+\s+issues?\s+in\s+this\s+volume', re.IGNORECASE)):
        parent = element.parent
        if parent:
            parent.decompose()
            
    return soup

def scrape_data(search_query, library_type="Comic"):
    """
    Scraper hybride pour ComicVine avec validation de similarité de chaînes.
    - Étape A : Recherche de Volume stricte (Similarité >= 0.85).
    - Étape B : Repli d'Issue (Album) validé par similarité (Similarité >= 0.75 ou sous-chaîne).
    - Étape C : Récupération des détails riches et du staff de création.
    - Étape D : Récupération d'homonymes majeurs si la description de la réédition est vide.
    - Étape E : Concaténation et validation de données textuelles.
    """
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    
    api_key = config.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        logging.error(t.get("err_comicvine_missing", "❌ Clé API ComicVine manquante."))
        return None
        
    cleaned_query = clean_title(search_query, library_type=library_type)
    
    headers = {
        "User-Agent": "MetaKavita-Metadata-Fetcher/1.0 (contact@metakavita.com)",
        "Accept": "application/json"
    }
    
    # -------------------------------------------------------------------------
    # ÉTAPE A : Tentative de recherche directe du Volume (Série globale)
    # -------------------------------------------------------------------------
    msg_step_a = t.get("log_cv_step_a", "🔍 [ComicVine] Étape A : Recherche de Volume pour '{0}'...").format(cleaned_query)
    logging.info(msg_step_a)
    
    url = "https://comicvine.gamespot.com/api/search/"
    params = {
        "api_key": api_key,
        "format": "json",
        "resources": "volume",
        "query": cleaned_query,
        "limit": 5
    }
    
    time.sleep(1.0) # Respect du rate-limiting
    
    volume_results = []
    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
        if res.status_code in [401, 403]:
            logging.error(t.get("err_comicvine_auth", "❌ Clé API ComicVine invalide."))
            return None
        res.raise_for_status()
        res_json = res.json()
        if res_json.get("status_code") != 100:
            volume_results = res_json.get("results", [])
    except Exception as e:
        logging.error(f"[ComicVine] Erreur recherche : {e}")

    # -------------------------------------------------------------------------
    # ÉTAPE B : Analyse et sélection du Volume OU Repli sur l'Issue (Tome/Album)
    # -------------------------------------------------------------------------
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
        
        # Test de similarité de volume strict pour écarter les faux-positifs
        vol_similarity = calculate_similarity(vol_title, cleaned_query)
        
        if vol_similarity >= 0.85:
            matched_volume = first_vol
            volume_id = matched_volume.get("id")
            volume_name = matched_volume.get("name")
            msg_vol_matched = t.get("log_cv_vol_matched", "🎯 [ComicVine] Match Volume : '{0}' (ID: 4050-{1})").format(volume_name, volume_id)
            logging.info(msg_vol_matched + f" (Similarité: {vol_similarity:.2f})")
        else:
            logging.info(f"⚠️ [ComicVine] Volume '{vol_title}' rejeté (Similarité {vol_similarity:.2f} < 0.85 avec '{cleaned_query}')")

    if not matched_volume:
        msg_step_b = t.get("log_cv_step_b", "🔍 [ComicVine] Étape B : Recherche Issue pour '{0}'...").format(cleaned_query)
        logging.info(msg_step_b)
        
        issue_params = {
            "api_key": api_key,
            "format": "json",
            "resources": "issue",
            "query": cleaned_query,
            "limit": 5
        }
        
        time.sleep(1.0)
        
        try:
            res_issue = requests.get(url, params=issue_params, headers=headers, timeout=15)
            res_issue.raise_for_status()
            issue_json = res_issue.json()
            issue_results = issue_json.get("results", [])
            
            if issue_results:
                matched_issue = issue_results[0]
                issue_title = matched_issue.get("name") or ""
                
                # Validation de similarité de l'album (Issue)
                issue_similarity = calculate_similarity(issue_title, cleaned_query)
                norm_query = normalize_str(cleaned_query)
                norm_issue = normalize_str(issue_title)
                
                # Autoriser si similarité élevée OU s'il y a inclusion logique de mots-clés significatifs
                is_substring = (norm_query in norm_issue or norm_issue in norm_query) if (norm_query and norm_issue) else False
                
                if issue_similarity >= 0.75 or (is_substring and len(norm_query) >= 4 and len(norm_issue) >= 4):
                    issue_id = matched_issue.get("id")
                    issue_name = matched_issue.get("name") or f"Issue #{matched_issue.get('issue_number')}"
                    msg_issue_found = t.get("log_cv_issue_found", "📦 [ComicVine] Album trouvé : '{0}' (ID: {1})").format(issue_name, issue_id)
                    logging.info(msg_issue_found + f" (Similarité: {issue_similarity:.2f})")
                    
                    raw_issue_desc = matched_issue.get("description") or matched_issue.get("deck") or ""
                    if raw_issue_desc:
                        soup_issue = BeautifulSoup(raw_issue_desc, "html.parser")
                        soup_issue = clean_comicvine_html(soup_issue) # Nettoyage anti-bruit
                        issue_summary = soup_issue.get_text().strip()
                        
                    img_dict = matched_issue.get("image")
                    if isinstance(img_dict, dict):
                        issue_cover = img_dict.get("original_url") or img_dict.get("super_url")
                        
                    parent_vol = matched_issue.get("volume")
                    if isinstance(parent_vol, dict):
                        volume_id = parent_vol.get("id")
                        volume_name = parent_vol.get("name")
                        msg_parent = t.get("log_cv_parent_resolved", "⚓ [ComicVine] Série résolue : '{0}' (ID: 4050-{1})").format(volume_name, volume_id)
                        logging.info(msg_parent)
                else:
                    logging.warning(f"⚠️ [ComicVine] Album '{issue_title}' rejeté (Similarité {issue_similarity:.2f} < 0.75 avec '{cleaned_query}')")
        except Exception as e:
            logging.error(f"[ComicVine] Erreur lors de la recherche de l'album : {e}")

    if not volume_id:
        msg_no_resolve = t.get("log_cv_no_resolve", "⚠️ [ComicVine] Impossible d'associer '{0}'.").format(cleaned_query)
        logging.warning(msg_no_resolve)
        return None

    # -------------------------------------------------------------------------
    # ÉTAPE C : Récupération des données détaillées (Volume & Issue)
    # -------------------------------------------------------------------------
    if issue_id:
        msg_fetch_issue = t.get("log_cv_fetch_issue", "⚡ [ComicVine] Étape C : Récupération détaillée de l'album ID 4000-{0}...").format(issue_id)
        logging.info(msg_fetch_issue)
        issue_url = f"https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"
        time.sleep(1.0)
        try:
            issue_res = requests.get(issue_url, params={"api_key": api_key, "format": "json"}, headers=headers, timeout=15)
            issue_res.raise_for_status()
            issue_detail = issue_res.json().get("results", {})
            if issue_detail:
                raw_issue_desc = issue_detail.get("description") or issue_detail.get("deck") or ""
                if raw_issue_desc:
                    soup_issue = BeautifulSoup(raw_issue_desc, "html.parser")
                    soup_issue = clean_comicvine_html(soup_issue) # Nettoyage anti-bruit
                    issue_summary = soup_issue.get_text().strip()
                    
                img_dict = issue_detail.get("image")
                if isinstance(img_dict, dict):
                    issue_cover = img_dict.get("original_url") or img_dict.get("super_url")
                    
                person_credits = issue_detail.get("person_credits", [])
                if isinstance(person_credits, list):
                    for person in person_credits:
                        p_name = person.get("name")
                        p_role = person.get("role", "").lower()
                        if not p_name:
                            continue
                            
                        mapped_role = None
                        if any(r in p_role for r in ["writer", "plotter", "scripter"]):
                            mapped_role = "Story"
                        elif any(r in p_role for r in ["penciller", "penciler", "breakdowns", "artist"]):
                            mapped_role = "Art"
                        elif any(r in p_role for r in ["colorist", "colourist", "colorer", "colourer"]):
                            mapped_role = "Color"
                        elif any(r in p_role for r in ["letterer"]):
                            mapped_role = "Translator"
                        elif any(r in p_role for r in ["cover", "covers", "coverartist", "cover artist"]):
                            mapped_role = "Cover"
                        elif any(r in p_role for r in ["editor"]):
                            mapped_role = "Editor"
                            
                        if mapped_role:
                            staff_credits.append({
                                "role": mapped_role,
                                "node": {"name": {"full": p_name}}
                            })
        except Exception as e:
            logging.error(f"[ComicVine] Erreur lors des détails de l'album : {e}")

    msg_fetch_volume = t.get("log_cv_fetch_volume", "⚡ [ComicVine] Étape C : Récupération détaillée du volume parent ID 4050-{0}...").format(volume_id)
    logging.info(msg_fetch_volume)
    detail_url = f"https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"
    detail_params = {
        "api_key": api_key,
        "format": "json"
    }
    
    time.sleep(1.0)
    
    volume_summary = ""
    volume_cover = None
    publisher_name = None
    year = None
    tags = ["Comics", "ComicVine"]
    site_url = f"https://comicvine.gamespot.com/volume/4050-{volume_id}/"
    
    try:
        detail_res = requests.get(detail_url, params=detail_params, headers=headers, timeout=15)
        detail_res.raise_for_status()
        volume_detail = detail_res.json().get("results", {})
        
        if volume_detail:
            raw_vol_desc = volume_detail.get("description") or volume_detail.get("deck") or ""
            if raw_vol_desc:
                soup_vol = BeautifulSoup(raw_vol_desc, "html.parser")
                soup_vol = clean_comicvine_html(soup_vol) # Nettoyage anti-bruit
                
                for br in soup_vol.find_all("br"):
                    br.replace_with("\n")
                for block in soup_vol.find_all(["p", "div", "h2", "h3", "h4"]):
                    block.append("\n\n")
                volume_summary = soup_vol.get_text()
                volume_summary = re.sub(r'\n{3,}', '\n\n', volume_summary).strip()
                
            img_dict = volume_detail.get("image")
            if isinstance(img_dict, dict):
                volume_cover = img_dict.get("original_url") or img_dict.get("super_url")
                
            start_year_str = volume_detail.get("start_year")
            if start_year_str and str(start_year_str).isdigit():
                year = int(start_year_str)
                
            pub_dict = volume_detail.get("publisher")
            if isinstance(pub_dict, dict):
                publisher_name = pub_dict.get("name")
                
            if publisher_name:
                tags.append(publisher_name)
            
            characters_list = volume_detail.get("characters", [])
            if isinstance(characters_list, list):
                for char in characters_list[:5]:
                    name = char.get("name")
                    if name:
                        tags.append(name)
                        
            concepts_list = volume_detail.get("concepts", [])
            if isinstance(concepts_list, list):
                for con in concepts_list[:5]:
                    name = con.get("name")
                    if name and name not in tags:
                        tags.append(name)
                        
            site_url = volume_detail.get("site_detail_url") or site_url
            
    except Exception as e:
        logging.error(f"[ComicVine] Erreur lors des détails du volume : {e}")

    # -------------------------------------------------------------------------
    # ÉTAPE D : Extraction de secours des homonymes vides
    # -------------------------------------------------------------------------
    if not volume_summary and volume_name:
        msg_empty_desc = t.get("log_cv_empty_desc", "📝 [ComicVine] Étape D : Description vide pour 4050-{0}. Analyse des homonymes...").format(volume_id)
        logging.info(msg_empty_desc)
        
        # 1. Analyse des résultats déjà en mémoire
        for other_vol in volume_results:
            if calculate_similarity(other_vol.get("name", ""), volume_name) >= 0.90:
                raw_desc = other_vol.get("description") or other_vol.get("deck") or ""
                if raw_desc and len(raw_desc) > 30:
                    soup_other = BeautifulSoup(raw_desc, "html.parser")
                    soup_other = clean_comicvine_html(soup_other) # Nettoyage anti-bruit
                    
                    for br in soup_other.find_all("br"):
                        br.replace_with("\n")
                    for block in soup_other.find_all(["p", "div", "h2", "h3", "h4"]):
                        block.append("\n\n")
                    volume_summary = soup_other.get_text()
                    volume_summary = re.sub(r'\n{3,}', '\n\n', volume_summary).strip()
                    msg_hom_mem = t.get("log_cv_homonym_mem", "👉 [ComicVine] Description extraite de l'homonyme en mémoire (ID : 4050-{0})").format(other_vol.get('id'))
                    logging.info(msg_hom_mem)
                    break
                    
        # 2. Recherche d'homonymes via API (et tri par nombre d'albums décroissant)
        if not volume_summary:
            msg_hom_search = t.get("log_cv_homonym_search", "🔍 [ComicVine] Étape D : Recherche d'homonymes via l'API...")
            logging.info(msg_hom_search)
            fallback_params = {
                "api_key": api_key,
                "format": "json",
                "resources": "volume",
                "query": volume_name,
                "limit": 5
            }
            time.sleep(1.0)
            try:
                fallback_res = requests.get("https://comicvine.gamespot.com/api/search/", params=fallback_params, headers=headers, timeout=15)
                if fallback_res.status_code == 200:
                    fallback_results = fallback_res.json().get("results", [])
                    fallback_results.sort(key=lambda x: x.get("count_of_issues") or 0, reverse=True)
                    
                    for other_vol in fallback_results:
                        other_vol_name = other_vol.get("name") or ""
                        if calculate_similarity(other_vol_name, volume_name) >= 0.90:
                            other_id = other_vol.get("id")
                            if other_id != volume_id:
                                msg_hom_fetch = t.get("log_cv_homonym_fetch", "⚡ [ComicVine] Requête de détails sur le meilleur homonyme ID 4050-{0}...").format(other_id)
                                logging.info(msg_hom_fetch)
                                other_detail_url = f"https://comicvine.gamespot.com/api/volume/4050-{other_id}/"
                                time.sleep(1.0)
                                other_detail_res = requests.get(other_detail_url, params={"api_key": api_key, "format": "json"}, headers=headers, timeout=15)
                                if other_detail_res.status_code == 200:
                                    other_detail = other_detail_res.json().get("results", {})
                                    raw_other_desc = other_detail.get("description") or other_detail.get("deck") or ""
                                    
                                    if raw_other_desc:
                                        soup_other = BeautifulSoup(raw_other_desc, "html.parser")
                                        soup_other = clean_comicvine_html(soup_other) # Nettoyage anti-bruit
                                        
                                        for br in soup_other.find_all("br"):
                                            br.replace_with("\n")
                                        for block in soup_other.find_all(["p", "div", "h2", "h3", "h4"]):
                                            block.append("\n\n")
                                        volume_summary = soup_other.get_text()
                                        volume_summary = re.sub(r'\n{3,}', '\n\n', volume_summary).strip()
                                        msg_hom_succ = t.get("log_cv_homonym_success", "👉 [ComicVine] Description trouvée sur l'homonyme majeur (ID : 4050-{0})").format(other_id)
                                        logging.info(msg_hom_succ)
                                        break
            except Exception as e:
                logging.error(f"[ComicVine] Erreur lors de l'étape D : {e}")

    # -------------------------------------------------------------------------
    # ÉTAPE E : Concaténation des Métadonnées et Validation
    # -------------------------------------------------------------------------
    final_cover = issue_cover if issue_cover else volume_cover
    
    final_summary = ""
    if issue_summary:
        final_summary += f"📖 [Album : {issue_name}]\n{issue_summary}\n\n"
    if volume_summary:
        final_summary += f"📚 [Série : {volume_name}]\n{volume_summary}"
        
    if not final_summary.strip():
        msg_fail = t.get("log_cv_fail_summary", "⚠️ [ComicVine] Échec : Aucun résumé textuel rédigé trouvé pour '{0}'.").format(cleaned_query)
        logging.warning(msg_fail)
        return None
        
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