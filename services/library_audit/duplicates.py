"""Cluster likely duplicate series (score_candidate matrix + relation markers)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from scrapers.utils import (
    extract_distinctive_words,
    extract_year_from_title,
    find_title_relation_markers,
    get_dup_accept_threshold,
    normalize_str,
    relation_title_penalty,
    score_candidate,
)

from .series_identity import (
    build_score_candidate_from_identity,
    merge_series_identity,
)


def dup_group_key(series_ids: List[int]) -> str:
    """Stable key for a duplicate group (sorted ids)."""
    parts = ",".join(str(int(x)) for x in sorted({int(i) for i in series_ids}))
    return hashlib.sha1(parts.encode("utf-8")).hexdigest()


def _identity_as_existing_metadata(identity: dict) -> dict:
    authors = []
    for s in identity.get("staff") or []:
        if isinstance(s, dict):
            name = ((s.get("node") or {}).get("name") or {}).get("full") or ""
            if name:
                authors.append(name)
    return {
        "isbn": identity.get("isbn") or "",
        "localized_name": identity.get("localizedName") or "",
        "authors": authors,
        "publisher": identity.get("publisher") or "",
        "year": identity.get("year"),
        "genres": identity.get("genres") or [],
    }


def _as_identity(series: dict) -> dict:
    if series.get("ids") is not None and series.get("name") is not None and "raw_series" in series:
        return series
    meta = series.get("raw_metadata") if isinstance(series.get("raw_metadata"), dict) else {}
    if not meta and isinstance(series.get("metadata"), dict):
        meta = series["metadata"]
    return merge_series_identity(
        series.get("raw_series") if isinstance(series.get("raw_series"), dict) else series,
        meta,
        series_name=series.get("name") or "",
        library_type=series.get("libraryType") or "Manga",
    )


def score_duplicate_pair(a: dict, b: dict) -> Dict[str, Any]:
    """
    Score two series identities for dedup.
    Returns {score: float, reasons: list[str]}.
    """
    ia = _as_identity(a)
    ib = _as_identity(b)
    reasons: List[str] = []

    ids_a = ia.get("ids") or {}
    ids_b = ib.get("ids") or {}
    # Un identifiant partagé tranche, mais l'égalité passe avant la différence, et
    # l'ordre des fournisseurs est fixé : deux séries portant le même id AniList et
    # des id MAL divergents (un des deux mal renseigné) basculaient d'un verdict à
    # l'autre d'une analyse à la suivante, au gré de l'itération sur un `set`.
    same, different = [], []
    for prov in sorted(set(ids_a) & set(ids_b)):
        if not (ids_a[prov] and ids_b[prov]):
            continue
        (same if str(ids_a[prov]) == str(ids_b[prov]) else different).append(prov)
    if same:
        return {"score": 1.0, "reasons": [f"same_{same[0]}_id"]}
    if different:
        return {"score": 0.0, "reasons": [f"different_{different[0]}_id"]}

    def _isbn(x: Any) -> str:
        return "".join(c for c in str(x or "") if c.isdigit())

    ia_isbn, ib_isbn = _isbn(ia.get("isbn")), _isbn(ib.get("isbn"))
    if ia_isbn and ib_isbn and ia_isbn == ib_isbn and len(ia_isbn) >= 10:
        return {"score": 1.0, "reasons": ["same_isbn"]}

    ya = extract_year_from_title(ia.get("name") or "")
    yb = extract_year_from_title(ib.get("name") or "")
    if ya and yb and ya != yb:
        return {"score": 0.0, "reasons": ["different_comic_year"]}

    cand_a = build_score_candidate_from_identity(ia)
    cand_b = build_score_candidate_from_identity(ib)
    meta_a = _identity_as_existing_metadata(ia)
    meta_b = _identity_as_existing_metadata(ib)
    s_ab = score_candidate(cand_b, ia.get("name") or "", meta_a)
    s_ba = score_candidate(cand_a, ib.get("name") or "", meta_b)
    base = min(s_ab, s_ba)
    reasons.append("score_candidate")

    ma = find_title_relation_markers(normalize_str(ia.get("name") or ""))
    mb = find_title_relation_markers(normalize_str(ib.get("name") or ""))
    penalty, rel_reasons = relation_title_penalty(ma, mb)
    score = max(0.0, min(1.0, base - penalty))
    reasons.extend(rel_reasons)

    # Artbook / guidebook noise: if only one side has noise keyword in title, kill
    from scrapers.utils import NOISE_KEYWORDS

    na = normalize_str(ia.get("name") or "")
    nb = normalize_str(ib.get("name") or "")
    noise_a = any(kw in na for kw in NOISE_KEYWORDS)
    noise_b = any(kw in nb for kw in NOISE_KEYWORDS)
    if noise_a != noise_b:
        score = max(0.0, score - 0.50)
        reasons.append("noise_keyword")

    return {"score": round(score, 4), "reasons": reasons}


def _bucket_key(name: str) -> str:
    words = sorted(extract_distinctive_words(name or ""))
    return words[0] if words else (normalize_str(name or "")[:8] or "_")


def cluster_duplicate_series(
    series_list: List[dict],
    *,
    threshold: Optional[float] = None,
    title_threshold: Optional[float] = None,  # legacy alias
    library_id: Optional[Any] = None,
    exclude_keys: Optional[Set[str]] = None,
    config: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """
    Return groups of likely duplicates.

    Each group: { group_id, group_key, series_ids, names, score, reasons[] }
    """
    if threshold is None:
        threshold = title_threshold if title_threshold is not None else get_dup_accept_threshold(config)
    exclude_keys = exclude_keys or set()

    items = []
    for s in series_list or []:
        if not isinstance(s, dict) or s.get("id") is None:
            continue
        if library_id is not None and str(s.get("libraryId")) != str(library_id):
            continue
        identity = _as_identity(s)
        identity["id"] = int(s["id"])
        if s.get("libraryId") is not None:
            identity["libraryId"] = s.get("libraryId")
        items.append(identity)

    n = len(items)
    if n > 2000:
        logging.warning(
            "[Inventaire] duplicate cluster n=%s > 2000 — buckets forcés", n
        )

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    edge_meta: Dict[Tuple[int, int], Tuple[float, List[str]]] = {}

    # Bucket by first distinctive word (always when n large; also used to cut pairs)
    buckets: Dict[str, List[int]] = {}
    for i, it in enumerate(items):
        buckets.setdefault(_bucket_key(it.get("name") or ""), []).append(i)

    # Also union hard same-id across buckets
    by_ext: Dict[Tuple[str, str], List[int]] = {}
    for i, it in enumerate(items):
        for prov, pid in (it.get("ids") or {}).items():
            if pid:
                by_ext.setdefault((prov, str(pid)), []).append(i)
    for idxs in by_ext.values():
        if len(idxs) < 2:
            continue
        for a in idxs[1:]:
            union(idxs[0], a)
            key = (min(idxs[0], a), max(idxs[0], a))
            edge_meta[key] = (1.0, ["same_external_id"])

    pair_iters: List[Tuple[int, int]] = []
    for idxs in buckets.values():
        if len(idxs) < 2:
            continue
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                pair_iters.append((idxs[ii], idxs[jj]))

    # If small library, also compare across buckets for near-identical titles
    if n <= 2000:
        # Extra: pairs already covered in same bucket; skip cross-bucket unless
        # identical normalized short names — handled via score in-bucket only for perf.
        pass

    for i, j in pair_iters:
        result = score_duplicate_pair(items[i], items[j])
        score = float(result["score"])
        if score < threshold:
            continue
        union(i, j)
        key = (min(i, j), max(i, j))
        prev = edge_meta.get(key)
        if not prev or score > prev[0]:
            edge_meta[key] = (score, list(result.get("reasons") or []))

    groups_map: Dict[int, List[int]] = {}
    for i in range(n):
        groups_map.setdefault(find(i), []).append(i)

    groups: List[Dict[str, Any]] = []
    gid = 0
    for members in groups_map.values():
        if len(members) < 2:
            continue
        best = 0.0
        reasons: Set[str] = set()
        for a_i, a in enumerate(members):
            for b in members[a_i + 1 :]:
                key = (min(a, b), max(a, b))
                meta = edge_meta.get(key)
                if meta:
                    best = max(best, meta[0])
                    reasons.update(meta[1])
        if best <= 0 and not reasons:
            best = 1.0
            reasons.add("same_external_id")
        series_ids = [int(items[i]["id"]) for i in members]
        gkey = dup_group_key(series_ids)
        if gkey in exclude_keys:
            continue
        gid += 1
        groups.append(
            {
                "group_id": f"dup-{gid}",
                "group_key": gkey,
                "series_ids": series_ids,
                "names": [items[i].get("name") or "" for i in members],
                "score": round(best, 3),
                "reasons": sorted(reasons),
            }
        )

    groups.sort(key=lambda g: (-g["score"], -len(g["series_ids"])))
    return groups
