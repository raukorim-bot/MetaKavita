"""
S5 — Fournisseurs dégradés, et cadence sous charge.

Ce qu'on éprouve :

* un fournisseur qui rend n'importe quoi (timeout, 429, 500, JSON invalide,
  HTML tronqué, réponse géante, type inattendu) au milieu d'une passe ;
* la bascule vers le fournisseur suivant, et le fait qu'une panne ne condamne
  pas toute la passe ;
* le respect du `rate_limit` (`services/provider_throttle.py`) quand plusieurs
  chemins de MetaKavita interrogent le MÊME fournisseur en même temps ;
* le vrai parseur d'index de ComicVine (`scrapers/comicvine.py`) face à des
  réponses HTTP dégradées, avec `requests` remplacé par un double — aucun appel
  réseau n'est émis.

Ce qu'on mesure : durée, unités écrites, séries en échec, écarts entre appels
au même fournisseur (violations de cadence), mémoire sur une réponse géante.

Relance :
    python debug/stress/s5_providers_degraded.py
"""
from __future__ import annotations

import threading
import time

from _harness import (
    FakeKavitaAPI,
    FakeScraper,
    Patches,
    Report,
    Snapshot,
    banner,
    make_index,
    make_library,
    percentile,
    reset_job_state,
    temp_db,
    wait_idle,
    wire_volume_pass,
)


def scenario_degraded_modes(report):
    """Chaque mode de panne, en tête de cascade, avec un fournisseur sain derrière."""
    from services.volume_enrichment import job

    modes = [
        ("timeout", "lecture qui n'aboutit jamais"),
        ("http429", "quota dépassé"),
        ("http500", "erreur serveur"),
        ("badjson", "JSON invalide"),
        ("truncated", "HTML tronqué"),
        ("empty", "réponse vide"),
        ("junk", "type inattendu (chaîne au lieu d'un dict)"),
    ]
    for mode, label in modes:
        series, volumes = make_library([("normal", 60, 4)])
        with temp_db() as (_db, _f), Patches() as patches:
            api = FakeKavitaAPI(series, volumes)
            broken = FakeScraper("BROKEN", mode=mode)
            healthy = FakeScraper("HEALTHY")
            wire_volume_pass(patches, api, [broken, healthy])
            reset_job_state()

            t0 = time.perf_counter()
            job.start_volume_enrich("all")
            finished, _ = wait_idle(timeout=300)
            elapsed = time.perf_counter() - t0
            state = job.get_volume_enrich_state()
            counts = state.get("counts") or {}

            report.add(
                f"fournisseur {mode} ({label})",
                duration_s=round(elapsed, 2),
                writes=api.write_count(),
                done=counts.get("done"),
                failed=counts.get("failed"),
                nothing=counts.get("nothing"),
                broken_calls=broken.calls,
                healthy_calls=healthy.calls,
                finished=finished,
                error=state.get("error"),
            )
            if counts.get("failed"):
                report.finding(
                    "MOYEN" if mode != "junk" else "MAJEUR",
                    f"Le mode `{mode}` fait échouer des séries entières",
                    f"{counts.get('failed')} séries en échec, {api.write_count()} "
                    "écritures au lieu de 240 : le repli sur le fournisseur suivant "
                    "n'a pas joué.",
                )
            elif api.write_count() < 240:
                report.finding(
                    "MOYEN",
                    f"Le mode `{mode}` prive la passe du fournisseur de repli",
                    f"{api.write_count()} écritures au lieu de 240 attendues.",
                )


def scenario_slow_provider(report):
    """Un fournisseur lent : coût réel d'une passe, et où part le temps."""
    from services.volume_enrichment import job

    for latency in (0.2, 1.0):
        series, volumes = make_library([("normal", 30, 5)])
        with temp_db() as (_db, _f), Patches() as patches:
            api = FakeKavitaAPI(series, volumes)
            slow = FakeScraper("SLOW", latency=latency)
            wire_volume_pass(patches, api, [slow])
            reset_job_state()
            t0 = time.perf_counter()
            job.start_volume_enrich("all")
            wait_idle(timeout=600)
            elapsed = time.perf_counter() - t0
            report.add(
                f"index lent ({latency * 1000:.0f} ms/série)",
                series=30,
                duration_s=round(elapsed, 2),
                s_per_series=round(elapsed / 30, 3),
                provider_share_pct=round(100 * latency * 30 / elapsed, 1),
                writes=api.write_count(),
            )


