"""League of Comic Geeks — comics via HTML/XHR du site (pas d'API officielle).

L'API partenaire (`client_id` / `client_secret`) n'est **pas** en libre-service
sur leagueofcomicgeeks.com. Ce scraper utilise les mêmes endpoints XHR que le site
(`/comic/get_comics` + pages `/comics/series/{id}/…`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
)

_BASE = "https://leagueofcomicgeeks.com"
_YEAR_RE = re.compile(r"(1[89]\d{2}|20\d{2})")
_SERIES_PATH_RE = re.compile(r"/comics/series/(\d+)(?:/([^/?#]+))?", re.I)
_BROWSE_PREFIX_RE = re.compile(
    r"^Browse issues from the comic book series,\s*.+?,\s*from\s+[^.]+\.\s*",
    re.I,
)
_ARTICLES_RE = re.compile(r"^(?:the|an|a|le|la|les|l'|el|los|las|die|der|das)\s+", re.I)


def _title_key(title: Optional[str]) -> str:
    t = (title or "").casefold().strip()
    t = _ARTICLES_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def _abs(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = str(url).strip()
    if u.startswith("data:"):
        return None
    return urljoin(_BASE, u.split("#", 1)[0])


def _prefer_large_cover(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return url.replace("/covers/medium-", "/covers/large-").replace(
        "/covers/small-", "/covers/large-"
    )


class LocgScraper(BaseScraper):
    id = "LOCG"
    is_core = True
    display_name = "League of Comic Geeks"
    supported_types = {"Comic"}
    rate_limit = 5.0  # interactive HTML/XHR; Crawl-delay 30 is for search bots — do not bulk-crawl
    # 1.1.0 : les 5 s de cadence s'appliquent désormais à chaque requête (une
    # recherche déclenche jusqu'à neuf pages de série, elles partaient en rafale)
    # et le HTML est décodé par BeautifulSoup. La montée de version est ce qui
    # autorise l'image à remplacer la copie 1.0.x déjà installée sous data/.
    version = "1.1.0"
    proxy_domains = [
        "leagueofcomicgeeks.com",
        "www.leagueofcomicgeeks.com",
        "comicgeeks.app",
        "s3.amazonaws.com",
    ]
    has_direct_id_support = True
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "search_title": "🔍 [LoCG] Recherche pour '{0}'…",
            "direct_id": "🎯 [LoCG] series_id={0}",
            "no_match": "⚠️ [LoCG] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [LoCG] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [LoCG] Erreur : {0}",
            "covers_err": "❌ [Covers] LoCG : {0}",
        },
        "en": {
            "search_title": "🔍 [LoCG] Searching for '{0}'…",
            "direct_id": "🎯 [LoCG] series_id={0}",
            "no_match": "⚠️ [LoCG] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [LoCG] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [LoCG] Error: {0}",
            "covers_err": "❌ [Covers] LoCG: {0}",
        },
    }

    def __init__(self) -> None:
        self._session = requests.Session(impersonate="chrome110")
        self._session.headers.update(
            {
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{_BASE}/",
            }
        )

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        raw = url.strip()
        if raw.isdigit():
            return raw
        path = urlparse(raw).path if "://" in raw else raw
        m = _SERIES_PATH_RE.search(path)
        if m:
            return m.group(1)
        parts = [p for p in path.split("/") if p]
        for i, p in enumerate(parts):
            if p in {"series", "comics"} and i + 1 < len(parts) and parts[i + 1].isdigit():
                return parts[i + 1]
            if p.isdigit() and i > 0 and parts[i - 1] in {"series", "comic", "comics"}:
                return p
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Comic",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            if is_id:
                sid = self.extract_id_from_url(query)
                if not sid:
                    return None
                logging.info(self.t("direct_id").format(sid))
                cand = self._series_detail(sid, href=None, seed=None)
                return attach_match_score(cand, 1.0) if cand else None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned:
                return None
            logging.info(self.t("search_title").format(cleaned))
            hits = self._search_series(cleaned)
            best, best_score = None, -1.0
            ranked: List[tuple] = []
            want_year = None
            if existing_metadata and existing_metadata.get("year"):
                try:
                    want_year = int(existing_metadata["year"])
                except (TypeError, ValueError):
                    want_year = None

            for hit in hits:
                seed = self._hit_to_cand(hit)
                if not seed:
                    continue
                score = score_candidate(seed, cleaned, existing_metadata)
                if _title_key(seed.get("title")) == _title_key(cleaned):
                    score = min(1.0, score + 0.12)
                issues = int(hit.get("issues") or 0)
                if issues >= 12:
                    score = min(1.0, score + 0.05)
                elif issues >= 6:
                    score = min(1.0, score + 0.03)
                pub = (hit.get("publisher") or "").strip().casefold()
                if pub in {"other", "unknown", "n/a", ""}:
                    score = max(0.0, score - 0.08)
                # Départage éditions (traductions) : année proche + plus d'issues
                ydist = 9999
                if want_year is not None and hit.get("year"):
                    try:
                        ydist = abs(int(hit["year"]) - want_year)
                    except (TypeError, ValueError):
                        ydist = 9999
                ranked.append((score, ydist, -issues, hit, seed))

            # score desc, année proche, plus d'issues
            ranked.sort(key=lambda x: (-x[0], x[1], x[2]))

            for score, _yd, _iss, hit, seed in ranked[:8]:
                cand = self._series_detail(
                    str(hit["id"]), href=hit.get("href"), seed=seed
                ) or seed
                rescore = score_candidate(cand, cleaned, existing_metadata)
                if _title_key(cand.get("title")) == _title_key(cleaned):
                    rescore = min(1.0, rescore + 0.12)
                pub = ""
                for st in cand.get("staff") or []:
                    if isinstance(st, dict) and (st.get("role") or "").casefold() == "publisher":
                        node = (st.get("node") or {}).get("name") or {}
                        pub = str(node.get("full") or "").casefold()
                        break
                if pub in {"other", "unknown", "n/a"}:
                    rescore = max(0.0, rescore - 0.08)
                if want_year is not None and cand.get("year"):
                    try:
                        yd = abs(int(cand["year"]) - want_year)
                        if yd == 0:
                            rescore = min(1.0, rescore + 0.04)
                        elif yd <= 2:
                            rescore = min(1.0, rescore + 0.02)
                    except (TypeError, ValueError):
                        pass
                if rescore > best_score:
                    best_score, best = rescore, cand
                elif rescore == best_score and best and want_year is not None:
                    # garder l'année la plus proche en cas d'égalité
                    try:
                        by = abs(int(best.get("year") or 0) - want_year)
                        cy = abs(int(cand.get("year") or 0) - want_year)
                        if cy < by:
                            best = cand
                    except (TypeError, ValueError):
                        pass

            if not best or best_score < get_match_accept_threshold():
                logging.warning(
                    self.t("no_match").format(cleaned, int(max(best_score, 0) * 100))
                )
                return None
            logging.info(self.t("matched").format(best.get("title"), int(best_score * 100)))
            return attach_match_score(best, best_score)
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def fetch_covers(self, query: str, library_type: str = "Comic") -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return covers
        try:
            for hit in self._search_series(cleaned)[:8]:
                url = _prefer_large_cover(_abs(hit.get("cover")))
                if not url:
                    continue
                covers.append(
                    {
                        "provider": self.display_name,
                        "title": hit.get("title") or cleaned,
                        "url": url,
                    }
                )
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers

    def _get(self, url: str, **kwargs) -> Any:
        # Point de passage unique du scraper : c'est ici que la cadence est due,
        # une recherche enchaînant jusqu'à neuf requêtes (XHR + fiches série).
        return self._http_get(self._session, url, timeout=kwargs.pop("timeout", 25), **kwargs)

    @staticmethod
    def _soup(res) -> BeautifulSoup:
        """Soupe construite sur les OCTETS de la réponse, pas sur `res.text`.

        `curl_cffi` décode en UTF-8 avec `errors="replace"` quand le
        `Content-Type` n'annonce pas de charset, sans jamais lire le
        `<meta charset>` de la page : les caractères non-UTF-8 deviennent des
        U+FFFD irrécupérables, écrits tels quels dans Kavita. Sur les octets,
        BeautifulSoup lit le `<meta charset>` et décode juste.

        Le repli sur `res.text` couvre les fausses réponses des tests, qui
        n'exposent pas toujours d'octets exploitables.
        """
        raw = getattr(res, "content", None)
        if not isinstance(raw, (bytes, bytearray)):
            raw = res.text
        return BeautifulSoup(raw, "html.parser")

    def _search_series(self, terms: str) -> List[dict]:
        res = self._get(
            f"{_BASE}/comic/get_comics",
            params={"list": "search", "title": terms, "list_option": "series"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{_BASE}/comics",
            },
        )
        if not response_is_ok(self, res, context="recherche de séries"):
            return []
        try:
            data = res.json()
        except Exception:
            return []
        html = data.get("list") or ""
        if not html:
            return []
        return self._parse_search_list(html)

    def _parse_search_list(self, html: str) -> List[dict]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[dict] = []
        seen = set()
        for li in soup.select("ul.comic-series-thumb-list > li, #comic-list-titles > li"):
            link = li.select_one("a.link-collection-series[data-id], a.link-collection-series")
            if not link:
                continue
            sid = (link.get("data-id") or "").strip()
            href = link.get("href") or ""
            if not sid:
                m = _SERIES_PATH_RE.search(href)
                if m:
                    sid = m.group(1)
            if not sid or sid in seen:
                continue
            seen.add(sid)
            title_el = li.select_one(".title a") or link
            title = (title_el.get_text(" ", strip=True) or "").strip()
            if not title:
                img = link.select_one("img[alt]")
                title = (img.get("alt") if img else "") or ""
            if not title:
                continue
            pub = year = issues = None
            meta = li.select_one(".copy-really-small")
            if meta:
                spans = [sp.get_text(" ", strip=True) for sp in meta.select("span")]
                if spans:
                    pub = spans[0] or None
                for sp in spans[1:]:
                    m = _YEAR_RE.search(sp.replace("\xa0", " "))
                    if m:
                        year = int(m.group(0))
                        break
            ci = li.select_one(".count-issues")
            if ci:
                m = re.search(r"\d+", ci.get_text())
                if m:
                    issues = int(m.group(0))
            img = li.select_one("img[data-src], img[src]")
            cover = None
            if img:
                cover = img.get("data-src") or img.get("src")
            out.append(
                {
                    "id": sid,
                    "href": href,
                    "title": title,
                    "publisher": pub,
                    "year": year,
                    "issues": issues,
                    "cover": cover,
                }
            )
        return out

    def _series_detail(
        self,
        sid: str,
        href: Optional[str] = None,
        seed: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        urls = []
        if href:
            urls.append(_abs(href))
        if seed and seed.get("url"):
            urls.append(seed["url"])
        urls.append(f"{_BASE}/comics/series/{sid}")
        # slug inconnu : certaines pages marchent sans slug
        page = None
        final_url = None
        for u in urls:
            if not u:
                continue
            res = self._get(u, headers={"Accept": "text/html,application/xhtml+xml"})
            if res.status_code != 200:
                continue
            text = res.text or ""
            if "just a moment" in text.casefold() or len(text) < 8000:
                # stub / CF — tenter ajax series
                continue
            page = self._soup(res)
            final_url = str(res.url) if getattr(res, "url", None) else u
            break

        if page is None:
            # Fallback XHR minimal
            return self._series_from_ajax(sid, seed)

        title = None
        h1 = page.select_one("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        if not title and page.title:
            title = re.sub(r"\s+from\s+.+$", "", page.title.get_text(" ", strip=True), flags=re.I)

        publisher = None
        pub_el = page.select_one(".publisher")
        if pub_el:
            publisher = pub_el.get_text(" ", strip=True)

        year = None
        header = page.select_one("#content-header, header")
        header_txt = header.get_text(" ", strip=True) if header else ""
        # "DC Comics · 1986 - 1987 Watchmen"
        m = re.search(
            r"(?:·|\u00b7)\s*(\d{4})(?:\s*[-–]\s*(\d{4}))?",
            header_txt.replace("\xa0", " "),
        )
        if m:
            year = int(m.group(1))
        if not publisher and header_txt:
            pm = re.match(r"^\s*([^·\u00b7]+)", header_txt)
            if pm:
                publisher = pm.group(1).strip() or None

        summary = ""
        meta = page.select_one('meta[name="description"]')
        if meta and meta.get("content"):
            summary = _BROWSE_PREFIX_RE.sub("", meta["content"]).strip()
        og = page.select_one('meta[property="og:description"]')
        if not summary and og and og.get("content"):
            summary = _BROWSE_PREFIX_RE.sub("", og["content"]).strip()

        cover = None
        if seed and seed.get("cover_url"):
            cover = seed["cover_url"]
        if not cover:
            img = page.select_one("img.lazy[data-src*='covers'], .cover img[data-src], .cover img")
            if img:
                cover = _abs(img.get("data-src") or img.get("src"))
        cover = _prefer_large_cover(cover)

        if not year:
            years = []
            for li in page.select("li.issue")[:40]:
                for ym in _YEAR_RE.finditer(li.get_text(" ", strip=True)):
                    years.append(int(ym.group(0)))
            if years:
                year = min(years)

        if not title and seed:
            title = seed.get("title")
        if not title:
            return seed

        staff = []
        if publisher:
            staff.append({"role": "Publisher", "node": {"name": {"full": publisher}}})

        url = final_url or f"{_BASE}/comics/series/{sid}"
        genres = ["Comic"][: get_max_genres()]
        tags: List[str] = []
        if seed and seed.get("tags"):
            tags = list(seed["tags"])[: get_max_tags()]

        return {
            "title": title,
            "alternative_titles": [],
            "summary": summary or (seed.get("summary") if seed else "") or "",
            "cover_url": cover or (seed.get("cover_url") if seed else None),
            "genres": genres,
            "tags": tags,
            "year": year or (seed.get("year") if seed else None),
            "staff": staff or (seed.get("staff") if seed else []),
            "format": "comic",
            "url": url,
            "links": [url],
        }

    def _series_from_ajax(
        self, sid: str, seed: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        res = self._get(
            f"{_BASE}/comic/get_comics",
            params={"list": "series", "series_id": sid},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{_BASE}/comics/series/{sid}",
            },
        )
        # Dernier recours du chemin série : si celui-là est refusé, plus rien ne
        # sortira de League of Comic Geeks — c'est le moment de le dire.
        if not response_is_ok(self, res, context="repli XHR série"):
            return seed
        try:
            data = res.json()
        except Exception:
            return seed
        series = data.get("series") if isinstance(data, dict) else None
        if not isinstance(series, dict):
            return seed
        title = series.get("title") or (seed.get("title") if seed else None)
        if not title:
            return seed
        publisher = series.get("publisher_name")
        staff = []
        if publisher:
            staff.append({"role": "Publisher", "node": {"name": {"full": str(publisher)}}})
        url = f"{_BASE}/comics/series/{sid}"
        return {
            "title": title,
            "alternative_titles": [],
            "summary": (series.get("description") or "")
            or (seed.get("summary") if seed else "")
            or "",
            "cover_url": seed.get("cover_url") if seed else None,
            "genres": ["Comic"][: get_max_genres()],
            "tags": [],
            "year": seed.get("year") if seed else None,
            "staff": staff or (seed.get("staff") if seed else []),
            "format": "comic",
            "url": url,
            "links": [url],
        }

    def _hit_to_cand(self, hit: dict) -> Optional[Dict[str, Any]]:
        title = hit.get("title")
        if not title:
            return None
        sid = hit.get("id")
        href = hit.get("href")
        url = _abs(href) if href else (
            f"{_BASE}/comics/series/{sid}" if sid else None
        )
        staff = []
        pub = hit.get("publisher")
        if pub:
            staff.append({"role": "Publisher", "node": {"name": {"full": str(pub)}}})
        return {
            "title": title,
            "alternative_titles": [],
            "summary": "",
            "cover_url": _prefer_large_cover(_abs(hit.get("cover"))),
            "genres": ["Comic"][: get_max_genres()],
            "tags": [],
            "year": hit.get("year"),
            "staff": staff,
            "format": "comic",
            "url": url,
            "links": [url] if url else [],
        }
