"""
BDTheque.com (https://www.bdtheque.com/) — base communautaire franco-belge.

À ne pas confondre avec Bédéthèque (bedetheque.com / scraper BEDETHEQUE).
Recherche via AJAX typeahead : GET /ajax/search/series/{query}
Fiches séries : /series/{id}/{slug}
"""
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from config_manager import get_max_genres, get_max_tags
from .base import BaseScraper
from .utils import attach_match_score, clean_title, get_match_accept_threshold, score_candidate

BASE_URL = "https://www.bdtheque.com"
USER_AGENT = "MetaKavita/1.6 (+https://github.com; BD metadata enrichment)"


def format_author_name(name: str) -> str:
    """« Macherot (Raymond) » → « Raymond Macherot » ; ignore placeholders."""
    name = (name or "").strip()
    if not name:
        return ""
    lower = name.lower()
    if "indéterminé" in lower or "indeterminé" in lower or "quadrichromie" in lower:
        return ""
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", name)
    if m:
        return f"{m.group(2).strip()} {m.group(1).strip()}"
    return name


def generate_search_queries(title: str) -> list:
    queries = [title]
    pattern = r"^(le\s+|la\s+|les\s+|l[\'’]\s*|the\s+|a\s+|an\s+|un\s+|une\s+|des\s+)(.*)$"
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


def cover_url_from_couv(couv: Optional[str]) -> Optional[str]:
    """Mappe le champ AJAX `couv` vers une URL repupload.

    Le typeahead du site utilise toujours ``/repupload/T/{couv}``
    (ex. ``T_2375.JPG`` ou ``83637-couverture-bd-….jpg``). Les planches
    d'album vivent sous ``/repupload/G/`` etc. et ne passent pas par ce champ.
    """
    if not couv or not isinstance(couv, str):
        return None
    name = couv.strip().lstrip("/")
    if not name:
        return None
    if name.startswith("http"):
        return name
    if name.startswith("repupload/"):
        return f"{BASE_URL}/{name}"
    # Préfixe lettre_ (T_2375.JPG, G_…) → dossier = 1re lettre ; sinon dossier T/
    m = re.match(r"^([A-Za-z])_", name)
    folder = m.group(1).upper() if m else "T"
    return f"{BASE_URL}/repupload/{folder}/{name}"