def scenario_rate_limit_under_load(report):
    """Même fournisseur sollicité par la passe ET par trois autres chemins."""
    from services.provider_throttle import reset_throttle_state, throttle_provider
    from services.volume_enrichment import job

    reset_throttle_state()
    series, volumes = make_library([("normal", 12, 3)])
    with temp_db() as (_db, _f), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        shared = FakeScraper("SHARED", rate_limit=0.25)
        wire_volume_pass(patches, api, [shared])
        reset_job_state()

        stop = threading.Event()
        side_calls = {"n": 0}

        def side_channel():
            """Recherche de couvertures / diagnostic : même scraper, autre chemin."""
            while not stop.is_set():
                throttle_provider(shared)
                with shared.lock:
                    shared.call_times.append(time.perf_counter())
                side_calls["n"] += 1

        threads = [threading.Thread(target=side_channel, daemon=True) for _ in range(3)]
        for thread in threads:
            thread.start()
        job.start_volume_enrich("all")
        wait_idle(timeout=600)
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

        with shared.lock:
            times = sorted(shared.call_times)
        gaps = [b - a for a, b in zip(times, times[1:])]
        violations = sum(1 for gap in gaps if gap < 0.25 - 0.02)

        report.add(
            "cadence 0,25 s — passe + 3 chemins parallèles",
            total_calls=len(times),
            side_calls=side_calls["n"],
            min_gap_ms=round(min(gaps) * 1000, 1) if gaps else 0,
            p50_gap_ms=round(percentile(gaps, 50) * 1000, 1),
            violations=violations,
        )
        if violations:
            report.finding(
                "MAJEUR",
                "Cadence fournisseur violée sous charge",
                f"{violations} appels partis à moins de 250 ms d'écart "
                "(services/provider_throttle.py:50).",
            )
    reset_throttle_state()


