"""Planète BD (planetebd.com) — métadonnées BD / comics FR (HTML, pas d'API)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    extract_volume_number,
    get_match_accept_threshold,
    score_candidate,
)

_BASE = "https://www.planetebd.com"
_NON_ISBN = re.compile(r"[^0-9Xx]")
_ALBUM_RE = re.compile(
    r"^/(?P<kind>bd|comics|mangas)/(?P<publisher>[^/]+)/(?P<series>[^/]+)/(?P<album>[^/]+)/(?P<id>\d+)\.html",
    re.I,
)
_SERIES_RE = re.compile(
    r"^/(?P<kind>bd|comics|mangas)/series/(?P<slug>[^/]+)/(?P<id>\d+)\.html",
    re.I,
)
_YEAR = re.compile(r"(1[0-9]{3}|20[0-9]{2})")

# Catégories Planetebd acceptées pour library_type Comic
_COMIC_CATS = {"bande dessinée", "bandes dessinées", "comics", "comic"}


def _normalize_isbn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = _NON_ISBN.sub("", str(raw)).upper()
    if len(cleaned) in (10, 13):
        return cleaned
    return None


def _abs(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return urljoin(_BASE, url.split("#", 1)[0])


def _series_title_from_album_label(label: str) -> str:
    """'Astérix T41 : …' / 'Watchmen T12' → titre de série approximatif."""
    label = (label or "").strip()
    if not label:
        return ""
    # Couper sous-titre après " : "
    head = label.split(" : ", 1)[0].strip()
    head = re.sub(r"\s+T(?:ome)?\s*\d+\s*$", "", head, flags=re.I).strip()
    head = re.sub(r",\s*T\d+\s*$", "", head, flags=re.I).strip()
    return head or label


class PlanetebdScraper(BaseScraper):
    id = "PLANETEBD"
    display_name = "Planète BD"
    supported_types = {"Comic"}
    rate_limit = 2.5  # HTML — anti-ban IP
    proxy_domains = ["planetebd.com", "static.planetebd.com", "www.planetebd.com"]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "direct_id": "🎯 [PlanèteBD] Requête directe id={0}",
            "search_title": "🔍 [PlanèteBD] Recherche pour '{0}'…",
            "no_match": "⚠️ [PlanèteBD] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [PlanèteBD] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [PlanèteBD] Erreur : {0}",
            "covers_err": "❌ [Covers] PlanèteBD : {0}",
        },
        "en": {
            "direct_id": "🎯 [PlanèteBD] Direct id request={0}",
            "search_title": "🔍 [PlanèteBD] Searching for '{0}'…",
            "no_match": "⚠️ [PlanèteBD] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [PlanèteBD] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [PlanèteBD] Error: {0}",
            "covers_err": "❌ [Covers] PlanèteBD: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        url = url.strip()
        if url.isdigit():
            return url
        path = urlparse(url).path if "://" in url else url
        m = _SERIES_RE.match(path)
        if m:
            return m.group("id")
        m = _ALBUM_RE.match(path)
        if m:
            return m.group("id")
        m = re.search(r"/(?:bd|comics|mangas)/series/[^/]+/(\d+)\.html", path)
        if m:
            return m.group(1)
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Comic",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if library_type not in self.supported_types and library_type != "ComicFlexible":
            if not is_id:
                return None

        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
                "Referer": f"{_BASE}/",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        try:
            if is_id:
                sid = self.extract_id_from_url(query) or (
                    query.strip() if query.strip().isdigit() else None
                )
                if not sid:
                    return None
                logging.info(self.t("direct_id").format(sid))
                # Bare numeric ID: probe with a placeholder slug — the site
                # redirects to the canonical /series/<slug>/<id>.html URL.
                for kind in ("bd", "comics", "mangas"):
                    probe = f"{_BASE}/{kind}/series/s/{sid}.html"
                    try:
                        res = session.get(probe, timeout=20, allow_redirects=True)
                        if res is None or getattr(res, "status_code", 0) != 200:
                            continue
                        final = getattr(res, "url", None) or probe
                        cand = self._candidate_from_series_or_album(session, final)
                        if cand:
                            return attach_match_score(cand, 1.0)
                    except Exception as e:
                        logging.debug("PlaneteBD bare-id probe %s failed: %s", probe, e)
                # Fallback : URL complète fournie
                if "planetebd.com" in query or query.startswith("/"):
                    cand = self._candidate_from_series_or_album(session, query)
                    if cand:
                        return attach_match_score(cand, 1.0)
                return None

            cleaned = clean_title(query, library_type="Comic")
            if not cleaned:
                return None

            logging.info(self.t("search_title").format(cleaned))
            hits = self._search(session, cleaned)
            if not hits:
                return None

            # Dédupliquer par slug série album, préférer tome 1
            by_series: Dict[str, dict] = {}
            for hit in hits:
                key = hit.get("series_key") or hit.get("url")
                if not key:
                    continue
                vol = extract_volume_number(hit.get("label") or "")
                prev = by_series.get(key)
                if not prev:
                    by_series[key] = hit
                    continue
                prev_vol = extract_volume_number(prev.get("label") or "")
                if vol == 1 and prev_vol != 1:
                    by_series[key] = hit
                elif (prev_vol is None or prev_vol > 1) and vol is not None and (
                    prev_vol is None or vol < prev_vol
                ):
                    by_series[key] = hit

            ranked_hits = list(by_series.values())[:8]

            best_match = None
            best_score = -1.0
            for hit in ranked_hits:
                candidate = self._candidate_from_series_or_album(
                    session, hit["url"], search_hint=cleaned, hit=hit
                )
                if not candidate or not candidate.get("title"):
                    continue
                score = score_candidate(candidate, cleaned, existing_metadata)
                if (candidate.get("title") or "").casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.12)
                # Bonus franchise courte dans le titre
                if cleaned.casefold() in (candidate.get("title") or "").casefold():
                    score = min(1.0, max(score, 0.72))
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
        self, query: str, library_type: str = "Comic"
    ) -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        cleaned = clean_title(query, library_type="Comic")
        if not cleaned:
            return covers
        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": f"{_BASE}/",
            }
        )
        try:
            hits = self._search(session, cleaned)
            for hit in hits:
                url = hit.get("cover")
                title = _series_title_from_album_label(hit.get("label") or cleaned)
                if url and url not in [c["url"] for c in covers]:
                    covers.append(
                        {
                            "provider": self.display_name,
                            "title": title,
                            "url": url,
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

    # ------------------------------------------------------------------ Search

    def _search(self, session, terms: str) -> List[dict]:
        res = session.get(
            f"{_BASE}/recherche/",
            params={"mot-clef": terms},
            timeout=25,
        )
        if res.status_code != 200:
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        hits: List[dict] = []
        for art in soup.select("article.featured"):
            cat_el = art.select_one(".cat")
            cat = (cat_el.get_text(" ", strip=True) if cat_el else "").casefold()
            if cat and cat not in _COMIC_CATS:
                # Laisser passer si pas de cat (rare)
                if cat not in {"", "tous"}:
                    continue
            a = art.select_one(".image a[href], a[href*='/bd/'], a[href*='/comics/']")
            if not a:
                continue
            href = _abs(a.get("href"))
            if not href:
                continue
            path = urlparse(href).path
            m = _ALBUM_RE.match(path)
            if not m:
                continue
            img = art.select_one("img[src]")
            label = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
            # Nettoyer label type "… (0), bd chez …"
            label = re.split(r",\s*(?:bd|comics)\s+chez\s+", label, maxsplit=1, flags=re.I)[
                0
            ].strip()
            hits.append(
                {
                    "url": href,
                    "label": label,
                    "cover": img.get("src") if img else None,
                    "cat": cat,
                    "series_key": f"{m.group('kind')}/{m.group('publisher')}/{m.group('series')}",
                    "kind": m.group("kind"),
                }
            )
        return hits

    # ------------------------------------------------------------------ Detail

    def _candidate_from_series_or_album(
        self,
        session,
        url_or_path: str,
        *,
        search_hint: str = "",
        hit: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        url = _abs(url_or_path)
        if not url:
            return None
        path = urlparse(url).path

        # Si déjà une page série
        sm = _SERIES_RE.match(path)
        album_meta: Dict[str, Any] = {}
        series_url = None
        series_title = None
        series_id = None

        if sm:
            series_url = url
            series_id = sm.group("id")
            series_title = self._fetch_series_title(session, url)
            # Prendre un album de la série pour cover/staff
            album_meta = self._first_album_from_series(session, url) or {}
        else:
            album_meta = self._parse_album(session, url) or {}
            if not album_meta:
                return None
            series_url = album_meta.get("series_url")
            series_title = album_meta.get("series_title")
            series_id = album_meta.get("series_id")
            # Affiner le titre série via page série
            if series_url:
                st = self._fetch_series_title(session, series_url)
                if st:
                    series_title = st

        title = (
            series_title
            or _series_title_from_album_label(
                (hit or {}).get("label") or album_meta.get("album_title") or ""
            )
            or search_hint
        )
        if not title:
            return None

        cover = album_meta.get("cover_url") or (hit or {}).get("cover")
        staff = album_meta.get("staff") or []
        genres = album_meta.get("genres") or []
        tags = album_meta.get("tags") or []
        summary = album_meta.get("summary") or ""
        publisher = album_meta.get("publisher")
        year = album_meta.get("year")
        isbn = album_meta.get("isbn")
        status = album_meta.get("status")
        if series_url and not status:
            status = self._fetch_series_status(session, series_url)

        out: Dict[str, Any] = {
            "title": title,
            "alternative_titles": [],
            "summary": summary,
            "cover_url": cover,
            "genres": genres[: get_max_genres()] if genres else ["Comic"],
            "tags": tags[: get_max_tags()],
            "year": year,
            "staff": staff,
            "publisher": publisher,
            "format": "comic",
            "url": series_url or url,
            "links": [u for u in [series_url, url] if u],
        }
        if isbn:
            out["isbn"] = isbn
        if status:
            out["status"] = status
        # Pas d'age_rating inventé
        return out

    def _get_soup(self, session, url: str) -> Optional[BeautifulSoup]:
        res = session.get(url, timeout=25)
        if res.status_code != 200:
            return None
        return BeautifulSoup(res.text, "html.parser")

    def _fetch_series_title(self, session, series_url: str) -> Optional[str]:
        soup = self._get_soup(session, series_url)
        if not soup:
            return None
        if soup.h1:
            t = soup.h1.get_text(" ", strip=True)
            if t and "oops" not in t.casefold():
                return t
        return None

    def _fetch_series_status(self, session, series_url: str) -> Optional[str]:
        soup = self._get_soup(session, series_url)
        if not soup:
            return None
        text = soup.get_text(" ", strip=True).casefold()
        if "série terminée" in text or "serie terminee" in text:
            return "FINISHED"
        if "série en cours" in text or "serie en cours" in text:
            return "RELEASING"
        return None

    def _first_album_from_series(
        self, session, series_url: str
    ) -> Optional[Dict[str, Any]]:
        soup = self._get_soup(session, series_url)
        if not soup:
            return None
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            path = urlparse(urljoin(_BASE, href)).path
            if _ALBUM_RE.match(path):
                return self._parse_album(session, urljoin(_BASE, href))
        return None

    def _parse_album(self, session, album_url: str) -> Optional[Dict[str, Any]]:
        soup = self._get_soup(session, album_url)
        if not soup or not soup.title:
            return None

        og_title = soup.select_one('meta[property="og:title"]')
        og_desc = soup.select_one('meta[property="og:description"]')
        og_img = soup.select_one('meta[property="og:image"]')
        og_isbn = soup.select_one('meta[property="og:isbn"]')

        album_title = None
        if soup.h1:
            album_title = soup.h1.get_text(" ", strip=True)
        if not album_title and og_title:
            album_title = (og_title.get("content") or "").strip()

        # Série : lien /bd|comics/series/slug/id.html — préférer celui
        # dont le slug apparaît dans l'URL album
        path = urlparse(album_url).path
        am = _ALBUM_RE.match(path)
        series_slug = am.group("series") if am else ""
        series_url = None
        series_title = None
        series_id = None
        for a in soup.select("a[href*='/series/']"):
            href = _abs(a.get("href"))
            if not href:
                continue
            sm = _SERIES_RE.match(urlparse(href).path)
            if not sm:
                continue
            if series_slug and sm.group("slug") == series_slug:
                series_url = href
                series_title = a.get_text(" ", strip=True) or None
                series_id = sm.group("id")
                break
            if series_url is None:
                series_url = href
                series_title = a.get_text(" ", strip=True) or None
                series_id = sm.group("id")

        # Staff via /auteur/
        authors: List[str] = []
        seen = set()
        for a in soup.select("a[href*='/auteur/']"):
            name = a.get_text(" ", strip=True) or (a.get("title") or "").strip()
            key = name.casefold()
            if name and key not in seen and len(name) > 1:
                seen.add(key)
                authors.append(name)
        staff: List[Dict[str, Any]] = []
        for i, name in enumerate(authors[:6]):
            role = "Story" if i == 0 else ("Art" if i == 1 else "Art")
            if len(authors) == 1:
                role = "Story & Art"
            staff.append({"role": role, "node": {"name": {"full": name}}})

        # Fallback title tag: "… bd chez Éditeur de A, B"
        if not staff and soup.title:
            m = re.search(
                r"(?:bd|comics)\s+chez\s+.+?\s+de\s+(.+)$",
                soup.title.get_text(" ", strip=True),
                flags=re.I,
            )
            if m:
                for i, name in enumerate(
                    [x.strip() for x in m.group(1).split(",") if x.strip()][:4]
                ):
                    role = "Story" if i == 0 else "Art"
                    staff.append({"role": role, "node": {"name": {"full": name}}})

        editor = soup.select_one("[itemprop=editor]")
        publisher = editor.get_text(" ", strip=True) if editor else None

        year = None
        dp = soup.select_one('meta[itemprop="datePublished"]')
        if dp and dp.get("content"):
            ym = _YEAR.search(dp["content"])
            if ym:
                year = int(ym.group(1))

        genres = []
        for g in soup.select("[itemprop=genre]"):
            label = g.get_text(" ", strip=True)
            if label and label not in genres:
                genres.append(label)

        return {
            "album_title": album_title,
            "series_url": series_url,
            "series_title": series_title or _series_title_from_album_label(album_title or ""),
            "series_id": series_id,
            "cover_url": (og_img.get("content") if og_img else None),
            "summary": (og_desc.get("content") if og_desc else "") or "",
            "isbn": _normalize_isbn(og_isbn.get("content") if og_isbn else None),
            "publisher": publisher,
            "year": year,
            "staff": staff,
            "genres": genres,
            "tags": [],
            "status": None,
        }
