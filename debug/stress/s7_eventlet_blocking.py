"""
S7 — Ce que la passe fait au worker eventlet (le scénario de production).

`app.py:19-20` appelle `eventlet.monkey_patch()` et le déploiement tourne en
`gunicorn -w 1` avec le worker eventlet : **un seul processus, une seule boucle
d'événements**. Les `threading.Thread` de `job.py` et de `hygiene_scan.py` n'y
sont donc pas des threads système mais des greenthreads coopératifs. Tout appel
qui bloque sans rendre la main — SQLite (extension C), une boucle de calcul pur
— gèle l'application entière, HTTP compris.

Les scénarios S1 à S6 tournent en threads système : ils sont *plus indulgents*
que la production. Ce script reproduit la vraie forme.

Ce qu'on mesure : latence HTTP réelle (client dans un thread système non
patché, serveur eventlet en boucle locale) au repos, pendant la passe par tome,
et pendant la phase de regroupement des doublons du scan d'hygiène. Plus les
décrochages de l'ordonnanceur (« stalls ») vus par un battement de cœur
greenthread.

Aucun réseau sortant : le serveur écoute sur 127.0.0.1 sur un port éphémère.

Relance :
    python debug/stress/s7_eventlet_blocking.py
"""
from __future__ import annotations

import eventlet  # noqa: E402  (doit précéder tout import réseau)

eventlet.monkey_patch()

import json  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

import eventlet.wsgi  # noqa: E402

from _harness import (  # noqa: E402
    FakeKavitaAPI,
    FakeScraper,
    Patches,
    Report,
    banner,
    make_library,
    percentile,
    reset_job_state,
    temp_db,
    wire_volume_pass,
)

# Thread système authentique : sous monkey_patch, `threading.Thread` produirait
# un greenthread, et le client mesurerait le même gel que le serveur.
_real_threading = eventlet.patcher.original("threading")


class HttpProbe:
    """Sonde HTTP dans un vrai thread système : mesure ce que voit le navigateur."""

    def __init__(self, url, interval=0.02):
        self.url = url
        self.interval = interval
        self.samples = []
        self.errors = 0
        self._stop = _real_threading.Event()
        self._thread = _real_threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.is_set():
            start = time.perf_counter()
            try:
                with urllib.request.urlopen(self.url, timeout=30) as response:
                    response.read()
            except Exception:  # noqa: BLE001
                self.errors += 1
            self.samples.append((start, time.perf_counter() - start))
            time.sleep(self.interval)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=10)

    def window(self, t0, t1):
        return [d for start, d in self.samples if t0 <= start <= t1]


def _stats(latencies):
    if not latencies:
        return {"n": 0}
    return {
        "n": len(latencies),
        "p50_ms": round(percentile(latencies, 50) * 1000, 1),
        "p95_ms": round(percentile(latencies, 95) * 1000, 1),
        "max_ms": round(max(latencies) * 1000, 1),
        "over_1s": sum(1 for value in latencies if value > 1.0),
        "over_5s": sum(1 for value in latencies if value > 5.0),
    }


