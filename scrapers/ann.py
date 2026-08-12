"""Anime News Network — encyclopédie manga via API XML publique (cdn.animenewsnetwork.com)."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    get_match_accept_threshold,
    score_candidate,
)

_API = "https://cdn.animenewsnetwork.com/encyclopedia/api.xml"
_SITE = "https://www.animenewsnetwork.com"
_YEAR = re.compile(r"(1[0-9]{3}|20[0-9]{2})")
_ID = re.compile(r"^\d{1,8}$")

# ANN Objectionable content → Kavita age_rating (signal explicite seulement)
_AGE_MAP = {
    "g": "safe",
    "pg": "safe",
    "ta": "suggestive",
    "ma": "erotica",
    "ao": "pornographic",
}


def _upgrade_cover(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if "/fit200x200/" in url:
        return url.replace("/fit200x200/", "/max500x600/")
    return url


def _text(el: Optional[ET.Element]) -> str:
    if el is None or el.text is None:
        return ""
    return (el.text or "").strip()


def _parse_year(vintage_blob: str) -> Optional[int]:
    """Premier millésime crédible dans les champs Vintage ANN."""
    if not vintage_blob:
        return None
    years = [int(y) for y in _YEAR.findall(vintage_blob)]
    if not years:
        return None
    # Préférer une année de sérialisation JP (souvent la plus ancienne)
    return min(years)


def _map_age(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _AGE_MAP.get(raw.strip().lower())


class AnnScraper(BaseScraper):
    id = "ANN"
    is_core = True
    display_name = "Anime News Network"
    supported_types = {"Manga"}
    rate_limit = 1.1  # ~0.91/s: 10% under ANN official 1 req/s
    proxy_domains = [
        "animenewsnetwork.com",
        "cdn.animenewsnetwork.com",
    ]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "direct_id": "🎯 [ANN] Requête directe id={0}",
            "search_title": "🔍 [ANN] Recherche pour '{0}'…",
            "no_match": "⚠️ [ANN] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [ANN] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [ANN] Erreur : {0}",
            "covers_err": "❌ [Covers] ANN : {0}",
        },
        "en": {
            "direct_id": "🎯 [ANN] Direct id request={0}",
            "search_title": "🔍 [ANN] Searching for '{0}'…",
            "no_match": "⚠️ [ANN] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [ANN] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [ANN] Error: {0}",
            "covers_err": "❌ [Covers] ANN: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        url = url.strip()
        if _ID.match(url):
            return url
        # https://www.animenewsnetwork.com/encyclopedia/manga.php?id=4354
        m = re.search(r"[?&]id=(\d{1,8})\b", url)
        if m and "animenewsnetwork.com" in url:
            return m.group(1)
        m = re.search(r"/encyclopedia/(?:manga|anime)\.php\?id=(\d{1,8})", url)
        if m:
            return m.group(1)
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Manga",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if library_type not in self.supported_types and not is_id:
            return None

        session = requests.Session()
        try:
            if is_id:
                mid = self.extract_id_from_url(query) or (
                    query.strip() if _ID.match(query.strip()) else None
                )
                if not mid:
                    return None
                logging.info(self.t("direct_id").format(mid))
                el = self._fetch_manga_el(session, mid)
                if el is None:
                    return None
                candidate = self._build_candidate(el)
                if not candidate:
                    return None
                return attach_match_score(candidate, 1.0)

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned:
                return None

            logging.info(self.t("search_title").format(cleaned))
            hits = self._search(session, cleaned, limit=12)
            if not hits:
                return None

            best_match = None
            best_score = -1.0
            # Pré-score sur le nom ANN, détail seulement top candidats
            prelim: List[Tuple[float, ET.Element]] = []
            for el in hits:
                title = (el.attrib.get("name") or "").strip()
                if not title:
                    continue
                stub = {"title": title, "alternative_titles": self._alt_titles(el)}
                score = score_candidate(stub, cleaned, existing_metadata)
                if (title or "").casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.12)
                prelim.append((score, el))
            prelim.sort(key=lambda x: x[0], reverse=True)

            for _, el in prelim[:5]:
                mid = el.attrib.get("id")
                # La recherche ~ renvoie déjà des fiches riches ; re-fetch ID pour
                # garantir Picture / Plot complets quand le hit est un résumé.
                detailed = self._fetch_manga_el(session, mid) if mid else None
                candidate = self._build_candidate(detailed or el)
                if not candidate or not candidate.get("title"):
                    continue
                score = score_candidate(candidate, cleaned, existing_metadata)
                if (candidate.get("title") or "").casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.12)
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
        self, query: str, library_type: str = "Manga"
    ) -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return covers
        session = requests.Session()
        try:
            hits = self._search(session, cleaned, limit=10)
            ranked: List[Tuple[float, ET.Element]] = []
            for el in hits:
                title = (el.attrib.get("name") or "").strip()
                stub = {"title": title, "alternative_titles": self._alt_titles(el)}
                score = score_candidate(stub, cleaned, None)
                if title.casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.12)
                ranked.append((score, el))
            ranked.sort(key=lambda x: x[0], reverse=True)
            for _, el in ranked:
                pic = None
                for info in el.findall("info"):
                    if info.attrib.get("type") == "Picture":
                        pic = _upgrade_cover(info.attrib.get("src"))
                        break
                title = (el.attrib.get("name") or cleaned).strip()
                if pic and pic not in [c["url"] for c in covers]:
                    covers.append(
                        {
                            "provider": self.display_name,
                            "title": title,
                            "url": pic,
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

    def _get_xml(self, session, params: Dict[str, str]) -> Optional[ET.Element]:
        res = session.get(
            _API,
            params=params,
            impersonate="chrome",
            headers={
                "Accept": "application/xml, text/xml, */*",
                "Accept-Language": "en-US,en;q=0.8",
                "User-Agent": "MetaKavita-ANN/1.0 (self-hosted; +https://github.com)",
            },
            timeout=25,
        )
        if res.status_code != 200:
            return None
        try:
            return ET.fromstring(res.content)
        except ET.ParseError:
            return None

    def _search(
        self, session, terms: str, *, limit: int = 12
    ) -> List[ET.Element]:
        # `manga=~query` = recherche encyclopédie limitée aux mangas
        root = self._get_xml(session, {"manga": f"~{terms}"})
        if root is None:
            return []
        if root.find("warning") is not None:
            return []
        hits = [
            el
            for el in root.findall("manga")
            if el.attrib.get("id") and (el.attrib.get("name") or "").strip()
        ]
        return hits[: max(1, min(limit, 20))]

    def _fetch_manga_el(self, session, manga_id: str) -> Optional[ET.Element]:
        root = self._get_xml(session, {"manga": str(manga_id)})
        if root is None or root.find("warning") is not None:
            return None
        return root.find("manga")

    # ------------------------------------------------------------------ Build

    def _alt_titles(self, el: ET.Element) -> List[str]:
        alts: List[str] = []
        seen = set()
        for info in el.findall("info"):
            if info.attrib.get("type") != "Alternative title":
                continue
            t = _text(info)
            key = t.casefold()
            if t and key not in seen:
                seen.add(key)
                alts.append(t)
        return alts

    def _build_candidate(self, el: ET.Element) -> Optional[Dict[str, Any]]:
        title = (el.attrib.get("name") or "").strip()
        if not title:
            # Fallback Main title
            for info in el.findall("info"):
                if info.attrib.get("type") == "Main title":
                    title = _text(info)
                    break
        if not title:
            return None

        mid = el.attrib.get("id") or ""
        genres: List[str] = []
        tags: List[str] = []
        summary = ""
        cover = None
        vintages: List[str] = []
        age_raw = None
        seen_g: set = set()
        seen_t: set = set()

        for info in el.findall("info"):
            kind = info.attrib.get("type") or ""
            if kind == "Picture" and not cover:
                cover = _upgrade_cover(info.attrib.get("src"))
            elif kind == "Plot Summary":
                summary = _text(info) or summary
            elif kind == "Genres":
                g = _text(info)
                key = g.casefold()
                if g and key not in seen_g:
                    seen_g.add(key)
                    genres.append(g.title() if g.islower() else g)
            elif kind == "Themes":
                t = _text(info)
                key = t.casefold()
                if t and key not in seen_t and key not in seen_g:
                    seen_t.add(key)
                    tags.append(t.title() if t.islower() else t)
            elif kind == "Vintage":
                v = _text(info)
                if v:
                    vintages.append(v)
            elif kind == "Objectionable content":
                age_raw = _text(info) or age_raw

        staff: List[Dict[str, Any]] = []
        for st in el.findall("staff"):
            role = _text(st.find("task")) or "Story"
            person = _text(st.find("person"))
            if not person:
                continue
            # Normaliser Story/Art ANN → Kavita
            role_map = {
                "story": "Story",
                "art": "Art",
                "story & art": "Story & Art",
                "original creator": "Story",
            }
            role_out = role_map.get(role.casefold(), role)
            staff.append(
                {"role": role_out, "node": {"name": {"full": person}}}
            )

        year = _parse_year(" | ".join(vintages))
        alts = self._alt_titles(el)
        url = f"{_SITE}/encyclopedia/manga.php?id={mid}" if mid else None
        age = _map_age(age_raw)

        out: Dict[str, Any] = {
            "title": title,
            "alternative_titles": alts,
            "summary": summary,
            "cover_url": cover,
            "genres": genres[: get_max_genres()] if genres else ["Manga"],
            "tags": tags[: get_max_tags()],
            "year": year,
            "staff": staff,
            "format": "manga",
            "url": url,
            "links": [url] if url else [],
        }
        if age:
            out["age_rating"] = age
        # Pas de statut inventé (ANN n'expose pas ongoing/finished proprement)
        return out
