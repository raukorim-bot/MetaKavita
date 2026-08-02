"""Babelio (babelio.com) — métadonnées littéraires francophones (HTML, pas d'API publique)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    score_candidate,
)

_BASE = "https://www.babelio.com"
_ENCODING = "iso-8859-1"
_ISBN13 = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_VOIR_PLUS = re.compile(r"voir_plus_a\(\s*'[^']*'\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_EDITORIAL_ROLE = re.compile(r"\([^)]*\)\s*$")
_WHITESPACE = re.compile(r"\s+")
_TITLE_SUFFIX = " - Babelio"
_TAG_CATEGORY = re.compile(r"^tc_(\d+)$")
_TAG_RELEVANCE = re.compile(r"^tag_t(\d+)$")
_AMAZON_SIZE = re.compile(r"\._S[XY]\d+_.*?(\.[A-Za-z]+)$")
_NON_ISBN = re.compile(r"[^0-9Xx]")


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "")).strip()


def _normalize_isbn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = _NON_ISBN.sub("", str(raw)).upper()
    if len(cleaned) == 13 and cleaned.isdigit():
        return cleaned
    if len(cleaned) == 10:
        return cleaned
    return None


def _full_resolution_cover(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return _AMAZON_SIZE.sub(r"\1", url)


def _id_from_livres_href(href: str) -> Optional[str]:
    if not href or "/livres/" not in href:
        return None
    return href.split("/livres/", 1)[1].split("?", 1)[0].rstrip("/")


def _soup(html: bytes) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser", from_encoding=_ENCODING)


class BabelioScraper(BaseScraper):
    id = "BABELIO"
    display_name = "Babelio (Littérature FR)"
    supported_types = {"Book"}
    rate_limit = 3.0  # HTML — anti-ban IP
    proxy_domains = [
        "babelio.com",
        "www.babelio.com",
        "images-na.ssl-images-amazon.com",
        "images-eu.ssl-images-amazon.com",
        "ecx.images-amazon.com",
        "m.media-amazon.com",
    ]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "direct_id": "🎯 [Babelio] Requête directe : '{0}'",
            "search_isbn": "🔎 [Babelio] Recherche prioritaire via ISBN : '{0}'",
            "matched_isbn": "🎯 [Babelio] Match exact par ISBN ({0}) : '{1}'",
            "search_title": "🔍 [Babelio] Recherche pour '{0}'...",
            "no_match": "⚠️ [Babelio] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Babelio] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [Babelio] Erreur : {0}",
            "covers_err": "❌ [Covers] Erreur Babelio : {0}",
            "blocked": "🚫 [Babelio] Accès refusé (HTTP 403). Réessayez plus tard.",
        },
        "en": {
            "direct_id": "🎯 [Babelio] Direct request: '{0}'",
            "search_isbn": "🔎 [Babelio] Priority search via ISBN: '{0}'",
            "matched_isbn": "🎯 [Babelio] Exact ISBN match ({0}): '{1}'",
            "search_title": "🔍 [Babelio] Searching for '{0}'...",
            "no_match": "⚠️ [Babelio] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Babelio] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [Babelio] Error: {0}",
            "covers_err": "❌ [Covers] Babelio error: {0}",
            "blocked": "🚫 [Babelio] Access denied (HTTP 403). Try again later.",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        if "babelio.com" in url and "/livres/" in url:
            return _id_from_livres_href(url)
        # Magic Input : slug/id brut (ex. Saint-Exupery-Le-Petit-Prince/36712)
        if re.match(r"^[\w\-]+/\d+$", url.strip()):
            return url.strip()
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Book",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        session = requests.Session()
        try:
            self._warmup(session)

            # 1. Magic Input / ID direct
            if is_id:
                book_id = self.extract_id_from_url(query) or query.strip().lstrip("/")
                if book_id.startswith("livres/"):
                    book_id = book_id[len("livres/") :]
                logging.info(self.t("direct_id").format(book_id))
                candidate = self._fetch_book(session, book_id)
                if candidate:
                    return attach_match_score(candidate, 1.0)
                return None

            existing_isbn = _normalize_isbn(
                (existing_metadata or {}).get("isbn") if existing_metadata else None
            )

            # 2. ISBN prioritaire (Kavita)
            if existing_isbn:
                logging.info(self.t("search_isbn").format(existing_isbn))
                hits = self._search(session, existing_isbn)
                for hit in hits[:3]:
                    candidate = self._fetch_book(session, hit["babelio_id"])
                    if not candidate:
                        continue
                    cand_isbn = _normalize_isbn(candidate.get("isbn"))
                    if cand_isbn and cand_isbn == existing_isbn:
                        logging.info(
                            self.t("matched_isbn").format(
                                existing_isbn, candidate.get("title")
                            )
                        )
                        return attach_match_score(candidate, 1.0)
                    # ISBN recherché mais page sans EAN : scorer quand même
                    score = score_candidate(candidate, clean_title(query, library_type=library_type) or query, existing_metadata)
                    if score >= get_match_accept_threshold():
                        return attach_match_score(candidate, score)

            # 3. Recherche textuelle
            cleaned = clean_title(query, library_type=library_type)
            if not cleaned:
                return None
            logging.info(self.t("search_title").format(cleaned))
            hits = self._search(session, cleaned)
            if not hits:
                return None

            best_match = None
            best_score = -1.0
            for hit in hits[:5]:
                candidate = self._fetch_book(session, hit["babelio_id"])
                if not candidate or not candidate.get("title"):
                    # Fallback léger depuis le hit de recherche
                    candidate = {
                        "title": hit.get("title") or "",
                        "staff": (
                            [
                                {
                                    "role": "Story",
                                    "node": {"name": {"full": hit["author"]}},
                                }
                            ]
                            if hit.get("author")
                            else []
                        ),
                        "url": f"{_BASE}/livres/{hit['babelio_id']}",
                        "format": "book",
                    }
                if not candidate.get("title"):
                    continue
                score = score_candidate(candidate, cleaned, existing_metadata)
                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < get_match_accept_threshold():
                logging.warning(
                    self.t("no_match").format(cleaned, int(max(best_score, 0) * 100))
                )
                return None

            logging.info(
                self.t("matched").format(best_match.get("title"), int(best_score * 100))
            )
            return attach_match_score(best_match, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_covers(
        self, query: str, library_type: str = "Book"
    ) -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return covers

        session = requests.Session()
        try:
            self._warmup(session)
            hits = self._search(session, cleaned)
            for hit in hits[:5]:
                candidate = self._fetch_book(session, hit["babelio_id"])
                if not candidate:
                    continue
                cover = candidate.get("cover_url")
                title = candidate.get("title") or hit.get("title") or cleaned
                if cover and cover not in [c["url"] for c in covers]:
                    covers.append(
                        {
                            "provider": self.display_name,
                            "title": title,
                            "url": cover,
                        }
                    )
                if len(covers) >= 5:
                    break
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        finally:
            try:
                session.close()
            except Exception:
                pass
        return covers

    # ------------------------------------------------------------------ HTTP

    def _headers(self, *, form: bool = False, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Origin"] = _BASE
            headers["Referer"] = referer or f"{_BASE}/"
        return headers

    def _warmup(self, session) -> None:
        try:
            session.get(
                f"{_BASE}/",
                impersonate="chrome",
                headers=self._headers(),
                timeout=15,
            )
        except Exception:
            pass

    def _get(self, session, url: str, *, referer: Optional[str] = None):
        res = session.get(
            url,
            impersonate="chrome",
            headers=self._headers(referer=referer),
            timeout=20,
        )
        if res.status_code == 403:
            logging.error(self.t("blocked"))
            return None
        if res.status_code != 200:
            return None
        return res

    def _post_search(self, session, terms: str):
        # Babelio attend un corps ISO-8859-1 (accents FR), comme le client Calibre.
        safe = terms.encode(_ENCODING, "ignore").decode(_ENCODING)
        body = urlencode({"Recherche": safe}, encoding=_ENCODING).encode(_ENCODING)
        res = session.post(
            f"{_BASE}/recherche",
            data=body,
            impersonate="chrome",
            headers=self._headers(form=True),
            timeout=20,
        )
        if res.status_code == 403:
            logging.error(self.t("blocked"))
            return None
        if res.status_code != 200:
            return None
        return res

    def _search(self, session, terms: str) -> List[Dict[str, str]]:
        res = self._post_search(session, terms)
        if not res:
            return []
        return self._parse_search_results(res.content)

    def _fetch_book(self, session, babelio_id: str) -> Optional[Dict[str, Any]]:
        url = f"{_BASE}/livres/{babelio_id}"
        res = self._get(session, url, referer=f"{_BASE}/")
        if not res:
            return None
        book = self._parse_book_page(res.content, fallback_id=babelio_id)
        if not book:
            return None

        # Résumé tronqué → AJAX "voir plus"
        summary_type = book.pop("_summary_type", None)
        summary_id = book.pop("_summary_id", None)
        if summary_type is not None and summary_id is not None:
            full = self._fetch_full_summary(
                session, summary_type, summary_id, referer=url
            )
            if full and len(full) > len(book.get("summary") or ""):
                book["summary"] = full
        return book

    def _fetch_full_summary(
        self, session, summary_type: int, obj_id: int, *, referer: str
    ) -> Optional[str]:
        try:
            body = f"type={summary_type}&id_obj={obj_id}".encode("ascii")
            res = session.post(
                f"{_BASE}/aj_voir_plus_a.php",
                data=body,
                impersonate="chrome",
                headers={
                    **self._headers(form=True, referer=referer),
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
            )
            if res.status_code != 200:
                return None
            return self._parse_full_summary(res.content)
        except Exception:
            return None

    # ------------------------------------------------------------------ Parse

    def _parse_search_results(self, html: bytes) -> List[Dict[str, str]]:
        soup = _soup(html)
        hits: List[Dict[str, str]] = []
        seen: set = set()

        for meta in soup.select(".cr_meta"):
            hit = self._parse_cr_meta(meta)
            if hit and hit["babelio_id"] not in seen:
                seen.add(hit["babelio_id"])
                hits.append(hit)

        if hits:
            return hits

        for item in soup.select("ul.livres_mozaique li.item"):
            hit = self._parse_mosaic_item(item)
            if hit and hit["babelio_id"] not in seen:
                seen.add(hit["babelio_id"])
                hits.append(hit)
        return hits

    def _parse_cr_meta(self, meta) -> Optional[Dict[str, str]]:
        link = meta.select_one(".titre1 a") or meta.select_one("a.titre1")
        if link is None:
            return None
        href = link.get("href") or ""
        babelio_id = _id_from_livres_href(href)
        if not babelio_id:
            return None
        author_node = meta.select_one(".libelle")
        author = _collapse(author_node.get_text(" ", strip=True)) if author_node else ""
        return {
            "babelio_id": babelio_id,
            "title": _collapse(link.get_text(" ", strip=True)),
            "author": author,
        }

    def _parse_mosaic_item(self, item) -> Optional[Dict[str, str]]:
        link = item.select_one('a[href^="/livres/"]')
        if link is None:
            return None
        href = link.get("href") or ""
        babelio_id = _id_from_livres_href(href)
        if not babelio_id:
            return None
        title_node = item.select_one(".titre_compact")
        title = (
            title_node.get_text(" ", strip=True)
            if title_node
            else link.get_text(" ", strip=True)
        )
        return {
            "babelio_id": babelio_id,
            "title": _collapse(title),
            "author": "",
        }

    def _parse_book_page(
        self, html: bytes, *, fallback_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        soup = _soup(html)
        babelio_id = self._parse_babelio_id(soup) or fallback_id
        refs = soup.select_one(".livre_refs.grey_light")
        if babelio_id is None and refs is None:
            return None

        refs_text = refs.get_text(" ", strip=True) if refs is not None else ""
        title = self._parse_title(soup)
        if not title:
            return None

        authors = self._parse_authors(soup)
        staff = [
            {"role": "Story", "node": {"name": {"full": name}}} for name in authors
        ]

        genres, tags = self._parse_genres_tags(soup)
        year = self._parse_year(refs_text)
        isbn = _normalize_isbn(self._parse_isbn(refs_text))
        publisher = self._parse_publisher(refs)
        cover_url = _full_resolution_cover(self._parse_cover_url(soup))
        summary = self._parse_summary(soup) or ""
        summary_type, summary_id = self._parse_summary_full_args(soup)

        series = self._parse_series(soup)
        alternative_titles = [series] if series and series.casefold() != title.casefold() else []

        url = f"{_BASE}/livres/{babelio_id}" if babelio_id else None

        return {
            "title": title,
            "alternative_titles": alternative_titles,
            "summary": summary,
            "cover_url": cover_url,
            "genres": genres[: get_max_genres()] if genres else ["Book"],
            "tags": tags[: get_max_tags()],
            "year": year,
            # BF59 : pas de statut inventé (Babelio n'en expose pas d'autoritatif)
            "staff": staff,
            "publisher": publisher,
            # BF56 : pas d'âge inventé
            "format": "book",
            "url": url,
            "links": [url] if url else [],
            "isbn": isbn,
            "_summary_type": summary_type,
            "_summary_id": summary_id,
        }

    def _parse_babelio_id(self, soup: BeautifulSoup) -> Optional[str]:
        canonical = soup.select_one('link[rel="canonical"]')
        if canonical is None:
            return None
        href = canonical.get("href") or ""
        return _id_from_livres_href(href)

    def _parse_title(self, soup: BeautifulSoup) -> str:
        node = soup.select_one("head > title") or soup.select_one("title")
        raw = _collapse(node.get_text(" ", strip=True)) if node is not None else ""
        if raw.endswith(_TITLE_SUFFIX):
            # "<title> - <author> - Babelio"
            return raw.rsplit(" - ", 2)[0]
        h1 = soup.find("h1")
        if h1:
            return _collapse(h1.get_text(" ", strip=True))
        return raw

    def _parse_authors(self, soup: BeautifulSoup) -> List[str]:
        container = soup.select_one(".livre_con")
        if container is None:
            return []
        authors: List[str] = []
        seen: set = set()
        for link in container.select('a[href^="/auteur/"]'):
            # Important : separator=" " — strip=True seul colle "de"+"Saint"
            name = _collapse(link.get_text(" ", strip=True))
            if not name or name in seen or _EDITORIAL_ROLE.search(name):
                continue
            seen.add(name)
            authors.append(name)
        return authors

    def _parse_isbn(self, refs_text: str) -> Optional[str]:
        match = _ISBN13.search(refs_text or "")
        return match.group(1) if match else None

    def _parse_publisher(self, refs) -> Optional[str]:
        if refs is None:
            return None
        names: List[str] = []
        seen: set = set()
        for link in refs.select('a[href^="/editeur"]'):
            name = _collapse(link.get_text(" ", strip=True))
            if not name or name in seen or name.casefold() == "voir plus":
                continue
            # La 1re ancre éditeur est le vrai éditeur ; la suivante est souvent la collection.
            seen.add(name)
            names.append(name)
            break
        return names[0] if names else None

    def _parse_year(self, refs_text: str) -> Optional[int]:
        match = _DATE.search(refs_text or "")
        if not match:
            return None
        try:
            year = int(match.group(3))
        except ValueError:
            return None
        return year if 1000 <= year <= 2100 else None

    def _parse_cover_url(self, soup: BeautifulSoup) -> Optional[str]:
        link = soup.select_one('link[rel="image_src"]')
        if link and link.get("href"):
            return link["href"]
        og = soup.select_one('meta[property="og:image"]')
        if og and og.get("content"):
            return og["content"]
        return None

    def _parse_summary(self, soup: BeautifulSoup) -> Optional[str]:
        node = soup.select_one(".livre_resume")
        if node is None:
            return None
        text = _collapse(node.get_text(" ", strip=True))
        # Retire le bouton "Voir plus" collé en fin de texte
        text = re.sub(r"\s*Voir plus\s*$", "", text, flags=re.IGNORECASE).strip()
        return text or None

    def _parse_summary_full_args(
        self, soup: BeautifulSoup
    ) -> Tuple[Optional[int], Optional[int]]:
        node = soup.select_one(".livre_resume")
        if node is None:
            return None, None
        for tag in [node, *node.select("[onclick]")]:
            onclick = tag.get("onclick") if hasattr(tag, "get") else None
            if not onclick:
                continue
            match = _VOIR_PLUS.search(onclick)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None, None

    def _parse_full_summary(self, html: bytes) -> Optional[str]:
        soup = _soup(html)
        for br in soup.find_all("br"):
            br.replace_with("\n")
        lines = [
            collapsed
            for raw in soup.get_text().split("\n")
            if (collapsed := _collapse(raw))
        ]
        return "\n".join(lines) or None

    def _parse_series(self, soup: BeautifulSoup) -> Optional[str]:
        link = soup.select_one('a[href^="/serie/"]')
        if link is None:
            return None
        name = _collapse(link.get_text(" ", strip=True))
        return name or None

    def _parse_genres_tags(self, soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
        """tc_0 = genres Babelio ; tc_1+ = thèmes / lieux / périodes → tags."""
        genres: List[str] = []
        tags: List[str] = []
        seen_g: set = set()
        seen_t: set = set()

        for link in soup.select(".tags a"):
            category_idx = None
            relevance = 0
            for cls in link.get("class") or []:
                cm = _TAG_CATEGORY.match(cls)
                if cm:
                    category_idx = int(cm.group(1))
                    continue
                rm = _TAG_RELEVANCE.match(cls)
                if rm:
                    relevance = int(rm.group(1))
            name = _collapse(link.get_text(" ", strip=True))
            if not name or category_idx is None:
                continue
            key = name.casefold()
            if category_idx == 0:
                if key not in seen_g and relevance >= 10:
                    seen_g.add(key)
                    genres.append(name)
            else:
                if key not in seen_t and relevance >= 10:
                    seen_t.add(key)
                    tags.append(name)

        # Filet : si aucun genre scoré, prendre les premiers tc_0 sans seuil
        if not genres:
            for link in soup.select(".tags a.tc_0"):
                name = _collapse(link.get_text(" ", strip=True))
                key = name.casefold()
                if name and key not in seen_g:
                    seen_g.add(key)
                    genres.append(name)
                if len(genres) >= 3:
                    break

        return genres, tags
