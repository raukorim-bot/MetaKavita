"""Cluster likely duplicate series (score_candidate matrix + relation markers)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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


#: Type de bibliothèque retenu quand Kavita n'en annonce aucun, ou quand un
#: groupe en mélange plusieurs (un doublon manga/comic de la même œuvre) : mieux
#: vaut la valeur neutre qu'un arbitrage arbitraire entre deux conventions.
DEFAULT_LIBRARY_TYPE = "Manga"

#: Chapitres qu'un tome contient, par convention d'édition. Sert à comparer sur
#: une seule échelle une copie rangée en tomes et une copie rangée en chapitres.
#:
#: Ce sont des conventions, pas des mesures : un tankōbon porte 8 à 12 chapitres,
#: un *trade paperback* recueille environ 6 numéros, un volume de light novel ou
#: de roman en compte plutôt vingt-cinq. MetaKavita servant des bibliothèques
#: très différentes les unes des autres, appliquer partout la moyenne manga
#: sous-évaluait les comics rangés au numéro et sur-évaluait les romans.
CHAPTERS_PER_VOLUME_BY_TYPE = {
    "Manga": 10,
    "Comic": 6,
    "ComicFlexible": 6,
    "Book": 25,
}


def chapters_per_volume(library_type: Any = None) -> int:
    """Combien de chapitres pèse un tome dans ce type de bibliothèque."""
    key = str(library_type or "").strip()
    return CHAPTERS_PER_VOLUME_BY_TYPE.get(
        key, CHAPTERS_PER_VOLUME_BY_TYPE[DEFAULT_LIBRARY_TYPE]
    )


def completeness_score(
    volume_count: Any, chapter_count: Any, library_type: Any = None
) -> Tuple[float, int]:
    """« Quelle copie possède le plus de contenu ? », en tomes équivalents.

    Le couple brut `(tomes, chapitres)` se comparait lexicographiquement : une
    copie à 1 tome battait une copie à 364 chapitres, parce que les chapitres ne
    départageaient qu'à nombre de tomes égal. Sur une série que Kavita ne connaît
    qu'en chapitres — le cas que tout le reste du module traite explicitement
    via `unit_mode` — la recommandation désignait donc la copie la plus vide, et
    l'auto-sélection de l'Atelier cochait la plus complète pour la corbeille.

    Les deux comptes sont deux *unités* du même contenu, jamais deux contenus à
    additionner : une copie sans aucun tome se mesure en chapitres, les autres en
    tomes. Le compte de chapitres ne sert plus qu'à départager deux copies de
    même volumétrie.

    Le ratio n'intervient donc que sur une seule comparaison — chapitres contre
    tomes — où il se lit comme un seuil : la copie en chapitres l'emporte si
    `chapitres > ratio × tomes`. Entre deux copies de même unité, il s'annule.
    """
    vols = max(0, int(volume_count or 0))
    chaps = max(0, int(chapter_count or 0))
    weight = float(vols) if vols else (chaps / chapters_per_volume(library_type))
    return (weight, chaps)


def group_library_type(library_types: Sequence[Any]) -> str:
    """Le type d'un groupe de doublons : celui de ses membres s'ils s'accordent.

    Un groupe qui en mélange plusieurs retombe sur la valeur neutre : arbitrer
    entre la convention manga et la convention comic sur un doublon qui tient des
    deux reviendrait à trancher au hasard.
    """
    seen = {str(t or "").strip() for t in library_types or []}
    seen.discard("")
    return seen.pop() if len(seen) == 1 else DEFAULT_LIBRARY_TYPE


def recommend_keep_id(
    series_ids: Sequence[Any],
    volume_counts: Sequence[Any],
    chapter_counts: Sequence[Any],
    library_type: Any = None,
) -> Optional[int]:
    """La copie à garder, ou `None` s'il n'y a pas de gagnante nette.

    Seule porte de décision : le regroupement, le nettoyage des orphelines et la
    purge d'une série en tenaient chacun leur propre copie, libres de diverger.
    Une recommandation n'est rendue que si une seule copie domine — l'ambiguïté
    se tranche à l'œil, pas par un tri arbitraire.
    """
    ids = [int(s) for s in series_ids or []]
    if len(ids) < 2:
        return None
    scores = group_completeness(ids, volume_counts, chapter_counts, library_type)
    if len(set(scores)) < 2:
        return None
    best = max(scores)
    winners = [ids[i] for i, sc in enumerate(scores) if sc == best]
    return winners[0] if len(winners) == 1 else None


def group_completeness(
    series_ids: Sequence[Any],
    volume_counts: Sequence[Any],
    chapter_counts: Sequence[Any],
    library_type: Any = None,
) -> List[Tuple[float, int]]:
    """Volumétrie de chaque membre d'un groupe, alignée sur `series_ids`."""
    return [
        completeness_score(
            volume_counts[i] if i < len(volume_counts or []) else 0,
            chapter_counts[i] if i < len(chapter_counts or []) else 0,
            library_type,
        )
        for i in range(len(series_ids or []))
    ]


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
    if series.get("ids") is not None and series.get("name") is not None:
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
        # Les seaux sont toujours actifs (voir `_word_set_key`) : rien n'est
        # « forcé » ici, l'ancien libellé laissait croire à une bascule de mode.
        logging.info(
            "[Inventaire] regroupement des doublons sur %s séries — seaux par "
            "mots distinctifs %s",
            n,
            "stricts" if float(threshold) > WORD_SET_KEY_MIN_THRESHOLD else "larges",
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

        # Le type est un *fait* sur le groupe, écrit une fois : les recalculs
        # ultérieurs (orphelines, purge d'une série) retaillent les listes par
        # index et n'ont ainsi rien de plus à maintenir.
        lib_type = group_library_type(
            [items[i].get("libraryType") for i in members]
        )
        recommended_keep_id = recommend_keep_id(
            series_ids, volume_counts, chapter_counts, lib_type
        )

        groups.append(
            {
                "group_id": f"dup-{gid}",
                "group_key": gkey,
                "series_ids": series_ids,
                "names": [items[i].get("name") or "" for i in members],
                "folder_paths": [items[i].get("folder_path") or "" for i in members],
                "library_ids": [items[i].get("libraryId") for i in members],
                "library_type": lib_type,
                "volume_counts": volume_counts,
                "chapter_counts": chapter_counts,
                "recommended_keep_id": recommended_keep_id,
                "score": round(best, 3),
                "reasons": sorted(reasons),
            }
        )

    groups.sort(key=lambda g: (-g["score"], -len(g["series_ids"])))
    return groups


def recluster_library_duplicates(
    library_id: Any,
    threshold: float,
    *,
    config: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """
    Re-cluster duplicate groups for a library (or 'all') at a new threshold in memory.
    Updates duplicate_group_cache and hygiene_library_meta counts without rescraping.
    """
    from db_manager import (
        get_hygiene_series_identities,
        save_hygiene_series_identities,
        save_duplicate_groups_cache,
        list_dismissed_group_keys,
        get_hygiene_library_meta,
        set_hygiene_library_meta,
        list_hygiene_library_meta,
        get_volume_report_cache,
    )

    lib_str = str(library_id).strip()
    is_all = lib_str in ("all", "*")
    api_lib_id = None if is_all else library_id

    identities = get_hygiene_series_identities(None if is_all else lib_str)
    if not identities:
        # Fallback if scan occurred before hygiene_series_identities table was created
        try:
            from kavita_api import KavitaAPI

            api = KavitaAPI(config=config)
            series_list = (
                api.get_all_series(api_lib_id)
                if hasattr(api, "get_all_series")
                else []
            )
            reconstructed = []
            for s in series_list or []:
                if not isinstance(s, dict) or s.get("id") is None:
                    continue
                sid = int(s["id"])
                rep = get_volume_report_cache(sid) or {}
                vol_c = int(
                    rep.get("primary", {}).get("count")
                    or rep.get("stats", {}).get("primary_count")
                    or 0
                )
                chap_c = int(rep.get("chapters", {}).get("count") or 0)
                identity = merge_series_identity(
                    s,
                    {},
                    series_name=s.get("name") or "",
                    library_type=s.get("libraryType") or "Manga",
                )
                identity["id"] = sid
                identity["libraryId"] = s.get("libraryId") or api_lib_id
                identity["volume_count"] = vol_c
                identity["chapter_count"] = chap_c
                reconstructed.append(identity)
            if reconstructed:
                save_hygiene_series_identities(reconstructed)
                identities = reconstructed
        except Exception as e:
            logging.warning(
                "[Inventaire] recluster identity fallback failed: %s", str(e)
            )

    exclude = list_dismissed_group_keys(lib_str)
    new_groups = cluster_duplicate_series(
        identities,
        library_id=api_lib_id,
        threshold=threshold,
        exclude_keys=exclude,
        config=config,
    )

    save_duplicate_groups_cache(lib_str, new_groups)

    meta = get_hygiene_library_meta(lib_str)
    if meta and isinstance(meta.get("counts"), dict):
        counts = meta["counts"]
        counts["duplicates"] = len(new_groups)
        set_hygiene_library_meta(lib_str, counts, scanned_at=meta.get("scanned_at"))

    if is_all:
        lib_groups_map: Dict[str, list] = {}
        for g in new_groups or []:
            unique_lids = {
                str(lid).strip()
                for lid in (g.get("library_ids") or [])
                if lid is not None and str(lid).strip()
            }
            for lid_str in unique_lids:
                lib_groups_map.setdefault(lid_str, []).append(g)
        for sub_meta in list_hygiene_library_meta():
            sub_lid = str(sub_meta.get("library_id") or "").strip()
            if not sub_lid or sub_lid in ("all", "*"):
                continue
            sub_groups = lib_groups_map.get(sub_lid, [])
            save_duplicate_groups_cache(sub_lid, sub_groups)
            sc = sub_meta.get("counts") or {}
            sc["duplicates"] = len(sub_groups)
            set_hygiene_library_meta(sub_lid, sc, scanned_at=sub_meta.get("scanned_at"))
    elif get_hygiene_library_meta("all") is not None:
        all_identities = get_hygiene_series_identities(None)
        if all_identities:
            all_exclude = list_dismissed_group_keys("all")
            all_groups = cluster_duplicate_series(
                all_identities,
                library_id=None,
                threshold=threshold,
                exclude_keys=all_exclude,
                config=config,
            )
            save_duplicate_groups_cache("all", all_groups)
            all_meta = get_hygiene_library_meta("all")
            if all_meta and isinstance(all_meta.get("counts"), dict):
                ac = all_meta["counts"]
                ac["duplicates"] = len(all_groups)
                set_hygiene_library_meta("all", ac, scanned_at=all_meta.get("scanned_at"))

    return new_groups
