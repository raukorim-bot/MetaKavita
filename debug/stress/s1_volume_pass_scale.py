"""
S1 — La passe d'enrichissement par tome à grande échelle.

Ce qu'on éprouve : `services/volume_enrichment/job.py` sur des bibliothèques
synthétiques de plusieurs milliers de séries, des séries à 300 tomes, des tomes
multi-chapitres, les sentinelles Kavita (-100000 feuilles volantes, 100000
spéciaux), les numéros décimaux et les séries sans aucun tome.

Ce qu'on mesure : durée totale, temps par série et par unité, mémoire du
process, croissance de la base, nombre d'appels Kavita, et surtout la
**réconciliation** entre les compteurs finaux de la passe et les écritures
réellement faites sur le double.

Aucun réseau, aucune écriture Kavita, base SQLite temporaire jetée à la fin.

Relance :
    python debug/stress/s1_volume_pass_scale.py            # profil normal
    python debug/stress/s1_volume_pass_scale.py --big      # 4000 séries
"""
from __future__ import annotations

import sys
import time

from _harness import (  # le dossier du script est sys.path[0]
    FakeKavitaAPI,
    FakeScraper,
    Patches,
    Report,
    Snapshot,
    banner,
    make_index,
    make_library,
    reset_job_state,
    temp_db,
    unit_total,
    wait_idle,
    wire_volume_pass,
)


def expected_matched(volumes):
    """Nombre d'unités que l'appariement devrait retenir, calculé à part.

    Réimplémente volontairement la règle (tome à un fichier -> numéro de tome,
    tome à plusieurs -> numéro de chapitre, spéciaux écartés, sentinelles
    neutralisées) plutôt que d'appeler le code testé : c'est ce qui permet de
    détecter un écart.
    """
    from services.volume_enrichment.matching import is_sentinel, number_key

    index = make_index()
    total = 0
    for vols in volumes.values():
        for volume in vols:
            chapters = [c for c in volume.get("chapters", []) if c.get("id")]
            for chapter in chapters:
                if volume.get("isSpecial") or chapter.get("isSpecial"):
                    continue
                key = None
                if len(chapters) <= 1:
                    raw = volume.get("minNumber")
                    key = None if is_sentinel(raw) else number_key(raw)
                if key is None:
                    raw = chapter.get("minNumber")
                    key = None if is_sentinel(raw) else number_key(raw)
                if key is not None and key in index:
                    total += 1
    return total


def run_pass(report, label, spec, *, force=False, with_credits=False):
    from services.volume_enrichment import job

    series, volumes = make_library(spec)
    units = unit_total(volumes)
    wanted = expected_matched(volumes)

    with temp_db() as (db, db_file), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        scraper = FakeScraper("FAKEVINE", rate_limit=0.0)
        emits = {}
        wire_volume_pass(patches, api, [scraper], emit_counter=emits)
        reset_job_state()

        snap = Snapshot(db_file)
        started = job.start_volume_enrich("all", force=force, with_credits=with_credits)
        assert started.get("started"), started
        finished, waited = wait_idle(timeout=1800)
        measures = snap.close()

        state = job.get_volume_enrich_state()
        counts = state.get("counts") or {}
        writes = api.write_count()
        conn = db._connect()
        rows = conn.execute("SELECT COUNT(*) FROM volume_unit_cache").fetchone()[0]
        sentinel_rows = conn.execute(
            "SELECT COUNT(*) FROM volume_unit_cache WHERE chapter_id = 0"
        ).fetchone()[0]
        conn.close()

        report.add(
            label,
            series=len(series),
            units=units,
            duration_s=measures["duration_s"],
            ms_per_series=round(measures["duration_s"] * 1000 / max(1, len(series)), 2),
            ms_per_unit=round(measures["duration_s"] * 1000 / max(1, units), 3),
            units_per_s=round(units / max(0.001, measures["duration_s"]), 1),
            rss_delta_mb=measures["rss_delta_mb"],
            db_mb=measures["db_end_mb"],
            db_kb_per_unit=round(measures["db_end_mb"] * 1024 / max(1, units), 2),
            kavita_calls=sum(api.calls.values()),
            provider_calls=scraper.calls,
            emits=sum(emits.values()),
            done=counts.get("done", 0),
            skipped=counts.get("skipped", 0),
            nothing=counts.get("nothing", 0),
            failed=counts.get("failed", 0),
            real_writes=writes,
            expected_matched=wanted,
            cache_rows=rows,
            series_done_rows=sentinel_rows,
            finished=finished,
        )

        if counts.get("done", 0) != writes:
            report.finding(
                "MAJEUR",
                "Compteur « done » ≠ écritures réelles",
                f"{label} : counts.done={counts.get('done')} pour {writes} appels "
                "update_chapter_metadata sur le double.",
            )
        if wanted != counts.get("done", 0) + counts.get("skipped", 0) + counts.get(
            "nothing", 0
        ) + counts.get("failed", 0):
            report.finding(
                "MINEUR",
                "Unités appariées ≠ somme des compteurs",
                f"{label} : attendu {wanted}, compteurs {counts}.",
            )
        return {"label": label, "state": dict(state), "api_calls": dict(api.calls)}


