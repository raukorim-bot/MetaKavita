"""Build a read-only volume/chapter hygiene report from Kavita volume DTOs."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Sentinelles Kavita (Parser.SpecialVolumeNumber / Parser.LooseLeafVolumeNumber).
# Le volume « feuilles volantes » vaut -100000 depuis Kavita 0.8 ; les versions
# antérieures rangeaient ces chapitres dans le volume 0.
_SPECIAL_VOL = 100_000
_LOOSE_VOL = -100_000
_ONESHOT_RE = re.compile(r"\bone[\s_-]?shot\b", re.I)
# Kavita retombe sur le `range` du fichier quand il n'y a pas de titre : la
# colonne « Nom » du rapport recopiait alors le numéro (« 1 », « 2 », « 3 »), et
# la sentinelle elle-même quand le chapitre couvre tout le tome (« -100000 »).
_NUMERIC_NAME_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")

# Une série encore publiée dont on possède tout le publié n'est pas « incomplète ».
_ONGOING_PUB = frozenset({"RELEASING", "NOT_YET_RELEASED", "HIATUS"})


def _as_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _vol_number(vol: dict) -> Optional[float]:
    for key in ("number", "minNumber", "Number", "MinNumber"):
        n = _as_float(vol.get(key))
        if n is not None:
            return n
    name = vol.get("name") or vol.get("Name") or ""
    m = re.search(r"(\d+(?:\.\d+)?)", str(name))
    if m:
        return float(m.group(1))
    return None


def _chap_number(chap: dict) -> Optional[float]:
    for key in ("number", "minNumber", "range", "Number", "MinNumber"):
        raw = chap.get(key)
        if raw is None or raw == "":
            continue
        s = str(raw).strip()
        # `range` peut être une plage (« 1-3 ») ; un nombre négatif n'en est pas
        # une, c'est la sentinelle des chapitres sans numéro.
        if not s.startswith("-"):
            s = s.split("-")[0].strip()
        n = _as_float(s)
        if n is None:
            continue
        # Un chapitre qui couvre tout un tome n'a pas de numéro : Kavita 0.8 y
        # met -100000 (Parser.DefaultChapterNumber), ce n'est pas un chapitre.
        if abs(n - _LOOSE_VOL) < 0.01 or abs(n - _SPECIAL_VOL) < 0.01:
            return None
        return n
    return None


def _is_special_vol(vol: dict, num: Optional[float]) -> bool:
    # Ce que Kavita fournit réellement au niveau du tome, c'est la sentinelle
    # 100000 : `VolumeDto` n'a pas de propriété `IsSpecial` (le drapeau appartient
    # à `ChapterDto`, lu plus bas). Le drapeau et le nom restent des tolérances,
    # jamais l'unique preuve.
    if num is not None and abs(num - _SPECIAL_VOL) < 0.01:
        return True
    if vol.get("isSpecial") or vol.get("IsSpecial"):
        return True
    name = str(vol.get("name") or vol.get("Name") or "")
    if _ONESHOT_RE.search(name):
        return True
    return False


def _unit_name(raw: Any) -> str:
    name = str(raw or "").strip()
    return "" if _NUMERIC_NAME_RE.match(name) else name


def _summary_nonempty(obj: dict) -> bool:
    for key in ("summary", "Summary", "overview", "Overview"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _has_isbn(obj: dict) -> bool:
    """Un ISBN vient du chapitre : `VolumeDto` ne porte pas la propriété.

    Le repli sur le tome, plus bas, ne sert donc que les dictionnaires assemblés
    autrement (tome sans chapitre, appelant de test) — il ne coûte rien et évite
    de perdre un ISBN que l'appelant aurait bel et bien.
    """
    isbn = obj.get("isbn") or obj.get("Isbn") or ""
    return bool(str(isbn).strip())


def _has_cover(obj: dict) -> bool:
    if obj.get("coverImage") or obj.get("CoverImage"):
        return True
    # chapters sometimes expose pages with cover elsewhere — treat coverImageLocked as weak signal
    return False


def _positive_int(val: Any) -> Optional[int]:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def format_number_ranges(numbers: List[Any], *, max_groups: int = 8) -> str:
    """« 2, 3, 4, 12 » → « 2–4, 12 ».

    Les longues séries produisent des listes de dizaines de numéros : les afficher
    un par un noie l'information utile (voir les « trous locaux » du rapport).
    Au-delà de `max_groups` intervalles, la suite est élidée.
    """
    ints = sorted({int(n) for n in numbers or [] if n is not None})
    if not ints:
        return ""
    groups: List[Tuple[int, int]] = []
    start = prev = ints[0]
    for n in ints[1:]:
        if n == prev + 1:
            prev = n
            continue
        groups.append((start, prev))
        start = prev = n
    groups.append((start, prev))
    parts = [str(a) if a == b else f"{a}\u2013{b}" for a, b in groups[:max_groups]]
    if len(groups) > max_groups:
        parts.append("\u2026")
    return ", ".join(parts)


def resolve_completion_state(
    count: Optional[int],
    expected: Optional[int],
    *,
    missing_count: int = 0,
    publication_status: str = "UNKNOWN",
    is_oneshot: bool = False,
    structure: str = "",
) -> Tuple[str, Optional[float]]:
    """Étiquette de complétion + ratio, pour le code couleur du dashboard.

    États : neutral (one-shot / spéciaux), unknown (pas d'attendu), overshoot
    (plus que l'attendu — signe d'un spécial compté comme tome, pas d'une
    complétion), uptodate (série en cours dont on a tout le publié), complete,
    near (1–2 manquants), partial (≥ 50 %), poor.
    """
    if is_oneshot or structure == "specials_only":
        return "neutral", None
    exp = _positive_int(expected)
    have = max(0, int(count or 0))
    if not exp:
        return "unknown", None
    ratio = have / exp
    if have > exp:
        return "overshoot", ratio
    if have >= exp:
        pub = (publication_status or "UNKNOWN").strip().upper()
        return ("uptodate" if pub in _ONGOING_PUB else "complete"), ratio
    missing = missing_count if missing_count > 0 else (exp - have)
    if missing <= 2:
        return "near", ratio
    if ratio >= 0.5:
        return "partial", ratio
    return "poor", ratio


def split_out_of_range(
    numbers: List[Any], expected: Optional[int]
) -> Tuple[List[int], List[int]]:
    """Sépare les numéros du récit de ceux qui tombent hors de la plage attendue.

    Une intégrale ou un hors-série mal numéroté par Kavita (tome `101` sur une
    série de 17) faisait deux dégâts : le compte passait à 18/17 (« plus que
    l'attendu ») et les trous locaux annonçaient `18–100`, soit 83 numéros
    fantômes. Un numéro n'est écarté que s'il dépasse l'attendu **et** qu'un
    fossé le sépare du reste de la collection : les tomes 18-19-20 d'une série
    dont le catalogue est resté à 17 continuent la série, donc ils comptent (et
    l'état « overshoot » garde son sens).
    """
    ints = sorted({int(n) for n in numbers or [] if n is not None and n > 0})
    exp = _positive_int(expected)
    if not exp or not ints:
        return ints, []
    tolerance = max(2, exp // 4)
    kept: List[int] = []
    outliers: List[int] = []
    prev: Optional[int] = None
    for n in ints:
        if n <= exp or prev is None or n - prev <= tolerance:
            kept.append(n)
            prev = n
        else:
            outliers.append(n)
    return kept, outliers


def compute_volume_gaps(numbers: List[float]) -> List[int]:
    """Integer gaps in a sorted unique sequence of volume numbers (ignores decimals)."""
    ints: Set[int] = set()
    for n in numbers:
        if n is None:
            continue
        if n <= 0 or abs(n - _SPECIAL_VOL) < 0.01:
            continue
        ints.add(int(n))
    if len(ints) < 2:
        return []
    lo, hi = min(ints), max(ints)
    return [i for i in range(lo, hi + 1) if i not in ints]


def classify_series_structure(
    story_count: int,
    special_count: int,
    loose_chapter_count: int,
    oneshot_hint: bool,
) -> str:
    if oneshot_hint or (story_count <= 1 and special_count <= 1 and loose_chapter_count <= 1):
        if story_count + special_count + loose_chapter_count <= 1:
            return "oneshot"
    if story_count == 0 and special_count > 0 and loose_chapter_count == 0:
        return "specials_only"
    if story_count >= 2:
        # loose/specials dominate story volumes
        noise = special_count + loose_chapter_count
        if noise >= story_count * 2 and loose_chapter_count >= 3:
            return "loose_heavy"
        return "multi_volume"
    if story_count == 1:
        return "oneshot" if special_count + loose_chapter_count <= 1 else "loose_heavy"
    if loose_chapter_count >= 3:
        return "loose_heavy"
    return "oneshot"


def build_volume_report(
    series_id: int,
    volumes: List[dict],
    *,
    series_name: str = "",
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure function: Kavita volumes JSON (+ optional catalogue count) → hygiene report."""
    units: List[Dict[str, Any]] = []
    story_nums: List[float] = []
    chapter_nums: List[float] = []
    special_count = 0
    loose_chapter_count = 0
    oneshot_hint = bool(_ONESHOT_RE.search(series_name or ""))

    for vol in volumes or []:
        if not isinstance(vol, dict):
            continue
        vnum = _vol_number(vol)
        is_special = _is_special_vol(vol, vnum)
        chapters = vol.get("chapters") or vol.get("Chapters") or []
        if not isinstance(chapters, list):
            chapters = []

        # Loose-leaf: volume 0 or empty number with many chapters often means chapter-based
        is_loose_vol = bool(
            (vnum is not None and (abs(vnum) < 0.01 or abs(vnum - _LOOSE_VOL) < 0.01))
            or (vnum is None and not is_special and chapters)
        )
        # Les sentinelles n'ont pas de sens à l'écran : le rapport affichait
        # « Tome -100000 » sur chaque ligne d'une série en chapitres.
        vnum_shown = None if vnum is not None and (
            abs(vnum - _SPECIAL_VOL) < 0.01 or abs(vnum - _LOOSE_VOL) < 0.01
        ) else vnum

        if is_special:
            special_count += 1
            if _ONESHOT_RE.search(str(vol.get("name") or "")):
                oneshot_hint = True
        elif is_loose_vol:
            loose_chapter_count += max(len(chapters), 1)
        elif vnum is not None:
            story_nums.append(vnum)

        if not chapters:
            units.append(
                {
                    "volume_id": vol.get("id") or vol.get("Id"),
                    "chapter_id": None,
                    "volume_number": vnum_shown,
                    "chapter_number": None,
                    "name": _unit_name(vol.get("name") or vol.get("Name")),
                    "isbn": str(vol.get("isbn") or "").strip() or None,
                    "has_summary": _summary_nonempty(vol),
                    "has_isbn": _has_isbn(vol),
                    "has_cover": _has_cover(vol),
                    "is_special": is_special,
                    "is_loose": is_loose_vol,
                }
            )
            continue

        for chap in chapters:
            if not isinstance(chap, dict):
                continue
            cname = chap.get("title") or chap.get("Title") or chap.get("range") or chap.get("Range") or ""
            if _ONESHOT_RE.search(str(cname)):
                oneshot_hint = True
            chap_special = is_special or bool(chap.get("isSpecial") or chap.get("IsSpecial"))
            cnum = _chap_number(chap)
            if not chap_special and cnum is not None:
                chapter_nums.append(cnum)
            units.append(
                {
                    "volume_id": vol.get("id") or vol.get("Id"),
                    "chapter_id": chap.get("id") or chap.get("Id"),
                    "volume_number": vnum_shown,
                    "chapter_number": _chap_number(chap),
                    "name": _unit_name(cname) or _unit_name(vol.get("name") or vol.get("Name")),
                    "isbn": str(chap.get("isbn") or vol.get("isbn") or "").strip() or None,
                    "has_summary": _summary_nonempty(chap) or _summary_nonempty(vol),
                    "has_isbn": _has_isbn(chap) or _has_isbn(vol),
                    "has_cover": _has_cover(chap) or _has_cover(vol),
                    "is_special": chap_special,
                    "is_loose": is_loose_vol,
                }
            )

    from .catalog_count import missing_volume_numbers

    catalog = catalog or {}
    catalog_status = (catalog.get("status") or "").strip().lower()
    catalog_expected = catalog.get("expected")
    try:
        catalog_expected = int(catalog_expected) if catalog_expected is not None else None
    except (TypeError, ValueError):
        catalog_expected = None
    if catalog_expected is not None and catalog_expected < 1:
        catalog_expected = None
    # Legacy callers pass expected without status → treat as ok
    if not catalog_status:
        catalog_status = "ok" if catalog_expected else "unknown"

    # Le compte et les trous se lisent sur les seuls numéros de récit : un tome
    # isolé loin au-delà de l'attendu est un hors-série, pas le 18ᵉ volume.
    story_ints, story_out_of_range = split_out_of_range(
        story_nums, catalog_expected if catalog_status == "ok" else None
    )
    story_count = len(story_ints)
    # Prefer counting distinct story volume numbers; if none, count non-special units
    if story_count == 0:
        story_units = [
            u
            for u in units
            if not u.get("is_special") and not u.get("is_loose")
        ]
        story_count = len(story_units)

    structure = classify_series_structure(
        story_count, special_count, loose_chapter_count, oneshot_hint
    )

    # Product: expected > 1 means incomplete multi-volume, never oneshot
    if catalog_status == "ok" and catalog_expected and catalog_expected > 1:
        if structure == "oneshot":
            structure = "incomplete" if story_count <= 1 else "multi_volume"
        is_oneshot = False
    elif catalog_status == "ok" and catalog_expected == 1:
        structure = "oneshot"
        is_oneshot = True
    else:
        is_oneshot = structure == "oneshot"

    gaps = (
        []
        if is_oneshot or structure in ("specials_only",)
        else compute_volume_gaps(story_ints)
    )

    missing_summary = sum(1 for u in units if not u.get("has_summary"))
    missing_isbn = sum(1 for u in units if not u.get("has_isbn"))
    total = len(units)
    kavita_count = story_count

    publication_status = (catalog.get("publication_status") or "UNKNOWN").strip().upper()
    catalog_reason = (catalog.get("reason") or "").strip()
    catalog_source = (catalog.get("source") or "cascade").strip() or "cascade"
    backup_from = (catalog.get("backup_from") or "").strip()
    forced = catalog_reason == "manual" or (catalog.get("provider") or "") == "MANUAL"

    # Chapitres : seule unité disponible quand Kavita ne connaît aucun tome
    # numéroté (fichiers rangés en chapitres, volume 0 « loose »).
    all_chapter_ints = sorted(
        {
            int(n)
            for n in chapter_nums
            if n is not None and n > 0 and abs(n - _SPECIAL_VOL) > 0.01
        }
    )
    expected_chapters = _positive_int(catalog.get("expected_chapters"))
    unit_mode = "volumes" if story_count > 0 else ("chapters" if all_chapter_ints else "volumes")
    # Même garde-fou côté chapitres : un chapitre `999` ne doit pas creuser mille
    # trous ni compter comme un chapitre du récit.
    chapter_expected_ref = catalog_expected if forced else expected_chapters
    # En mode tomes, l'attendu volumes sert de repère faute de mieux : seuls les
    # numéros isolés loin devant sont écartés, une longue série de chapitres
    # consécutifs reste intacte (c'est le fossé qui décide, pas le seuil).
    chapter_ints, chapter_out_of_range = split_out_of_range(
        all_chapter_ints,
        chapter_expected_ref if unit_mode == "chapters" else (expected_chapters or catalog_expected),
    )
    local_chapter_count = len(chapter_ints)
    out_of_range = chapter_out_of_range if unit_mode == "chapters" else story_out_of_range

    # Tomes manquants = face au seul attendu scrapé, et seulement si la série est
    # bien paginée en tomes : une série en chapitres n'attend aucun tome, son
    # manque se mesure en chapitres juste en dessous.
    if catalog_status == "ok" and catalog_expected and unit_mode == "volumes":
        missing_volumes = missing_volume_numbers(story_ints, catalog_expected)
    else:
        missing_volumes = []

    if unit_mode == "chapters":
        primary_count = local_chapter_count
        # Un attendu forcé s'applique à l'unité de la série : sur une série
        # connue en chapitres, le nombre saisi compte des chapitres.
        primary_expected = chapter_expected_ref
        primary_missing = missing_volume_numbers(chapter_ints, primary_expected)
        primary_gaps = compute_volume_gaps(chapter_ints)
        primary_unit = "chapters"
    else:
        primary_count = kavita_count
        primary_expected = catalog_expected if catalog_status == "ok" else None
        primary_missing = missing_volumes
        primary_gaps = gaps
        primary_unit = (catalog.get("unit") or "volumes").strip() or "volumes"

    completion_state, completion_ratio = resolve_completion_state(
        primary_count,
        primary_expected,
        missing_count=len(primary_missing),
        publication_status=publication_status,
        is_oneshot=is_oneshot,
        structure=structure,
    )

    badge = "—"
    if is_oneshot:
        badge = "OS"
    elif structure == "specials_only":
        badge = "SP"
    elif primary_expected:
        badge = f"{primary_count}/{primary_expected}"
        if unit_mode == "chapters":
            badge += " ch"
        if primary_missing:
            badge += f" ⚠{len(primary_missing)}"
        if forced:
            badge += "*"
    elif unit_mode == "chapters":
        badge = f"{primary_count}/? ch"
    elif catalog_status == "unknown":
        badge = f"{kavita_count}/?" if kavita_count else "?"
    elif kavita_count:
        badge = str(kavita_count)

    return {
        "series_id": int(series_id),
        "series_name": series_name or "",
        "structure": structure,
        "is_oneshot": is_oneshot,
        "units": units,
        "gaps": gaps,
        "missing_volumes": missing_volumes,
        "unit_mode": unit_mode,
        "primary": {
            "unit": primary_unit,
            "count": primary_count,
            "expected": primary_expected,
            "missing": primary_missing,
            "missing_label": format_number_ranges(primary_missing),
            "gaps": primary_gaps,
            "gaps_label": format_number_ranges(primary_gaps),
            "out_of_range": out_of_range,
            "out_of_range_label": format_number_ranges(out_of_range),
        },
        "completion": {
            "state": completion_state,
            "ratio": completion_ratio,
            "missing_count": len(primary_missing),
            "forced": forced,
        },
        "chapters": {
            "count": local_chapter_count,
            "expected": expected_chapters,
            "gaps": compute_volume_gaps(chapter_ints) if unit_mode == "volumes" else primary_gaps,
        },
        "out_of_range": out_of_range,
        "catalog": {
            "expected": catalog_expected,
            "expected_chapters": expected_chapters,
            "provider": catalog.get("provider"),
            "unit": catalog.get("unit") or "volumes",
            "title": catalog.get("title") or "",
            "provider_id": catalog.get("provider_id") or "",
            "status": catalog_status,
            "publication_status": publication_status or "UNKNOWN",
            "reason": catalog_reason,
            "source": catalog_source,
            "backup_from": backup_from,
        },
        "stats": {
            "total": total,
            "kavita_count": kavita_count,
            "catalog_expected": catalog_expected,
            "missing_volume_count": len(missing_volumes),
            "story_volume_count": story_count,
            "special_count": special_count,
            "loose_chapter_count": loose_chapter_count,
            "missing_summary": missing_summary,
            "missing_isbn": missing_isbn,
            "gap_count": len(gaps),
            "with_summary": total - missing_summary,
            "chapter_count": local_chapter_count,
            "expected_chapters": expected_chapters,
            "primary_count": primary_count,
            "primary_expected": primary_expected,
            "primary_missing_count": len(primary_missing),
            "completion_state": completion_state,
            "completion_ratio": completion_ratio,
            "forced_expected": forced,
            "out_of_range_count": len(out_of_range),
        },
        "badge": badge,
        "publication_status": publication_status or "UNKNOWN",
    }