def absolute_image_url(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or "placeholder" in url.lower():
        return None
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return f"{BASE_URL}{url}"
    return f"{BASE_URL}/{url.lstrip('/')}"


def extract_cover_from_img(tag) -> Optional[str]:
    """Préfère data-echo / data-src (lazy-load echo.js) au src placeholder."""
    if not tag:
        return None
    for attr in ("data-echo", "data-src", "data-lazy", "src"):
        url = absolute_image_url(tag.get(attr))
        if url:
            return url
    return None


class BdthequeScraper(BaseScraper):
    id = "BDTHEQUE"
    display_name = "BDTheque.com (Franco-Belge)"
    supported_types = {"Comic"}
    uses_unified_scoring = True
    rate_limit = 1.5
    proxy_domains = ["bdtheque.com", "www.bdtheque.com"]
    has_direct_id_support = True

    translations = {
        "fr": {
            "search": "🔍 [BDTheque] Recherche pour '{0}'...",
            "not_found": "⚠️ [BDTheque] Aucune série trouvée pour '{0}'.",
            "scraping": "⚡ [BDTheque] Scraping série ({0})",
            "error": "❌ [BDTheque] Erreur : {0}",
            "covers_err": "❌ [Covers] Erreur BDTheque pour '{0}' : {1}",
            "direct_id": "🎯 [BDTheque] ID / URL directe : '{0}'",
            "invalid_id": "⚠️ [BDTheque] Identifiant série invalide : {0}",
        },
        "en": {
            "search": "🔍 [BDTheque] Searching for '{0}'...",
            "not_found": "⚠️ [BDTheque] No series found for '{0}'.",
            "scraping": "⚡ [BDTheque] Scraping series ({0})",
            "error": "❌ [BDTheque] Error: {0}",
            "covers_err": "❌ [Covers] BDTheque error for '{0}': {1}",
            "direct_id": "🎯 [BDTheque] Direct ID / URL: '{0}'",
            "invalid_id": "⚠️ [BDTheque] Invalid series id: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrait `590/clifton` ou `590` depuis une URL bdtheque.com (jamais bedetheque)."""
        if not url or not isinstance(url, str):
            return None
        low = url.lower()
        if "bedetheque.com" in low:
            return None
        if "bdtheque.com" not in low:
            return None
        m = re.search(r"/series/(\d+)(?:/([^/?#]+))?", url, re.IGNORECASE)
        if not m:
            return None
        series_id, slug = m.group(1), m.group(2)
        return f"{series_id}/{slug}" if slug else series_id

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
            "Referer": f"{BASE_URL}/",
        }

    def _normalize_series_id(self, raw: str) -> Optional[str]:
        raw = (raw or "").strip()
        if not raw:
            return None
        # URL collée dans le champ ID
        from_url = self.extract_id_from_url(raw)
        if from_url:
            return from_url
        m = re.match(r"^(\d+)(?:/([A-Za-z0-9\-]+))?$", raw)
        if m:
            return f"{m.group(1)}/{m.group(2)}" if m.group(2) else m.group(1)
        return None

    def _series_url(self, series_id: str) -> str:
        return f"{BASE_URL}/series/{series_id}"

    def _ajax_search(self, session: requests.Session, query: str) -> List[dict]:
        path = quote(query.strip(), safe="")
        url = f"{BASE_URL}/ajax/search/series/{path}"
        res = session.get(url, headers=self._headers(), timeout=12)
        if res.status_code != 200:
            logging.warning(self.t("error").format(f"HTTP {res.status_code} (search)"))
            return []
        try:
            data = res.json()
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict) and x.get("id")]

    def _parse_status(self, raw: str) -> str:
        text = (raw or "").lower()
        if "one shot" in text or "oneshot" in text:
            return "FINISHED"
        if any(x in text for x in ("abandonn", "annul", "arrêt", "arret")):
            return "CANCELLED"
        if any(x in text for x in ("termin", "complét", "complet")):
            return "FINISHED"
        if "hiatus" in text or "pause" in text:
            return "HIATUS"
        if "en cours" in text or "histoire par tome" in text:
            return "RELEASING"
        return "RELEASING"

    def _parse_age(self, public: str) -> str:
        text = (public or "").lower()
        if any(x in text for x in ("adulte", "erotique", "érotique", "porn")):
            return "suggestive"
        return "safe"

    def _row_links(self, row) -> List[str]:
        return [format_author_name(a.get_text(strip=True)) for a in row.find_all("a")]

    def _parse_series_html(self, html: str, series_id: str, series_url: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        if not title:
            return None

        summary = ""
        lead = soup.select_one("p.lead")
        if lead:
            summary = lead.get_text(" ", strip=True)
        if len(summary) < 20:
            # Second paragraphe descriptif fréquent sous le lead
            for p in soup.find_all("p"):
                cls = " ".join(p.get("class") or [])
                if "lead" in cls or "card-text" in cls or "text-right" in cls:
                    continue
                text = p.get_text(" ", strip=True)
                if len(text) > 40 and not text.lower().startswith("site réalisé"):
                    summary = text
                    break
        if len(summary) < 15:
            meta = soup.find("meta", property="og:description") or soup.find(
                "meta", attrs={"name": "description"}
            )
            if meta and meta.get("content"):
                summary = meta["content"].strip()

        cover_url = None
        cover_img = soup.select_one("img.cover") or soup.find("img", class_="cover")
        cover_url = extract_cover_from_img(cover_img)
        if not cover_url:
            # Fallback : première image repupload hors planches G_ si présente en data-echo
            for img in soup.find_all("img"):
                cand = extract_cover_from_img(img)
                if cand and "/repupload/T/" in cand:
                    cover_url = cand
                    break

        writers: List[str] = []
        pencillers: List[str] = []
        colorists: List[str] = []
        publisher = ""
        genres: List[str] = []
        public = ""
        year = None
        status_raw = ""

        for tr in soup.select("table.table-sm tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True).lower()
            value_cell = cells[1]
            links = [x for x in self._row_links(value_cell) if x]
            value_text = value_cell.get_text(" ", strip=True)

            if "scénario" in label or "scenario" in label:
                writers.extend(links or [format_author_name(value_text)])
            elif label.startswith("dessin") or "dessin" in label:
                pencillers.extend(links or [format_author_name(value_text)])
            elif "couleur" in label:
                colorists.extend(links or [format_author_name(value_text)])
            elif "editeur" in label or "éditeur" in label:
                # Première ancre = éditeur (collection éventuelle en 2e)
                if links:
                    publisher = links[0]
                else:
                    publisher = value_text.split("/")[0].strip()
            elif "genre" in label:
                # Genre / Public / Type — 3 liens typiques
                genre_links = value_cell.find_all("a")
                for i, a in enumerate(genre_links):
                    t = a.get_text(strip=True)
                    if not t:
                        continue
                    href = (a.get("href") or "").lower()
                    if "public=" in href:
                        public = t
                    elif "type=" in href:
                        continue
                    elif "genre=" in href or i == 0:
                        if t not in genres:
                            genres.append(t)
            elif "parution" in label:
                ym = re.search(r"\b((19|20)\d{2})\b", value_text)
                if ym:
                    year = int(ym.group(1))
            elif "statut" in label:
                status_raw = value_text

        staff: List[dict] = []
        seen = set()
        for role, names in (
            ("Story", writers),
            ("Art", pencillers),
            ("Coloring", colorists),
        ):
            for n in names:
                n = (n or "").strip()
                if not n:
                    continue
                key = (role, n.lower())
                if key in seen:
                    continue
                seen.add(key)
                staff.append({"role": role, "node": {"name": {"full": n}}})

        alt_titles: List[str] = []
        # Titre VO éventuel dans le HTML (rare) — sinon rempli depuis AJAX
        vo = soup.select_one(".nomvo, .serie-vo, [data-nomvo]")
        if vo:
            vo_t = vo.get_text(strip=True)
            if vo_t and vo_t.lower() != title.lower():
                alt_titles.append(vo_t)

        tags = ["BDTheque"] + genres
        if public:
            tags.append(public)

        candidate = {
            "title": title,
            "alternative_titles": alt_titles,
            "summary": summary,
            "cover_url": cover_url,
            "genres": (genres or ["BD"])[: get_max_genres()],
            "tags": tags[: get_max_tags()],
            "year": year,
            "status": self._parse_status(status_raw),
            "staff": staff,
            "publisher": publisher,
            "age_rating": self._parse_age(public),
            "format": "comic",
            "url": series_url,
            "links": [series_url],
            "bdtheque_id": series_id,
        }
        return candidate

    def _fetch_series(
        self, session: requests.Session, series_id: str, sleep: bool = True
    ) -> Optional[Dict[str, Any]]:
        series_id = self._normalize_series_id(series_id) or series_id
        url = self._series_url(series_id)
        if sleep:
            time.sleep(self.rate_limit)
        logging.info(self.t("scraping").format(url))
        res = session.get(url, headers=self._headers(), timeout=15)
        if res.status_code != 200:
            logging.warning(self.t("error").format(f"HTTP {res.status_code} ({url})"))
            return None
        # ID final depuis l'URL effective (redirect /series/590 → …/slug)
        final_id = self.extract_id_from_url(res.url) or series_id
        return self._parse_series_html(res.text, final_id, res.url.split("?")[0])

    def fetch(
        self,
        query: str,
        library_type: str = "Comic",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        session = requests.Session()
        try:
            if is_id:
                series_id = self._normalize_series_id(query)
                if not series_id:
                    logging.warning(self.t("invalid_id").format(query))
                    return None
                logging.info(self.t("direct_id").format(series_id))
                candidate = self._fetch_series(session, series_id, sleep=False)
                if not candidate:
                    return None
                return attach_match_score(candidate, 1.0)

            clean_q = clean_title(query, library_type=library_type) or query
            logging.info(self.t("search").format(clean_q))

            hits: List[dict] = []
            seen_ids = set()
            for q in generate_search_queries(clean_q):
                for item in self._ajax_search(session, q):
                    sid = str(item.get("id") or "").strip()
                    if not sid or sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    hits.append(item)
                if hits:
                    break

            if not hits:
                logging.warning(self.t("not_found").format(clean_q))
                return None

            # Pré-tri approximatif sur le nom AJAX avant de charger les fiches
            def _name_score(item: dict) -> float:
                names = [item.get("nom") or "", item.get("nomvo") or ""]
                best = 0.0
                for n in names:
                    if not n:
                        continue
                    stub = {"title": n, "alternative_titles": [x for x in names if x and x != n]}
                    best = max(best, score_candidate(stub, clean_q, existing_metadata))
                return best

            ranked = sorted(hits, key=_name_score, reverse=True)[:5]
            threshold = get_match_accept_threshold()
            best: Optional[Dict[str, Any]] = None
            best_score = -1.0

            for i, item in enumerate(ranked):
                sid = str(item["id"])
                candidate = self._fetch_series(session, sid, sleep=(i > 0))
                if not candidate:
                    continue
                vo = (item.get("nomvo") or "").strip()
                if vo and vo.lower() != (candidate.get("title") or "").lower():
                    alts = list(candidate.get("alternative_titles") or [])
                    if vo not in alts:
                        alts.append(vo)
                    candidate["alternative_titles"] = alts
                if not candidate.get("cover_url"):
                    candidate["cover_url"] = cover_url_from_couv(item.get("couv"))

                score = score_candidate(candidate, clean_q, existing_metadata)
                if score > best_score:
                    best_score = score
                    best = attach_match_score(candidate, score)
                if score >= 0.95:
                    break

            if not best or best_score < threshold:
                return None
            return best
        except Exception as e:
            logging.error(self.t("error").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_covers(self, query: str, library_type: str = "Comic") -> List[Dict[str, str]]:
        clean = clean_title(query, library_type=library_type) or query
        queries_to_try = generate_search_queries(clean)
        session = requests.Session()
        exact_matches: List[Dict[str, str]] = []
        fallback_matches: List[Dict[str, str]] = []
        seen = set()
        try:
            for q in queries_to_try:
                for item in self._ajax_search(session, q):
                    title = (item.get("nom") or "").strip() or q
                    url = cover_url_from_couv(item.get("couv"))
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    cover_data = {
                        "provider": self.display_name,
                        "title": title,
                        "url": url,
                    }
                    norm_title = title.lower().strip()
                    is_exact = any(norm_title == qt.lower().strip() for qt in queries_to_try)
                    if not is_exact:
                        no_art_title = re.sub(
                            r"\s*\((le|la|les|l['’])\)$", "", norm_title, flags=re.I
                        ).strip()
                        no_art_query = re.sub(
                            r"^(le|la|les|l['’])\s+", "", clean.lower().strip(), flags=re.I
                        ).strip()
                        if no_art_title == no_art_query:
                            is_exact = True
                    if is_exact:
                        exact_matches.append(cover_data)
                    else:
                        fallback_matches.append(cover_data)
                if exact_matches:
                    break
        except Exception as e:
            logging.error(self.t("covers_err").format(query, e))
        finally:
            try:
                session.close()
            except Exception:
                pass
        return exact_matches if exact_matches else fallback_matches
