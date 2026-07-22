import time
import logging
import re
import os
from bs4 import BeautifulSoup
from curl_cffi import requests
from .base import BaseScraper
from .utils import clean_title
from typing import Optional

# -- IMPORT DES TRADUCTIONS UNIQUEMENT POUR UI/LOGS --
try:
    from translations import translations
    app_lang = os.getenv("METAKAVITA_LANG", "fr")
    if app_lang not in translations:
        app_lang = "fr"
    T = translations[app_lang]
except ImportError:
    T = {}

def _t(key: str, default: str) -> str:
    """Helper pour récupérer la valeur traduite ou le fallback par défaut"""
    return T.get(key, default)

def format_author_name(name: str) -> str:
    """
    Transforme 'Díaz Canales, Juan' en 'Juan Díaz Canales' pour un affichage propre.
    Ignore les auteurs indéterminés ou les mentions techniques (ex: Quadrichromie).
    """
    name = name.strip()
    lower_name = name.lower()
    
    # On ignore les pollutions dans les métadonnées
    if not name or "indéterminé" in lower_name or "quadrichromie" in lower_name:
        return ""
        
    if ',' in name:
        parts = name.split(',', 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name

def generate_search_queries(title: str) -> list:
    """
    Génère les 3 variations de titre de façon dynamique.
    """
    queries = [title]
    pattern = r'^(le\s+|la\s+|les\s+|l[\'’]\s*|the\s+|a\s+|an\s+|un\s+|une\s+|des\s+)(.*)$'
    match = re.match(pattern, title, flags=re.IGNORECASE)
    
    if match:
        article = match.group(1).strip()
        rest = match.group(2).strip()
        if rest:
            var2 = f"{rest} ({article})"
            if var2 not in queries:
                queries.append(var2)
            if rest not in queries:
                queries.append(rest)
    return queries

class BedethequeScraper(BaseScraper):
    id = "BEDETHEQUE"
    display_name = "Bédéthèque (Franco-Belge)"
    supported_types = {"Comic"}
    rate_limit = 2.0
    proxy_domains = ["bedetheque.com"]
    has_direct_id_support = True # 👈 NOUVEAU : Active l'URL Magique

    def extract_id_from_url(self, url: str) -> Optional[str]:
        """Pour Bédéthèque, l'ID magique EST l'URL complète"""
        if "bedetheque.com" in url:
            return url
        return None

    def _get_csrf_token(self, session, headers):
        try:
            res = session.get("https://www.bedetheque.com/search/albums", headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            tag = soup.find('input', {'name': 'csrf_token_bel'})
            return tag['value'] if tag else ""
        except Exception:
            return ""

    def _extract_summary(self, soup):
        for css_class in ['synopsis', 'histoire', 'story']:
            div = soup.find(class_=css_class)
            if div:
                for br in div.find_all('br'):
                    br.replace_with('\n')
                text = div.get_text(separator='\n', strip=True)
                
                text = re.sub(r'^Résumé\s*:\s*', '', text, flags=re.IGNORECASE).strip()
                if len(text) > 15:
                    return text
                    
        meta_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            text = meta_desc['content'].strip()
            
            text = re.sub(r'^Tout sur la série.*?:\s*', '', text, flags=re.IGNORECASE).strip()
            if len(text) > 15 and not text.startswith("Rechercher sur les site"):
                return text
        return ""

    def _extract_staff_and_publisher(self, soup, staff, publisher):
        """Extrait le staff et l'éditeur de manière robuste depuis n'importe quelle page Bédéthèque."""
        for label_tag in soup.find_all(['label', 'span']):
            if label_tag.name == 'span' and 'type' not in label_tag.get('class', []):
                continue
            
            label_text = label_tag.get_text(strip=True).lower()
            
            is_writer = "scénario" in label_text or "scénariste" in label_text
            is_penciller = "dessin" in label_text
            is_colorist = "couleur" in label_text
            is_publisher = "editeur" in label_text or "éditeur" in label_text
            
            if not any([is_writer, is_penciller, is_colorist, is_publisher]):
                continue
            
            parent = label_tag.parent
            if not parent:
                continue
                
            a_tags = parent.find_all('a')
            authors = []
            if a_tags:
                for a in a_tags:
                    authors.append(a.get_text(strip=True))
            else:
                text_content = parent.get_text(strip=True).replace(label_tag.get_text(strip=True), '')
                for auth in re.split(r'[·&,;]', text_content):
                    if auth.strip():
                        authors.append(auth.strip())
                        
            for name_raw in authors:
                name = format_author_name(name_raw)
                if not name:
                    continue
                    
                if is_writer:
                    staff.append({"role": "Story", "node": {"name": {"full": name}}})
                elif is_penciller:
                    staff.append({"role": "Art", "node": {"name": {"full": name}}})
                elif is_colorist:
                    staff.append({"role": "Color", "node": {"name": {"full": name}}})
                elif is_publisher and not publisher:
                    publisher = name_raw
                    
        return staff, publisher

    def fetch(self, query: str, library_type: str = "Comic", is_id: bool = False):
        session = requests.Session(impersonate="chrome110")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": "https://www.bedetheque.com/search/albums"
        }
        
        album_url = None
        serie_url = None
        fallback_url = None

        try:
            # =======================================================
            # ÉTAPE 1 : RÉSOLUTION DU LIEN (Recherche ou URL Magique)
            # =======================================================
            if is_id:
                logging.info(f"🎯 [Bédéthèque] Court-circuit activé : Scraping direct de l'URL '{query}'")
                if '/album-' in query:
                    album_url = query
                elif '/serie-' in query:
                    serie_url = query
                else:
                    logging.warning(f"⚠️ [Bédéthèque] L'URL fournie n'est ni un album ni une série reconnue : {query}")
                    return None
            else:
                clean = clean_title(query, library_type=library_type)
                queries_to_try = generate_search_queries(clean)
                csrf_token = self._get_csrf_token(session, headers)
                
                for q in queries_to_try:
                    params = {"RechSerie": q, "csrf_token_bel": csrf_token}
                    msg_search = _t("bedetheque_search", "🔍 [Bédéthèque] Recherche pour '{0}'...")
                    logging.info(msg_search.format(q))
                    
                    res_search = session.get("https://www.bedetheque.com/search/albums", params=params, headers=headers, timeout=15)
                    if res_search.status_code != 200: continue
                    
                    soup_search = BeautifulSoup(res_search.text, 'html.parser')
                    results_ul = soup_search.find('ul', class_='search-list')
                    if not results_ul: continue
                        
                    lis = results_ul.find_all('li')
                    if not lis: continue

                    for li in lis:
                        a_tag = li.find('a', class_='image-tooltip') or li.find('a')
                        if not a_tag or not a_tag.get('href'): continue
                        
                        serie_span = a_tag.find('span', class_='serie')
                        if serie_span:
                            serie_text = serie_span.get_text(strip=True)
                            if serie_text.lower() == q.lower() or serie_text.lower() == clean.lower():
                                album_url = a_tag['href']
                                break # Correspondance exacte trouvée !
                    
                    if album_url: break 
                    
                    if not fallback_url:
                        for li in lis:
                            a_tag = li.find('a', class_='image-tooltip') or li.find('a')
                            if not a_tag or not a_tag.get('href'): continue
                            fallback_url = a_tag['href']
                            break
                
                if not album_url:
                    if fallback_url:
                        album_url = fallback_url
                    else:
                        msg_not_found = _t("bedetheque_not_found", "⚠️ [Bédéthèque] Aucun album trouvé pour '{0}'.")
                        logging.warning(msg_not_found.format(clean))
                        return None

            # Formattage propre des URLs trouvées
            if album_url and not album_url.startswith('http'): 
                album_url = f"https://www.bedetheque.com{album_url}"
            if serie_url and not serie_url.startswith('http'):
                serie_url = f"https://www.bedetheque.com{serie_url}"


            # =======================================================
            # ÉTAPE 2 : SCRAPING DE L'ALBUM (Si disponible)
            # =======================================================
            album_summary = ""
            staff = []
            publisher = None
            
            if album_url:
                time.sleep(1.0)
                res_album = session.get(album_url, headers=headers, timeout=15)
                soup_album = BeautifulSoup(res_album.text, 'html.parser')
                album_summary = self._extract_summary(soup_album)
                staff, publisher = self._extract_staff_and_publisher(soup_album, staff, publisher)

                # Si c'est pas un court-circuit de série direct, on cherche la série parente
                if not serie_url:
                    h1_serie = soup_album.find('h1')
                    if h1_serie and h1_serie.find('a'):
                        serie_url = h1_serie.find('a').get('href')
                    
                    if not serie_url:
                        serie_links = soup_album.find_all('a', href=lambda h: h and '/serie-' in h and '.html' in h)
                        if serie_links:
                            serie_url = serie_links[0]['href']

            # =======================================================
            # ÉTAPE 3 : SCRAPING DE LA SÉRIE (Pour les mots-clés/Statut)
            # =======================================================
            genres = []
            year = None
            status = "FINISHED"
            serie_summary = ""
            cover_url = None
            fetched_title = "" # NOUVEAU : Récupération du titre pour le Smart Match
            
            if serie_url:
                if not serie_url.startswith('http'): 
                    serie_url = f"https://www.bedetheque.com{serie_url}"
                    
                time.sleep(self.rate_limit)
                msg_scraping_serie = _t("bedetheque_scraping_serie", "⚡ [Bédéthèque] Scraping de la Série ({0})")
                logging.info(msg_scraping_serie.format(serie_url))
                
                res_serie = session.get(serie_url, headers=headers, timeout=15)
                soup_serie = BeautifulSoup(res_serie.text, 'html.parser')

                # Récupération du Titre !
                h1_title = soup_serie.find('h1')
                if h1_title:
                    fetched_title = h1_title.get_text(strip=True)

                cover_img = soup_serie.find('img', class_='couv') or soup_serie.select_one('.serie-image img')
                if not cover_img: 
                    cover_img = soup_serie.find('img', src=re.compile(r'Couvertures'))
                if cover_img and cover_img.get('src'): 
                    cover_url = cover_img['src']
                
                serie_summary = self._extract_summary(soup_serie)

                style_tag = soup_serie.find(class_='style') or soup_serie.find(class_='genre')
                if style_tag:
                    raw_style = style_tag.get_text(strip=True)
                    parts = re.split(r'[/,]', raw_style)
                    for p in parts:
                        if p.strip(): genres.append(p.strip().capitalize())
                
                albums_list = soup_serie.find('ul', class_='liste-albums') or soup_serie.find('div', class_='liste-albums')
                if albums_list:
                    match = re.search(r'\b(19|20)\d{2}\b', albums_list.get_text())
                    if match: year = int(match.group())

                if soup_serie.find(string=re.compile(r'En cours', re.IGNORECASE)):
                    status = "RELEASING"
                    
                # Si l'album ne possédait aucun auteur (ou court-circuit direct sur série), on chope le staff
                if not staff:
                    staff, publisher = self._extract_staff_and_publisher(soup_serie, staff, publisher)
            else:
                # Si pas de page série, on tente d'extraire de la page Album
                if soup_album:
                    h1_title = soup_album.find('h1')
                    if h1_title: fetched_title = h1_title.get_text(strip=True)
                    cover_img = soup_album.find('img', class_='couv')
                    if cover_img and cover_img.get('src'):
                        cover_url = cover_img['src']

            if cover_url:
                cover_url = cover_url.replace('/cache/thb_couv/', '/media/Couvertures/')
                if not cover_url.startswith('http'):
                    cover_url = f"https://www.bedetheque.com{cover_url}"

            final_summary = album_summary if album_summary else serie_summary

            # Dé-doublonnage du staff pour garder une liste propre
            unique_staff = []
            seen_staff = set()
            for s in staff:
                key = (s["role"], s["node"]["name"]["full"])
                if key not in seen_staff:
                    seen_staff.add(key)
                    unique_staff.append(s)

            tags = ["Bédéthèque"] + genres

            if not final_summary and not cover_url and not unique_staff:
                return None

            return {
                'title': fetched_title, # Indispensable pour le Smart Match !
                'alternative_titles': [],
                'summary': final_summary,
                'cover_url': cover_url,
                'genres': ["BD"] if not genres else [genres[0]],
                'tags': tags[:15],
                'year': year,
                'status': status,
                'staff': unique_staff,
                'publisher': publisher,
                'age_rating': 'safe',
                'format': 'comic',
                'url': serie_url or album_url,
                'links': [serie_url] if serie_url else [album_url]
            }
        except Exception as e:
            msg_error = _t("bedetheque_error", "❌ [Bédéthèque] Erreur inattendue : {0}")
            logging.error(msg_error.format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Comic"):
        covers = []
        clean = clean_title(query, library_type=library_type)
        queries_to_try = generate_search_queries(clean)
        
        session = requests.Session(impersonate="chrome110")
        headers = {"Accept": "text/html", "Referer": "https://www.bedetheque.com/search/albums"}
        
        csrf_token = self._get_csrf_token(session, headers)
        
        exact_matches = []
        fallback_matches = []
        
        for q in queries_to_try:
            params = {"RechSerie": q, "csrf_token_bel": csrf_token}
            
            try:
                res = session.get("https://www.bedetheque.com/search/albums", params=params, headers=headers, timeout=10)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    results_ul = soup.find('ul', class_='search-list')
                    
                    if results_ul:
                        for li in results_ul.find_all('li'):
                            a_tag = li.find('a', class_='image-tooltip')
                            if not a_tag or not a_tag.get('rel'):
                                continue
                                
                            raw_rel = a_tag['rel']
                            cover_url = raw_rel[0] if isinstance(raw_rel, list) else raw_rel
                            
                            cover_url = cover_url.replace('/cache/thb_couv/', '/media/Couvertures/')
                            if not cover_url.startswith('http'):
                                cover_url = f"https://www.bedetheque.com{cover_url}"
                                
                            serie_span = a_tag.find('span', class_='serie')
                            title_span = a_tag.find('span', class_='titre')
                            num_span = a_tag.find('span', class_='num')
                            
                            txt_unknown = _t("bedetheque_unknown", "Inconnu")
                            serie_text = serie_span.get_text(strip=True) if serie_span else txt_unknown
                            title = serie_text
                            
                            if num_span and num_span.get_text(strip=True):
                                title += f" {num_span.get_text(strip=True)}"
                                
                            if title_span and title_span.get_text(strip=True):
                                title += f" - {title_span.get_text(strip=True)}"
                            
                            cover_data = {
                                "provider": "Bédéthèque",
                                "title": title,
                                "url": cover_url
                            }
                            
                            is_exact = False
                            norm_serie = serie_text.lower().strip()
                            
                            for qt in queries_to_try:
                                if norm_serie == qt.lower().strip():
                                    is_exact = True
                                    break
                            
                            if not is_exact:
                                clean_serie_no_article = re.sub(r'\s*\((le|la|les|l\')\)$', '', norm_serie).strip()
                                clean_query_no_article = re.sub(r'^(le|la|les|l\')\s+', '', clean.lower().strip()).strip()
                                if clean_serie_no_article == clean_query_no_article:
                                    is_exact = True

                            if is_exact:
                                if cover_url not in [c['url'] for c in exact_matches]:
                                    exact_matches.append(cover_data)
                            else:
                                if cover_url not in [c['url'] for c in fallback_matches]:
                                    fallback_matches.append(cover_data)
                                    
                        if len(exact_matches) >= 1:
                            break
                            
            except Exception as e:
                msg_covers_err = _t("bedetheque_covers_err", "❌ [Covers] Erreur Bédéthèque pour '{0}' : {1}")
                logging.error(msg_covers_err.format(q, e))
                
        best_covers = exact_matches if exact_matches else fallback_matches
        return best_covers[:8]