def scenario_shapes(report):
    """Formes tordues : sentinelles, décimaux, multi-chapitres, séries vides."""
    from services.volume_enrichment import job
    from services.volume_enrichment.matching import units_from_volumes
    from services.volume_enrichment.plan import build_plan

    series, volumes = make_library(
        [("sentinel", 1, 0), ("decimal", 1, 0), ("multi", 1, 50), ("empty", 1, 0)]
    )
    index = make_index()
    detail = {}
    for sid, vols in volumes.items():
        units = units_from_volumes(vols)
        plan = build_plan(units, index)
        detail[series[sid - 1]["name"]] = {
            "units": len(units),
            "matched": plan["counts"]["matched"],
            "unmatched": plan["counts"]["unmatched"],
            "matched_on": [entry["matched_on"] for entry in plan["units"]],
        }
    for name, data in detail.items():
        report.add(f"forme::{name}", **{k: v for k, v in data.items()})

    sentinel = detail[[n for n in detail if n.startswith("Sentinel")][0]]
    if "2" in sentinel["matched_on"]:
        report.finding(
            "MAJEUR",
            "Volume spécial (100000) non marqué isSpecial apparié sur un vrai numéro",
            "services/volume_enrichment/matching.py:149 neutralise la sentinelle du "
            "tome puis retombe sur le numéro de chapitre : un hors-série rangé dans "
            "le volume 100000 sans drapeau isSpecial reçoit les métadonnées du tome "
            f"correspondant (appariements observés : {sentinel['matched_on']}).",
        )

    # Série sans aucun tome : la passe doit la clore sans jamais interroger un
    # fournisseur, sinon chaque passe repaie la recherche.
    with temp_db() as (db, _db_file), Patches() as patches:
        empty_series = [s for s in series if s["name"].startswith("Empty")]
        api = FakeKavitaAPI(empty_series, {empty_series[0]["id"]: []})
        scraper = FakeScraper("FAKEVINE")
        wire_volume_pass(patches, api, [scraper])
        reset_job_state()
        job.start_volume_enrich("all")
        wait_idle(timeout=60)
        report.add(
            "forme::série vide",
            provider_calls=scraper.calls,
            closed=len(db.list_enriched_series_ids()),
            counts=job.get_volume_enrich_state().get("counts"),
        )


def scenario_giant_series(report):
    """Une seule série de 300 tomes : coût par unité, mémoire du plan."""
    return run_pass(report, "300 tomes x 20 séries", [("long", 20, 300)])


def main():
    big = "--big" in sys.argv
    report = Report("s1_volume_pass_scale")

    banner("S1 — passe par tome à grande échelle")
    scenario_shapes(report)

    banner("S1 — 500 séries de 3 tomes")
    run_pass(report, "500 séries x 3 tomes", [("normal", 500, 3)])

    banner("S1 — 2000 séries de 3 tomes")
    run_pass(report, "2000 séries x 3 tomes", [("normal", 2000, 3)])

    banner("S1 — 20 séries de 300 tomes")
    scenario_giant_series(report)

    banner("S1 — bibliothèque mélangée")
    run_pass(
        report,
        "mélange 1000 séries",
        [
            ("normal", 700, 5),
            ("long", 10, 300),
            ("multi", 100, 40),
            ("sentinel", 100, 0),
            ("decimal", 50, 0),
            ("empty", 40, 0),
        ],
    )

    if big:
        banner("S1 — 4000 séries (profil --big)")
        run_pass(report, "4000 séries x 5 tomes", [("normal", 4000, 5)])

    report.save()


if __name__ == "__main__":
    main()
