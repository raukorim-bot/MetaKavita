import logging
import re
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests
from .base import BaseScraper
from .utils import (
    album_number_key,
    attach_match_score,
    calculate_similarity,
    clean_title,
    get_match_accept_threshold,
    normalize_str,
    response_is_ok,
    score_candidate,
)
from config_manager import get_max_tags, get_max_genres

STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or", "no", "de", "la", "le", "les", "du", "un", "une", "des"}

_VOL_HREF = re.compile(r"/manga/([^/]+)/vol-(\d+(?:[.,]\d+)?)(?:/|$)", re.I)
_ISBN_RE = re.compile(r"\b(97[89]\d{10})\b")
_MOIS = {
    "janvier": "01", "février": "02", "fevrier": "02", "mars": "03",
    "avril": "04", "mai": "05", "juin": "06", "juillet": "07",
    "août": "08", "aout": "08", "septembre": "09", "octobre": "10",
    "novembre": "11", "décembre": "12", "decembre": "12",
}

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
    is_core = True
    display_name = "Manga-News (Catalogue VF)"
    supported_types = {"Manga"}
    scopes = {"series", "volume"}
    # 6 s : une page HTML par tome, derrière Cloudflare. 2,5 s suffisaient à la
    # fiche série (quatre requêtes) ; l'index en envoie une par album, et c'est
    # exactement le profil qui a valu un ban Bédéthèque. Mieux vaut une série
    # lente qu'un fournisseur muet pour le reste de la journée.
    rate_limit = 6.0
    # 40 × 6 s = quatre minutes. Au-delà, une série-fleuve mangerait la passe.
    VOLUME_INDEX_MAX = 40
    # 1.2.0 : index des tomes VF (titre, résumé, ISBN, date) et cadence portée
    # à 6 s. La montée de version est ce qui autorise l'image à remplacer la
    # copie 1.1.x déjà installée sous data/.
    version = "1.2.0"
    proxy_domains = ["manga-news.com", "www.manga-news.com"]
    has_direct_id_support = True
    requires_proxy = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "display_name": "Manga-News (Catalogue VF)",
            "direct_url": "[Manga-News] Requête directe par URL/ID : '{0}'",
            "search_title": "[Manga-News] Recherche VF pour : '{0}'",
            "no_match": "⚠️ [Manga-News] Aucun résultat VF pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Manga-News] Match validé sur : {0} (Score: {1}%)",
            "err": "[Manga-News] Erreur : {0}",
            "covers_err": "[Covers] Erreur Manga-News : {0}",
            "cover_provider_series": "Manga-News (Série)",
            "cover_provider_volume": "Manga-News (Tome)",
            "volume_index_err": "[Manga-News] Index des tomes : {0}",
        },
        "en": {
            "display_name": "Manga-News (French catalog)",
            "direct_url": "[Manga-News] Direct URL/ID request: '{0}'",
            "search_title": "[Manga-News] VF Search for: '{0}'",
            "no_match": "⚠️ [Manga-News] No relevant VF result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Manga-News] Match validated on: {0} (Score: {1}%)",
            "err": "[Manga-News] Error: {0}",
            "covers_err": "[Covers] Manga-News error: {0}",
            "cover_provider_series": "Manga-News (Series)",
            "cover_provider_volume": "Manga-News (Volume)",
            "volume_index_err": "[Manga-News] Volume index: {0}",
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None

        if "manga-news.com" in url:
            if "/index.php/serie/" in url or "/index.php/manga/" in url:
                return url
        return None

    @staticmethod
    def _raw_html(res) -> Any:
        """OCTETS de la réponse plutôt que `res.text` déjà décodé.

        `curl_cffi` décode en UTF-8 avec `errors="replace"` quand le
        `Content-Type` n'annonce pas de charset, et ne lit jamais le
        `<meta charset>` de la page : les accents des titres et synopsis VF
        deviennent des U+FFFD irrécupérables, écrits puis verrouillés dans
        Kavita. Sur les octets, BeautifulSoup lit ce `<meta charset>`.

        Le repli sur `res.text` couvre les fausses réponses des tests, qui
        n'exposent pas toujours d'octets exploitables.
        """
        raw = getattr(res, "content", None)
        return raw if isinstance(raw, (bytes, bytearray)) else res.text

    @staticmethod
    def _soup(res) -> BeautifulSoup:
        return BeautifulSoup(MangaNewsScraper._raw_html(res), 'html.parser')

    def _parse_html_page(self, html: Any, url: str) -> Optional[Dict[str, Any]]:
        # `html` en octets quand il vient du réseau (cf. `_raw_html`), en texte
        # quand un appelant fournit déjà du HTML décodé.
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

        # BF56: pas de défaut safe — seulement si #agenumber donne un signal.
        age_rating = ""
        age_div = soup.find(id='agenumber')
        if age_div:
            age_text = age_div.get_text().lower()
            if "18" in age_text or "averti" in age_text:
                age_rating = "pornographic"
            elif "16" in age_text or "14" in age_text:
                age_rating = "suggestive"

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
            'genres': genres[:get_max_genres()] if genres else ["Manga"],
            'tags': (tags + genres)[:get_max_tags()],
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
        headers = self._headers()

        try:
            if is_id:
                logging.info(self.t("direct_url").format(query))
                # Une URL de tome collée dans le Champ Magique doit ouvrir la
                # fiche série, pas la page du volume — sinon on parse un album
                # comme s'il était la série.
                target_url = self._serie_url_from_ref(query) or (
                    query if query.startswith("http")
                    else f"https://www.manga-news.com/index.php/serie/{query}"
                )
                res = self._http_get(session, target_url, headers=headers, timeout=12)
                if response_is_ok(self, res, context="fiche par identifiant"):
                    return attach_match_score(self._parse_html_page(self._raw_html(res), target_url), 1.0)
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned: return None

            logging.info(self.t("search_title").format(cleaned))
            search_url = "https://www.manga-news.com/index.php/recherche/"
            params = {"q": cleaned}

            res = self._http_get(session, search_url, params=params, headers=headers, timeout=12)
            if not response_is_ok(self, res, context="recherche"): return None

            soup = self._soup(res)
            result_links = soup.find_all('a', href=re.compile(r'/index\.php/serie/'))
            if not result_links: return None

            query_keywords = extract_meaningful_words(cleaned)

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

            # Pré-filtre bon marché (texte de la page de résultats, sans requête HTTP en plus) :
            # la liste de recherche Manga-News ne donne ni auteur ni staff (uniquement titre +
            # URL), il faut la fiche détaillée pour ça. On classe donc d'abord les candidats par
            # ressemblance de titre.
            prefiltered = []
            for cand_url, cand_title in candidates.items():
                item_score = calculate_similarity(cleaned, cand_title)
                if query_keywords:
                    cand_words = extract_meaningful_words(cand_title)
                    missing = query_keywords - cand_words
                    if missing:
                        item_score -= (0.25 * len(missing))
                if item_score > 0.0:
                    prefiltered.append((item_score, cand_url))

            if not prefiltered:
                logging.warning(self.t("no_match").format(cleaned, 0))
                return None

            prefiltered.sort(key=lambda x: x[0], reverse=True)

            # On ne récupère la fiche complète (staff inclus) que pour les 3 candidats les plus
            # plausibles au pré-filtre, pas pour toute la liste : Manga-News est du scraping HTML
            # protégé Cloudflare (curl_cffi) — multiplier les requêtes de fiche détaillée par le
            # nombre de résultats de recherche augmenterait nettement la latence et le risque de
            # blocage. 3 est un compromis entre la protection anti-homonyme (qui nécessite
            # l'auteur, disponible uniquement sur la fiche détaillée) et la charge imposée au site.
            best_candidate = None
            best_score = -1.0

            for _, cand_url in prefiltered[:3]:
                # Plus de pause explicite ici : `_http_get` garantit le `rate_limit`
                # requête par requête, y compris pour la recherche qui précède.
                detail_res = self._http_get(session, cand_url, headers=headers, timeout=12)
                if not response_is_ok(self, detail_res, context="fiche d'un candidat"):
                    continue

                candidate = self._parse_html_page(self._raw_html(detail_res), cand_url)
                if not candidate or not candidate.get("title"):
                    continue

                score = score_candidate(candidate, cleaned, existing_metadata)
                if score > best_score:
                    best_score = score
                    best_candidate = candidate

            if not best_candidate or best_score < get_match_accept_threshold():
                logging.warning(self.t("no_match").format(cleaned, int(best_score*100)))
                return None

            logging.info(self.t("matched").format(best_candidate.get("title"), int(best_score*100)))
            return attach_match_score(best_candidate, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    @staticmethod
    def _headers() -> Dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    @staticmethod
    def _absolute(url: str) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        return f"https://www.manga-news.com{url}"

    @staticmethod
    def _upgrade_cover(url: str) -> str:
        if not url:
            return ""
        url = MangaNewsScraper._absolute(url)
        return (
            url.replace("_medium.webp", "_large.webp")
            .replace("_small.webp", "_large.webp")
            .replace("_medium.jpg", "_large.jpg")
            .replace("_small.jpg", "_large.jpg")
        )

    @staticmethod
    def _serie_url_from_ref(raw: str) -> Optional[str]:
        """URL de fiche série, ou None si ce n'est pas du Manga-News."""
        raw = (raw or "").strip()
        if not raw:
            return None
        if raw.startswith("http") and "manga-news.com" not in raw:
            return None
        if not raw.startswith("http"):
            if raw.startswith("/"):
                raw = f"https://www.manga-news.com{raw}"
            elif "/index.php/" in raw:
                raw = f"https://www.manga-news.com/{raw.lstrip('/')}"
            else:
                raw = f"https://www.manga-news.com/index.php/serie/{raw}"
        raw = raw.split("?")[0]
        vol = _VOL_HREF.search(raw)
        if vol:
            return f"https://www.manga-news.com/index.php/serie/{vol.group(1)}"
        raw = raw.replace("/serie/editions/", "/serie/")
        if "/index.php/serie/" in raw:
            return raw
        return None

    def _resolve_serie_url(
        self, session, headers, query, library_type, series_id, existing_metadata
    ) -> Optional[str]:
        for candidate in (
            series_id,
            (existing_metadata or {}).get("url"),
        ):
            url = self._serie_url_from_ref(str(candidate or ""))
            if url:
                return url

        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return None
        res = self._http_get(
            session,
            "https://www.manga-news.com/index.php/recherche/",
            params={"q": cleaned},
            headers=headers,
            timeout=15,
        )
        if not response_is_ok(self, res, context="recherche de série (tomes)"):
            return None
        soup = self._soup(res)
        query_keywords = extract_meaningful_words(cleaned)
        best_url, best_score = None, -1.0
        for a in soup.find_all("a", href=re.compile(r"/index\.php/serie/")):
            href = a.get("href") or ""
            if not href or any(ign in href for ign in ("/critique/", "/vol-", "/preview/", "/editions/")):
                continue
            raw_title = a.get_text(strip=True) or a.get("title") or ""
            if not raw_title and a.find("img"):
                raw_title = a.find("img").get("alt") or a.find("img").get("title") or ""
            if not raw_title:
                continue
            cand_title = clean_result_title(raw_title)
            score = calculate_similarity(cleaned, cand_title)
            if query_keywords:
                missing = query_keywords - extract_meaningful_words(cand_title)
                if missing:
                    score -= 0.25 * len(missing)
            if score > best_score:
                best_score = score
                best_url = self._absolute(href)
        if not best_url or best_score < 0.45:
            return None
        return best_url

    @staticmethod
    def _volume_links_from_serie(soup, serie_url: str = "") -> List[Dict[str, str]]:
        """Liens des tomes, lus uniquement dans `#serieVolumes`.

        Le reste de la page est plein de `/vol-` (critiques, VO, suggestions) :
        les suivre multiplierait le coût et écrirait le mauvais manga. Le slug
        de la série, quand on l'a, écarte en plus un lien étranger qui se
        serait glissé dans le bandeau.
        """
        if soup is None:
            return []
        block = soup.find(id="serieVolumes")
        if block is None:
            return []
        slug = ""
        slug_match = re.search(r"/serie/(?:editions/)?([^/?#]+)", serie_url or "")
        if slug_match:
            slug = slug_match.group(1)
        out: List[Dict[str, str]] = []
        seen = set()
        for a in block.find_all("a", href=True):
            href = a["href"]
            match = _VOL_HREF.search(href)
            if not match or "/critique/" in href:
                continue
            if slug and match.group(1).lower() != slug.lower():
                continue
            number = album_number_key(match.group(2))
            if number is None or number in seen:
                continue
            seen.add(number)
            img = a.find("img")
            cover = ""
            if img and img.get("src"):
                cover = MangaNewsScraper._upgrade_cover(img["src"])
            label = (a.get("title") or "").strip()
            if not label and img is not None:
                label = (img.get("alt") or "").strip()
            out.append({
                "number": number,
                "url": MangaNewsScraper._absolute(href),
                "cover_url": cover,
                "label": label,
            })
        return out

    @staticmethod
    def _volume_title(h1: str) -> str:
        """Sous-titre du tome, sans le « Naruto Vol.7 » que Kavita affiche déjà."""
        if not h1:
            return ""
        match = re.search(r"(?i)vol\.?\s*\d+(?:[.,]\d+)?\s*(.*)$", h1)
        subtitle = (match.group(1) if match else "").strip(" -–:")
        return subtitle

    @staticmethod
    def _volume_isbn(text: str) -> str:
        labeled = re.search(r"(?i)(?:EAN|ISBN)\s*[:\s]+(97[89][\d\- ]{10,16})", text or "")
        raw = labeled.group(1) if labeled else ""
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 13 and digits.startswith(("978", "979")):
            return digits
        found = _ISBN_RE.search(text or "")
        return found.group(1) if found else ""

    @staticmethod
    def _volume_release_date(text: str) -> str:
        match = re.search(
            r"(?i)Date de publication\s*:\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+((?:19|20)\d{2})",
            text or "",
        )
        if not match:
            return ""
        day, month_name, year = match.group(1), match.group(2), match.group(3)
        month = _MOIS.get(month_name.lower())
        if not month:
            return year
        return f"{year}-{month}-{int(day):02d}"

    def _parse_volume_page(self, html, url: str, fallback_cover: str = "") -> Dict[str, str]:
        soup = BeautifulSoup(html, "html.parser") if html else None
        if soup is None:
            return {}
        h1 = soup.find("h1", class_="entry-page-title") or soup.find("h1")
        title = self._volume_title(h1.get_text(" ", strip=True) if h1 else "")
        summary = ""
        summary_div = (
            soup.select_one("#summary .bigsize")
            or soup.find(id="fiche_synopsis")
            or soup.find(class_="synopsis")
        )
        if summary_div:
            for br in summary_div.find_all("br"):
                br.replace_with("\n")
            summary = clean_text_formatting(summary_div.get_text(separator="\n", strip=True))
        img = soup.find("img", class_="entryPicture")
        cover = ""
        if img and img.get("src"):
            cover = self._upgrade_cover(img["src"])
        page_text = soup.get_text(" ", strip=True)
        payload = {
            "provider_ref": url,
            "title": title,
            "summary": summary,
            "release_date": self._volume_release_date(page_text),
            "isbn": self._volume_isbn(page_text),
            "cover_url": cover or fallback_cover,
        }
        return {k: v for k, v in payload.items() if v}

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Manga",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """`{numéro: payload}` en lisant la liste `#serieVolumes`, puis chaque fiche.

        Une requête pour la série, une par tome, à `rate_limit`. On ne visite
        pas la page « tous les volumes » : elle porte les mêmes liens, sans
        résumé.
        """
        session = requests.Session(impersonate="chrome110")
        headers = self._headers()
        try:
            serie_url = self._resolve_serie_url(
                session, headers, query, library_type, series_id, existing_metadata
            )
            if not serie_url:
                return None
            res = self._http_get(session, serie_url, headers=headers, timeout=15)
            if not response_is_ok(self, res, context="fiche série (tomes)"):
                return None
            links = self._volume_links_from_serie(self._soup(res), serie_url=serie_url)
            if not links:
                return None

            index: Dict[str, Any] = {}
            for link in links[: self.VOLUME_INDEX_MAX]:
                vol_res = self._http_get(session, link["url"], headers=headers, timeout=15)
                if not response_is_ok(self, vol_res, context=f"tome {link['number']}"):
                    continue
                payload = self._parse_volume_page(
                    self._raw_html(vol_res), link["url"], fallback_cover=link.get("cover_url") or ""
                )
                if payload:
                    index[link["number"]] = payload
            return index or None
        except Exception as e:
            logging.error(self.t("volume_index_err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned: return covers

        session = requests.Session(impersonate="chrome110")
        headers = self._headers()

        try:
            search_url = "https://www.manga-news.com/index.php/recherche/"
            res = self._http_get(session, search_url, params={"q": cleaned}, headers=headers, timeout=10)
            if not response_is_ok(self, res, context="recherche de couvertures"): return covers

            soup = self._soup(res)
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

            detail_res = self._http_get(session, best_url, headers=headers, timeout=10)
            if response_is_ok(self, detail_res, context="fiche de couvertures"):
                detail_soup = self._soup(detail_res)
                
                main_img = detail_soup.find('img', class_='entryPicture')
                main_url = main_img['src'] if main_img and main_img.get('src') else None
                if not main_url:
                    og_img = detail_soup.find('meta', property='og:image')
                    if og_img and og_img.get('content'): main_url = og_img['content']

                if main_url:
                    if not main_url.startswith('http'): main_url = f"https://www.manga-news.com{main_url}"
                    covers.append({
                        "provider": self.t("cover_provider_series"),
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
                                    "provider": self.t("cover_provider_volume"),
                                    "title": v_title,
                                    "url": v_url
                                })

        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        finally:
            try:
                session.close()
            except Exception:
                pass

        return covers[:8]