"""
S2 — Annulation et reprise de la passe par tome.

Ce qu'on éprouve : annuler une passe au milieu, la relancer, et vérifier
qu'aucune unité n'est perdue ni écrite deux fois. On mesure aussi la latence
réelle de l'annulation, y compris quand elle tombe pendant un appel fournisseur
lent (le cas Bédéthèque, dont l'index prend des minutes).

Ce qu'on mesure : latence d'annulation (demande -> `running=False`), unités
écrites avant/après, doublons d'écriture, séries réinterrogées à la reprise,
coût fournisseur de la reprise.

Aucun réseau, aucune écriture Kavita, base SQLite temporaire jetée à la fin.

Relance :
    python debug/stress/s2_cancel_resume.py
"""
from __future__ import annotations

import threading
import time

from _harness import (
    FakeKavitaAPI,
    FakeScraper,
    Patches,
    Report,
    banner,
    make_index,
    make_library,
    reset_job_state,
    temp_db,
    unit_total,
    wait_idle,
    wire_volume_pass,
)


def _filled(api):
    """Chapitres dont le résumé est renseigné côté double."""
    with api.lock:
        return {cid for cid, ch in api._chapters.items() if (ch.get("summary") or "")}


def scenario_cancel_then_resume(report, *, force=False):
    """Annuler à mi-parcours puis relancer : rien de perdu, rien de refait."""
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 400, 5)])
    total_units = unit_total(volumes)
    label = f"annulation+reprise (force={force})"

    with temp_db() as (db, db_file), Patches() as patches:
        api = FakeKavitaAPI(series, volumes, write_delay=0.001)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()

        job.start_volume_enrich("all", force=force)
        # Laisser la passe entrer franchement dans le lot avant de couper.
        deadline = time.perf_counter() + 30
        while time.perf_counter() < deadline:
            if job.get_volume_enrich_state().get("done", 0) >= 60:
                break
            time.sleep(0.01)

        done_at_cancel = job.get_volume_enrich_state().get("done", 0)
        writes_at_cancel = api.write_count()
        t_cancel = time.perf_counter()
        job.cancel_volume_enrich()
        finished, _ = wait_idle(timeout=120)
        cancel_latency = time.perf_counter() - t_cancel

        first_pass_writes = api.write_count()
        first_series_closed = len(db.list_enriched_series_ids())
        provider_calls_first = scraper.calls
        state_after_cancel = dict(job.get_volume_enrich_state())

        # Reprise : la passe repart, resume=True par défaut.
        api.writes.clear()
        api.calls.clear()
        scraper.calls = 0
        reset_job_state()
        t0 = time.perf_counter()
        job.start_volume_enrich("all", force=force)
        wait_idle(timeout=900)
        resume_duration = time.perf_counter() - t0

        second_pass_writes = api.write_count()
        duplicates = len(api.duplicate_writes())
        filled = len(_filled(api))
        closed = len(db.list_enriched_series_ids())

        report.add(
            label,
            series=len(series),
            units=total_units,
            done_at_cancel=done_at_cancel,
            writes_at_cancel=writes_at_cancel,
            cancel_latency_ms=round(cancel_latency * 1000, 1),
            writes_pass1=first_pass_writes,
            series_closed_pass1=first_series_closed,
            provider_calls_pass1=provider_calls_first,
            skipped_on_resume=state_after_cancel.get("skipped"),
            writes_pass2=second_pass_writes,
            provider_calls_pass2=scraper.calls,
            resume_duration_s=round(resume_duration, 2),
            duplicate_writes_pass2=duplicates,
            chapters_filled=filled,
            series_closed_total=closed,
            cancelled_flag_after=state_after_cancel.get("cancelled"),
        )

        if filled != total_units:
            report.finding(
                "MAJEUR",
                "Unités perdues par le couple annulation/reprise",
                f"{label} : {filled}/{total_units} chapitres renseignés après les "
                "deux passes.",
            )
        overlap = first_pass_writes + second_pass_writes - total_units
        if overlap > 0:
            report.finding(
                "MAJEUR" if force else "MOYEN",
                "Unités réécrites à la reprise",
                f"{label} : {overlap} écritures en trop — la reprise ne consulte "
                "pas `volume_unit_cache` au niveau de l'unité "
                "(services/volume_enrichment/job.py:218, apply.py:133).",
            )
        return {"cancel_latency_ms": round(cancel_latency * 1000, 1)}


