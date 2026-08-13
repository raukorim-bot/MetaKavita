#!/usr/bin/env python3
"""
Benchmark batch « tout allumé » — chronomètre un petit lot de séries en séquentiel
(comme le worker réel), avec les options lourdes forcées.

Usage (depuis la racine du projet, sur le host Linux) :
  python debug/benchmark_batch.py --limit 10
  python debug/benchmark_batch.py --limit 10 --live --i-know
  python debug/benchmark_batch.py --library-id 2 --limit 20
  python debug/benchmark_batch.py --ids 19797,42 --live --i-know

Défaut = dry-run : scrape / fusion / traduction réels, écritures Kavita mockées
(metadata / general / cover). --live écrit vraiment (force_update + RESET_CONTEXT).

Au démarrage, le script demande interactivement le **token / clé API Kavita**
(getpass — non echo, non logué) ; `KAVITA_URL` vient de `config.json`.

Note : ce script tourne dans le venv *host*. MetaKavita en Docker utilise Python 3.11
(où `googletrans` fonctionne). Sur un host Python 3.13+, `googletrans` peut échouer
(`No module named 'cgi'`) — ce n'est pas une régression du conteneur MetaKavita.
Pour un bench fidèle à la prod, lance-le dans le même environnement Python que Docker
(3.11) ou via `docker exec` dans le conteneur.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _live_network_guard import confirm_live_network  # noqa: E402
from config_manager import load_config  # noqa: E402
from kavita_api import KavitaAPI  # noqa: E402
from services import enrichment_engine  # noqa: E402
from services.enrichment_engine import enrich_series  # noqa: E402


ALL_ON_FLAGS = {
    "SMART_SCORING": True,
    "SMART_COMPLETION": True,
    "TITLE_FALLBACK_TRANSLATION": True,
    "RESET_CONTEXT_ON_FORCE": True,
    "AUTO_COVER": True,
    "AUTO_READING_DIR": True,
}


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _build_overlay_config(base: dict) -> dict:
    cfg = dict(base)
    cfg.update(ALL_ON_FLAGS)
    provider = (cfg.get("TRANSLATION_PROVIDER") or "NONE").upper()
    if provider == "NONE":
        cfg["TRANSLATION_PROVIDER"] = "GOOGLE"
    return cfg


def _install_config_overlay(overlay: dict) -> None:
    """Force load_config() (engine + config_manager) à renvoyer l'overlay pour ce process."""

    def _overlay_loader(config=None):
        return overlay

    enrichment_engine.load_config = _overlay_loader  # type: ignore[assignment]
    import config_manager as cm

    cm.load_config = _overlay_loader  # type: ignore[assignment]


def _install_dry_run_write_mocks() -> None:
    """Skip écritures Kavita + update_status cache (GET auth/metadata restent réels)."""

    def _ok_meta(self, metadata):
        return True, "dry-run (metadata non écrit)"

    def _ok_general(self, series_id, localized_name=None, format_val=None):
        return True, "dry-run (général non écrit)"

    def _ok_cover(self, series_id, cover_url):
        return True, "dry-run (cover non uploadée)"

    KavitaAPI.update_series_metadata = _ok_meta  # type: ignore[method-assign]
    KavitaAPI.update_series_general = _ok_general  # type: ignore[method-assign]
    KavitaAPI.upload_series_cover = _ok_cover  # type: ignore[method-assign]
    enrichment_engine.update_status = lambda *a, **k: None  # type: ignore[assignment]


def _parse_ids(raw: Optional[str]) -> Optional[List[int]]:
    if not raw:
        return None
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out or None


def _select_series(
    api: KavitaAPI,
    *,
    library_id: Optional[str],
    ids: Optional[List[int]],
    limit: int,
) -> List[Tuple[int, str]]:
    if ids:
        all_series = api.get_all_series(library_id=library_id)
        by_id = {int(s["id"]): s.get("name") or f"#{s['id']}" for s in all_series}
        selected = []
        for sid in ids:
            name = by_id.get(sid, f"#{sid}")
            selected.append((sid, name))
        return selected

    series_list = api.get_all_series(library_id=library_id)
    picked = series_list[: max(0, limit)]
    return [(int(s["id"]), s.get("name") or f"#{s['id']}") for s in picked]


