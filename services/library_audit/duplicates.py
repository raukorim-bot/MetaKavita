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

from services.cooperative import yield_to_worker

from .series_identity import (
    build_score_candidate_from_identity,
    merge_series_identity,
    series_folder_path,
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
        if series.get("folder_path"):
            return series
        filled = dict(series)
        filled["folder_path"] = series_folder_path(series)
        return filled
    meta = series.get("raw_metadata") if isinstance(series.get("raw_metadata"), dict) else {}
    if not meta and isinstance(series.get("metadata"), dict):
        meta = series["metadata"]
    return merge_series_identity(
        series.get("raw_series") if isinstance(series.get("raw_series"), dict) else series,
        meta,
        series_name=series.get("name") or "",
        library_type=series.get("libraryType") or "Manga",
    )


def _isbn_digits(raw: Any) -> str:
    return "".join(c for c in str(raw or "") if c.isdigit())


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

    ia_isbn, ib_isbn = _isbn_digits(ia.get("isbn")), _isbn_digits(ib.get("isbn"))
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


def _word_set_key(name: str) -> str:
    """Seau formé sur **tous** les mots distinctifs, et non sur le premier.

    Le seau au premier mot redevenait quadratique dès qu'une partie de la
    bibliothèque le partageait — une collection, un éditeur, un univers étendu.
    Mesuré sous eventlet : 33,5 s pour 1 500 séries dont la moitié partagent
    leur premier mot, 152,8 s quand toutes le partagent, sans un seul point de
    bascule pendant lequel l'application aurait pu répondre.

    Au seuil par défaut, resserrer la clé ne perd aucune paire : `score_candidate`
    retire 0,35 dès qu'un mot-clé majeur manque d'un côté, et le meilleur bonus
    qu'il puisse rendre vaut 0,25. Deux titres dont les mots distinctifs
    diffèrent plafonnent donc à 0,90 — en dessous du seuil de 0,92 — et le
    verdict `min(s_ab, s_ba)` suffit à ce qu'il tienne dans les deux sens. La
    règle d'or de `score_candidate` (ISBN identique) est le seul chemin qui
    l'ignore : ces paires-là sont réunies par leur propre seau.
    """
    words = sorted(extract_distinctive_words(name or ""))
    return " ".join(words) if words else (normalize_str(name or "")[:8] or "_")


#: En dessous de ce seuil, la démonstration ci-dessus ne tient plus : on
#: retombe sur le seau large du premier mot, dont l'utilisateur a explicitement
#: demandé la largeur en abaissant son seuil.
WORD_SET_KEY_MIN_THRESHOLD = 0.90

#: Paires examinées entre deux points de bascule. Assez pour que le coût du
#: `sleep(0)` reste invisible, assez peu pour qu'une requête HTTP n'attende
#: jamais plus de quelques millisecondes.
_YIELD_EVERY_PAIRS = 2_000


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
        if s.get("volume_count") is not None:
            identity["volume_count"] = s.get("volume_count")
        if s.get("chapter_count") is not None:
            identity["chapter_count"] = s.get("chapter_count")
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

    # Seau de comparaison : l'ensemble des mots distinctifs au seuil par défaut
    # (voir `_word_set_key`), le premier mot seulement quand l'utilisateur a
    # abaissé son seuil sous 0,90.
    strict = float(threshold) > WORD_SET_KEY_MIN_THRESHOLD
    key_of = _word_set_key if strict else _bucket_key
    buckets: Dict[str, List[int]] = {}
    for i, it in enumerate(items):
        buckets.setdefault(key_of(it.get("name") or ""), []).append(i)

    if strict:
        # Un ISBN partagé vaut identité quels que soient les titres : c'est la
        # règle d'or de `score_candidate`, et le seul verdict que les mots
        # distinctifs ne bornent pas. Ces paires-là ont donc leur propre seau.
        for i, it in enumerate(items):
            digits = _isbn_digits(it.get("isbn"))
            if digits:
                buckets.setdefault(f"isbn:{digits}", []).append(i)

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

    examined = 0
    for idxs in buckets.values():
        if len(idxs) < 2:
            continue
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                i, j = idxs[ii], idxs[jj]
                examined += 1
                if examined % _YIELD_EVERY_PAIRS == 0:
                    # Calcul pur : sans ce point de bascule, l'application
                    # entière est muette jusqu'à la fin du regroupement, à la
                    # fin de chaque scan.
                    yield_to_worker()
                if find(i) == find(j):
                    # Déjà réunies par une autre paire : les comparer ne peut
                    # plus rien changer au regroupement, et c'est exactement ce
                    # que payait le pire cas — 1,1 million de comparaisons pour
                    # un seul groupe. Le score affiché est alors celui du lien
                    # qui les a réunies, pas le meilleur du groupe.
                    continue
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

    # Le meilleur lien de chaque groupe, lu une fois par arête plutôt qu'une
    # fois par paire de membres : un groupe de 1 500 séries faisait à lui seul
    # un million de recherches dans `edge_meta`.
    best_by_root: Dict[int, float] = {}
    reasons_by_root: Dict[int, Set[str]] = {}
    for (a, _b), (score, edge_reasons) in edge_meta.items():
        root = find(a)
        if score > best_by_root.get(root, 0.0):
            best_by_root[root] = score
        reasons_by_root.setdefault(root, set()).update(edge_reasons)

    groups: List[Dict[str, Any]] = []
    gid = 0
    for root, members in groups_map.items():
        if len(members) < 2:
            continue
        best = best_by_root.get(root, 0.0)
        reasons: Set[str] = set(reasons_by_root.get(root) or ())
        if best <= 0 and not reasons:
            best = 1.0
            reasons.add("same_external_id")
        series_ids = [int(items[i]["id"]) for i in members]
        gkey = dup_group_key(series_ids)
        if gkey in exclude_keys:
            continue
        gid += 1
        volume_counts = [int(items[i].get("volume_count") or 0) for i in members]
        chapter_counts = [int(items[i].get("chapter_count") or 0) for i in members]

        best_idx = 0
        best_vol_score = (-1, -1)
        for idx, i in enumerate(members):
            score_tuple = (int(items[i].get("volume_count") or 0), int(items[i].get("chapter_count") or 0))
            if score_tuple > best_vol_score:
                best_vol_score = score_tuple
                best_idx = idx
        recommended_keep_id = series_ids[best_idx] if series_ids else None

        groups.append(
            {
                "group_id": f"dup-{gid}",
                "group_key": gkey,
                "series_ids": series_ids,
                "names": [items[i].get("name") or "" for i in members],
                "folder_paths": [items[i].get("folder_path") or "" for i in members],
                "library_ids": [items[i].get("libraryId") for i in members],
                "volume_counts": volume_counts,
                "chapter_counts": chapter_counts,
                "recommended_keep_id": recommended_keep_id,
                "score": round(best, 3),
                "reasons": sorted(reasons),
            }
        )

    groups.sort(key=lambda g: (-g["score"], -len(g["series_ids"])))
    return groups
