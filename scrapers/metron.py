"""Metron (metron.cloud) — métadonnées comics via API REST (auth requise)."""
from __future__ import annotations

import base64
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags, load_config
from scrapers.base import BaseScraper
from scrapers.utils import (
    attach_match_score,
    clean_title,
    extract_year_from_title,
    get_match_accept_threshold,
    score_candidate,
)

_API = "https://metron.cloud/api"
_SITE = "https://metron.cloud"

_STATUS_MAP = {
    "ongoing": "RELEASING",
    "completed": "FINISHED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "hiatus": "HIATUS",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    return _STATUS_MAP.get(raw.strip().lower())


def _generic_name(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        name = obj.get("name")
        return str(name).strip() if name else None
    return None


def _auth_header(api_key: str) -> Dict[str, str]:
    """Bearer token (recommandé) ou Basic si la clé est `user:password`."""
    key = api_key.strip()
    # user:password → Basic Auth (un seul ':')
    if key.count(":") == 1:
        user, _, password = key.partition(":")
        if user and password and " " not in user and len(user) < 80:
            token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {token}"}
    return {"Authorization": f"Bearer {key}"}


class MetronScraper(BaseScraper):
    id = "METRON"
    is_core = True
    display_name = "Metron (Comics API)"
    supported_types = {"Comic"}
    rate_limit = 3.0  # Burst API : 20 req/min
    proxy_domains = [
        "metron.cloud",
        "static.metron.cloud",
    ]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = True
    uses_unified_scoring = True

    translations = {
        "fr": {
            "err_missing": "❌ Clé Metron manquante. Compte sur metron.cloud → API Token (ou user:password) dans Config.",
            "direct_id": "🎯 [Metron] Requête série id={0}",
            "search": "🔍 [Metron] Recherche série pour '{0}'…",
            "no_match": "⚠️ [Metron] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [Metron] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [Metron] Erreur : {0}",
            "err_auth": "❌ [Metron] Auth refusée (401). Vérifiez METRON_API_KEY.",
            "covers_err": "❌ [Covers] Erreur Metron : {0}",
        },
        "en": {
            "err_missing": "❌ Metron key missing. Account on metron.cloud → API Token (or user:password) in Config.",
            "direct_id": "🎯 [Metron] Series request id={0}",
            "search": "🔍 [Metron] Series search for '{0}'…",
            "no_match": "⚠️ [Metron] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [Metron] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [Metron] Error: {0}",
            "err_auth": "❌ [Metron] Auth rejected (401). Check METRON_API_KEY.",
            "covers_err": "❌ [Covers] Metron error: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        url = url.strip()
        if url.isdigit():
            return url
        # https://metron.cloud/series/123/  (rare) ou …/series/slug-2018/
        m = re.search(r"metron\.cloud/series/(\d+)/?", url)
        if m:
            return m.group(1)
        # Slug seul : on renvoie l'URL pour résolution search côté fetch(is_id)
        if "metron.cloud/series/" in url:
            return url
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Comic",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        config = load_config()
        api_key = (config.get("METRON_API_KEY") or "").strip()
        if not api_key:
            logging.error(self.t("err_missing"))
            return None

        session = requests.Session()
        headers = {
            **_auth_header(api_key),
            "Accept": "application/json",
            "User-Agent": "MetaKavita-Metron/1.0",
        }

        try:
            if is_id:
                sid = self._resolve_series_id(session, headers, query)
                if sid is None:
                    return None
                logging.info(self.t("direct_id").format(sid))
                detail = self._get_json(session, headers, f"{_API}/series/{sid}/")
                if not detail:
                    return None
                cover = self._first_cover(session, headers, sid)
                candidate = self._build_candidate(detail, cover_url=cover)
                if candidate:
                    candidate["staff"] = self._staff_from_series(session, headers, sid)
                    return attach_match_score(candidate, 1.0)
                return None

            cleaned = clean_title(query, library_type=library_type)
            if not cleaned:
                return None

            year_hint = None
            if existing_metadata and existing_metadata.get("year") is not None:
                try:
                    year_hint = int(existing_metadata["year"])
                except (TypeError, ValueError):
                    year_hint = None
            if year_hint is None:
                year_hint = extract_year_from_title(query)

            logging.info(self.t("search").format(cleaned))
            params: Dict[str, Any] = {"name": cleaned}
            if year_hint:
                params["year_began"] = year_hint

            data = self._get_json(
                session, headers, f"{_API}/series/", params=params
            )
            results = (data or {}).get("results") or []

            # Repli sans year_began si trop restrictif
            if not results and year_hint:
                data = self._get_json(
                    session, headers, f"{_API}/series/", params={"name": cleaned}
                )
                results = (data or {}).get("results") or []

            if not results:
                return None

            # Pré-classement sur la liste (évite 8× detail + issue_list → 429 / faux max)
            ranked: List[Tuple[float, dict]] = []
            for hit in results:
                prelim = self._candidate_from_list_hit(hit)
                if not prelim:
                    continue
                score = score_candidate(prelim, cleaned, existing_metadata)
                if year_hint and prelim.get("year") == year_hint:
                    score = min(1.0, score + 0.08)
                # Bonus titre exact (ex. "Batman" vs "Absolute Batman")
                if (prelim.get("title") or "").casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.15)
                ranked.append((score, hit))
            ranked.sort(key=lambda x: x[0], reverse=True)

            best_match = None
            best_score = -1.0

            for prelim_score, hit in ranked[:3]:
                sid = hit.get("id")
                if not sid:
                    continue
                detail = self._get_json(session, headers, f"{_API}/series/{sid}/")
                if detail:
                    candidate = self._build_candidate(detail, cover_url=None)
                else:
                    candidate = self._candidate_from_list_hit(hit)
                if not candidate or not candidate.get("title"):
                    continue

                score = score_candidate(candidate, cleaned, existing_metadata)
                if year_hint and candidate.get("year") == year_hint:
                    score = min(1.0, score + 0.08)
                if (candidate.get("title") or "").casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.15)
                # Ne pas descendre sous le pré-score liste si detail pauvre
                score = max(score, prelim_score * 0.95)

                if score > best_score:
                    best_score = score
                    best_match = candidate
                    best_match["_series_id"] = int(sid)

            if not best_match or best_score < get_match_accept_threshold():
                logging.warning(
                    self.t("no_match").format(cleaned, int(max(best_score, 0) * 100))
                )
                return None

            # Cover + staff (crédits 1er issue) uniquement pour le gagnant
            sid = best_match.pop("_series_id", None)
            if sid:
                if not best_match.get("cover_url"):
                    best_match["cover_url"] = self._first_cover(session, headers, sid)
                if not best_match.get("staff"):
                    best_match["staff"] = self._staff_from_series(session, headers, sid)

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
        config = load_config()
        api_key = (config.get("METRON_API_KEY") or "").strip()
        if not api_key:
            return covers

        cleaned = clean_title(query, library_type=library_type)
        if not cleaned:
            return covers

        session = requests.Session()
        headers = {
            **_auth_header(api_key),
            "Accept": "application/json",
            "User-Agent": "MetaKavita-Metron/1.0",
        }
        try:
            data = self._get_json(
                session, headers, f"{_API}/series/", params={"name": cleaned}
            )
            for hit in (data or {}).get("results") or []:
                sid = hit.get("id")
                if not sid:
                    continue
                title = (
                    hit.get("series")
                    or hit.get("name")
                    or hit.get("display_name")
                    or cleaned
                )
                for url in self._issue_covers(session, headers, int(sid), limit=3):
                    if url not in [c["url"] for c in covers]:
                        covers.append(
                            {
                                "provider": self.display_name,
                                "title": title,
                                "url": url,
                            }
                        )
                    if len(covers) >= 5:
                        return covers
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        finally:
            try:
                session.close()
            except Exception:
                pass
        return covers

    # ------------------------------------------------------------------ HTTP

    def _get_json(
        self,
        session,
        headers: Dict[str, str],
        url: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        res = session.get(
            url,
            params=params,
            headers=headers,
            impersonate="chrome",
            timeout=20,
        )
        if res.status_code == 401:
            logging.error(self.t("err_auth"))
            return None
        if res.status_code == 404:
            return None
        if res.status_code != 200:
            return None
        try:
            data = res.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _resolve_series_id(
        self, session, headers: Dict[str, str], query: str
    ) -> Optional[int]:
        q = (query or "").strip()
        if q.isdigit():
            return int(q)
        extracted = self.extract_id_from_url(q)
        if extracted and extracted.isdigit():
            return int(extracted)
        # Slug URL → search by name dérivé
        slug_m = re.search(r"metron\.cloud/series/([^/?#]+)/?", q)
        if slug_m:
            slug = slug_m.group(1)
            # death-of-the-inhumans-2018 → name + year
            year = None
            ym = re.search(r"-(\d{4})$", slug)
            if ym:
                year = int(ym.group(1))
                slug = slug[: ym.start()]
            name = slug.replace("-", " ").strip()
            params: Dict[str, Any] = {"name": name}
            if year:
                params["year_began"] = year
            data = self._get_json(
                session, headers, f"{_API}/series/", params=params
            )
            results = (data or {}).get("results") or []
            if results and results[0].get("id"):
                return int(results[0]["id"])
        return None

    def _first_cover(
        self, session, headers: Dict[str, str], series_id: int
    ) -> Optional[str]:
        urls = self._issue_covers(session, headers, series_id, limit=1)
        return urls[0] if urls else None

    def _issue_list(
        self, session, headers: Dict[str, str], series_id: int
    ) -> List[dict]:
        data = self._get_json(
            session, headers, f"{_API}/series/{series_id}/issue_list/"
        )
        results = (data or {}).get("results") or []
        return results if isinstance(results, list) else []

    def _issue_covers(
        self,
        session,
        headers: Dict[str, str],
        series_id: int,
        *,
        limit: int = 5,
    ) -> List[str]:
        urls: List[str] = []
        for issue in self._issue_list(session, headers, series_id):
            img = issue.get("image")
            if img:
                urls.append(str(img))
            if len(urls) >= limit:
                break
        return urls

    def _staff_from_series(
        self, session, headers: Dict[str, str], series_id: int
    ) -> List[Dict[str, Any]]:
        """Metron n'expose pas les creators au niveau série — crédits du 1er issue."""
        issues = self._issue_list(session, headers, series_id)
        if not issues:
            return []
        issue_id = issues[0].get("id")
        if not issue_id:
            return []
        detail = self._get_json(session, headers, f"{_API}/issue/{issue_id}/")
        credits = (detail or {}).get("credits") or []
        if not isinstance(credits, list):
            return []

        role_map = {
            "writer": "Story",
            "artist": "Art",
            "penciller": "Art",
            "inker": "Art",
            "colorist": "Color",
            "letterer": "Lettering",
            "cover": "Cover",
            "editor": "Editor",
        }
        priority = {
            "Story": 0,
            "Art": 1,
            "Cover": 2,
            "Color": 3,
            "Lettering": 4,
            "Editor": 5,
        }
        staff: List[Dict[str, Any]] = []
        seen: set = set()
        ranked: List[Tuple[int, str, str]] = []
        for cred in credits:
            if not isinstance(cred, dict):
                continue
            name = (cred.get("creator") or "").strip()
            if not name:
                continue
            roles_raw = cred.get("role") or []
            role_names = []
            if isinstance(roles_raw, list):
                for r in roles_raw:
                    if isinstance(r, dict) and r.get("name"):
                        role_names.append(str(r["name"]))
                    elif isinstance(r, str):
                        role_names.append(r)
            mapped = "Story"
            for rn in role_names:
                key = rn.strip().lower()
                if key in role_map:
                    mapped = role_map[key]
                    break
                if "writer" in key:
                    mapped = "Story"
                    break
                if "artist" in key or "penciller" in key:
                    mapped = "Art"
                    break
            ranked.append((priority.get(mapped, 9), mapped, name))

        ranked.sort(key=lambda x: (x[0], x[2].casefold()))
        for _, role, name in ranked:
            key = (role, name.casefold())
            if key in seen:
                continue
            seen.add(key)
            staff.append({"role": role, "node": {"name": {"full": name}}})
            if len(staff) >= 6:
                break
        return staff

    # ------------------------------------------------------------------ Build

    def _candidate_from_list_hit(self, hit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        title = (
            hit.get("series")
            or hit.get("name")
            or hit.get("display_name")
            or ""
        )
        title = re.sub(r"\s*\(\d{4}\)\s*$", "", str(title)).strip()
        if not title:
            return None
        year = hit.get("year_began")
        sid = hit.get("id")
        url = f"{_SITE}/series/{sid}/" if sid else None
        return {
            "title": title,
            "alternative_titles": [],
            "summary": "",
            "cover_url": None,
            "genres": ["Comic"],
            "tags": [],
            "year": year if isinstance(year, int) else None,
            "staff": [],
            "publisher": None,
            "format": "comic",
            "url": url,
            "links": [url] if url else [],
        }

    def _build_candidate(
        self, detail: Dict[str, Any], *, cover_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        title = (detail.get("name") or "").strip()
        if not title:
            return None

        alt = []
        sort_name = (detail.get("sort_name") or "").strip()
        if sort_name and sort_name.casefold() != title.casefold():
            alt.append(sort_name)
        for a in detail.get("alt_names") or []:
            if isinstance(a, str) and a.strip() and a.strip().casefold() != title.casefold():
                if a.strip() not in alt:
                    alt.append(a.strip())

        genres = []
        for g in detail.get("genres") or []:
            name = _generic_name(g)
            if name:
                genres.append(name)

        tags = []
        series_type = _generic_name(detail.get("series_type"))
        if series_type:
            tags.append(series_type)
        imprint = _generic_name(detail.get("imprint"))
        if imprint:
            tags.append(imprint)

        publisher = _generic_name(detail.get("publisher"))
        year = detail.get("year_began")
        if not isinstance(year, int):
            year = None

        status = _map_status(detail.get("status"))

        sid = detail.get("id")
        resource = detail.get("resource_url")
        url = str(resource) if resource else (
            f"{_SITE}/series/{sid}/" if sid else None
        )

        summary = (detail.get("desc") or "").strip()
        # Strip HTML basique si présent
        if summary and "<" in summary:
            summary = re.sub(r"<[^>]+>", " ", summary)
            summary = re.sub(r"\s+", " ", summary).strip()

        candidate: Dict[str, Any] = {
            "title": title,
            "alternative_titles": alt,
            "summary": summary,
            "cover_url": cover_url,
            "genres": genres[: get_max_genres()] if genres else ["Comic"],
            "tags": tags[: get_max_tags()],
            "year": year,
            "staff": [],
            "publisher": publisher,
            # BF56 : pas d'âge série-level Metron
            "format": "comic",
            "url": url,
            "links": [url] if url else [],
        }
        if status:
            candidate["status"] = status
        return candidate
