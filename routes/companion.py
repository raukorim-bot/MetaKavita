"""
C33 Companion embed — Minimal Manual Review shell for the browser extension overlay.
"""
from __future__ import annotations

import secrets

from flask import Blueprint, request, render_template, jsonify, make_response

from companion_csp import (
    apply_companion_embed_framing_headers,
    is_allowed_parent_origin,
    is_http_origin,
    normalize_origin,
    parse_companion_frame_ancestors,
)
from config_manager import load_config
from scrapers.utils import get_match_accept_threshold
from services.companion_embed_auth import issue_embed_token, validate_embed_token
from translations import translations

companion_bp = Blueprint("companion", __name__)


def _extra_frame_ancestors(config) -> list:
    """
    Missing key → env fallback.
    Explicit empty string → no extras (do not re-read env).
    """
    cfg = config or {}
    if "COMPANION_FRAME_ANCESTORS" not in cfg:
        return parse_companion_frame_ancestors(None)
    raw = cfg.get("COMPANION_FRAME_ANCESTORS")
    if raw is None:
        return parse_companion_frame_ancestors(None)
    if str(raw).strip() == "":
        return []
    return parse_companion_frame_ancestors(str(raw))


def _mr_translations(t: dict) -> dict:
    """Subset of UI strings needed by manual_review.js / embed chrome."""
    out = {}
    for key, val in (t or {}).items():
        if key.startswith("mr_") or key.startswith("filter_") or key in (
            "buy_me_coffee",
            "save",
            "update",
            "err_kavita",
            "terminal_ready",
            "companion_wait_timeout",
            "companion_wait_text",
            "mr_streaming",
        ):
            out[key] = val
    return out


