"""CSV / TXT serializers for library audit reports."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

# Excel et LibreOffice évaluent toute cellule ouvrant sur l'un de ces caractères :
# une série nommée « =cmd|' /C calc'!A0 » devient un appel système à l'ouverture du
# fichier. La tabulation et le retour chariot servent à sortir de la cellule pour
# en réamorcer une, même protection donc.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _defused(value: Any) -> Any:
    """Neutralise une valeur textuelle susceptible d'être lue comme une formule.

    L'apostrophe de tête est la convention des tableurs : la cellule s'affiche
    telle quelle et le contenu reste lisible. Les nombres ne sont pas touchés —
    un `-3` numérique n'a jamais été une formule.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGERS):
        return "'" + value
    return value


def _write_row(writer, values) -> None:
    """Seule porte d'écriture des exports CSV : aucune colonne ne peut être oubliée."""
    writer.writerow([_defused(v) for v in values])


def volume_report_to_csv(report: Dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cat = report.get("catalog") or {}
    stats = report.get("stats") or {}
    primary = report.get("primary") or {}
    completion = report.get("completion") or {}
    missing = report.get("missing_volumes") or []
    # Les colonnes `unit` / `primary_*` datent de l'inventaire en chapitres : sans
    # elles, une série comptée en chapitres s'exportait avec `kavita_count` à 0 et
    # un attendu vide, alors que l'écran affichait 8/32 ch.
    _write_row(
        w,
        [
            "series_id",
            "series_name",
            "structure",
            "kavita_count",
            "catalog_expected",
            "catalog_provider",
            "catalog_status",
            "missing_volumes",
            "volume_number",
            "chapter_number",
            "name",
            "isbn",
            "has_summary",
            "has_isbn",
            "is_special",
            "is_loose",
            "unit",
            "primary_count",
            "primary_expected",
            "primary_missing",
            "out_of_range",
            "completion_state",
        ]
    )
    sid = report.get("series_id")
    sname = report.get("series_name") or ""
    structure = report.get("structure") or ""
    kavita = stats.get("kavita_count", "")
    expected = cat.get("expected", "")
    provider = cat.get("provider") or ""
    status = cat.get("status") or ""
    missing_s = "|".join(str(x) for x in missing)
    join = lambda values: "|".join(str(x) for x in values or [])
    tail = [
        primary.get("unit") or cat.get("unit") or "volumes",
        primary.get("count", kavita),
        primary.get("expected", expected),
        join(primary.get("missing")),
        join(primary.get("out_of_range")),
        completion.get("state") or "",
    ]
    for u in report.get("units") or []:
        _write_row(
            w,
            [
                sid,
                sname,
                structure,
                kavita,
                expected,
                provider,
                status,
                missing_s,
                u.get("volume_number"),
                u.get("chapter_number"),
                u.get("name") or "",
                u.get("isbn") or "",
                u.get("has_summary"),
                u.get("has_isbn"),
                u.get("is_special"),
                u.get("is_loose"),
                *tail,
            ]
        )
    for g in primary.get("missing") or missing:
        _write_row(
            w,
            [
                sid,
                sname,
                structure,
                kavita,
                expected,
                provider,
                status,
                missing_s,
                g,
                "",
                f"MISSING_{(tail[0] or 'volumes').upper()}_{g}",
                "",
                "",
                "",
                "",
                "",
                *tail,
            ]
        )
    return buf.getvalue()


def volume_report_to_txt(report: Dict[str, Any]) -> str:
    cat = report.get("catalog") or {}
    stats = report.get("stats") or {}
    status = cat.get("status") or "unknown"
    expected = cat.get("expected")
    if status == "ok" and expected is not None:
        attendu = f"{expected} ({cat.get('provider') or '?'})"
    elif status == "unknown":
        attendu = "Inconnu"
    elif status == "error":
        attendu = "Erreur"
    elif status == "skipped":
        attendu = "Ignoré (provider off)"
    else:
        attendu = str(expected if expected is not None else status)
    primary = report.get("primary") or {}
    unit = primary.get("unit") or cat.get("unit") or "volumes"
    lines = [
        f"Series {report.get('series_id')}: {report.get('series_name')}",
        f"Structure: {report.get('structure')}",
        f"Possédés: {primary.get('count', stats.get('kavita_count'))} {unit}",
        f"Attendu scrapé: {attendu}",
        f"Manquants ({unit}): {primary.get('missing', report.get('missing_volumes'))}",
        f"Trous locaux: {primary.get('gaps', report.get('gaps'))}",
    ]
    # Le hors-série écarté du compte : sans la ligne, l'export ne dit pas pourquoi
    # 18 tomes présents dans Kavita donnent un compte de 17.
    if primary.get("out_of_range"):
        lines.append(f"Hors plage: {primary.get('out_of_range')}")
    lines += [
        f"Stats: {stats}",
        "",
        "Units:",
    ]
    for u in report.get("units") or []:
        lines.append(
            f"  vol={u.get('volume_number')} ch={u.get('chapter_number')} "
            f"summary={u.get('has_summary')} isbn={u.get('isbn') or '-'} "
            f"| {u.get('name')}"
        )
    return "\n".join(lines) + "\n"


def duplicates_to_csv(groups: List[Dict[str, Any]], *, library_id: Any = "") -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    _write_row(w, ["library_id", "group_id", "group_key", "score", "reasons", "series_id", "name"])
    for g in groups or []:
        reasons = "|".join(g.get("reasons") or [])
        ids = g.get("series_ids") or []
        names = g.get("names") or []
        for i, sid in enumerate(ids):
            name = names[i] if i < len(names) else ""
            _write_row(
                w,
                [
                    library_id,
                    g.get("group_id"),
                    g.get("group_key") or "",
                    g.get("score"),
                    reasons,
                    sid,
                    name,
                ]
            )
    return buf.getvalue()


def missing_volumes_to_csv(rows: List[Dict[str, Any]], *, library_id: Any = "") -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    _write_row(
        w,
        [
            "library_id",
            "series_id",
            "name",
            "badge",
            "kavita_count",
            "catalog_expected",
            "catalog_status",
            "catalog_provider",
            "publication_status",
            "reason",
            "missing_volumes",
            "unit",
            "count",
            "expected",
            "completion_state",
            "forced_expected",
        ]
    )
    for r in rows or []:
        missing = r.get("missing_volumes") or []
        _write_row(
            w,
            [
                library_id,
                r.get("series_id"),
                r.get("name") or "",
                r.get("badge") or "",
                r.get("kavita_count"),
                r.get("catalog_expected"),
                r.get("catalog_status") or "",
                r.get("catalog_provider") or "",
                r.get("publication_status") or "",
                r.get("reason") or "",
                "|".join(str(x) for x in missing),
                r.get("unit") or "volumes",
                r.get("count"),
                r.get("expected"),
                r.get("completion_state") or "",
                bool(r.get("forced_expected")),
            ]
        )
    return buf.getvalue()


def missing_volumes_to_txt(rows: List[Dict[str, Any]], *, library_id: Any = "") -> str:
    lines = [f"Missing volumes report (library={library_id})", "=" * 40, ""]
    if not rows:
        lines.append("(none)")
        return "\n".join(lines) + "\n"
    for r in rows:
        missing = r.get("missing_volumes") or []
        lines.append(
            f"#{r.get('series_id')} {r.get('name') or ''} — "
            f"badge={r.get('badge')} pub={r.get('publication_status') or '?'} "
            f"missing={missing} ({r.get('unit') or 'volumes'})"
        )
    return "\n".join(lines) + "\n"


def duplicates_to_txt(groups: List[Dict[str, Any]], *, library_id: Any = "") -> str:
    lines = [f"Duplicates report (library={library_id})", "=" * 40, ""]
    if not groups:
        lines.append("(none)")
        return "\n".join(lines) + "\n"
    for g in groups:
        lines.append(
            f"[{g.get('group_id')}] score={g.get('score')} "
            f"reasons={','.join(g.get('reasons') or [])}"
        )
        for sid, name in zip(g.get("series_ids") or [], g.get("names") or []):
            lines.append(f"  - {sid}: {name}")
        lines.append("")
    return "\n".join(lines)
