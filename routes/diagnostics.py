"""
API de diagnostic scrapers (préflight Internet/Kavita + probes).

Endpoints :
  diagnostics.preflight   POST /api/diagnostics/preflight
  diagnostics.probe_one   POST /api/scrapers/<scraper_id>/probe
  diagnostics.probe_all   POST /api/scrapers/probe-all
      → ?scope=active|all (défaut all — rétrocompat)
      → NDJSON stream (une ligne JSON par événement) si Accept contient
        application/x-ndjson ou ?stream=1 ; sinon JSON bulk.
      C95 : les probes d'un scope partent ensemble (un worker par fournisseur) ;
      le flux annonce toutes les cibles puis rend les résultats dans l'ordre
      de finition. `throttle_provider` sérialise toujours le même scraper.

La page HTML vit sur pages.diagnostics (GET /diagnostics).
"""

import json

from flask import Blueprint, Response, jsonify, request, stream_with_context

from config_manager import load_config
from scrapers import ScraperRegistry
from services.scraper_diagnostics import (
    DEFAULT_PROBE_WORKERS,
    iter_probe_results,
    probe_all,
    probe_scraper,
    resolve_probe_targets,
    run_preflight,
)

diagnostics_bp = Blueprint("diagnostics", __name__)


def _parse_scope() -> str:
    raw = (request.args.get("scope") or "all").strip().lower()
    return "active" if raw == "active" else "all"


def _parse_workers() -> int:
    raw = (request.args.get("workers") or "").strip()
    if not raw:
        return DEFAULT_PROBE_WORKERS
    try:
        val = int(raw)
        return max(1, min(val, 8))
    except (ValueError, TypeError):
        return DEFAULT_PROBE_WORKERS


@diagnostics_bp.route("/api/diagnostics/preflight", methods=["POST"])
def preflight():
    config = load_config()
    return jsonify({"success": True, **run_preflight(config)})


@diagnostics_bp.route("/api/scrapers/<scraper_id>/probe", methods=["POST"])
def probe_one(scraper_id):
    config = load_config()
    if not ScraperRegistry.get(scraper_id, include_disabled=True):
        return jsonify({"success": False, "msg": "Unknown scraper", "id": scraper_id}), 404
    result = probe_scraper(scraper_id, config)
    return jsonify({"success": True, "result": result})


def _wants_ndjson_stream() -> bool:
    if request.args.get("stream", "").lower() in ("1", "true", "yes"):
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/x-ndjson" in accept


@diagnostics_bp.route("/api/scrapers/probe-all", methods=["POST"])
def probe_all_route():
    config = load_config()
    scope = _parse_scope()
    workers = _parse_workers()

    if not _wants_ndjson_stream():
        try:
            results = probe_all(config, scope=scope, max_workers=workers)
        except TypeError:
            results = probe_all(config, scope=scope)
        return jsonify({"success": True, "scope": scope, "results": results})

    scrapers = resolve_probe_targets(config, scope=scope)
    total = len(scrapers)

    @stream_with_context
    def generate():
        yield json.dumps(
            {"type": "start", "total": total, "scope": scope},
            ensure_ascii=False,
        ) + "\n"
        # Annoncer toutes les cibles avant le premier HTTP : l'UI les passe
        # toutes en « Test… » d'un coup, puis les résultats arrivent dans
        # l'ordre de finition (C95).
        for index, scraper in enumerate(scrapers, start=1):
            yield json.dumps(
                {
                    "type": "start_scraper",
                    "id": scraper.id,
                    "index": index,
                    "total": total,
                },
                ensure_ascii=False,
            ) + "\n"
        try:
            probe_gen = iter_probe_results(
                config, scope=scope, scrapers=scrapers, max_workers=workers,
            )
        except TypeError:
            probe_gen = iter_probe_results(
                config, scope=scope, scrapers=scrapers,
            )
        for done_index, done_total, result in probe_gen:
            yield json.dumps(
                {
                    "type": "result",
                    "index": done_index,
                    "total": done_total,
                    "result": result,
                },
                ensure_ascii=False,
            ) + "\n"
        yield json.dumps({"type": "done", "total": total, "scope": scope}, ensure_ascii=False) + "\n"

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