def _webhook_token_ok(config) -> bool:
    expected = (config or {}).get("WEBHOOK_TOKEN") or ""
    header = request.headers.get("X-Webhook-Token") or ""
    query = request.args.get("token") or ""
    token = header or query
    if not token or not expected:
        return False
    try:
        return secrets.compare_digest(
            token.encode("utf-8"),
            expected.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


@companion_bp.route("/companion/embed-token", methods=["POST"])
def companion_embed_token():
    """
    Issue a short-lived embed token (webhook auth).

    Body JSON: { seriesId, parent_origin? }
    """
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    if not _webhook_token_ok(config):
        return jsonify(success=False, code="unauthorized", message="Unauthorized"), 401

    payload = request.get_json(silent=True) or {}
    series_raw = payload.get("seriesId") or payload.get("series_id")
    try:
        series_id = int(series_raw)
        if series_id <= 0:
            raise ValueError("bad id")
    except (TypeError, ValueError):
        return jsonify(
            success=False,
            code="invalid_series_id",
            message=t.get("companion_embed_invalid_series", "series_id invalide"),
        ), 400

    parent_origin = (payload.get("parent_origin") or payload.get("parentOrigin") or "").strip()
    if parent_origin and not is_allowed_parent_origin(parent_origin):
        parent_origin = ""

    token = issue_embed_token(series_id, parent_origin=parent_origin)
    return jsonify(
        success=True,
        embed_token=token,
        series_id=series_id,
        expires_in=15 * 60,
    )


def _series_queue_state(series_id: int) -> dict:
    """En file, ou en cours ? Deux files coexistent, il faut les deux.

    `should_skip_batch_item` a la sémantique INVERSE de son nom : il rend True
    quand AUCUNE ligne active n'existe pour la série. Et `queued_series_ids` ne
    voit pas la série en cours de traitement — elle a déjà quitté la file.
    """
    queued = False
    running = False
    try:
        from services.batch_queue import should_skip_batch_item

        queued = not should_skip_batch_item(series_id)
    except Exception:  # noqa: BLE001 - un état indisponible n'est pas une erreur
        pass
    try:
        from services.background_tasks import queued_series_ids, is_batch_active

        if series_id in queued_series_ids():
            queued = True
        elif queued and is_batch_active():
            running = True
    except Exception:  # noqa: BLE001
        pass
    return {"queued": queued and not running, "running": running}


def _pending_review(series_id: int) -> bool:
    try:
        from db_manager import list_pending_reviews

        return any(
            str(r.get("series_id")) == str(series_id) for r in list_pending_reviews()
        )
    except Exception:  # noqa: BLE001
        return False


@companion_bp.route("/companion/series/<int:series_id>/status", methods=["GET"])
def companion_series_status(series_id):
    """Où en est cette série, vue de MetaKavita.

    Sert la pastille du Companion. Authentification par jeton webhook, vérifiée
    ICI — même schéma que `/companion/embed-token`, et pour la même raison : la
    requête part du service worker, jamais de la page Kavita.

    Un jeton d'embed aurait aussi pu convenir, mais il aurait fallu en ÉMETTRE
    un sur chaque série visitée — soit une capacité de quinze minutes sur les
    routes de review, juste pour afficher une pastille passive.

    Lecture seule et sans appel à Kavita : la pastille ne doit pas coûter un
    aller-retour réseau à chaque fiche ouverte.
    """
    from db_manager import get_cached_series, get_series_pass_state, get_workshop_series_override
    from services.build_info import build_commit
    from services.changelog_service import get_current_version

    config = load_config()
    if not _webhook_token_ok(config):
        return jsonify(success=False, code="unauthorized", message="Unauthorized"), 401

    cached = get_cached_series(series_id)
    pass_state = get_series_pass_state(series_id)
    try:
        draft = get_workshop_series_override(series_id)
    except Exception:  # noqa: BLE001
        draft = None

    payload = {
        "success": True,
        "series_id": series_id,
        "known": cached is not None,
        "status": (cached or {}).get("status") or None,
        "cover_manual": bool((cached or {}).get("cover_manual")),
        "inventory_excluded": bool((cached or {}).get("inventory_excluded")),
        "pending_review": _pending_review(series_id),
        "last_pass_at": (pass_state or {}).get("updated_at") or "",
        "has_workshop_draft": bool(draft),
        "volumes_enabled": bool(config.get("VOLUME_ENRICHMENT_ENABLED")),
        "server_version": get_current_version(),
        "server_commit": build_commit(),
    }
    payload.update(_series_queue_state(series_id))
    return jsonify(payload)


@companion_bp.route("/companion/embed", methods=["GET"])
def companion_embed():
    """
    MR shell for MetaKavita Companion (iframe inside extension overlay).

    Auth: Flask session OR valid embed_token (issued via /companion/embed-token).

    Query:
      series_id (required int)
      review_id (optional)
      parent_origin (optional chrome-extension://… / moz-extension://…)
      embed_token (optional Companion bypass for SameSite iframe)
    """
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])

    series_raw = request.args.get("series_id") or request.args.get("seriesId")
    if series_raw is None or str(series_raw).strip() == "":
        return jsonify(
            success=False,
            code="missing_series_id",
            message=t.get("companion_embed_missing_series", "series_id requis"),
        ), 400
    try:
        series_id = int(series_raw)
    except (TypeError, ValueError):
        return jsonify(
            success=False,
            code="invalid_series_id",
            message=t.get("companion_embed_invalid_series", "series_id invalide"),
        ), 400

    embed_token = (request.args.get("embed_token") or request.args.get("embedToken") or "").strip()
    token_data = validate_embed_token(embed_token, series_id) if embed_token else None

    review_id = (request.args.get("review_id") or request.args.get("reviewId") or "").strip() or None
    parent_origin = (request.args.get("parent_origin") or "").strip()
    if not parent_origin and token_data:
        parent_origin = str(token_data.get("parent_origin") or "")
    if parent_origin and not is_allowed_parent_origin(parent_origin):
        parent_origin = ""

    kavita_ui = (config.get("KAVITA_URL") or "").rstrip("/")

    # The embed iframe is nested: Kavita page (http) > extension overlay
    # (chrome/moz-extension) > this embed. CSP frame-ancestors must allow EVERY
    # ancestor, so whitelist the top-level Kavita page origin too. The same
    # origin is the real postMessage parent when the overlay injects the MR
    # iframe straight into the Kavita page (http-in-http, avoids mixed content).
    extras = list(_extra_frame_ancestors(config))
    top_origin = ""
    for candidate in (
        request.args.get("top_origin"),
        request.args.get("kavita_origin"),
        kavita_ui,
    ):
        origin = normalize_origin(candidate)
        if origin and is_http_origin(origin):
            if not top_origin:
                top_origin = origin
            if origin not in extras:
                extras.append(origin)

    # The embed shell has no sidebar, so manual_review.js cannot read the review
    # options from checkboxes like it does in the dashboard. Without these the
    # cover phase was silently skipped on every Companion Super Review (BF107).
    # manualMode / superReview are true by construction: this shell only exists
    # because the Companion webhook forced a Super Review for that one run.
    mr_options = {
        "manualMode": True,
        "superReview": True,
        "edit": bool(config.get("MANUAL_REVIEW_EDIT", True)),
        "coverPick": bool(config.get("MANUAL_REVIEW_COVER_PICK")),
    }

    html = render_template(
        "companion_embed.html",
        t=t,
        config=config,
        mr_options=mr_options,
        series_id=series_id,
        review_id=review_id or "",
        parent_origin=parent_origin,
        top_origin=top_origin,
        app_translations=_mr_translations(t),
        kavita_ui_url=kavita_ui,
        match_accept_threshold=get_match_accept_threshold(config),
        companion_wait_title=t.get("companion_wait_title", "Super Review"),
        companion_wait_text=t.get(
            "companion_wait_text",
            "Scraping en cours… les candidats s’affichent dès qu’ils arrivent.",
        ),
        embed_token=embed_token if token_data else "",
        companion_wait_timeout=t.get(
            "companion_wait_timeout",
            "Délai dépassé — ouvrez Manual Review dans MetaKavita ou réessayez.",
        ),
    )
    resp = make_response(html)
    # Marker for the extension to detect a real embed (vs login redirect HTML).
    resp.headers["X-MetaKavita-Companion-Embed"] = "1"
    if token_data:
        resp.headers["X-MetaKavita-Companion-Auth"] = "embed-token"
    return apply_companion_embed_framing_headers(resp, extras)
