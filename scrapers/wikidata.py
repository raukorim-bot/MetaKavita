"""
Scraper Wikidata (live SPARQL / Entity API).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

from .base import BaseScraper
from .utils import clean_title, score_candidate, get_match_accept_threshold, attach_match_score
from .wikidata_map import (
    TYPE_QIDS,
    entity_matches_library_type,
    entity_to_candidate,
    normalize_qid,
    _entity_ids_from_claims,
    P_AUTHOR,
    P_ILLUSTRATOR,
    P_CREATOR,
    P_PUBLISHER,
)

USER_AGENT = "MetaKavita/1.6 (https://github.com/raukorim/kavitafetcher; self-hosted metadata)"
WD_API = "https://www.wikidata.org/w/api.php"
ENTITY_DATA = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
SPARQL_URL = "https://query.wikidata.org/sparql"


class WikidataScraper(BaseScraper):
    id = "WIKIDATA"
    display_name = "Wikidata"
    supported_types = {"Manga", "Comic", "Book"}
    rate_limit = 1.2
    proxy_domains = [
        "wikidata.org",
        "www.wikidata.org",
        "commons.wikimedia.org",
        "upload.wikimedia.org",
    ]
    has_direct_id_support = True
    uses_unified_scoring = True
    needs_api_key = False

    translations = {
        "fr": {
            "req_id": "[Wikidata] Requête directe : {0}",
            "search_title": "[Wikidata] Recherche ({0}) : '{1}'",
            "err": "[Erreur Wikidata] {0}",
            "covers_err": "[Covers] Erreur Wikidata : {0}",
        },
        "en": {
            "req_id": "[Wikidata] Direct request: {0}",
            "search_title": "[Wikidata] Search ({0}): '{1}'",
            "err": "[Wikidata Error] {0}",
            "covers_err": "[Covers] Wikidata error: {0}",
        },
    }

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._last_call = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        wait = self.rate_limit - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        text = str(url).strip()
        qid = normalize_qid(text)
        if qid and ("wikidata.org" in text.lower() or re.fullmatch(r"Q\d+", text, flags=re.I)):
            return qid
        if "wikidata.org" in text.lower():
            return normalize_qid(text)
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Manga",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        qid = None
        if is_id:
            qid = normalize_qid(query) or self.extract_id_from_url(query)
        else:
            qid = self.extract_id_from_url(query)

        try:
            if qid:
                logging.info(self.t("req_id").format(qid))
                candidate = self._fetch_entity_live(qid, library_type)
                if candidate:
                    return attach_match_score(candidate, 1.0)
                return None

            clean = clean_title(query, library_type=library_type)
            logging.info(self.t("search_title").format(library_type, clean))
            return self._search_live(clean, library_type, existing_metadata)
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None

    def _get_json(self, url: str, params: Optional[dict] = None, timeout: int = 25) -> Optional[dict]:
        self._throttle()
        resp = self._session.get(url, params=params, timeout=timeout)
        if resp.status_code != 200:
            logging.warning("[Wikidata] HTTP %s for %s", resp.status_code, url)
            return None
        return resp.json()

    def _wbgetentities(self, qids: List[str]) -> Dict[str, dict]:
        if not qids:
            return {}
        out: Dict[str, dict] = {}
        for i in range(0, len(qids), 40):
            chunk = qids[i : i + 40]
            data = self._get_json(
                WD_API,
                {
                    "action": "wbgetentities",
                    "format": "json",
                    "ids": "|".join(chunk),
                    "props": "labels|descriptions|aliases|claims",
                    "languages": "en|fr|ja|de|es|it|ko|zh",
                    "languagefallback": 1,
                },
            )
            if data and data.get("entities"):
                out.update(data["entities"])
        return out

    def _label_lookup(self, qids: List[str]) -> Dict[str, str]:
        entities = self._wbgetentities(qids)
        lookup = {}
        for qid, ent in entities.items():
            labels = (ent.get("labels") or {})
            for lang in ("en", "fr", "ja"):
                blob = labels.get(lang)
                if isinstance(blob, dict) and blob.get("value"):
                    lookup[qid] = blob["value"]
                    break
            else:
                for blob in labels.values():
                    if isinstance(blob, dict) and blob.get("value"):
                        lookup[qid] = blob["value"]
                        break
        return lookup

    def _related_qids(self, entity: dict) -> List[str]:
        related = []
        for prop in (P_AUTHOR, P_ILLUSTRATOR, P_CREATOR, P_PUBLISHER):
            related.extend(_entity_ids_from_claims(entity, prop))
        seen = set()
        out = []
        for q in related:
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out

    def _fetch_entity_live(self, qid: str, library_type: str) -> Optional[Dict[str, Any]]:
        entities = self._wbgetentities([qid])
        entity = entities.get(qid)
        if not entity or entity.get("missing") is not None:
            data = self._get_json(ENTITY_DATA.format(qid=qid))
            if data and data.get("entities"):
                entity = data["entities"].get(qid)
        if not entity:
            return None
        lookup = self._label_lookup(self._related_qids(entity))
        return entity_to_candidate(entity, label_lookup=lookup, library_type=library_type)

    def _search_live(
        self,
        clean: str,
        library_type: str,
        existing_metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        search_data = self._get_json(
            WD_API,
            {
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "uselang": "en",
                "type": "item",
                "search": clean,
                "limit": 12,
            },
        )
        search_hits = (search_data or {}).get("search") or []
        qids = [h.get("id") for h in search_hits if h.get("id")]

        if len(qids) < 5:
            sparql_qids = self._sparql_search(clean, library_type, limit=10)
            for q in sparql_qids:
                if q not in qids:
                    qids.append(q)

        if not qids:
            return None

        entities = self._wbgetentities(qids[:15])
        related = []
        for ent in entities.values():
            related.extend(self._related_qids(ent))
        lookup = self._label_lookup(related[:80])

        best = None
        best_score = -1.0
        for qid in qids:
            ent = entities.get(qid)
            if not ent or ent.get("missing") is not None:
                continue
            inst = (ent.get("claims") or {}).get("P31")
            if inst and not entity_matches_library_type(ent, library_type):
                continue
            cand = entity_to_candidate(ent, label_lookup=lookup, library_type=library_type)
            if not cand:
                continue
            score = score_candidate(cand, clean, existing_metadata)
            if score > best_score:
                best_score = score
                best = cand

        if best and best_score >= get_match_accept_threshold():
            return attach_match_score(best, best_score)
        return None

    def _type_values_sparql(self, library_type: str) -> str:
        qids = set()
        if library_type == "ComicFlexible":
            qids |= TYPE_QIDS["Comic"] | TYPE_QIDS["Manga"]
        else:
            qids |= TYPE_QIDS.get(library_type, TYPE_QIDS["Manga"])
        return " ".join(f"wd:{q}" for q in sorted(qids))

    def _sparql_search(self, title: str, library_type: str, limit: int = 10) -> List[str]:
        safe = title.replace("\\", "\\\\").replace('"', '\\"')
        types = self._type_values_sparql(library_type)
        query = f"""
        SELECT DISTINCT ?item WHERE {{
          SERVICE wikibase:mwapi {{
            bd:serviceParam wikibase:api "EntitySearch" .
            bd:serviceParam wikibase:endpoint "www.wikidata.org" .
            bd:serviceParam mwapi:search "{safe}" .
            bd:serviceParam mwapi:language "en" .
            bd:serviceParam mwapi:limit "12" .
            ?item wikibase:apiOutputItem mwapi:item .
          }}
          ?item wdt:P31/wdt:P279* ?type .
          VALUES ?type {{ {types} }}
        }}
        LIMIT {int(limit)}
        """
        try:
            self._throttle()
            resp = self._session.get(
                SPARQL_URL,
                params={"format": "json", "query": query},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=40,
            )
            if resp.status_code != 200:
                return []
            bindings = resp.json().get("results", {}).get("bindings", [])
            out = []
            for b in bindings:
                uri = (b.get("item") or {}).get("value") or ""
                qid = normalize_qid(uri.split("/")[-1] if uri else "")
                if qid:
                    out.append(qid)
            return out
        except Exception as e:
            logging.warning("[Wikidata] SPARQL search failed: %s", e)
            return []

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        covers = []
        try:
            data = self.fetch(query, library_type=library_type, is_id=False)
            if data and data.get("cover_url"):
                covers.append(
                    {
                        "provider": "Wikidata",
                        "title": data.get("title") or "Unknown",
                        "url": data["cover_url"],
                    }
                )
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        return covers
