"""
S4 — SQLite sous charge.

Ce qu'on éprouve : le coût unitaire des écritures de `db_manager.py` (une
connexion neuve, deux PRAGMA et un `CREATE TABLE IF NOT EXISTS` par appel), la
tenue sous écritures concurrentes dans `volume_unit_cache`, `series_cache` et
les tables d'hygiène, la taille de la base après une grosse passe, et la
dégradation des requêtes fréquentes quand la table grossit.

Ce qu'on mesure : ops/s, latences p50/p95/p99, erreurs `database is locked`,
octets par ligne, temps des requêtes du tableau de bord à 10 k / 50 k / 200 k
unités en cache.

Base SQLite temporaire locale, jetée à la fin. Aucun réseau.

Relance :
    python debug/stress/s4_sqlite_load.py
"""
from __future__ import annotations

import sqlite3
import threading
import time

from _harness import (
    Patches,
    Report,
    banner,
    db_size_mb,
    percentile,
    temp_db,
)


def _timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    fn(*args, **kwargs)
    return time.perf_counter() - t0


def scenario_unit_write_cost(report):
    """Coût d'une écriture d'unité, seule, et comparaison avec un INSERT direct."""
    with temp_db() as (db, db_file):
        latencies = [
            _timed(db.save_volume_unit_state, 1, cid, "DONE", provider="FAKEVINE",
                   written_fields=["summary", "title"])
            for cid in range(1, 2001)
        ]
        size_after = db_size_mb(db_file)

        # Même volume d'écritures, mais une seule connexion et un seul commit :
        # mesure le prix payé par le « une connexion par appel ».
        conn = sqlite3.connect(db_file, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        t0 = time.perf_counter()
        conn.executemany(
            "INSERT OR REPLACE INTO volume_unit_cache (series_id, chapter_id, status, "
            "updated_at) VALUES (?, ?, ?, ?)",
            [(2, cid, "DONE", "2026-01-01") for cid in range(1, 2001)],
        )
        conn.commit()
        batched = time.perf_counter() - t0
        conn.close()

        per_call = sum(latencies) / len(latencies)
        report.add(
            "écriture unité (db_manager)",
            calls=len(latencies),
            total_s=round(sum(latencies), 2),
            mean_ms=round(per_call * 1000, 3),
            p50_ms=round(percentile(latencies, 50) * 1000, 3),
            p95_ms=round(percentile(latencies, 95) * 1000, 3),
            p99_ms=round(percentile(latencies, 99) * 1000, 3),
            ops_per_s=round(1 / per_call, 1),
            db_mb=round(size_after, 3),
        )
        report.add(
            "même volume, une connexion + un commit",
            total_s=round(batched, 3),
            speedup=round(sum(latencies) / max(batched, 1e-6), 1),
        )
        if per_call > 0.003:
            report.finding(
                "MOYEN",
                "Une connexion SQLite complète par unité écrite",
                f"{per_call * 1000:.1f} ms par appel de `save_volume_unit_state` "
                "(db_manager.py:1504) : connexion neuve, PRAGMA journal_mode + "
                "busy_timeout, CREATE TABLE IF NOT EXISTS, INSERT, commit. Sur une "
                f"passe de 20 000 tomes cela représente "
                f"{per_call * 20000:.0f} s de base seule.",
            )


def scenario_concurrent_writers(report):
    """1, 2, 4, 8 écrivains concurrents sur les trois tables chaudes."""
    from models import SeriesOverride

    for writers in (1, 2, 4, 8):
        with temp_db() as (db, db_file):
            errors = {"locked": 0, "other": 0, "samples": []}
            latencies = []
            guard = threading.Lock()
            per_thread = 400

            def worker(index):
                local = []
                for i in range(per_thread):
                    kind = i % 3
                    t0 = time.perf_counter()
                    try:
                        if kind == 0:
                            db.save_volume_unit_state(
                                index * 100000 + i, i + 1, "DONE",
                                provider="FAKEVINE", written_fields=["summary"]
                            )
                        elif kind == 1:
                            db.save_series_override(
                                SeriesOverride(
                                    series_id=index * 1000 + i,
                                    forced_id=str(i),
                                    forced_provider="ANILIST",
                                )
                            )
                        else:
                            db.save_volume_report_cache(
                                index * 1000 + i,
                                {
                                    "badge": "12/12",
                                    "completion": {"state": "complete",
                                                   "missing_count": 0},
                                    "stats": {"primary_count": 12},
                                    "catalog": {"status": "ok", "expected": 12},
                                },
                            )
                    except sqlite3.Error as exc:
                        with guard:
                            if "locked" in str(exc).lower():
                                errors["locked"] += 1
                            else:
                                errors["other"] += 1
                            if len(errors["samples"]) < 3:
                                errors["samples"].append(str(exc))
                    local.append(time.perf_counter() - t0)
                with guard:
                    latencies.extend(local)

            threads = [
                threading.Thread(target=worker, args=(n,)) for n in range(writers)
            ]
            t0 = time.perf_counter()
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            elapsed = time.perf_counter() - t0

            report.add(
                f"{writers} écrivain(s) concurrent(s)",
                ops=writers * per_thread,
                duration_s=round(elapsed, 2),
                ops_per_s=round(writers * per_thread / max(elapsed, 1e-6), 1),
                p50_ms=round(percentile(latencies, 50) * 1000, 2),
                p95_ms=round(percentile(latencies, 95) * 1000, 2),
                p99_ms=round(percentile(latencies, 99) * 1000, 2),
                max_ms=round(max(latencies) * 1000, 1),
                db_locked=errors["locked"],
                other_errors=errors["other"],
                samples=errors["samples"],
                db_mb=round(db_size_mb(db_file), 3),
            )
            if errors["locked"]:
                report.finding(
                    "MAJEUR",
                    f"`database is locked` à {writers} écrivains",
                    f"{errors['locked']} erreurs : {errors['samples']}",
                )


def scenario_query_growth(report):
    """Requêtes fréquentes du tableau de bord quand `volume_unit_cache` grossit."""
    with temp_db() as (db, db_file):
        conn = sqlite3.connect(db_file, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        inserted = 0
        for target in (10_000, 50_000, 200_000):
            rows = []
            while inserted < target:
                series_id = inserted // 20 + 1
                rows.append(
                    (series_id, inserted + 1, None, "1", "1", "DONE", "FAKEVINE",
                     '["summary"]', "2026-01-01T00:00:00")
                )
                inserted += 1
            conn.executemany(
                "INSERT OR REPLACE INTO volume_unit_cache (series_id, chapter_id, "
                "volume_id, volume_number, chapter_number, status, provider, "
                "written_fields, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            # Une série sur vingt est close, comme après une passe.
            conn.executemany(
                "INSERT OR REPLACE INTO volume_unit_cache (series_id, chapter_id, "
                "status, updated_at) VALUES (?, 0, 'SERIES_DONE', '2026-01-01')",
                [(sid,) for sid in range(1, target // 20 + 1)],
            )
            conn.commit()

            timings = {
                "list_enriched_series_ids": _timed(db.list_enriched_series_ids),
                "count_by_status": _timed(db.count_volume_units_by_status),
                "get_volume_unit_states(1)": _timed(db.get_volume_unit_states, 1),
                "get_all_cached_data": _timed(db.get_all_cached_data),
            }
            report.add(
                f"requêtes à {target:,} unités".replace(",", " "),
                db_mb=round(db_size_mb(db_file), 2),
                bytes_per_row=round(db_size_mb(db_file) * 1024 * 1024 / target, 1),
                **{name: round(value * 1000, 2) for name, value in timings.items()},
            )
            if timings["count_by_status"] > 0.5:
                report.finding(
                    "MOYEN",
                    "Comptage global lent",
                    f"`count_volume_units_by_status` prend "
                    f"{timings['count_by_status'] * 1000:.0f} ms à {target} unités "
                    "(db_manager.py:1593, GROUP BY sans index sur `status`).",
                )
        conn.close()


def scenario_reads_under_write_load(report):
    """Lectures du tableau de bord pendant que quatre écrivains travaillent.

    S3 a vu une lecture bloquée onze secondes : ce scénario isole la fonction
    responsable et le moment où le blocage tombe.
    """
    from models import SeriesOverride

    with temp_db() as (db, db_file):
        # Base déjà peuplée, comme après une passe.
        for sid in range(1, 400):
            db.save_series_override(SeriesOverride(series_id=sid, forced_id=str(sid)))
        conn = sqlite3.connect(db_file, timeout=30.0)
        conn.executemany(
            "INSERT OR REPLACE INTO volume_unit_cache (series_id, chapter_id, status, "
            "updated_at) VALUES (?, ?, 'DONE', '2026-01-01')",
            [(cid // 20 + 1, cid) for cid in range(1, 20_001)],
        )
        conn.commit()
        conn.close()

        stop = threading.Event()
        write_errors = {"n": 0}

        def writer(index):
            i = 0
            while not stop.is_set():
                i += 1
                try:
                    db.save_volume_unit_state(
                        900_000 + index, i, "DONE", provider="FAKEVINE",
                        written_fields=["summary"]
                    )
                except sqlite3.Error:
                    write_errors["n"] += 1

        threads = [threading.Thread(target=writer, args=(n,), daemon=True)
                   for n in range(4)]
        for thread in threads:
            thread.start()
        time.sleep(0.5)

        readers = {
            "get_all_cached_data": db.get_all_cached_data,
            "list_enriched_series_ids": db.list_enriched_series_ids,
            "count_volume_units_by_status": db.count_volume_units_by_status,
            "get_volume_unit_states(1)": lambda: db.get_volume_unit_states(1),
            "get_volume_report_badges": db.get_volume_report_badges,
        }
        measured = {}
        for name, fn in readers.items():
            latencies = [_timed(fn) for _ in range(120)]
            measured[name] = latencies
            report.add(
                f"lecture sous 4 écrivains :: {name}",
                p50_ms=round(percentile(latencies, 50) * 1000, 2),
                p95_ms=round(percentile(latencies, 95) * 1000, 2),
                max_ms=round(max(latencies) * 1000, 1),
                slow_over_1s=sum(1 for value in latencies if value > 1.0),
            )
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

        worst = max(measured.items(), key=lambda kv: max(kv[1]))
        if max(worst[1]) > 1.0:
            report.finding(
                "MAJEUR",
                "Une lecture du tableau de bord peut bloquer plusieurs secondes",
                f"`{worst[0]}` : pic à {max(worst[1]) * 1000:.0f} ms sous quatre "
                "écrivains. Toutes les lectures de db_manager rouvrent une "
                "connexion et rejouent `_ensure_*` (ALTER/CREATE) avant de lire "
                "(db_manager.py:20, 33, 143).",
            )


def scenario_wal_growth(report):
    """Le WAL grossit-il sans fin quand les lecteurs sont permanents ?"""
    with temp_db() as (db, db_file):
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    db.count_volume_units_by_status()
                except sqlite3.Error:
                    pass

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        sizes = []
        for batch in range(6):
            for cid in range(1000):
                db.save_volume_unit_state(batch + 1, cid + 1, "DONE")
            import os

            wal = db_file + "-wal"
            sizes.append(round(os.path.getsize(wal) / (1024 * 1024), 2)
                         if os.path.exists(wal) else 0.0)
        stop.set()
        thread.join(timeout=5)
        report.add(
            "WAL sous lecteur permanent",
            wal_mb_per_batch=sizes,
            db_mb=round(db_size_mb(db_file), 2),
        )
        if sizes and sizes[-1] > 20:
            report.finding(
                "MOYEN",
                "WAL non recyclé sous lecture permanente",
                f"le journal atteint {sizes[-1]} Mo : un lecteur toujours ouvert "
                "empêche le checkpoint automatique.",
            )


def main():
    report = Report("s4_sqlite_load")

    banner("S4 — coût d'une écriture d'unité")
    scenario_unit_write_cost(report)

    banner("S4 — écrivains concurrents")
    scenario_concurrent_writers(report)

    banner("S4 — croissance de la base et requêtes fréquentes")
    scenario_query_growth(report)

    banner("S4 — lectures pendant les écritures")
    scenario_reads_under_write_load(report)

    banner("S4 — croissance du WAL")
    scenario_wal_growth(report)

    report.save()


if __name__ == "__main__":
    main()
