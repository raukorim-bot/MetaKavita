"""
S6 — Fuites : mémoire, handles, threads, états en mémoire.

Ce qu'on éprouve : une passe longue (plusieurs dizaines de milliers d'unités)
et une série de passes répétées, pour voir si quelque chose croît sans jamais
redescendre — mémoire du process, handles Windows (fichiers + sockets), threads
non joints, dictionnaires globaux de module.

On mesure aussi le coût réel de l'émission Socket.IO faite à chaque série
(`_emit`) quand aucun serveur n'est démarré, puisque c'est le cas de tous les
threads de fond au démarrage du conteneur avant la première connexion navigateur.

Relance :
    python debug/stress/s6_leaks.py             # ~15 000 unités
    python debug/stress/s6_leaks.py --long      # ~45 000 unités
    python debug/stress/s6_leaks.py --mem-only  # seulement les points chauds mémoire
"""
from __future__ import annotations

import gc
import sys
import threading
import time

from _harness import (
    FakeKavitaAPI,
    FakeScraper,
    Patches,
    Report,
    banner,
    db_size_mb,
    handle_count,
    make_library,
    reset_job_state,
    rss_mb,
    temp_db,
    thread_count,
    unit_total,
    wait_idle,
    wire_volume_pass,
)


def scenario_long_pass(report, series_count=2500, volumes_per_series=6):
    """Une passe longue, échantillonnée en continu."""
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", series_count, volumes_per_series)])
    samples = []

    with temp_db() as (db, db_file), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()

        stop = threading.Event()

        def monitor():
            while not stop.is_set():
                state = job.get_volume_enrich_state()
                samples.append(
                    {
                        "done": state.get("done", 0),
                        "rss_mb": round(rss_mb(), 1),
                        "handles": handle_count(),
                        "threads": thread_count(),
                        "db_mb": round(db_size_mb(db_file), 2),
                    }
                )
                time.sleep(1.0)

        gc.collect()
        baseline = {"rss": rss_mb(), "handles": handle_count(),
                    "threads": thread_count()}
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        t0 = time.perf_counter()
        job.start_volume_enrich("all")
        finished, _ = wait_idle(timeout=3600)
        elapsed = time.perf_counter() - t0
        stop.set()
        watcher.join(timeout=5)
        gc.collect()
        time.sleep(0.5)

        quarters = [samples[int(len(samples) * f)] for f in (0.0, 0.25, 0.5, 0.75)]
        quarters.append(samples[-1])
        report.add(
            "passe longue",
            series=series_count,
            units=unit_total(volumes),
            duration_s=round(elapsed, 1),
            rss_baseline_mb=round(baseline["rss"], 1),
            rss_trace_mb=[s["rss_mb"] for s in quarters],
            rss_after_gc_mb=round(rss_mb(), 1),
            rss_growth_mb=round(rss_mb() - baseline["rss"], 1),
            handles_trace=[s["handles"] for s in quarters],
            handles_after=handle_count(),
            handles_growth=handle_count() - baseline["handles"],
            threads_trace=[s["threads"] for s in quarters],
            threads_after=thread_count(),
            db_mb=round(db_size_mb(db_file), 2),
            writes=api.write_count(),
            finished=finished,
        )
        if handle_count() - baseline["handles"] > 20:
            report.finding(
                "MAJEUR",
                "Handles non rendus après la passe",
                f"+{handle_count() - baseline['handles']} handles pour "
                f"{unit_total(volumes)} unités : une connexion SQLite non fermée "
                "par unité laisserait exactement cette trace.",
            )
        if rss_mb() - baseline["rss"] > 400:
            report.finding(
                "MOYEN",
                "Mémoire non rendue après la passe",
                f"+{rss_mb() - baseline['rss']:.0f} Mo après gc.collect().",
            )


def scenario_repeated_passes(report, rounds=25):
    """Vingt-cinq passes d'affilée : ce qui reste d'un tour à l'autre."""
    from kavita_api import KavitaAPI
    from services.provider_throttle import LAST_REQUEST_TIMES, _THROTTLE_LOCKS
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 40, 4)])
    trace = []

    with temp_db() as (db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])

        gc.collect()
        baseline = {"rss": rss_mb(), "handles": handle_count(),
                    "threads": thread_count()}
        for round_no in range(rounds):
            db.clear_volume_unit_states()
            reset_job_state()
            job.start_volume_enrich("all")
            wait_idle(timeout=300)
            if round_no % 5 == 0 or round_no == rounds - 1:
                gc.collect()
                trace.append(
                    {
                        "round": round_no,
                        "rss_mb": round(rss_mb(), 1),
                        "handles": handle_count(),
                        "threads": thread_count(),
                        "objects": len(gc.get_objects()),
                    }
                )

        report.add(
            f"{rounds} passes successives",
            trace=trace,
            rss_growth_mb=round(rss_mb() - baseline["rss"], 1),
            handles_growth=handle_count() - baseline["handles"],
            threads_growth=thread_count() - baseline["threads"],
            leftover_threads=[
                t.name for t in threading.enumerate() if t.name == "volume-enrich"
            ],
            throttle_entries=len(LAST_REQUEST_TIMES),
            throttle_locks=len(_THROTTLE_LOCKS),
            kavita_type_cache=len(KavitaAPI._series_lib_type_cache),
            job_state_keys=len(job._state),
        )
        if thread_count() - baseline["threads"] > 2:
            report.finding(
                "MAJEUR",
                "Threads de passe non terminés",
                f"+{thread_count() - baseline['threads']} threads après {rounds} passes.",
            )


