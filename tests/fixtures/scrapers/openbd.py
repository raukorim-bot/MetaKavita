"""openBD (JP) — métadonnées / covers livres japonais via API ISBN (gratuit, sans clé).

API : https://api.openbd.jp/v1/get?isbn=…
Recherche par titre non supportée par l’API → ISBN requis (query ou existing_metadata).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from curl_cffi import requests

from config_manager import get_max_genres
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    score_candidate,
)

_API = "https://api.openbd.jp/v1/get"
_NON_ISBN = re.compile(r"[^0-9Xx]")
_YEAR = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


def _norm_isbn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    c = _NON_ISBN.sub("", str(raw)).upper()
    return c if len(c) in (10, 13) else None


class OpenbdScraper(BaseScraper):
    id = "OPENBD"
    display_name = "openBD (JP)"
    supported_types = {"Book"}
    rate_limit = 1.0
    proxy_domains = [
        "openbd.jp",
        "api.openbd.jp",
        "cover.openbd.jp",
        "www.openbd.jp",
    ]
    has_direct_id_support = True
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "search_isbn": "🔎 [openBD] ISBN {0}…",
            "no_isbn": "⚠️ [openBD] ISBN requis (API ISBN-only)",
            "no_match": "⚠️ [openBD] Aucun résultat pour ISBN {0}",
            "matched": "🎯 [openBD] Match : '{0}'",
            "err": "❌ [openBD] Erreur : {0}",
            "covers_err": "❌ [Covers] openBD : {0}",
        },
        "en": {
            "search_isbn": "🔎 [openBD] ISBN {0}…",
            "no_isbn": "⚠️ [openBD] ISBN required (ISBN-only API)",
            "no_match": "⚠️ [openBD] No result for ISBN {0}",
            "matched": "🎯 [openBD] Match: '{0}'",
            "err": "❌ [openBD] Error: {0}",
            "covers_err": "❌ [Covers] openBD: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        return _norm_isbn(url.strip())

    def fetch(
        self,
        query: str,
        library_type: str = "Book",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            isbn = None
            if is_id:
                isbn = self.extract_id_from_url(query) or _norm_isbn(query)
            if not isbn:
                isbn = _norm_isbn((existing_metadata or {}).get("isbn"))
            if not isbn:
                isbn = _norm_isbn(query)
            if not isbn:
                logging.warning(self.t("no_isbn"))
                return None

            logging.info(self.t("search_isbn").format(isbn))
            cand = self._get_isbn(isbn)
            if not cand:
                logging.warning(self.t("no_match").format(isbn))
                return None
            cleaned = clean_title(query, library_type=library_type) or cand.get("title") or ""
            score = 1.0 if is_id or _norm_isbn(query) == isbn else score_candidate(
                cand, cleaned, existing_metadata
            )
            if score < get_match_accept_threshold() and not is_id:
                logging.warning(
                    self.t("no_match").format(isbn)
                    + f" (score {int(score * 100)}%)"
                )
                return None
            logging.info(self.t("matched").format(cand.get("title")))
            return attach_match_score(cand, min(1.0, score))
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Book") -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        isbn = _norm_isbn(query)
        if not isbn:
            return covers
        try:
            cand = self._get_isbn(isbn)
            if cand and cand.get("cover_url"):
                covers.append(
                    {
                        "provider": self.display_name,
                        "title": cand.get("title") or isbn,
                        "url": cand["cover_url"],
                    }
                )
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers

    def _get_isbn(self, isbn: str) -> Optional[Dict[str, Any]]:
        res = requests.get(_API, params={"isbn": isbn}, timeout=20)
        if res.status_code != 200:
            return None
        data = res.json()
        if not isinstance(data, list) or not data or not data[0]:
            return None
        row = data[0]
        summary = row.get("summary") if isinstance(row, dict) else None
        onix = row.get("onix") if isinstance(row, dict) else None
        title = None
        author = None
        publisher = None
        pubdate = None
        cover = None
        if isinstance(summary, dict):
            title = summary.get("title")
            author = summary.get("author")
            publisher = summary.get("publisher")
            pubdate = summary.get("pubdate")
            cover = summary.get("cover")
        if not title and isinstance(onix, dict):
            try:
                title = (
                    onix["DescriptiveDetail"]["TitleDetail"]["TitleElement"]["TitleText"]
                )
                if isinstance(title, dict):
                    title = title.get("content") or title.get("#text") or str(title)
            except Exception:
                title = None
        if not title:
            return None
        year = None
        if pubdate:
            m = _YEAR.search(str(pubdate))
            if m:
                year = int(m.group(1))
        staff = []
        if author:
            # "Surname/FirstName" or "A, B"
            for part in re.split(r"[,;/]", str(author)):
                name = part.strip().replace("／", " ").replace("/", " ").strip()
                if name:
                    staff.append({"role": "Story", "node": {"name": {"full": name}}})
        # Ne pas inventer cover.openbd.jp/{isbn}.jpg : beaucoup d'ISBN n'ont
        # pas d'image (404) → vignette cassée dans Manual Review / covers.
        if cover and not str(cover).startswith(("http://", "https://")):
            cover = None
        url = f"https://www.openbd.jp/"  # pas d'URL notice stable ; ISBN en id
        return {
            "title": str(title).strip(),
            "alternative_titles": [],
            "summary": "",
            "cover_url": cover or None,
            "genres": ["Book"][: get_max_genres()],
            "tags": [],
            "year": year,
            "staff": staff[:5],
            "publisher": publisher,
            "format": "book",
            "url": url,
            "links": [url],
            "isbn": isbn,
        }
