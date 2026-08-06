"""
Cover search orchestration with Magic Input awareness.

Import rules (acyclic): magic_input, ScraperRegistry, library_type_for_scraper.
Must NOT import enrichment_engine, metadata_fetcher, routes, sockets, or app.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from scrapers import ScraperRegistry
from scrapers.utils import library_type_for_scraper
from services.magic_input import is_http_url, resolve_magic_cover_query
from secure_logging import safe_exc_str


@dataclass(frozen=True)
class CoverJob:
    scraper: Any
    mode: str  # "by_id" | "by_title"
    query: str
    library_type: str
    priority: int  # lower = earlier (resolved by_id = 0)


def _provider_label(scraper: Any) -> str:
    return getattr(scraper, "localized_display_name", None) or getattr(
        scraper, "display_name", None
    ) or getattr(scraper, "id", "unknown")


def apply_display_urls(
    covers: Sequence[Dict[str, str]],
    scraper: Any,
    script_root: str = "",
) -> List[Dict[str, str]]:
    """Attach display_url (proxy when requires_proxy). Mutates copies."""
    root = script_root or ""
    out: List[Dict[str, str]] = []
    for c in covers:
        if not isinstance(c, dict) or not c.get("url"):
            continue
        item = dict(c)
        if getattr(scraper, "requires_proxy", False):
            item["display_url"] = f"{root}/api/proxy-image?url={quote(item['url'])}"
        else:
            item["display_url"] = item["url"]
        out.append(item)
    return out


def cover_dict_from_fetch(
    scraper: Any,
    id_query: str,
    library_type: str,
) -> List[Dict[str, str]]:
    """fetch(is_id=True) → 0..1 cover dicts with provider/title/url."""
    try:
        data = scraper.fetch(
            id_query,
            library_type=library_type,
            is_id=True,
            existing_metadata=None,
        )
    except Exception as exc:
        logging.error(
            "[Covers Magic] fetch(is_id) failed on %s: %s",
            getattr(scraper, "id", "?"),
            safe_exc_str(exc),
        )
        return []
    if not isinstance(data, dict):
        return []
    url = (data.get("cover_url") or "").strip()
    if not url:
        return []
    title = (
        data.get("title")
        or data.get("localized_title")
        or getattr(scraper, "id", "cover")
    )
    return [
        {
            "provider": _provider_label(scraper),
            "title": str(title),
            "url": url,
        }
    ]


def iter_cover_jobs(
    cache_data: Optional[Dict[str, Any]],
    series_name: str,
    library_type: str,
) -> List[CoverJob]:
    """
    One job per scraper of library_type: by_id XOR by_title.

    Never schedules fetch_covers with an http(s) URL.
    """
    magic = resolve_magic_cover_query(cache_data, series_name)
    target = ScraperRegistry.get_by_type(library_type) or ScraperRegistry.get_by_type(
        "Manga"
    )
    if not target:
        return []

    jobs: List[CoverJob] = []
    title_q = (magic.title_query or "").strip()

    for scraper in target:
        fetch_lt = library_type_for_scraper(scraper, library_type)
        use_by_id = False
        id_q: Optional[str] = None
        priority = 10

        if magic.magic_active and magic.id_query:
            if (
                magic.resolved_provider
                and scraper.id == magic.resolved_provider
            ):
                use_by_id = True
                id_q = magic.id_query
                priority = 0
            elif magic.raw_id_auto and getattr(
                scraper, "has_direct_id_support", False
            ):
                use_by_id = True
                id_q = magic.id_query
                priority = 5

        # by_id accepts numeric/slug ids OR full URL-as-id (Manga-News / Bedetheque).
        # Never fall through to by_title with an http(s) magic string.
        if use_by_id and id_q:
            jobs.append(
                CoverJob(
                    scraper=scraper,
                    mode="by_id",
                    query=id_q,
                    library_type=fetch_lt,
                    priority=priority,
                )
            )
            continue

        if not title_q or is_http_url(title_q):
            continue
        jobs.append(
            CoverJob(
                scraper=scraper,
                mode="by_title",
                query=title_q,
                library_type=fetch_lt,
                priority=priority,
            )
        )

    jobs.sort(key=lambda j: (j.priority, getattr(j.scraper, "id", "")))
    return jobs


def run_cover_job(
    job: CoverJob,
    script_root: str = "",
) -> List[Dict[str, str]]:
    """Execute one cover job; never raises."""
    scraper = job.scraper
    try:
        if job.mode == "by_id":
            covers = cover_dict_from_fetch(scraper, job.query, job.library_type)
        else:
            if is_http_url(job.query):
                logging.warning(
                    "[Covers Magic] refused fetch_covers with URL on %s",
                    getattr(scraper, "id", "?"),
                )
                return []
            covers = scraper.fetch_covers(job.query, library_type=job.library_type) or []
        if not covers:
            return []
        return apply_display_urls(covers, scraper, script_root=script_root)
    except Exception as exc:
        logging.error(
            "[Covers] Error on scraper %s: %s",
            getattr(scraper, "id", "?"),
            safe_exc_str(exc),
        )
        return []


def collect_covers_http(
    cache_data: Optional[Dict[str, Any]],
    series_name: str,
    library_type: str,
    script_root: str = "",
    *,
    max_covers: int = 20,
    max_workers: int = 8,
) -> List[Dict[str, str]]:
    """Parallel cover collect for HTTP endpoint; Magic by_id results prefixed."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = iter_cover_jobs(cache_data, series_name, library_type)
    if not jobs:
        return []

    by_id_first: List[Dict[str, str]] = []
    others: List[Dict[str, str]] = []

    def _run(job: CoverJob):
        return job, run_cover_job(job, script_root=script_root)

    workers = min(len(jobs), max_workers) if jobs else 1
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
        futures = [executor.submit(_run, j) for j in jobs]
        for fut in as_completed(futures):
            job, covers = fut.result()
            if not covers:
                continue
            if job.mode == "by_id" and job.priority == 0:
                by_id_first.extend(covers)
            else:
                others.extend(covers)

    return (by_id_first + others)[:max_covers]


__all__ = [
    "CoverJob",
    "apply_display_urls",
    "collect_covers_http",
    "cover_dict_from_fetch",
    "iter_cover_jobs",
    "run_cover_job",
]