def _serve(app):
    listener = eventlet.listen(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    eventlet.spawn(
        eventlet.wsgi.server, listener, app, log_output=False, debug=False
    )
    eventlet.sleep(0.3)
    return f"http://127.0.0.1:{port}"


def scenario_pass_under_eventlet(report, *, kavita_delay=0.0, series_count=900):
    """Passe par tome sous eventlet, avec un Kavita plus ou moins bavard.

    `kavita_delay` modélise le temps de réponse de Kavita. Il compte
    doublement : c'est le seul endroit où la passe rend la main au worker
    (`time.sleep` est patché par eventlet, comme le serait une vraie socket).
    À zéro, la passe ne bascule jamais — c'est la borne haute. À 4 ms, on est
    dans l'ordre de grandeur d'un Kavita local.
    """
    import routes.volume_enrichment as routes_ve
    from flask import Flask

    from services.volume_enrichment import job

    series, volumes = make_library([("normal", series_count, 5)])

    with temp_db() as (db, _db_file), Patches() as patches:
        api = FakeKavitaAPI(
            series, volumes, read_delay=kavita_delay, write_delay=kavita_delay
        )
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
        base_url = _serve(app)

        probe = HttpProbe(f"{base_url}/api/volume-enrich/status")
        probe.start()

        label = f"Kavita à {kavita_delay * 1000:.0f} ms"

        idle_start = time.perf_counter()
        eventlet.sleep(5)
        idle_end = time.perf_counter()
        idle_stats = _stats(probe.window(idle_start, idle_end))
        report.add(f"HTTP au repos ({label})", **idle_stats)

        pass_start = time.perf_counter()
        job.start_volume_enrich("all")
        while job.get_volume_enrich_state()["running"]:
            eventlet.sleep(0.05)
        pass_end = time.perf_counter()
        during = _stats(probe.window(pass_start, pass_end))
        state = job.get_volume_enrich_state()
        report.add(
            f"HTTP pendant la passe ({series_count * 5} unités, {label})",
            pass_duration_s=round(pass_end - pass_start, 1),
            units_written=api.write_count(),
            done=state.get("done"),
            **during,
        )
        probe.stop()

        if during.get("n") and during["p50_ms"] > 5 * max(idle_stats["p50_ms"], 0.1):
            report.finding(
                "MAJEUR",
                f"La passe par tome gèle la boucle eventlet ({label})",
                f"latence médiane des requêtes : {idle_stats['p50_ms']} ms au repos "
                f"contre {during['p50_ms']} ms pendant la passe "
                f"(pic {during['max_ms']} ms, {during.get('over_1s')} requêtes "
                "au-dessus d'une seconde). Chaque unité écrite fait un aller-retour "
                "SQLite complet (db_manager.py:20 et 1504) : l'extension C ne rend "
                "jamais la main au worker eventlet unique (app.py:19-20).",
            )
        return during


_WORDS = (
    "atlas boreal cendre dragon eclipse fjord gargouille horizon ivoire jade "
    "kraken lagune monolithe nadir obsidienne phenix quartz rivage sable tempete "
    "umbra vertige wagon xenon yggdrasil zephyr abysse basalte comete delta "
    "ecarlate faille givre hydre insomnie jungle karma limbe mirage nebuleuse "
    "orage pluie quiétude ruine spirale titan ultime vortex wapiti xylophone"
).split()


def _names(count, profile, seed=7):
    """Trois profils de titres, du plus réaliste au pire cas."""
    import random

    rng = random.Random(seed)
    if profile == "divers":
        return [
            f"{rng.choice(_WORDS).capitalize()} {rng.choice(_WORDS)} {rng.randint(1, 99)}"
            for _ in range(count)
        ]
    if profile == "collection":
        # La moitié de la bibliothèque partage son premier mot distinctif :
        # une collection, un éditeur, un univers étendu.
        half = count // 2
        return [f"Chroniques {rng.choice(_WORDS)} {i}" for i in range(half)] + [
            f"{rng.choice(_WORDS).capitalize()} {rng.choice(_WORDS)} {i}"
            for i in range(count - half)
        ]
    return [f"Série numéro {i}" for i in range(count)]  # pire cas : un seul seau


def scenario_duplicate_clustering(report):
    """Regroupement des doublons : coût réel selon la forme des titres."""
    from services.library_audit.duplicates import cluster_duplicate_series
    from services.library_audit.series_identity import merge_series_identity

    for profile in ("divers", "collection", "pire cas"):
        for count in (500, 1500):
            names = _names(count, profile)
            identities = []
            for sid, name in enumerate(names, start=1):
                identity = merge_series_identity(
                    {"id": sid, "name": name, "libraryId": 1},
                    {"summary": "", "webLinks": ""},
                    series_name=name,
                    library_type="Comic",
                )
                identity["id"] = sid
                identity["libraryId"] = 1
                identities.append(identity)

            t0 = time.perf_counter()
            groups = cluster_duplicate_series(identities, library_id=1, config={})
            elapsed = time.perf_counter() - t0
            report.add(
                f"doublons :: titres {profile} :: {count} séries",
                duration_s=round(elapsed, 2),
                groups=len(groups),
                ms_per_series=round(elapsed * 1000 / count, 1),
            )
            if elapsed > 2.0:
                report.finding(
                    "MAJEUR",
                    f"Regroupement des doublons : {elapsed:.0f} s pour {count} "
                    f"séries (titres « {profile} »)",
                    "services/library_audit/duplicates.py:133 compare les paires à "
                    "l'intérieur d'un seau formé sur le PREMIER mot distinctif du "
                    "titre : dès qu'une collection partage ce mot, le seau devient "
                    "quadratique. Calcul pur, sans point de bascule : sous le "
                    "worker eventlet unique (app.py:19-20) l'application entière "
                    "est muette pendant ce temps, à la fin de chaque scan.",
                )


def main():
    report = Report("s7_eventlet_blocking")

    banner("S7 — la passe sous eventlet, Kavita instantané (borne haute)")
    scenario_pass_under_eventlet(report, kavita_delay=0.0, series_count=900)

    banner("S7 — la passe sous eventlet, Kavita local à 4 ms (cas réaliste)")
    scenario_pass_under_eventlet(report, kavita_delay=0.004, series_count=400)

    banner("S7 — regroupement des doublons selon la forme des titres")
    scenario_duplicate_clustering(report)

    report.save()


if __name__ == "__main__":
    main()