def _print_report(rows: List[Dict[str, Any]], *, live: bool) -> None:
    print("\n" + "=" * 72)
    print(f"RÉSULTATS ({'LIVE' if live else 'DRY-RUN'})")
    print("=" * 72)
    for r in rows:
        status = "OK" if r["ok"] else "FAIL"
        print(
            f"  [{status}] {r['duration']:.2f}s  id={r['id']:<6}  {r['name']}"
            f"  — {r['message']}"
        )

    durations = [r["duration"] for r in rows]
    oks = sum(1 for r in rows if r["ok"])
    fails = len(rows) - oks
    if not durations:
        print("\nAucune série traitée.")
        return

    ordered = sorted(durations)
    total = sum(durations)
    mean = statistics.mean(durations)
    print("-" * 72)
    print(
        f"n={len(rows)}  ok={oks}  fail={fails}  "
        f"total={total:.2f}s  mean={mean:.2f}s  "
        f"p50={_percentile(ordered, 50):.2f}s  "
        f"p95={_percentile(ordered, 95):.2f}s  "
        f"max={max(durations):.2f}s"
    )
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark batch MetaKavita avec options lourdes forcées."
    )
    parser.add_argument("--limit", type=int, default=10, help="Nombre de séries (défaut 10)")
    parser.add_argument("--library-id", default=None, help="Filtrer une bibliothèque Kavita")
    parser.add_argument("--ids", default=None, help="IDs fixes séparés par des virgules")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Écrit vraiment vers Kavita (force_update + RESET_CONTEXT)",
    )
    parser.add_argument(
        "--i-know",
        action="store_true",
        help="Obligatoire avec --live (confirme les écritures / reset contexte)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Logs INFO scrapers")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.live and not args.i_know:
        print(
            "ERREUR: --live réécrit les fiches Kavita (force + RESET_CONTEXT_ON_FORCE).\n"
            "Relance avec --live --i-know si tu assumes le risque."
        )
        return 2

    # `--i-know` ne couvrait que les ÉCRITURES Kavita. Le scraping, lui, est
    # réel même en dry-run : un lot de vingt séries BD, c'est plusieurs
    # centaines de pages chez Bédéthèque et Planète BD.
    confirm_live_network(
        "benchmark_batch.py",
        "les fournisseurs de la cascade configurée, Bédéthèque et Planète BD compris",
        details="Le scraping est réel même en dry-run ; seules les écritures Kavita sont mockées.",
    )

    base = load_config()
    if not base.get("KAVITA_URL"):
        print("ERREUR: KAVITA_URL manquant dans config.json")
        return 1

    try:
        api_token = getpass.getpass("Kavita API token (clé API) : ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAnnulé.")
        return 2
    if not api_token:
        print("ERREUR: token requis — relance et saisis la clé API Kavita.")
        return 2

    overlay = _build_overlay_config(base)
    overlay["KAVITA_API_KEY"] = api_token
    _install_config_overlay(overlay)
    if not args.live:
        _install_dry_run_write_mocks()

    print("=" * 72)
    print("BENCHMARK BATCH — tout allumé")
    print(f"Mode        : {'LIVE (écritures réelles)' if args.live else 'DRY-RUN (écritures mockées)'}")
    print(f"Flags forcés: {', '.join(f'{k}={v}' for k, v in ALL_ON_FLAGS.items())}")
    print(f"Traduction  : {overlay.get('TRANSLATION_PROVIDER')}")
    print(f"force_update: True  |  séquentiel (1 worker)")
    print("Auth        : token saisi interactivement (non logué)")
    print("=" * 72)

    api = KavitaAPI(overlay["KAVITA_URL"], overlay["KAVITA_API_KEY"])
    if not api.authenticate():
        print("ERREUR: authentification Kavita échouée (token invalide ?)")
        return 1

    ids = _parse_ids(args.ids)
    try:
        series = _select_series(
            api, library_id=args.library_id, ids=ids, limit=args.limit
        )
    except Exception as e:
        print(f"ERREUR: impossible de lister les séries ({e})")
        return 1

    if not series:
        print("Aucune série à traiter.")
        return 1

    print(f"Séries      : {len(series)}")
    rows: List[Dict[str, Any]] = []
    for sid, name in series:
        print(f"\n>>> [{sid}] {name}")
        t0 = time.perf_counter()
        try:
            ok, msg, _providers = enrich_series(sid, name, force_update=True)
        except Exception as e:
            ok, msg = False, f"crash: {e}"
        duration = time.perf_counter() - t0
        rows.append(
            {
                "id": sid,
                "name": name,
                "ok": bool(ok),
                "message": msg or "",
                "duration": duration,
            }
        )
        print(f"    → {'OK' if ok else 'FAIL'} in {duration:.2f}s — {msg}")

    _print_report(rows, live=args.live)
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
