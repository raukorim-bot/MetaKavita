import logging
import re
import time
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests
from .base import BaseScraper
from .utils import clean_title, calculate_similarity, normalize_str

STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or", "no", "de", "la", "le", "les", "du", "un", "une", "des"}

def extract_meaningful_words(title: str) -> set:
    normalized = normalize_str(title)
    words = set(re.findall(r'\b\w+\b', normalized))
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}

def clean_result_title(raw_title: str) -> str:
    if not raw_title: return ""
    return re.sub(r'\s*\(\d{4}\).*$', '', raw_title).strip()

def clean_text_formatting(text: str) -> str:
    if not text: return ""
    cleaned = re.sub(r'^Résumé\s*:\s*', '', text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', cleaned)
    return cleaned

class MangaNewsScraper(BaseScraper):
    id = "MANGANEWS"
    display_name = "Manga-News (Catalogue VF)"
    supported_types = {"Manga"}
    rate_limit = 1.5
    proxy_domains = ["manga-news.com", "www.manga-news.com"]
    has_direct_id_support = True
    requires_proxy = False

    translations = {
        "fr": {
            "direct_url": "[Manga-News] Requête directe par URL/ID : '{0}'",
            "search_title": "[Manga-News] Recherche VF pour : '{0}'",
            "no_match": "⚠️ [Manga-News] Aucun résultat VF pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Manga-News] Match validé sur : {0} (Score: {1}%)",
            "err": "[Manga-News] Erreur : {0}",
            "covers_err": "[Covers] Erreur Manga-News : {0}"
        },
        "en": {
            "direct_url": "[Manga-News] Direct URL/ID request: '{0}'",
            "search_title": "[Manga-News] VF Search for: '{0}'",
            "no_match": "⚠️ [Manga-News] No relevant VF result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Manga-News] Match validated on: {0} (Score: {1}%)",
            "err": "[Manga-News] Error: {0}",
            "covers_err": "[Covers] Manga-News error: {0}"
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None

        if "manga-news.com" in url:
            if "/index.php/serie/" in url or "/index.php/manga/" in url:
                return url
        return None

    def _parse_html_page(self, html: str, url: str) -> Optional[Dict[str, Any]]:
        if not html: return None
        soup = BeautifulSoup(html, 'html.parser')

        title_tag = soup.find('h1', class_='entry-page-title') or soup.find('h1') or soup.find(id='manga-title')
        title = title_tag.get_text(strip=True) if title_tag else ""
        title = re.sub(r'\s*-\s*Manga\s*(série|fiche)?.*$', '', title, flags=re.IGNORECASE).strip()

        alternative_titles = []
        trad_h2 = soup.find('h2', class_='entry-page-title-trad')
        if trad_h2 and trad_h2.get_text(strip=True):
            alternative_titles.append(trad_h2.get_text(strip=True))

        vo_li = soup.find('li', class_='title-vo')
        if vo_li:
            vo_span = vo_li.find('span', class_='entry-data-wrapper') or vo_li
            vo_text = vo_span.get_text(strip=True).replace('Titre VO', '').replace(':', '').strip()
            if vo_text and vo_text not in alternative_titles:
                alternative_titles.append(vo_text)

        summary = ""
        summary_div = soup.select_one('#summary .bigsize') or soup.find(id='fiche_synopsis') or soup.find(class_='synopsis')
        if summary_div:
            for br in summary_div.find_all('br'): br.replace_with('\n')
            summary = summary_div.get_text(separator='\n', strip=True)
            summary = clean_text_formatting(summary)

        if not summary or len(summary) < 15:
            meta_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                summary = clean_text_formatting(meta_desc['content'].strip())

        cover_url = None
        img_tag = soup.find('img', class_='entryPicture')
        if img_tag and img_tag.get('src'):
            cover_url = img_tag['src']
        else:
            og_img = soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                cover_url = og_img['content']

        if cover_url:
            cover_url = cover_url.replace('_medium.webp', '_large.webp').replace('_small.webp', '_large.webp')
            cover_url = cover_url.replace('_medium.jpg', '_large.jpg').replace('_small.jpg', '_large.jpg')
            if not cover_url.startswith('http'):
                cover_url = f"https://www.manga-news.com{cover_url}"

        staff = []
        by_li = soup.find('li', class_='book-by')
        if by_li:
            for a in by_li.find_all('a'):
                name = a.get_text(strip=True)
                if name: staff.append({"role": "Art", "node": {"name": {"full": name}}})

        by2_li = soup.find('li', class_='book-by2')
        if by2_li:
            for a in by2_li.find_all('a'):
                name = a.get_text(strip=True)
                if name: staff.append({"role": "Story", "node": {"name": {"full": name}}})

        publisher = None
        pub_li = soup.find('li', class_='book-edit-vf')
        if pub_li and pub_li.find('a'):
            publisher = pub_li.find('a').get_text(strip=True)

        year = None
        origin_li = soup.find('li', class_='book-origin')
        if origin_li:
            match_year = re.search(r'\b(19|20)\d{2}\b', origin_li.get_text())
            if match_year:
                year = int(match_year.group())

        status = "RELEASING"
        number_block = soup.find(id='numberblock')
        if number_block:
            nb_text = number_block.get_text().lower()
            if "terminé" in nb_text or "complete" in nb_text: status = "FINISHED"
            elif "abandonné" in nb_text or "stoppé" in nb_text: status = "CANCELLED"

        genres = []
        tags = ["Manga-News", "VF"]

        type_li = soup.find('li', class_='book-type')
        if type_li and type_li.find('a'): genres.append(type_li.find('a').get_text(strip=True))

        genre_li = soup.find('li', class_='book-genre')
        if genre_li:
            for a in genre_li.find_all('a'):
                g_text = a.get_text(strip=True)
                if g_text and g_text not in genres: genres.append(g_text)

        themes_div = soup.find(id='product-themes')
        if themes_div:
            for theme_a in themes_div.find_all('a', class_='theme-item'):
                t_text = theme_a.get_text(strip=True)
                if t_text and t_text not in tags: tags.append(t_text)

        age_rating = "safe"
        age_div = soup.find(id='agenumber')
        if age_div:
            age_text = age_div.get_text().lower()
            if "18" in age_text or "averti" in age_text: age_rating = "pornographic"
            elif "16" in age_text or "14" in age_text: age_rating = "suggestive"

        format_type = "manga"
        type_str = " ".join(genres).lower()
        if "webtoon" in type_str or "manhwa" in type_str: format_type = "webtoon"

        unique_staff = []
        seen_staff = set()
        for s in staff:
            key = (s["role"], s["node"]["name"]["full"])
            if key not in seen_staff:
                seen_staff.add(key)
                unique_staff.append(s)

        if not summary and not cover_url and not unique_staff:
            return None

        return {
            'title': title,
            'alternative_titles': alternative_titles,
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres[:5] if genres else ["Manga"],
            'tags': (tags + genres)[:15],
            'year': year,
            'status': status,
            'staff': unique_staff,
            'publisher': publisher,
            'age_rating': age_rating,
            'format': format_type,
            'url': url
        }

    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        session = requests.Session(impersonate="chrome110")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            if is_id:
                logging.info(self.t("direct_url").format(query))
                target_url = query if query.startswith('http') else f"https://www.manga-news.com/index.php/serie/{query}"
                res = session.get(target_url, headers=headers, timeout=12)
                if res.status_code == 200:
                    return self._parse_html_page(res.text, target_url)
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None

            logging.info(self.t("search_title").format(cleaned))
            search_url = "https://www.manga-news.com/index.php/recherche/"
            params = {"q": cleaned}

            res = session.get(search_url, params=params, headers=headers, timeout=12)
            if res.status_code != 200: return None

            soup = BeautifulSoup(res.text, 'html.parser')
            result_links = soup.find_all('a', href=re.compile(r'/index\.php/serie/'))
            if not result_links: return None

            query_keywords = extract_meaningful_words(cleaned)
            best_url = None
            best_score = -1.0

            candidates = {}
            for a in result_links:
                href = a.get('href', '')
                if not href or any(ign in href for ign in ["/critique/", "/vol-", "/preview/"]):
                    continue

                raw_title = a.get_text(strip=True) or a.get('title', '')
                if not raw_title and a.find('img'):
                    raw_title = a.find('img').get('alt', '') or a.find('img').get('title', '')

                if not raw_title: continue

                cand_title = clean_result_title(raw_title)
                full_url = href if href.startswith('http') else f"https://www.manga-news.com{href}"
                candidates[full_url] = cand_title

            for cand_url, cand_title in candidates.items():
                item_score = calculate_similarity(cleaned, cand_title)
                
                if query_keywords:
                    cand_words = extract_meaningful_words(cand_title)
                    missing = query_keywords - cand_words
                    if missing:
                        item_score -= (0.25 * len(missing))

                if item_score > best_score:
                    best_score = item_score
                    best_url = cand_url

            if not best_url or best_score < 0.45:
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_url, int(best_score*100)))

            time.sleep(self.rate_limit)
            detail_res = session.get(best_url, headers=headers, timeout=12)
            if detail_res.status_code == 200:
                return self._parse_html_page(detail_res.text, best_url)

            return None

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers

        session = requests.Session(impersonate="chrome110")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            search_url = "https://www.manga-news.com/index.php/recherche/"
            res = session.get(search_url, params={"q": cleaned}, headers=headers, timeout=10)
            if res.status_code != 200: return covers

            soup = BeautifulSoup(res.text, 'html.parser')
            result_links = soup.find_all('a', href=re.compile(r'/index\.php/serie/'))
            if not result_links: return covers

            query_keywords = extract_meaningful_words(cleaned)
            best_url = None
            best_score = -1.0

            candidates = {}
            for a in result_links:
                href = a.get('href', '')
                if not href or any(ign in href for ign in ["/critique/", "/vol-", "/preview/"]):
                    continue

                raw_title = a.get_text(strip=True) or a.get('title', '')
                if not raw_title and a.find('img'):
                    raw_title = a.find('img').get('alt', '') or a.find('img').get('title', '')

                if not raw_title: continue

                cand_title = clean_result_title(raw_title)
                full_url = href if href.startswith('http') else f"https://www.manga-news.com{href}"
                candidates[full_url] = cand_title

            for cand_url, cand_title in candidates.items():
                item_score = calculate_similarity(cleaned, cand_title)
                if query_keywords:
                    cand_words = extract_meaningful_words(cand_title)
                    missing = query_keywords - cand_words
                    if missing: item_score -= (0.25 * len(missing))

                if item_score > best_score:
                    best_score = item_score
                    best_url = cand_url

            if not best_url or best_score < 0.45: return covers

            detail_res = session.get(best_url, headers=headers, timeout=10)
            if detail_res.status_code == 200:
                detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                
                main_img = detail_soup.find('img', class_='entryPicture')
                main_url = main_img['src'] if main_img and main_img.get('src') else None
                if not main_url:
                    og_img = detail_soup.find('meta', property='og:image')
                    if og_img and og_img.get('content'): main_url = og_img['content']

                if main_url:
                    if not main_url.startswith('http'): main_url = f"https://www.manga-news.com{main_url}"
                    covers.append({
                        "provider": "Manga-News (Série)",
                        "title": candidates[best_url],
                        "url": main_url
                    })

                vols_block = detail_soup.find(id='serieVolumes')
                if vols_block:
                    for vol_img in vols_block.find_all('img'):
                        v_src = vol_img.get('src')
                        if v_src:
                            v_url = v_src if v_src.startswith('http') else f"https://www.manga-news.com{v_src}"
                            v_title = vol_img.get('alt') or vol_img.get('title') or candidates[best_url]
                            v_title = re.sub(r'^(Manga|Manhwa|Manhua)\s*[-_]?\s*', '', v_title, flags=re.IGNORECASE).strip()
                            
                            if v_url not in [c['url'] for c in covers]:
                                covers.append({
                                    "provider": "Manga-News (Tome)",
                                    "title": v_title,
                                    "url": v_url
                                })

        except Exception as e:
            logging.error(self.t("covers_err").format(e))

        return covers[:8]