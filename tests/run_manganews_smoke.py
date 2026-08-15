"""Live battery — Manga-News série + index de tomes.

Manga-News est le primaire VF : une recherche, jusqu'à 3 fiches, puis une
page HTML par tome (plafond 40, cadence 6 s). Cette batterie mesure le
match sur les titres Kavita (souvent EN) et la qualité des tomes.

Usage :
  set PYTHONPATH=Z:\\kavitafetcher
  python tests/run_manganews_smoke.py

MN_SMOKE_FAST=1 abaisse la cadence à 0.4 s (recherche uniquement).
MN_SMOKE_ONLY=Demon Slayer,Frieren,Hellsing restreint la batterie.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.manganews import MangaNewsScraper

# Titre Kavita / EN, puis repli VF si le catalogue ne connaît que le titre français.
SERIES: List[Tuple[str, str, Optional[str]]] = [
    ("Death Note", "control", None),
    ("One Punch Man", "hyphen", "One-Punch Man"),
    ("Attack on Titan", "EN ≠ VF", "L'Attaque des Titans"),
    ("Demon Slayer", "EN ≠ VF", "Demon Slayer"),
    ("Jujutsu Kaisen", "shonen", None),
    ("Chainsaw Man", "short", None),
    ("Spy x Family", "x", "Spy × Family"),
    ("Frieren", "colon often stripped", "Frieren"),
    ("Dandadan", "new", None),
    ("Vinland Saga", "seinen", None),
    ("My Hero Academia", "long EN", "My Hero Academia"),
    ("Tokyo Ghoul", "compact", None),
    ("The Promised Neverland", "The", None),
    ("Komi Can't Communicate", "apostrophe / VF", "Komi cherche ses mots"),
    ("Kaguya-sama", "honorific", "Kaguya-sama - Love is War"),
    ("Oshi no Ko", "particle", None),
    ("Blue Lock", "two words", None),
    ("Dorohedoro", "seinen niche", None),
    ("Hellsing", "short seinen", None),
    ("20th Century Boys", "number", "20th Century Boys"),
    ("Delicious in Dungeon", "EN vs dungeon meshi", "Gloutons et Dragons"),
    ("The Apothecary Diaries", "The + long", "Les Carnets de l'Apothicaire"),
    ("Made in Abyss", "in", None),
    ("JoJo's Bizarre Adventure", "apostrophe", "Jojo's Bizarre Adventure"),
    ("Fullmetal Alchemist", "classic", None),
    ("Hunter x Hunter", "x", None),
    ("Goodnight Punpun", "literary", "Bonne nuit Punpun"),
    ("A Silent Voice", "leading A", "A Silent Voice"),
    ("7th Garden", "short / niche", None),
    ("A Couple of Cuckoos", "article + last word", "A Couple of Cuckoos"),
    ("Naruto", "long series / cap 40", None),
    ("One Piece", "long series / cap 40", None),
    ("Berserk", "seinen classic", None),
    ("Blacksad", "comic — should miss", None),
]

# Index complet (le reste : 3 tomes échantillon — 1er, 2e, dernier listé).
FULL_INDEX = {
    "Death Note",
    "7th Garden",
    "A Couple of Cuckoos",
    "Naruto",
    "One Piece",
    "Komi Can't Communicate",
    "The Apothecary Diaries",
}

OUT_JSON = ROOT / "tests" / "_manganews_smoke.json"
OUT_TXT = ROOT / "tests" / "_manganews_smoke.txt"


def _stats(index: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not index:
        return {"n": 0, "title": 0, "summary": 0, "date": 0, "isbn": 0, "cover": 0}
    keys = list(index)
    return {
        "n": len(keys),
        "title": sum(1 for k in keys if index[k].get("title")),
        "summary": sum(1 for k in keys if index[k].get("summary")),
        "date": sum(1 for k in keys if index[k].get("release_date")),
        "isbn": sum(1 for k in keys if index[k].get("isbn")),
        "cover": sum(1 for k in keys if index[k].get("cover_url")),
    }


def _sample(index: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not index:
        return []
    keys = sorted(index, key=lambda k: float(k) if str(k).replace(".", "", 1).isdigit() else 0)
    out = []
    for key in keys[:2] + ([keys[-1]] if len(keys) > 2 else []):
        payload = index[key]
        out.append(
            {
                "n": str(key),
                "title": (payload.get("title") or "")[:80],
                "date": payload.get("release_date") or "",
                "isbn": payload.get("isbn") or "",
                "summary": (payload.get("summary") or "")[:160],
            }
        )
    return out


def _fetch_series(scraper: MangaNewsScraper, name: str, fallback: Optional[str]) -> Dict[str, Any]:
    tried = [name]
    found = scraper.fetch(name, library_type="Manga")
    used = name
    if not found and fallback and fallback != name:
        tried.append(fallback)
        found = scraper.fetch(fallback, library_type="Manga")
        used = fallback
    return {"found": found, "used": used, "tried": tried}


def _volume_index(
    scraper: MangaNewsScraper,
    query: str,
    series_url: str,
    full: bool,
) -> Optional[Dict[str, Any]]:
    if full:
        return scraper.fetch_volume_index(
            query, library_type="Manga", series_id=series_url
        )
    # Échantillon : on laisse fetch_volume_index faire le travail, mais on
    # borne VOLUME_INDEX_MAX à 3 pour ne pas tirer 40 pages × 30 séries.
    previous = scraper.VOLUME_INDEX_MAX
    scraper.VOLUME_INDEX_MAX = 3
    try:
        return scraper.fetch_volume_index(
            query, library_type="Manga", series_id=series_url
        )
    finally:
        scraper.VOLUME_INDEX_MAX = previous


def main() -> int:
    scraper = MangaNewsScraper()
    fast = os.environ.get("MN_SMOKE_FAST") == "1"
    if fast:
        scraper.rate_limit = 0.4
    lines = [
        f"MANGANEWS smoke  version={scraper.version}  rate={scraper.rate_limit}  fast={int(fast)}",
        "",
    ]
    rows: List[Dict[str, Any]] = []

    only = {
        item.strip()
        for item in (os.environ.get("MN_SMOKE_ONLY") or "").split(",")
        if item.strip()
    }
    selected = [row for row in SERIES if not only or row[0] in only]
    for name, note, fallback in selected:
        started = time.monotonic()
        series_err = ""
        try:
            series_hit = _fetch_series(scraper, name, fallback)
        except Exception as exc:
            series_hit = {"found": None, "used": name, "tried": [name]}
            series_err = f"{type(exc).__name__}: {exc}"
        found = series_hit["found"]
        series_s = round(time.monotonic() - started, 2)

        vol_err = ""
        index = None
        vol_s = 0.0
        if found and found.get("url") and name != "Blacksad":
            v0 = time.monotonic()
            try:
                index = _volume_index(
                    scraper,
                    series_hit["used"],
                    found["url"],
                    full=name in FULL_INDEX,
                )
            except Exception as exc:
                vol_err = f"{type(exc).__name__}: {exc}"
            vol_s = round(time.monotonic() - v0, 2)

        stats = _stats(index)
        row = {
            "query": name,
            "note": note,
            "tried": series_hit["tried"],
            "used": series_hit["used"],
            "series_ok": bool(found),
            "series_title": (found or {}).get("title") or "",
            "series_score": (found or {}).get("_match_score"),
            "series_url": (found or {}).get("url") or "",
            "year": (found or {}).get("year") or "",
            "status": (found or {}).get("status") or "",
            "staff": len((found or {}).get("staff") or []),
            "summary_len": len((found or {}).get("summary") or ""),
            "cover": bool((found or {}).get("cover_url")),
            "series_s": series_s,
            "series_err": series_err,
            "volume_full": name in FULL_INDEX,
            "volume_s": vol_s,
            "volume_err": vol_err,
            **{f"vol_{k}": v for k, v in stats.items()},
            "sample": _sample(index),
        }
        rows.append(row)

        sflag = "OK" if found else "MISS"
        vflag = "—" if name == "Blacksad" else ("EMPTY" if found and stats["n"] == 0 else ("OK" if stats["n"] else "skip"))
        lines.append(
            f"{sflag:4} {vflag:5} {name:28} "
            f"score={row['series_score'] if row['series_score'] is not None else '-':>5} "
            f"title={row['series_title']!r}  "
            f"vol={stats['n']:2} sum={stats['summary']:2} date={stats['date']:2} "
            f"isbn={stats['isbn']:2}  {series_s}+{vol_s}s  {note}"
        )
        if series_err:
            lines.append(f"      SERIES {series_err}")
        if vol_err:
            lines.append(f"      VOLUME {vol_err}")
        if row["sample"]:
            first = row["sample"][0]
            lines.append(
                f"      #1 {first['title']!r} {first['date']} {first['isbn']} "
                f"{first['summary'][:100]}"
            )

    series_ok = sum(1 for r in rows if r["series_ok"] and r["query"] != "Blacksad")
    series_total = sum(1 for r in rows if r["query"] != "Blacksad")
    vol_ok = sum(1 for r in rows if r["vol_n"] >= 1 and r["query"] != "Blacksad")
    payload = {
        "version": scraper.version,
        "fast": fast,
        "series_ok": series_ok,
        "series_total": series_total,
        "volume_ok": vol_ok,
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines.append("")
    lines.append(
        f"series={series_ok}/{series_total}  volumes={vol_ok}/{series_total}  "
        f"Blacksad miss attendu  → {OUT_JSON.name}"
    )
    text = "\n".join(lines) + "\n"
    OUT_TXT.write_text(text, encoding="utf-8")
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    return 0 if series_ok >= series_total * 0.6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