def scenario_socketio_emit_cost(report):
    """Coût de `_emit` réel, sans serveur Socket.IO démarré."""
    from extensions import socketio

    payload = {"running": True, "done": 1, "total": 2000, "counts": {"done": 1}}
    failures = 0
    t0 = time.perf_counter()
    for _ in range(2000):
        try:
            socketio.emit("volume_enrich_progress", payload)
        except Exception:  # noqa: BLE001
            failures += 1
    elapsed = time.perf_counter() - t0
    report.add(
        "socketio.emit x2000 sans serveur",
        total_s=round(elapsed, 3),
        per_emit_ms=round(elapsed * 1000 / 2000, 3),
        exceptions=failures,
        rss_mb=round(rss_mb(), 1),
    )
    if elapsed / 2000 > 0.005:
        report.finding(
            "MOYEN",
            "Émission Socket.IO coûteuse à vide",
            f"{elapsed * 1000 / 2000:.1f} ms par émission sans serveur : une passe "
            "de 2 000 séries y passe "
            f"{elapsed:.0f} s (services/volume_enrichment/job.py:50).",
        )


def scenario_memory_hotspots(report):
    """Où la passe consomme de la mémoire : grosse série, index géant, gros plan."""
    from _harness import FakeScraper as _FakeScraper  # index paramétrable
    from services.volume_enrichment import job

    cases = [
        ("20 séries de 300 tomes", [("long", 20, 300)], "ok"),
        ("index géant 20 000 entrées x 4 ko", [("long", 2, 300)], "giant"),
        ("2000 séries de 3 tomes", [("normal", 2000, 3)], "ok"),
    ]
    for label, spec, mode in cases:
        series, volumes = make_library(spec)
        with temp_db() as (_db, db_file), Patches() as patches:
            api = FakeKavitaAPI(series, volumes)
            scraper = _FakeScraper("FAKEVINE", mode=mode)
            wire_volume_pass(patches, api, [scraper])
            reset_job_state()
            gc.collect()
            before = rss_mb()
            peak = {"rss": before}
            stop = threading.Event()

            def watch():
                while not stop.is_set():
                    peak["rss"] = max(peak["rss"], rss_mb())
                    time.sleep(0.2)

            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            job.start_volume_enrich("all")
            wait_idle(timeout=1800)
            stop.set()
            watcher.join(timeout=5)
            gc.collect()
            after_pass = rss_mb()
            units, writes = unit_total(volumes), api.write_count()

        # Le double retient l'état de chaque chapitre écrit : sans le libérer,
        # sa propre empreinte serait imputée à l'application.
        del api, series, volumes
        gc.collect()
        report.add(
            f"mémoire :: {label}",
            rss_before_mb=round(before, 1),
            rss_peak_mb=round(peak["rss"], 1),
            rss_after_pass_mb=round(after_pass, 1),
            rss_after_double_freed_mb=round(rss_mb(), 1),
            peak_growth_mb=round(peak["rss"] - before, 1),
            retained_by_app_mb=round(rss_mb() - before, 1),
            units=units,
            writes=writes,
        )
        if peak["rss"] - before > 250:
                report.finding(
                    "MOYEN",
                    f"Pic mémoire de {peak['rss'] - before:.0f} Mo ({label})",
                    "l'index fournisseur et le plan complet d'une série vivent en "
                    "mémoire en même temps (providers.py:106, plan.py:130).",
                )


def main():
    long_run = "--long" in sys.argv
    report = Report("s6_leaks")

    if "--mem-only" in sys.argv:
        banner("S6 — points chauds mémoire")
        scenario_memory_hotspots(report)
        report.save()
        return

    banner("S6 — coût de l'émission Socket.IO")
    scenario_socketio_emit_cost(report)

    banner("S6 — passes répétées")
    scenario_repeated_passes(report)

    banner("S6 — passe longue")
    scenario_long_pass(
        report,
        series_count=5000 if long_run else 2500,
        volumes_per_series=9 if long_run else 6,
    )

    banner("S6 — points chauds mémoire")
    scenario_memory_hotspots(report)

    report.save()


if __name__ == "__main__":
    main()