def scenario_giant_response(report):
    """Index de 20 000 albums, 4 ko de résumé chacun : coût mémoire et temps."""
    from services.volume_enrichment import job

    series, volumes = make_library([("long", 2, 300)])
    with temp_db() as (_db, db_file), Patches() as patches:
        api = FakeKavitaAPI(series, volumes)
        giant = FakeScraper("GIANT", mode="giant")
        wire_volume_pass(patches, api, [giant])
        reset_job_state()

        snap = Snapshot(db_file)
        job.start_volume_enrich("all")
        finished, _ = wait_idle(timeout=1200)
        measures = snap.close()
        report.add(
            "index géant (20 000 entrées x 4 ko)",
            duration_s=measures["duration_s"],
            rss_delta_mb=measures["rss_delta_mb"],
            writes=api.write_count(),
            done=(job.get_volume_enrich_state().get("counts") or {}).get("done"),
            finished=finished,
        )
    # Le working set du process ne dit pas grand-chose d'une allocation
    # transitoire : `tracemalloc` mesure exactement ce que l'index et le plan
    # coûtent côté Python.
    import tracemalloc

    from services.volume_enrichment.matching import units_from_volumes
    from services.volume_enrichment.plan import build_plan

    from _harness import make_series

    _series, vols = make_series(1, shape="long", volume_count=300)
    units = units_from_volumes(vols)
    giant = FakeScraper("GIANT", mode="giant")
    tracemalloc.start()
    index = giant.fetch_volume_index("X")
    after_index, _ = tracemalloc.get_traced_memory()
    plan = build_plan(units, index)
    after_plan, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report.add(
        "empreinte d'un index de 20 000 entrées",
        entries=len(index),
        units=len(units),
        index_mb=round(after_index / 1e6, 1),
        plan_mb=round(after_plan / 1e6, 1),
        peak_mb=round(peak / 1e6, 1),
        matched=plan["counts"]["matched"],
    )
    if after_index / 1e6 > 50:
        report.finding(
            "MINEUR",
            "L'index fournisseur n'est pas élagué aux tomes réellement présents",
            f"{after_index / 1e6:.0f} Mo pour {len(index)} entrées dont "
            f"{plan['counts']['matched']} seulement peuvent s'apparier : "
            "`normalize_index` (matching.py:69) recopie tout avant de comparer. "
            "Les scrapers livrés plafonnent (ComicVine 3 000 albums, Bédéthèque "
            "et Planète BD 50), un scraper sideloadé n'a pas cette limite.",
        )


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def scenario_real_comicvine_parser(report):
    """Le vrai parseur d'index ComicVine face à des réponses HTTP dégradées.

    `requests` est remplacé par un double : aucun paquet ne sort de la machine.
    """
    import scrapers.comicvine as comicvine

    scraper = comicvine.ComicVineScraper()

    cases = {
        "429": _FakeResponse(status_code=429, payload={}),
        "500": _FakeResponse(status_code=500, payload={}),
        "json invalide": _FakeResponse(status_code=200, raise_json=True),
        "html au lieu de json": _FakeResponse(
            status_code=200, raise_json=True, text="<html><body>maintenance"
        ),
        "results non-liste": _FakeResponse(status_code=200,
                                           payload={"results": "cassé"}),
        "issue non-dict": _FakeResponse(status_code=200,
                                        payload={"results": ["cassé", 42]}),
        "numéro manquant": _FakeResponse(
            status_code=200,
            payload={"results": [{"id": 1, "name": "A"}], "number_of_total_results": 1},
        ),
        "page géante": _FakeResponse(
            status_code=200,
            payload={
                "results": [
                    {"id": n, "issue_number": str(n), "name": f"T{n}",
                     "description": "<p>" + "x" * 3000 + "</p>"}
                    for n in range(1, 101)
                ],
                "number_of_total_results": 100,
            },
        ),
    }

    for label, response in cases.items():
        with Patches() as patches:
            calls = {"n": 0}

            class _FakeRequests:
                @staticmethod
                def get(*args, **kwargs):
                    calls["n"] += 1
                    return response

            patches.attr(comicvine, "requests", _FakeRequests)
            patches.attr(comicvine, "load_config",
                         lambda: {"COMICVINE_API_KEY": "double", "MAX_TAGS": 10})
            patches.attr(
                comicvine.ComicVineScraper, "_resolve_volume_id",
                lambda self, *a, **kw: "4050-1234"
            )
            t0 = time.perf_counter()
            error = ""
            try:
                index = scraper.fetch_volume_index("Saga", library_type="Comic")
            except Exception as exc:  # noqa: BLE001
                index = None
                error = f"{type(exc).__name__}: {exc}"
            elapsed = time.perf_counter() - t0

            report.add(
                f"comicvine::{label}",
                http_calls=calls["n"],
                entries=len(index) if isinstance(index, dict) else 0,
                duration_ms=round(elapsed * 1000, 1),
                exception=error,
            )
            if error:
                report.finding(
                    "MAJEUR",
                    f"`fetch_volume_index` ComicVine lève sur « {label} »",
                    f"{error} — remonté à `fetch_index` qui l'attrape "
                    "(providers.py:140), mais la série perd son fournisseur.",
                )


def main():
    import sys

    report = Report("s5_providers_degraded")
    wanted = [arg for arg in sys.argv[1:] if not arg.startswith("-")]

    def run(key, title, fn):
        if wanted and not any(w in key for w in wanted):
            return
        banner(title)
        fn(report)

    run("degrade", "S5 — modes dégradés en tête de cascade", scenario_degraded_modes)
    run("lent", "S5 — fournisseur lent", scenario_slow_provider)
    run("cadence", "S5 — cadence sous charge", scenario_rate_limit_under_load)
    run("giant", "S5 — réponse géante", scenario_giant_response)
    run("comicvine", "S5 — parseur ComicVine réel, réponses dégradées",
        scenario_real_comicvine_parser)

    report.save()


if __name__ == "__main__":
    main()
