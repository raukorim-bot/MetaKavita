"""
S3 — Concurrence : passe par tome, scan d'hygiène et trafic HTTP en même temps.

Ce qu'on éprouve : les trois gros consommateurs de MetaKavita qui tournent
ensemble sur la même base SQLite (`services/volume_enrichment/job.py`,
`services/library_audit/hygiene_scan.py`, plus un écrivain « sync » qui met à
jour `series_cache`), le trafic HTTP pendant une passe, et les états globaux de
module (`_state` sous verrou) sous sollicitation.

Ce qu'on mesure : erreurs `database is locked`, latence des requêtes HTTP
(p50/p95/max) pendant la passe, débit de chaque acteur, threads restés marqués
`running`, cohérence des compteurs à la fin.

Aucun réseau, aucune écriture Kavita, base SQLite temporaire jetée à la fin.

Relance :
    python debug/stress/s3_concurrency.py
"""
from __future__ import annotations

import sqlite3
import threading
import time

from _harness import (
    FakeKavitaAPI,
    FakeScraper,
    Patches,
    Report,
    banner,
    make_library,
    percentile,
    reset_job_state,
    temp_db,
    unit_total,
    wait_idle,
    wire_volume_pass,
)


def _wire_hygiene(patches, api, config=None):
    """Branche le scan d'hygiène sur le double, sans appel fournisseur."""
    from services.library_audit import hygiene_scan

    cfg = {"KAVITA_URL": "http://double", "KAVITA_API_KEY": "double"}
    cfg.update(config or {})
    patches.attr(hygiene_scan, "load_config", lambda: cfg)
    patches.attr(hygiene_scan, "KavitaAPI", lambda url, key: api)
    patches.attr(
        hygiene_scan,
        "resolve_catalog_expected",
        lambda **kw: {"status": "ok", "expected": 12, "provider": "DOUBLE"},
    )
    patches.attr(hygiene_scan, "_emit", lambda event, payload: None)
    patches.attr(hygiene_scan, "_emit_progress", lambda payload: None)
    return cfg


def _wait_hygiene_idle(timeout=1800):
    from services.library_audit import hygiene_scan

    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if not hygiene_scan.get_hygiene_scan_state()["running"]:
            return True
        time.sleep(0.02)
    return False


def _reset_hygiene_state():
    from services.library_audit import hygiene_scan

    with hygiene_scan._lock:
        hygiene_scan._state.update(
            {"running": False, "cancelled": False, "done": 0, "total": 0, "counts": {}}
        )


class LockCounter:
    """Compte les `database is locked` levés n'importe où pendant le scénario."""

    def __init__(self):
        self.locked = 0
        self.other = 0
        self.samples = []
        self.lock = threading.Lock()

    def record(self, exc):
        with self.lock:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                self.locked += 1
            else:
                self.other += 1
            if len(self.samples) < 5:
                self.samples.append(str(exc))


