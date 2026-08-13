"""Decitre — métadonnées livres FR (HTML /search + fiche produit JSON-LD)."""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)

_BASE = "https://www.decitre.fr"
_PRODUCT = re.compile(r"^/livres/[^/]+-(\d{10,13})(?:_|\.html)", re.I)
_NON_ISBN = re.compile(r"[^0-9Xx]")
_YEAR = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


def _norm_isbn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    c = _NON_ISBN.sub("", str(raw)).upper()
    return c if len(c) in (10, 13) else None


class DecitreScraper(BaseScraper):
    id = "DECITRE"
    is_core = True
    display_name = "Decitre"
    supported_types = {"Book"}
    rate_limit = 2.5  # HTML e-commerce — anti-ban IP
    # 1.1.0 : les 2,5 s de cadence portent désormais sur chaque requête (une
    # recherche ouvre jusqu'à huit fiches produit, elles partaient en rafale) et le
    # HTML est décodé par BeautifulSoup, `curl_cffi` remplaçant sinon les accents
    # par des U+FFFD définitifs. La montée de version est ce qui autorise l'image à
    # remplacer la copie 1.0.x déjà installée sous data/.
    version = "1.1.0"
    proxy_domains = ["decitre.fr", "www.decitre.fr", "products-images.di-static.com", "di-static.com"]
    has_direct_id_support = True
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "search_title": "🔍 [Decitre] Recherche pour '{0}'…",
            "direct_id": "🎯 [Decitre] ISBN/URL={0}",
            "no_match": "⚠️ [Decitre] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Decitre] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [Decitre] Erreur : {0}",
            "covers_err": "❌ [Covers] Decitre : {0}",
        },
        "en": {
            "search_title": "🔍 [Decitre] Searching for '{0}'…",
            "direct_id": "🎯 [Decitre] ISBN/URL={0}",
            "no_match": "⚠️ [Decitre] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Decitre] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [Decitre] Error: {0}",
            "covers_err": "❌ [Covers] Decitre: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        if re.fullmatch(r"\d{10}|\d{13}", url.strip()):
            return url.strip()
        path = urlparse(url).path if "://" in url else url
        m = _PRODUCT.match(path)
        return m.group(1) if m else _norm_isbn(url)

    def fetch(
        self,
        query: str,
        library_type: str = "Book",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": f"{_BASE}/",
            }
        )
        try:
            if is_id:
                isbn = self.extract_id_from_url(query)
                logging.info(self.t("direct_id").format(isbn or query))
                if "decitre.fr" in query or query.startswith("/livres/"):
                    cand = self._parse_product(session, urljoin(_BASE, query))
                    if cand:
                        return attach_match_score(cand, 1.0)
                if isbn:
                    hits = self._search(session, isbn)
                    for h in hits[:3]:
                        cand = self._parse_product(session, h["url"])
                        if cand and _norm_isbn(cand.get("isbn")) == isbn:
                            return attach_match_score(cand, 1.0)
                return None

            existing_isbn = _norm_isbn(
                (existing_metadata or {}).get("isbn") if existing_metadata else None
            )
            cleaned = clean_title(query, library_type=library_type)
            term = existing_isbn or cleaned
            if not term:
                return None
            logging.info(self.t("search_title").format(term))
            hits = self._search(session, term)
            best, best_score = None, -1.0
            for hit in hits[:8]:
                cand = self._parse_product(session, hit["url"])
                if not cand:
                    continue
                if existing_isbn and _norm_isbn(cand.get("isbn")) == existing_isbn:
                    return attach_match_score(cand, 1.0)
                score = score_candidate(cand, cleaned or term, existing_metadata)
                # Rééditions libraire : léger malus année très récente si titre exact
                y = cand.get("year")
                if isinstance(y, int) and y >= date.today().year - 1:
                    score = max(0.0, score - 0.05)
                if (cand.get("title") or "").casefold() == (cleaned or term).casefold():
                    score = min(1.0, score + 0.08)
                # À score égal, préférer l'édition la plus ancienne
                better = score > best_score
                if (
                    not better
                    and score == best_score
                    and best
                    and isinstance(y, int)
                    and isinstance(best.get("year"), int)
                    and y < best["year"]
                ):
                    better = True
                if better:
                    best_score, best = score, cand
            if not best or best_score < get_match_accept_threshold():
                logging.warning(
                    self.t("no_match").format(term, int(max(best_score, 0) * 100))
                )
                return None
            logging.info(self.t("matched").format(best.get("title"), int(best_score * 100)))
            return attach_match_score(best, best_score)
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_covers(self, query: str, library_type: str = "Book") -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return covers
        session = requests.Session(impersonate="chrome110")
        try:
            for hit in self._search(session, cleaned)[:5]:
                cand = self._parse_product(session, hit["url"])
                if cand and cand.get("cover_url"):
                    covers.append(
                        {
                            "provider": self.display_name,
                            "title": cand.get("title") or cleaned,
                            "url": cand["cover_url"],
                        }
                    )
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        finally:
            try:
                session.close()
            except Exception:
                pass
        return covers

    @staticmethod
    def _soup(res) -> BeautifulSoup:
        """Soupe construite sur les OCTETS de la réponse, pas sur `res.text`.

        `curl_cffi` décode en UTF-8 avec `errors="replace"` quand le
        `Content-Type` n'annonce pas de charset, et ne lit jamais le
        `<meta charset>` de la page : les accents des titres et des résumés
        Decitre deviennent des U+FFFD irrécupérables, écrits puis verrouillés
        dans Kavita. Sur les octets, BeautifulSoup lit ce `<meta charset>`.

        Le repli sur `res.text` couvre les fausses réponses des tests, qui
        n'exposent pas toujours d'octets exploitables.
        """
        raw = getattr(res, "content", None)
        if not isinstance(raw, (bytes, bytearray)):
            raw = res.text
        return BeautifulSoup(raw, "html.parser")

    def _search(self, session, terms: str) -> List[dict]:
        res = self._http_get(session, f"{_BASE}/search", params={"search": terms}, timeout=25)
        if not response_is_ok(self, res, context="recherche"):
            return []
        soup = self._soup(res)
        hits, seen = [], set()
        for a in soup.select('a[href*="/livres/"]'):
            href = a.get("href") or ""
            path = urlparse(urljoin(_BASE, href)).path
            m = _PRODUCT.match(path)
            if not m:
                continue
            url = urljoin(_BASE, path)
            if url in seen:
                continue
            seen.add(url)
            title = a.get_text(" ", strip=True) or path
            hits.append({"url": url, "title": title, "isbn": m.group(1)})
            if len(hits) >= 12:
                break
        return hits

    def _parse_product(self, session, url: str) -> Optional[Dict[str, Any]]:
        res = self._http_get(session, url, timeout=25)
        if not response_is_ok(self, res, context="fiche produit"):
            return None
        soup = self._soup(res)
        data = None
        for sc in soup.select('script[type="application/ld+json"]'):
            raw = (sc.string or "").strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("@type") in ("Book", "Product"):
                data = obj
                break
            if isinstance(obj, list):
                for it in obj:
                    if isinstance(it, dict) and it.get("@type") in ("Book", "Product"):
                        data = it
                        break
        if not data:
            return None
        title = (data.get("name") or "").strip()
        if not title:
            return None
        authors = []
        auth = data.get("author")
        if isinstance(auth, dict):
            authors = [auth.get("name")] if auth.get("name") else []
        elif isinstance(auth, list):
            authors = [a.get("name") for a in auth if isinstance(a, dict) and a.get("name")]
        elif isinstance(auth, str):
            authors = [auth]
        staff = [
            {"role": "Story", "node": {"name": {"full": n.strip()}}}
            for n in authors
            if n and str(n).strip()
        ]
        isbn = _norm_isbn(
            data.get("isbn")
            or data.get("gtin13")
            or (data.get("offers") or {}).get("gtin13")
            if isinstance(data.get("offers"), dict)
            else data.get("isbn")
        )
        if not isbn:
            isbn = self.extract_id_from_url(url)
        year = None
        for key in ("datePublished", "copyrightYear"):
            m = _YEAR.search(str(data.get(key) or ""))
            if m:
                year = int(m.group(1))
                break
        publisher = None
        pub = data.get("publisher")
        if isinstance(pub, dict):
            publisher = pub.get("name")
        elif isinstance(pub, str):
            publisher = pub
        cover = data.get("image")
        if isinstance(cover, list):
            cover = cover[0] if cover else None
        if isinstance(cover, dict):
            cover = cover.get("url")
        summary = (data.get("description") or "").strip()
        return {
            "title": title,
            "alternative_titles": [],
            "summary": summary,
            "cover_url": cover,
            "genres": ["Book"],
            "tags": [],
            "year": year,
            "staff": staff,
            "publisher": publisher,
            "format": "book",
            "url": url,
            "links": [url],
            "isbn": isbn,
        }
