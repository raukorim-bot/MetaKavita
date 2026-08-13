import logging
import re
from bs4 import BeautifulSoup
from curl_cffi import requests
from typing import Optional, Dict, Any, List
from .base import BaseScraper
from .utils import (
    album_number_key,
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)
from config_manager import get_max_tags, get_max_genres

def format_author_name(name: str) -> str:
    name = name.strip()
    lower_name = name.lower()
    if not name or "indéterminé" in lower_name or "quadrichromie" in lower_name:
        return ""
    if ',' in name:
        parts = name.split(',', 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name

def generate_search_queries(title: str) -> list:
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
    is_core = True
    display_name = "Bédéthèque (Franco-Belge)"
    supported_types = {"Comic"}
    scopes = {"series", "volume"}
    # 1.2.0 : cadence appliquée à chaque requête (les pauses en dur de 1 s
    # dépassaient de deux fois le rate_limit déclaré), jeton CSRF absent
    # journalisé, année de série plus déduite d'un nombre à quatre chiffres,
    # décodage HTML confié à BeautifulSoup. La montée de version est ce qui
    # autorise l'image à remplacer la copie 1.1.x déjà installée sous data/.
    version = "1.2.0"
    uses_unified_scoring = True
    rate_limit = 2.0
    proxy_domains = ["bedetheque.com"]
    has_direct_id_support = True

    translations = {
        "fr": {
            "display_name": "Bédéthèque (Franco-Belge)",
            "search": "🔍 [Bédéthèque] Recherche pour '{0}'...",
            "not_found": "⚠️ [Bédéthèque] Aucun album trouvé pour '{0}'.",
            "scraping_serie": "⚡ [Bédéthèque] Scraping de la Série ({0})",
            "error": "❌ [Bédéthèque] Erreur inattendue : {0}",
            "covers_err": "❌ [Covers] Erreur Bédéthèque pour '{0}' : {1}",
            "unknown": "Inconnu",
            "direct_url": "🎯 [Bédéthèque] Court-circuit activé : Scraping direct de l'URL '{0}'",
            "invalid_url": "⚠️ [Bédéthèque] L'URL fournie n'est ni un album ni une série reconnue : {0}",
            "http_err": "⚠️ [Bédéthèque] HTTP {0} sur {1} — page ignorée.",
            "csrf_err": "⚠️ [Bédéthèque] Jeton CSRF introuvable : la recherche va rendre zéro résultat ({0})."
        },
        "en": {
            "display_name": "Bedetheque (Franco-Belgian)",
            "search": "🔍 [Bédéthèque] Searching for '{0}'...",
            "not_found": "⚠️ [Bédéthèque] No album found for '{0}'.",
            "scraping_serie": "⚡ [Bédéthèque] Scraping Series ({0})",
            "error": "❌ [Bédéthèque] Unexpected error: {0}",
            "covers_err": "❌ [Covers] Bédéthèque error for '{0}': {1}",
            "unknown": "Unknown",
            "direct_url": "🎯 [Bédéthèque] Direct URL override active for '{0}'",
            "invalid_url": "⚠️ [Bédéthèque] Provided URL is not a recognized album or series: {0}",
            "http_err": "⚠️ [Bédéthèque] HTTP {0} on {1} — page skipped.",
            "csrf_err": "⚠️ [Bédéthèque] CSRF token not found: the search will return zero result ({0})."
        }
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if "bedetheque.com" in url:
            return url
        return None

    def _get_csrf_token(self, session, headers):
        """Jeton anti-CSRF du formulaire de recherche, ou chaîne vide — en le disant.

        Sans jeton, Bédéthèque rend une page de résultats vide : la recherche
        aboutissait donc à « Aucun album trouvé » alors que la série existe, et
        la cause — formulaire modifié, page interceptée par un anti-bot — n'était
        journalisée nulle part puisque l'exception était avalée.
        """
        try:
            res = self._http_get(
                session, "https://www.bedetheque.com/search/albums", headers=headers, timeout=10
            )
            if not response_is_ok(self, res, context="jeton CSRF"):
                return ""
            soup = self._soup(res)
            tag = soup.find('input', {'name': 'csrf_token_bel'})
            if tag and tag.get('value'):
                return tag['value']
            logging.warning(self.t("csrf_err").format("champ absent de la page"))
            return ""
        except Exception as e:
            logging.warning(self.t("csrf_err").format(e))
            return ""

    @staticmethod
    def _soup(res) -> BeautifulSoup:
        """Soupe construite sur les OCTETS de la réponse, pas sur `res.text`.

        `curl_cffi` suppose UTF-8 quand le serveur n'annonce pas de `charset` et
        décode avec `errors="replace"` : sur une page Bédéthèque en ISO-8859-1,
        les accents devenaient des U+FFFD irrécupérables, écrits puis verrouillés
        dans Kavita. En recevant les octets, BeautifulSoup lit le
        `<meta charset>` de la page et retombe juste dans les deux cas.

        Le repli sur `res.text` vise les doublures de test : un `MagicMock`
        fabrique un `.content` factice qu'il ne faut pas confondre avec des
        octets réels, d'où le contrôle de type plutôt qu'un test de nullité.
        """
        raw = getattr(res, "content", None)
        if not isinstance(raw, (bytes, bytearray)):
            raw = res.text
        return BeautifulSoup(raw, 'html.parser')

    def _get_page(self, session, url, headers):
        """Soupe de la page, ou None si Bédéthèque n'a pas répondu 200.

        Sans ce contrôle, une page 404 / 503 / de maintenance était analysée comme
        une fiche : son `<h1>` devenait le titre récupéré, son message d'attente le
        résumé, et le statut de publication gardait son défaut `FINISHED`. La seule
        chose qui manquait dans les journaux était la vraie cause.

        Le contrôle passe par `response_is_ok` et non par un test de code écrit
        ici : c'est ce qui distingue un 403 de bannissement — journalisé en ERROR
        et remonté à l'appelant comme cause `auth` — d'un 404 de page disparue.
        Les fiches album et série sont les requêtes les plus nombreuses du
        scraper, donc les premières à se faire bloquer quand Bédéthèque coupe :
        c'est précisément là qu'un simple WARNING générique laissait croire à
        l'utilisateur que le site n'avait rien sur sa série.
        """
        res = self._http_get(session, url, headers=headers, timeout=15)
        if not response_is_ok(self, res, context=url):
            return None
        return self._soup(res)

    # ===== Index des albums (issue #27) =====

    #: Une page par album à 2 s de cadence : au-delà, l'index coûterait plus de
    #: deux minutes pour une série que personne ne possède en entier.
    VOLUME_INDEX_MAX = 50

    @staticmethod
    def _album_number(text: str) -> Optional[str]:
        """Numéro de tome d'un libellé Bédéthèque (« 3. Le Sceau du dragon »).

        La décimale fait partie du numéro. Bédéthèque range les hors-série
        intercalaires en 1.5, 3.5, et l'ancienne version les tronquait à `1` :
        un tome 1.5 croisé avant le tome 1 prenait sa place dans l'index — la
        boucle garde la première entrée d'une clé — et le vrai tome 1 repartait
        avec le résumé et la couverture du hors-série.
        """
        raw = str(text or "").strip()
        match = re.match(
            r"^\s*(?:T(?:ome)?\.?\s*)?(\d{1,4}(?:[.,]\d{1,2})?)\s*[.\-–:]", raw, re.I
        )
        if not match:
            match = re.search(r"\bT(?:ome)?\.?\s*(\d{1,4}(?:[.,]\d{1,2})?)\b", raw, re.I)
        return album_number_key(match.group(1)) if match else None

    #: Libellés de la fiche album qui portent une vraie date de parution.
    _DATE_LABELS = ("depot legal", "dépot légal", "dépôt légal", "date de parution", "parution")

    @staticmethod
    def _album_release_date(soup_album) -> str:
        """Date de parution d'un album, ou rien.

        L'ancienne version prenait la première suite de quatre chiffres
        rencontrée dans les quatre mille premiers caractères de la page. Sur une
        fiche Bédéthèque, c'est aussi bien l'année de naissance du dessinateur,
        une année du menu de recherche ou la mention de copyright du pied de
        page — et cette date-là partait chez Kavita, verrouillée. Mieux vaut
        aucune date qu'une date fausse qu'on ne pourra plus corriger
        automatiquement : on ne lit donc que les emplacements qui la déclarent.
        """
        if soup_album is None:
            return ""
        meta = soup_album.find('meta', attrs={'itemprop': 'datePublished'})
        content = (meta.get('content') if meta else "") or ""
        iso = re.match(r'^((?:19|20)\d{2})(?:-(\d{2})(?:-(\d{2}))?)?', content.strip())
        if iso:
            return "-".join(part for part in iso.groups() if part)

        for label in soup_album.find_all('label'):
            text = (label.get_text(" ", strip=True) or "").lower()
            if not any(text.startswith(prefix) for prefix in BedethequeScraper._DATE_LABELS):
                continue
            holder = label.find_parent(['li', 'div', 'p']) or label.parent
            if holder is None:
                continue
            value = holder.get_text(" ", strip=True)[len(label.get_text(" ", strip=True)):]
            day = re.search(r'\b(\d{2})/(\d{2})/((?:19|20)\d{2})\b', value)
            if day:
                return f"{day.group(3)}-{day.group(2)}-{day.group(1)}"
            month = re.search(r'\b(\d{2})/((?:19|20)\d{2})\b', value)
            if month:
                return f"{month.group(2)}-{month.group(1)}"
            year = re.search(r'\b((?:19|20)\d{2})\b', value)
            if year:
                return year.group(1)
        return ""

    @staticmethod
    def _serie_year(soup_serie, soup_album) -> Optional[int]:
        """Année de la série, uniquement là où une date est déclarée.

        L'ancienne version prenait le premier nombre à quatre chiffres de la
        liste d'albums : un album intitulé « 1984 », un numéro de collection ou
        un prix y suffisaient, et cette année-là partait chez Kavita, verrouillée.
        C'est exactement l'heuristique que le docstring de `_album_release_date`
        condamne pour les dates d'album, et elle n'est pas plus défendable pour
        une série. On réutilise donc le même lecteur de dates déclarées : la
        fiche série d'abord, la fiche album ensuite — c'est l'album que la
        recherche a retenu, presque toujours le tome 1, donc l'entrée en matière
        de la série. Aucune date déclarée : aucune année, plutôt qu'une fausse.
        """
        for soup in (soup_serie, soup_album):
            if soup is None:
                continue
            declared = BedethequeScraper._album_release_date(soup)
            match = re.match(r'^((?:19|20)\d{2})', declared or "")
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _album_title(label: str) -> str:
        """Titre d'album sans son numéro de rang.

        La liste des albums écrit « 3. La Galère noire » : Kavita affiche déjà
        le numéro du tome à côté du titre, le garder le doublerait. La décimale
        fait partie du rang à retirer, sans quoi « 1.5. Hors-série » laisserait
        un « 5. » orphelin en tête de titre.
        """
        return re.sub(
            r'^\s*\d{1,4}(?:[.,]\d{1,2})?\s*[.\-–:]\s*', '', str(label or "")
        ).strip()

    def _album_links_from_serie(self, soup_serie) -> List[Dict[str, Any]]:
        """Liens et numéros des albums d'une fiche série.

        La liste `liste-albums` n'était lue qu'au lasso, pour en extraire une
        année avec une expression régulière sur tout le texte. Elle porte en
        fait un lien et un numéro par album : de quoi écrire tome par tome.
        """
        if soup_serie is None:
            return []
        container = (
            soup_serie.find('ul', class_='liste-albums')
            or soup_serie.find('div', class_='liste-albums')
        )
        if container is None:
            return []

        out: List[Dict[str, Any]] = []
        seen = set()
        for a in container.find_all('a', href=True):
            href = a['href']
            # Bédéthèque écrit tantôt « /album-1234-… », tantôt « …-album-1234 » :
            # exiger la barre oblique laisserait passer la moitié des séries.
            if 'album-' not in href or not href.endswith('.html'):
                continue
            if not href.startswith('http'):
                href = f"https://www.bedetheque.com{href}"
            if href in seen:
                continue
            label = a.get_text(" ", strip=True) or (a.get('title') or "")
            number = self._album_number(label)
            if number is None:
                # Le libellé du lien est parfois l'image seule : le numéro est
                # alors sur l'élément de liste qui l'entoure.
                parent = a.find_parent('li')
                if parent is not None:
                    number = self._album_number(parent.get_text(" ", strip=True))
            if number is None:
                continue
            seen.add(href)
            out.append({"url": href, "number": number, "label": label})
        return out

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Comic",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """`{numéro de tome: payload}` en lisant la liste d'albums de la série."""
        session = requests.Session(impersonate="chrome110")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": "https://www.bedetheque.com/search/albums",
        }
        try:
            serie_url = self._resolve_serie_url(session, headers, query, library_type, series_id)
            if not serie_url:
                return None
            soup_serie = self._get_page(session, serie_url, headers)
            links = self._album_links_from_serie(soup_serie)
            if not links:
                return None

            index: Dict[str, Any] = {}
            for link in links[: self.VOLUME_INDEX_MAX]:
                if link["number"] in index:
                    continue
                # La cadence est celle de `_http_get` : une page d'album par
                # `rate_limit`, sans pause en dur qui la contredirait.
                soup_album = self._get_page(session, link["url"], headers)
                if soup_album is None:
                    continue
                cover = soup_album.find('img', class_='couv')
                cover_url = cover.get('src') if cover else ""
                if cover_url:
                    cover_url = cover_url.replace('/cache/thb_couv/', '/media/Couvertures/')
                    if not cover_url.startswith('http'):
                        cover_url = f"https://www.bedetheque.com{cover_url}"
                title_tag = soup_album.find('h1')
                payload = {
                    "provider_ref": link["url"],
                    "title": self._album_title(
                        link["label"] or (title_tag.get_text(strip=True) if title_tag else "")
                    ),
                    "summary": self._extract_summary(soup_album) or "",
                    "release_date": self._album_release_date(soup_album),
                    "cover_url": cover_url or "",
                }
                payload = {k: v for k, v in payload.items() if v}
                if payload:
                    index[link["number"]] = payload
            return index or None
        except Exception as e:
            logging.error("[Bédéthèque] index des albums: %s", e)
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _resolve_serie_url(self, session, headers, query, library_type, series_id):
        """URL de fiche série, par URL forcée si possible, par recherche sinon."""
        raw = str(series_id or "").strip()
        if '/serie-' in raw:
            return raw if raw.startswith('http') else f"https://www.bedetheque.com{raw}"
        if '/album-' in raw:
            soup = self._get_page(
                session,
                raw if raw.startswith('http') else f"https://www.bedetheque.com{raw}",
                headers,
            )
            if soup is not None:
                links = soup.find_all('a', href=lambda h: h and '/serie-' in h and '.html' in h)
                if links:
                    href = links[0]['href']
                    return href if href.startswith('http') else f"https://www.bedetheque.com{href}"

        clean = clean_title(query, library_type=library_type)
        if not clean:
            return None
        csrf_token = self._get_csrf_token(session, headers)
        for q in generate_search_queries(clean):
            try:
                res = self._http_get(
                    session,
                    "https://www.bedetheque.com/search/albums",
                    params={"RechSerie": q, "csrf_token_bel": csrf_token},
                    headers=headers,
                    timeout=15,
                )
            except Exception:
                continue
            if not response_is_ok(self, res, context="recherche de série"):
                continue
            soup = self._soup(res)
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/serie-' in href and '.html' in href:
                    return href if href.startswith('http') else f"https://www.bedetheque.com{href}"
            first = soup.select_one('ul.search-list a[href]')
            if first:
                href = first['href']
                album = href if href.startswith('http') else f"https://www.bedetheque.com{href}"
                soup_album = self._get_page(session, album, headers)
                if soup_album is not None:
                    links = soup_album.find_all(
                        'a', href=lambda h: h and '/serie-' in h and '.html' in h
                    )
                    if links:
                        href = links[0]['href']
                        return href if href.startswith('http') else f"https://www.bedetheque.com{href}"
        return None

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
            if not parent: continue
                
            a_tags = parent.find_all('a')
            authors = []
            if a_tags:
                for a in a_tags: authors.append(a.get_text(strip=True))
            else:
                text_content = parent.get_text(strip=True).replace(label_tag.get_text(strip=True), '')
                for auth in re.split(r'[·&,;]', text_content):
                    if auth.strip(): authors.append(auth.strip())
                        
            for name_raw in authors:
                name = format_author_name(name_raw)
                if not name: continue
                    
                if is_writer:
                    staff.append({"role": "Story", "node": {"name": {"full": name}}})
                elif is_penciller:
                    staff.append({"role": "Art", "node": {"name": {"full": name}}})
                elif is_colorist:
                    staff.append({"role": "Color", "node": {"name": {"full": name}}})
                elif is_publisher and not publisher:
                    publisher = name_raw
                    
        return staff, publisher

    # CORRECTION : La VRAIE méthode fetch() avec la bonne signature
    def fetch(self, query: str, library_type: str = "Comic", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        session = requests.Session(impersonate="chrome110")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": "https://www.bedetheque.com/search/albums"
        }
        
        album_url = None
        serie_url = None
        fallback_url = None
        soup_album = None

        try:
            if is_id:
                logging.info(self.t("direct_url").format(query))
                if '/album-' in query:
                    album_url = query
                elif '/serie-' in query:
                    serie_url = query
                else:
                    logging.warning(self.t("invalid_url").format(query))
                    return None
            else:
                clean = clean_title(query, library_type=library_type)
                queries_to_try = generate_search_queries(clean)
                csrf_token = self._get_csrf_token(session, headers)
                
                for q in queries_to_try:
                    params = {"RechSerie": q, "csrf_token_bel": csrf_token}
                    logging.info(self.t("search").format(q))
                    
                    res_search = self._http_get(
                        session,
                        "https://www.bedetheque.com/search/albums",
                        params=params,
                        headers=headers,
                        timeout=15,
                    )
                    if not response_is_ok(self, res_search, context="recherche d'album"):
                        continue

                    soup_search = self._soup(res_search)
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
                                break
                    
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
                        logging.warning(self.t("not_found").format(clean))
                        return None

            if album_url and not album_url.startswith('http'): 
                album_url = f"https://www.bedetheque.com{album_url}"
            if serie_url and not serie_url.startswith('http'):
                serie_url = f"https://www.bedetheque.com{serie_url}"

            album_summary = ""
            staff = []
            publisher = None
            
            if album_url:
                soup_album = self._get_page(session, album_url, headers)
                if soup_album is None and not serie_url:
                    # Ni fiche album lisible, ni série à parcourir : rien à scraper.
                    return None

            if soup_album is not None:
                album_summary = self._extract_summary(soup_album)
                staff, publisher = self._extract_staff_and_publisher(soup_album, staff, publisher)

                if not serie_url:
                    h1_serie = soup_album.find('h1')
                    if h1_serie and h1_serie.find('a'):
                        serie_url = h1_serie.find('a').get('href')
                    
                    if not serie_url:
                        serie_links = soup_album.find_all('a', href=lambda h: h and '/serie-' in h and '.html' in h)
                        if serie_links:
                            serie_url = serie_links[0]['href']

            genres = []
            year = None
            status = "FINISHED"
            serie_summary = ""
            cover_url = None
            fetched_title = ""
            
            soup_serie = None
            if serie_url:
                if not serie_url.startswith('http'): 
                    serie_url = f"https://www.bedetheque.com{serie_url}"

                logging.info(self.t("scraping_serie").format(serie_url))
                
                soup_serie = self._get_page(session, serie_url, headers)

            # Fiche série illisible (HTTP en erreur) : on retombe sur la page album
            # quand elle a répondu, au lieu de prendre le titre d'une page d'erreur.
            if soup_serie is not None:
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
                
                year = self._serie_year(soup_serie, soup_album)

                if soup_serie.find(string=re.compile(r'En cours', re.IGNORECASE)):
                    status = "RELEASING"
                    
                if not staff:
                    staff, publisher = self._extract_staff_and_publisher(soup_serie, staff, publisher)
            else:
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

            candidate = {
                'title': fetched_title,
                'alternative_titles': [],
                'summary': final_summary,
                'cover_url': cover_url,
                'genres': genres[:get_max_genres()] if genres else ["BD"],
                'tags': tags[:get_max_tags()],
                'year': year,
                'status': status,
                'staff': unique_staff,
                'publisher': publisher,
                'format': 'comic',
                'url': serie_url or album_url,
                'links': [serie_url] if serie_url else [album_url]
            }
            if is_id:
                return attach_match_score(candidate, 1.0)
            clean_q = clean_title(query, library_type=library_type) or query
            score = score_candidate(candidate, clean_q, existing_metadata)
            if score < get_match_accept_threshold():
                return None
            return attach_match_score(candidate, score)
        except Exception as e:
            logging.error(self.t("error").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    # CORRECTION : Renommé en fetch_covers et allègement de la signature
    def fetch_covers(self, query: str, library_type: str = "Comic") -> List[Dict[str, str]]:
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
                res = self._http_get(
                    session,
                    "https://www.bedetheque.com/search/albums",
                    params=params,
                    headers=headers,
                    timeout=10,
                )
                if response_is_ok(self, res, context="recherche de couvertures"):
                    soup = self._soup(res)
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
                            
                            serie_text = serie_span.get_text(strip=True) if serie_span else self.t("unknown")
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
                logging.error(self.t("covers_err").format(q, e))
                
        best_covers = exact_matches if exact_matches else fallback_matches
        try:
            return best_covers[:8]
        finally:
            try:
                session.close()
            except Exception:
                pass