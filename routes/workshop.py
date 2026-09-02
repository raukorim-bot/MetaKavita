"""API de l'atelier des tomes.

Hydratation Kavita/Meta (aucun scrape à l'ouverture), Champ Magique, envoi,
Review tome (staging atelier, pas Kavita), jaquettes déjà dans Kavita. La page HTML vit dans `routes.pages`.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from config_manager import load_config
from kavita_api import KavitaAPI
from services import kavita_cover_cache
from services.workshop import (
    begin_volume_review,
    confirm_volume_review,
    library_is_disabled,
    save_magic_override,
    send_selection,
    send_series,
    send_volume,
    workshop_payload,
    workshop_rail,
)
from translations import translations

workshop_bp = Blueprint("workshop", __name__)

_COVER_KINDS = frozenset({"series", "chapter", "volume"})


def _t():
    config = load_config()
    return translations.get(config.get("UI_LANG", "fr"), translations["fr"])


def _api() -> KavitaAPI:
    config = load_config()
    return KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))


def workshop_enabled(config: dict = None) -> bool:
    cfg = config if config is not None else load_config()
    return bool(cfg.get("VOLUME_ENRICHMENT_ENABLED", False))


@workshop_bp.before_request
def _guard_disabled():
    if workshop_enabled():
        return None
    t = _t()
    return jsonify(
        {
            "success": False,
            "error": t.get("vol_err_disabled", "Enrichissement par tome désactivé."),
            "disabled": True,
        }
    ), 403


def _guard_series(api: KavitaAPI, series_id: int, config: dict):
    series = api.get_series(series_id)
    if not isinstance(series, dict) or not series.get("id"):
        return None, (jsonify({"success": False, "error": "not_found"}), 404)
    if library_is_disabled(series, config):
        t = _t()
        return None, (
            jsonify(
                {
                    "success": False,
                    "error": t.get("workshop_lib_disabled", "Bibliothèque désactivée."),
                    "disabled": True,
                }
            ),
            403,
        )
    return series, None


@workshop_bp.route("/api/series/<int:series_id>/workshop", methods=["GET"])
def workshop_get(series_id):
    config = load_config()
    api = _api()
    series, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = workshop_payload(api, series_id, config=config)
    if not payload:
        return jsonify({"success": False, "error": "not_found"}), 404
    return jsonify({"success": True, **payload})


@workshop_bp.route("/api/workshop/rail", methods=["GET"])
def workshop_get_rail():
    config = load_config()
    return jsonify({"success": True, "rail": workshop_rail(_api(), config=config)})


@workshop_bp.route("/api/kavita-cover/<kind>/<int:entity_id>", methods=["GET"])
def kavita_cover(kind, entity_id):
    """Jaquette déjà dans Kavita. Session Meta, jamais la clé API dans le HTML."""
    name = str(kind or "").strip().lower()
    if name not in _COVER_KINDS:
        return Response(b"", status=404)
    etag = kavita_cover_cache.safe_etag(request.args.get("v") or "")
    cached = kavita_cover_cache.read(name, entity_id, etag)
    if cached:
        data, ctype = cached
    else:
        api = _api()
        data, code = api.fetch_kavita_image(name, entity_id)
        if not data:
            status = 404 if code == "not_found" else 502
            return Response(b"", status=status)
        ctype = code if isinstance(code, str) and code.startswith("image/") else "image/jpeg"
        kavita_cover_cache.write(name, entity_id, etag, data, ctype)
    quoted = f'"{etag}"'
    cache_control = (
        "private, max-age=86400, immutable" if etag != "0" else "private, max-age=300"
    )
    headers = {"Cache-Control": cache_control, "ETag": quoted}
    if etag != "0" and etag in request.if_none_match:
        return Response(status=304, headers=headers)
    return Response(data, mimetype=ctype, headers=headers)


@workshop_bp.route("/api/series/<int:series_id>/workshop/magic", methods=["POST"])
def workshop_magic(series_id):
    t = _t()
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    chapter_id = payload.get("chapter_id")
    url = str(payload.get("url") or "").strip()
    if not chapter_id or not url:
        return jsonify({"success": False, "error": t.get("workshop_err", "Requête incomplète.")}), 400
    result = save_magic_override(
        series_id,
        int(chapter_id),
        url,
        volume_number=payload.get("volume_number"),
    )
    if not result.get("success"):
        return jsonify(
            {
                "success": False,
                "error": t.get("workshop_no_match", "Aucun fournisseur pour cette URL."),
            }
        ), 404
    return jsonify(result)


@workshop_bp.route("/api/series/<int:series_id>/workshop/send", methods=["POST"])
def workshop_send_one(series_id):
    t = _t()
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    chapter_id = payload.get("chapter_id")
    if not chapter_id:
        return jsonify({"success": False, "error": t.get("workshop_err", "Requête incomplète.")}), 400
    result = send_volume(
        api,
        series_id,
        int(chapter_id),
        payload.get("edits") or {},
        # Toujours force : l'atelier n'est pas le comblement de la passe automatique.
        force=True,
        cover_url=str(payload.get("cover_url") or ""),
        extra={
            "volume_id": payload.get("volume_id"),
            "volume_number": payload.get("volume_number"),
            "chapter_number": payload.get("chapter_number"),
        },
    )
    return _send_response(result, t)


@workshop_bp.route("/api/series/<int:series_id>/workshop/send-series", methods=["POST"])
def workshop_send_series_only(series_id):
    t = _t()
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    result = send_series(
        api,
        series_id,
        payload.get("edits") or {},
        force=True,
        cover_url=str(payload.get("cover_url") or ""),
    )
    return _send_response(result, t)


@workshop_bp.route("/api/series/<int:series_id>/workshop/draft-series", methods=["POST"])
def workshop_save_draft_series(series_id):
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    from db_manager import get_workshop_series_override, save_workshop_series_override

    edits = payload.get("edits") or {}
    cover_url = str(payload.get("cover_url") or "").strip()
    existing = get_workshop_series_override(series_id) or {}
    existing_payload = existing.get("payload") or {}
    merged_payload = dict(edits)
    if "_external_ids" in existing_payload:
        merged_payload["_external_ids"] = existing_payload["_external_ids"]
    if not cover_url and existing.get("cover_url"):
        cover_url = str(existing.get("cover_url") or "")
    save_workshop_series_override(series_id, merged_payload, cover_url=cover_url)
    return jsonify({"success": True, "staged": True})


@workshop_bp.route("/api/series/<int:series_id>/workshop/draft-volume", methods=["POST"])
def workshop_save_draft_volume(series_id):
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    chapter_id = payload.get("chapter_id")
    if not chapter_id:
        return jsonify({"success": False, "error": "missing_chapter"}), 400
    edits = payload.get("edits") or {}
    cover_url = str(payload.get("cover_url") or "").strip()
    from db_manager import get_volume_unit_overrides, save_volume_unit_override

    existing = (get_volume_unit_overrides(series_id) or {}).get(int(chapter_id)) or {}
    existing_payload = existing.get("payload") or {}
    merged_payload = dict(existing_payload)
    merged_payload.update(edits)
    merged_payload["_staged"] = True
    merged_payload["_source"] = "manual"
    if cover_url:
        merged_payload["cover_url"] = cover_url
    elif not cover_url and "cover_url" in existing_payload:
        merged_payload["cover_url"] = existing_payload["cover_url"]
    save_volume_unit_override(
        series_id,
        int(chapter_id),
        provider=str(existing.get("provider") or ""),
        provider_ref=str(existing.get("provider_ref") or ""),
        payload=merged_payload,
    )
    return jsonify({"success": True, "staged": True})




@workshop_bp.route("/api/series/<int:series_id>/workshop/send-selection", methods=["POST"])
def workshop_send_checked(series_id):
    t = _t()
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    result = send_selection(
        api,
        series_id,
        payload.get("items") or [],
        force=True,
    )
    return _send_response(result, t)


@workshop_bp.route("/api/series/<int:series_id>/workshop/review", methods=["POST"])
def workshop_review(series_id):
    t = _t()
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    chapter_id = payload.get("chapter_id")
    if not chapter_id:
        return jsonify({"success": False, "error": t.get("workshop_err", "Requête incomplète.")}), 400
    isbn = str(payload.get("isbn") or "").strip() or None
    result = begin_volume_review(
        api,
        series_id,
        int(chapter_id),
        super_review=bool(payload.get("super") or payload.get("super_review")),
        isbn=isbn,
        config=config,
    )
    if not result.get("success"):
        return jsonify(result), 404
    return jsonify(result)


@workshop_bp.route("/api/series/<int:series_id>/workshop/review/confirm", methods=["POST"])
def workshop_review_confirm(series_id):
    t = _t()
    config = load_config()
    api = _api()
    _, err = _guard_series(api, series_id, config)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    chapter_id = payload.get("chapter_id")
    candidate = payload.get("candidate") or {}
    if not chapter_id:
        return jsonify({"success": False, "error": t.get("workshop_err", "Requête incomplète.")}), 400
    result = confirm_volume_review(
        api,
        series_id,
        int(chapter_id),
        candidate if isinstance(candidate, dict) else {},
        force=True,
    )
    return _send_response(result, t)


def _send_response(result: dict, t: dict):
    if result.get("busy"):
        return jsonify(
            {
                **result,
                "success": False,
                "error": result.get("error")
                or t.get("workshop_busy", "Une écriture est déjà en cours sur cette série."),
            }
        ), 409
    if result.get("success"):
        return jsonify(result)
    if result.get("partial"):
        return jsonify(
            {
                **result,
                "success": False,
                "error": result.get("error")
                or t.get("workshop_partial", "Une partie a été écrite, le reste a échoué."),
            }
        ), 200
    return jsonify(
        {
            **result,
            "error": result.get("error") or t.get("workshop_err", "Écriture impossible."),
        }
    ), 500