def scenario_three_writers(report):
    """Passe par tome + scan d'hygiène + écritures `series_cache` en parallèle."""
    from services.library_audit import hygiene_scan
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 600, 5)])
    counter = LockCounter()

    with temp_db() as (db, db_file), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        _wire_hygiene(patches, api)
        reset_job_state()
        _reset_hygiene_state()

        stop = threading.Event()
        sync_writes = {"n": 0}
        sync_latencies = []

        def sync_writer():
            """Imite la file de synchronisation : écritures `series_cache`."""
            from models import SeriesOverride

            i = 0
            while not stop.is_set():
                i += 1
                t0 = time.perf_counter()
                try:
                    db.save_series_override(
                        SeriesOverride(
                            series_id=(i % 600) + 1,
                            forced_id=str(i),
                            forced_provider="ANILIST",
                        )
                    )
                    sync_writes["n"] += 1
                except sqlite3.Error as exc:
                    counter.record(exc)
                sync_latencies.append(time.perf_counter() - t0)
                time.sleep(0.002)

        reader_latencies = []

        def dashboard_reader():
            """Imite le tableau de bord : lectures fréquentes pendant la passe."""
            while not stop.is_set():
                t0 = time.perf_counter()
                try:
                    db.get_all_cached_data()
                    db.count_volume_units_by_status()
                    db.list_enriched_series_ids()
                except sqlite3.Error as exc:
                    counter.record(exc)
                reader_latencies.append(time.perf_counter() - t0)
                time.sleep(0.01)

        writers = [threading.Thread(target=sync_writer, daemon=True) for _ in range(2)]
        readers = [threading.Thread(target=dashboard_reader, daemon=True) for _ in range(2)]
        for thread in writers + readers:
            thread.start()

        t0 = time.perf_counter()
        job.start_volume_enrich("all")
        hygiene_scan.start_hygiene_scan("all", with_catalog=True)
        volume_ok, _ = wait_idle(timeout=1800)
        hygiene_ok = _wait_hygiene_idle(timeout=1800)
        elapsed = time.perf_counter() - t0
        stop.set()
        for thread in writers + readers:
            thread.join(timeout=5)

        vol_state = job.get_volume_enrich_state()
        hyg_state = hygiene_scan.get_hygiene_scan_state()

        report.add(
            "passe + hygiène + sync + dashboard",
            series=len(series),
            units=unit_total(volumes),
            duration_s=round(elapsed, 2),
            db_locked_errors=counter.locked,
            other_sqlite_errors=counter.other,
            sqlite_error_samples=counter.samples,
            volume_done=vol_state.get("done"),
            volume_counts=vol_state.get("counts"),
            volume_writes=api.write_count(),
            hygiene_done=hyg_state.get("done"),
            hygiene_counts_series=(hyg_state.get("counts") or {}).get("series"),
            sync_writes=sync_writes["n"],
            sync_p95_ms=round(percentile(sync_latencies, 95) * 1000, 1),
            sync_max_ms=round(max(sync_latencies or [0]) * 1000, 1),
            dashboard_p95_ms=round(percentile(reader_latencies, 95) * 1000, 1),
            dashboard_max_ms=round(max(reader_latencies or [0]) * 1000, 1),
            volume_finished=volume_ok,
            hygiene_finished=hygiene_ok,
            threads_left=[
                t.name
                for t in threading.enumerate()
                if t.name in ("volume-enrich", "hygiene-scan")
            ],
        )

        if counter.locked:
            report.finding(
                "MAJEUR",
                "SQLite verrouillée sous charge concurrente",
                f"{counter.locked} erreurs `database is locked` : {counter.samples}",
            )
        if max(sync_latencies or [0]) > 5.0:
            report.finding(
                "MOYEN",
                "Écriture `series_cache` bloquée plusieurs secondes",
                f"pic à {max(sync_latencies) * 1000:.0f} ms pendant la passe.",
            )


