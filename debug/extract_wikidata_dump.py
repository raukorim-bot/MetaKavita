#!/usr/bin/env python3
"""
Extrait manga / comic / book depuis un dump Wikidata JSON.bz2 (streaming).

Usage :
  PYTHONUNBUFFERED=1 python3 -u debug/extract_wikidata_dump.py \\
    --dump ~/wikidata-dump/latest-all.json.bz2 \\
    --out data/wikidata.db \\
    --type manga \\
    2>&1 | tee -a data/wikidata_extract.log

Le dump n'est JAMAIS chargé en RAM : lecture ligne à ligne (.json.bz2).
"""
from __future__ import annotations

import argparse
import bz2
import json
import os
import sqlite3
import sys
import time
from typing import Dict, Iterable, List, Optional, Set

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scrapers.wikidata_map import (
    TYPE_QIDS,
    entity_to_candidate,
    extract_instance_qids,
    labels_map,
    _entity_ids_from_claims,
    P_AUTHOR,
    P_CREATOR,
    P_ILLUSTRATOR,
    P_PUBLISHER,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    qid TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    titles_json TEXT,
    alt_json TEXT,
    summary TEXT,
    year INTEGER,
    status TEXT,
    staff_json TEXT,
    publisher TEXT,
    isbn TEXT,
    cover_url TEXT,
    ids_json TEXT,
    fetch_status TEXT DEFAULT 'ok',
    error TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_title ON entities(title);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    title,
    alt_json,
    content='entities',
    content_rowid='rowid'
);
"""


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    try:
        conn.executescript(FTS_SQL)
    except sqlite3.OperationalError:
        pass
    return conn


def open_dump(path: str) -> Iterable[str]:
    if path.endswith(".bz2"):
        with bz2.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                yield line
    else:
        with open(path, "rt", encoding="utf-8") as f:
            for line in f:
                yield line


def allowed_types(kind: str) -> Dict[str, Set[str]]:
    if kind == "all":
        return TYPE_QIDS
    key = {"manga": "Manga", "comic": "Comic", "book": "Book"}[kind]
    return {key: TYPE_QIDS[key]}


def match_library_type(entity: dict, type_map: Dict[str, Set[str]]) -> Optional[str]:
    inst = extract_instance_qids(entity)
    # Priorité Manga > Comic > Book si overlap
    for lib in ("Manga", "Comic", "Book"):
        if lib in type_map and inst & type_map[lib]:
            return lib
    return None


def local_label_lookup(entity: dict) -> Dict[str, str]:
    """Sans 2e passe API : labels absents pour auteurs → on garde le Q-id."""
    # Les claims ne portent que des Q-ids ; le dump ne joint pas les labels.
    # On laisse entity_to_candidate utiliser le Q-id tant que non résolu.
    return {}


def candidate_to_row(candidate: dict, library_type: str) -> dict:
    return {
        "qid": candidate.get("wikidata_id") or "",
        "type": library_type,
        "title": candidate.get("title") or "",
        "titles_json": json.dumps(candidate.get("titles") or [], ensure_ascii=False),
        "alt_json": json.dumps(candidate.get("alternative_titles") or [], ensure_ascii=False),
        "summary": candidate.get("summary") or "",
        "year": candidate.get("year"),
        "status": candidate.get("status"),
        "staff_json": json.dumps(candidate.get("staff") or [], ensure_ascii=False),
        "publisher": candidate.get("publisher"),
        "isbn": candidate.get("isbn"),
        "cover_url": candidate.get("cover_url"),
        "ids_json": json.dumps(
            {
                "anilist_id": candidate.get("anilist_id"),
                "mal_id": candidate.get("mal_id"),
                "url": candidate.get("url"),
                "external_links": candidate.get("external_links") or [],
            },
            ensure_ascii=False,
        ),
    }


def upsert(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """
        INSERT INTO entities (
            qid, type, title, titles_json, alt_json, summary, year, status,
            staff_json, publisher, isbn, cover_url, ids_json, fetch_status, updated_at
        ) VALUES (
            :qid, :type, :title, :titles_json, :alt_json, :summary, :year, :status,
            :staff_json, :publisher, :isbn, :cover_url, :ids_json, 'ok', datetime('now')
        )
        ON CONFLICT(qid) DO UPDATE SET
            type=excluded.type,
            title=excluded.title,
            titles_json=excluded.titles_json,
            alt_json=excluded.alt_json,
            summary=excluded.summary,
            year=excluded.year,
            status=excluded.status,
            staff_json=excluded.staff_json,
            publisher=excluded.publisher,
            isbn=excluded.isbn,
            cover_url=excluded.cover_url,
            ids_json=excluded.ids_json,
            fetch_status='ok',
            updated_at=datetime('now')
        """,
        row,
    )


def rebuild_fts(conn: sqlite3.Connection):
    try:
        conn.execute("INSERT INTO entities_fts(entities_fts) VALUES('rebuild')")
    except sqlite3.OperationalError:
        try:
            conn.execute("DELETE FROM entities_fts")
            conn.execute(
                "INSERT INTO entities_fts(rowid, title, alt_json) "
                "SELECT rowid, title, alt_json FROM entities"
            )
        except sqlite3.OperationalError as e:
            print(f"[warn] FTS: {e}")


def parse_args():
    p = argparse.ArgumentParser(description="Extract manga/comic/book from Wikidata JSON dump")
    p.add_argument("--dump", required=True, help="Chemin latest-all.json.bz2")
    p.add_argument("--out", default=os.path.join("data", "wikidata.db"))
    p.add_argument("--type", choices=["manga", "comic", "book", "all"], default="manga")
    p.add_argument("--commit-every", type=int, default=500)
    p.add_argument("--progress-every", type=int, default=100000)
    p.add_argument("--max-keep", type=int, default=None, help="Stop after N kept entities (test)")
    return p.parse_args()


def main():
    args = parse_args()
    if not os.path.isfile(args.dump):
        print(f"[fatal] dump introuvable: {args.dump}", file=sys.stderr)
        sys.exit(1)

    type_map = allowed_types(args.type)
    allowed_qids: Set[str] = set()
    for s in type_map.values():
        allowed_qids |= s

    conn = connect(args.out)
    scanned = kept = 0
    t0 = time.time()
    print(f"[extract] dump={args.dump}")
    print(f"[extract] out={args.out} type={args.type} filter_qids={len(allowed_qids)}")

    try:
        for line in open_dump(args.dump):
            scanned += 1
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                entity = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entity.get("type") != "item":
                continue
            # Fast reject: no P31 intersection with our set (direct only — no P279*)
            inst = extract_instance_qids(entity)
            if not inst & allowed_qids:
                if scanned % args.progress_every == 0:
                    elapsed = time.time() - t0
                    rate = scanned / elapsed if elapsed else 0
                    print(f"[progress] scanned={scanned:,} kept={kept:,} rate={rate:,.0f} lines/s")
                continue

            lib = match_library_type(entity, type_map)
            if not lib:
                continue
            cand = entity_to_candidate(entity, label_lookup=local_label_lookup(entity), library_type=lib)
            if not cand:
                continue
            row = candidate_to_row(cand, lib)
            if not row["qid"]:
                continue
            upsert(conn, row)
            kept += 1
            if kept % 50 == 0:
                print(f"    [keep] {row['qid']} {row['title'][:70]}")
            if kept % args.commit_every == 0:
                conn.commit()
            if args.max_keep and kept >= args.max_keep:
                print(f"[extract] max-keep={args.max_keep} reached")
                break
            if scanned % args.progress_every == 0:
                elapsed = time.time() - t0
                rate = scanned / elapsed if elapsed else 0
                print(f"[progress] scanned={scanned:,} kept={kept:,} rate={rate:,.0f} lines/s")

        conn.commit()
        rebuild_fts(conn)
        conn.commit()
        size_mb = os.path.getsize(args.out) / (1024 * 1024)
        print(f"[done] scanned={scanned:,} kept={kept:,} → {args.out} ({size_mb:.1f} MiB)")
        print("Note: staff/publisher peuvent rester en Q-id (pas de jointure labels dans le dump stream).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