def scenario_cancel_during_slow_provider(report):
    """Annulation pendant un index fournisseur lent : latence réellement subie."""
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 40, 5)])
    with temp_db() as (_db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        # 4 s par index : l'ordre de grandeur d'un Bédéthèque (50 albums,
        # 2 s de pause chacun) est bien pire, on reste conservateur.
        scraper = FakeScraper("SLOWVINE", latency=4.0)
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()

        job.start_volume_enrich("all")
        time.sleep(1.0)  # la passe est dans l'appel fournisseur
        t_cancel = time.perf_counter()
        job.cancel_volume_enrich()
        finished, _ = wait_idle(timeout=120)
        latency = time.perf_counter() - t_cancel

        report.add(
            "annulation pendant index lent (4 s)",
            cancel_latency_ms=round(latency * 1000, 1),
            provider_latency_ms=4000,
            finished=finished,
        )
        if latency > 1.0:
            report.finding(
                "MOYEN",
                "L'annulation n'interrompt pas l'appel fournisseur en cours",
                f"latence mesurée {latency:.2f}s pour un index de 4 s : "
                "`fetch_index` ne teste `should_cancel` qu'entre deux "
                "fournisseurs (services/volume_enrichment/providers.py:128). Avec "
                "Bédéthèque (50 albums x 2 s de pause interne, "
                "scrapers/bedetheque.py:251) l'attente réelle se compte en minutes.",
            )


def scenario_cancel_during_long_series(report):
    """Annulation au milieu d'une série de 300 tomes : granularité de la reprise."""
    from services.volume_enrichment import job

    series, volumes = make_library([("long", 3, 300)])
    with temp_db() as (db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes, write_delay=0.002)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()

        job.start_volume_enrich("all")
        time.sleep(2.0)
        t_cancel = time.perf_counter()
        job.cancel_volume_enrich()
        wait_idle(timeout=120)
        latency = time.perf_counter() - t_cancel
        written_before = api.write_count()
        closed = db.list_enriched_series_ids()

        conn = db._connect()
        cached_units = conn.execute(
            "SELECT COUNT(*) FROM volume_unit_cache WHERE chapter_id != 0"
        ).fetchone()[0]
        conn.close()

        # Reprise, avec réécriture forcée : c'est le réglage
        # VOLUME_FORCE_OVERWRITE de la sidebar.
        api.writes.clear()
        scraper.calls = 0
        reset_job_state()
        job.start_volume_enrich("all", force=True)
        wait_idle(timeout=900)

        report.add(
            "annulation dans une série de 300 tomes",
            cancel_latency_ms=round(latency * 1000, 1),
            units_written_before_cancel=written_before,
            unit_rows_cached=cached_units,
            series_closed=len(closed),
            rewritten_on_forced_resume=api.write_count(),
            provider_calls_on_resume=scraper.calls,
        )
        if api.write_count() > 900 - written_before:
            report.finding(
                "MOYEN",
                "Reprise forcée : les unités déjà écrites repartent",
                f"{api.write_count()} écritures à la reprise alors que "
                f"{written_before} unités étaient déjà faites et tracées dans "
                "`volume_unit_cache` : `enrich_one_series` ne lit jamais cet état "
                "(services/volume_enrichment/job.py:154-192).",
            )


def scenario_cancel_races(report):
    """Annuler avant que le thread démarre, et annuler deux fois."""
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 200, 3)])
    with temp_db() as (_db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes, write_delay=0.002)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()

        job.start_volume_enrich("all")
        immediate = job.cancel_volume_enrich()  # sans laisser le thread démarrer
        wait_idle(timeout=60)
        report.add(
            "annulation immédiate",
            cancel_accepted=immediate.get("cancelled"),
            writes=api.write_count(),
            done=job.get_volume_enrich_state().get("done"),
        )

        idle_cancel = job.cancel_volume_enrich()
        report.add("annulation à vide", result=str(idle_cancel))

        # Redémarrage juste après l'annulation : le drapeau `cancelled` doit
        # être remis à zéro, sinon la nouvelle passe s'arrête aussitôt.
        reset_job_state()
        api.writes.clear()
        job.start_volume_enrich("all")
        wait_idle(timeout=300)
        state = job.get_volume_enrich_state()
        report.add(
            "redémarrage après annulation",
            writes=api.write_count(),
            done=state.get("done"),
            total=state.get("total"),
            cancelled_flag=state.get("cancelled"),
        )
        if state.get("cancelled"):
            report.finding(
                "MINEUR",
                "Le drapeau `cancelled` survit à la fin de la passe",
                "`get_volume_enrich_state()` rend cancelled=True alors que la "
                "passe suivante s'est terminée normalement "
                "(services/volume_enrichment/job.py:290-296).",
            )


def scenario_concurrent_starts(report):
    """Vingt démarrages simultanés : un seul thread doit exister."""
    from services.volume_enrichment import job

    series, volumes = make_library([("normal", 100, 3)])
    with temp_db() as (_db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes, write_delay=0.003)
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()

        results = []
        barrier = threading.Barrier(20)

        def attempt():
            barrier.wait()
            results.append(job.start_volume_enrich("all"))

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        time.sleep(0.2)
        live = [t for t in threading.enumerate() if t.name == "volume-enrich"]
        started = sum(1 for r in results if r.get("started"))
        wait_idle(timeout=300)

        report.add(
            "20 démarrages simultanés",
            accepted=started,
            refused=sum(1 for r in results if r.get("busy")),
            live_threads=len(live),
            writes=api.write_count(),
            provider_calls=scraper.calls,
        )
        if started != 1 or len(live) > 1:
            report.finding(
                "MAJEUR",
                "Plusieurs passes démarrées en parallèle",
                f"{started} démarrages acceptés, {len(live)} threads vivants.",
            )


def main():
    report = Report("s2_cancel_resume")

    banner("S2 — annulation puis reprise (comblement)")
    scenario_cancel_then_resume(report, force=False)

    banner("S2 — annulation puis reprise (réécriture forcée)")
    scenario_cancel_then_resume(report, force=True)

    banner("S2 — annulation pendant un index fournisseur lent")
    scenario_cancel_during_slow_provider(report)

    banner("S2 — annulation au milieu d'une série de 300 tomes")
    scenario_cancel_during_long_series(report)

    banner("S2 — courses autour de l'annulation")
    scenario_cancel_races(report)

    banner("S2 — démarrages simultanés")
    scenario_concurrent_starts(report)

    report.save()


if __name__ == "__main__":
    main()