def scenario_http_during_pass(report):
    """Trafic HTTP pendant une passe : latence des routes et cohérence de l'état."""
    import routes.volume_enrichment as routes_ve
    from flask import Flask

    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 800, 4)])

    with temp_db() as (db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        patches.attr(
            routes_ve,
            "load_config",
            lambda: {"UI_LANG": "fr", "VOLUME_ENRICHMENT_ENABLED": True},
        )
        reset_job_state()

        app = Flask(__name__)
        app.secret_key = "stress"
        app.register_blueprint(routes_ve.volume_enrichment_bp)

        latencies = {"status": [], "start": []}
        errors = {"n": 0, "samples": []}
        stop = threading.Event()
        busy_replies = {"n": 0}

        def poller():
            client = app.test_client()
            while not stop.is_set():
                t0 = time.perf_counter()
                try:
                    response = client.get("/api/volume-enrich/status")
                    if response.status_code != 200:
                        errors["n"] += 1
                except Exception as exc:  # noqa: BLE001
                    errors["n"] += 1
                    if len(errors["samples"]) < 3:
                        errors["samples"].append(str(exc))
                latencies["status"].append(time.perf_counter() - t0)
                time.sleep(0.005)

        def start_spammer():
            """Un onglet resté ouvert qui reclique « Lancer » : doit toujours 409."""
            client = app.test_client()
            while not stop.is_set():
                t0 = time.perf_counter()
                response = client.post("/api/libraries/1/volume-enrich", json={})
                if response.status_code == 409:
                    busy_replies["n"] += 1
                elif response.status_code == 200 and response.get_json().get("started"):
                    errors["n"] += 1
                    errors["samples"].append("une seconde passe a démarré")
                latencies["start"].append(time.perf_counter() - t0)
                time.sleep(0.02)

        pollers = [threading.Thread(target=poller, daemon=True) for _ in range(8)]
        spammer = threading.Thread(target=start_spammer, daemon=True)

        t0 = time.perf_counter()
        job.start_volume_enrich("all")
        for thread in pollers:
            thread.start()
        spammer.start()
        finished, _ = wait_idle(timeout=1800)
        elapsed = time.perf_counter() - t0
        stop.set()
        for thread in [*pollers, spammer]:
            thread.join(timeout=5)

        report.add(
            "HTTP pendant la passe",
            duration_s=round(elapsed, 2),
            status_requests=len(latencies["status"]),
            status_p50_ms=round(percentile(latencies["status"], 50) * 1000, 2),
            status_p95_ms=round(percentile(latencies["status"], 95) * 1000, 2),
            status_max_ms=round(max(latencies["status"] or [0]) * 1000, 2),
            start_requests=len(latencies["start"]),
            start_p95_ms=round(percentile(latencies["start"], 95) * 1000, 2),
            busy_409=busy_replies["n"],
            http_errors=errors["n"],
            samples=errors["samples"],
            writes=api.write_count(),
            finished=finished,
        )
        if errors["n"]:
            report.finding(
                "MAJEUR",
                "Requêtes HTTP en erreur pendant la passe",
                f"{errors['n']} erreurs : {errors['samples']}",
            )
        if max(latencies["status"] or [0]) > 1.0:
            report.finding(
                "MOYEN",
                "Route d'état bloquée pendant la passe",
                f"pic à {max(latencies['status']) * 1000:.0f} ms sur "
                "/api/volume-enrich/status.",
            )


def scenario_state_isolation(report):
    """Passe et scan démarrés en boucle : les deux états globaux ne se mélangent pas."""
    from services.library_audit import hygiene_scan
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 60, 3)])
    with temp_db() as (_db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes, write_delay=0.001)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        _wire_hygiene(patches, api)

        anomalies = []
        for round_no in range(6):
            reset_job_state()
            _reset_hygiene_state()
            job.start_volume_enrich("all")
            hygiene_scan.start_hygiene_scan("all")
            # Annulation croisée : on annule le scan, la passe doit continuer.
            time.sleep(0.05)
            hygiene_scan.cancel_hygiene_scan()
            volume_ok, _ = wait_idle(timeout=300)
            hygiene_ok = _wait_hygiene_idle(timeout=300)
            vol = job.get_volume_enrich_state()
            if vol.get("cancelled"):
                anomalies.append(
                    f"tour {round_no}: la passe tomes est marquée annulée alors que "
                    "seul le scan d'hygiène l'a été"
                )
            if not volume_ok or not hygiene_ok:
                anomalies.append(f"tour {round_no}: un thread est resté `running`")

        report.add(
            "annulations croisées x6",
            anomalies=len(anomalies),
            detail=anomalies[:3],
            leftover_threads=[
                t.name
                for t in threading.enumerate()
                if t.name in ("volume-enrich", "hygiene-scan")
            ],
        )
        if anomalies:
            report.finding("MOYEN", "États globaux mêlés", str(anomalies[:3]))


def main():
    report = Report("s3_concurrency")

    banner("S3 — trois écrivains sur la même base")
    scenario_three_writers(report)

    banner("S3 — trafic HTTP pendant la passe")
    scenario_http_during_pass(report)

    banner("S3 — isolation des états globaux")
    scenario_state_isolation(report)

    report.save()


if __name__ == "__main__":
    main()
