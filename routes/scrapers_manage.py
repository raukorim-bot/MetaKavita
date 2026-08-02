"""
Gestion des scrapers installés + Magasin community.

Pages :
  scrapers_manage.manage   GET /manage-scrapers
  scrapers_manage.store    GET /scraper-store

API :
  GET    /api/scrapers/installed
  POST   /api/scrapers/<id>/enable
  POST   /api/scrapers/<id>/disable
  DELETE /api/scrapers/<id>
  GET    /api/scrapers/store
  POST   /api/scrapers/store/install
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from config_manager import (
    CONFIG_LOCK,
    format_disabled_scrapers,
    get_disabled_scraper_ids,
    load_config,
    save_config,
)
from scrapers import ScraperRegistry
from services.changelog_service import get_current_version
from services.scraper_manager import (
    delete_scraper_file,
    is_core_filename,
    resolve_origin,
)
from services.scraper_store import StoreError, catalog_index, get_store_payload, install_from_catalog
from translations import translations

scrapers_manage_bp = Blueprint("scrapers_manage", __name__)


def _ui():
    config = load_config()
    ui_lang = config.get("UI_LANG", "fr")
    t = translations.get(ui_lang, translations["fr"])
    return config, ui_lang, t


def _provider_slots(config):
    keys = [
        "PROVIDER_1", "PROVIDER_2", "PROVIDER_3",
        "COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3",
        "BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3",
    ]
    used = []
    for k in keys:
        raw = (config.get(k) or "").strip().upper()
        if raw and raw != "NONE":
            used.append({"slot": k, "id": raw})
    return used


def list_installed_payload(config=None):
    config = config if config is not None else load_config()
    disabled = get_disabled_scraper_ids(config)
    slots = _provider_slots(config)
    slot_ids = {s["id"] for s in slots}
    cat = catalog_index()
    rows = []
    for scraper in ScraperRegistry.get_all(include_disabled=True):
        src = ScraperRegistry.get_source_file(scraper.id) or ""
        origin = resolve_origin(src) if src else "custom"
        is_core = is_core_filename(src) if src else False
        enabled = scraper.id not in disabled
        scopes = sorted(scraper.normalized_scopes()) if hasattr(scraper, "normalized_scopes") else ["series"]
        from_store = origin == "community"
        off_store = origin == "custom"
        in_catalog = bool(
            cat["available"]
            and (scraper.id in cat["ids"] or (src and src in cat["files"]))
        )
        removed_from_store = bool(from_store and cat["available"] and not in_catalog)
        retired = bool(scraper.id in cat["retired_ids"])
        rows.append({
            "id": scraper.id,
            "display_name": scraper.localized_display_name,
            "file": src,
            "origin": origin,
            "is_core": is_core,
            "enabled": enabled,
            "supported_types": sorted(scraper.supported_types or []),
            "scopes": scopes,
            "needs_api_key": bool(getattr(scraper, "needs_api_key", False)),
            "in_providers": scraper.id in slot_ids,
            "volume_ready_hint": "volume" in scopes and "series" not in scopes,
            "from_store": from_store,
            "off_store": off_store,
            "removed_from_store": removed_from_store,
            "retired": retired,
            "status": "retired" if retired else "",
        })
    rows.sort(key=lambda r: (
        0 if r.get("retired") else 1,
        0 if r.get("removed_from_store") else 1,
        0 if r.get("off_store") else 1,
        (r["display_name"] or r["id"]).lower(),
    ))

    warnings = []
    for slot in slots:
        sid = slot["id"]
        if ScraperRegistry.get(sid, include_disabled=True) is None:
            warnings.append({"type": "missing", "slot": slot["slot"], "id": sid})
        elif sid in disabled:
            warnings.append({"type": "disabled", "slot": slot["slot"], "id": sid})

    return {"scrapers": rows, "warnings": warnings}


def _set_disabled(scraper_id: str, disabled: bool):
    sid = (scraper_id or "").strip().upper()
    if not sid:
        return False, "missing id", 400
    if ScraperRegistry.get(sid, include_disabled=True) is None:
        return False, "unknown scraper", 404
    with CONFIG_LOCK:
        config = load_config()
        current = get_disabled_scraper_ids(config)
        if disabled:
            current.add(sid)
        else:
            current.discard(sid)
        config["DISABLED_SCRAPERS"] = format_disabled_scrapers(current)
        save_config(config)
    return True, "ok", 200


@scrapers_manage_bp.route("/manage-scrapers")
def manage():
    config, ui_lang, t = _ui()
    return render_template(
        "scraper_hub.html",
        config=config,
        t=t,
        app_version=get_current_version(),
        active_tab="manage",
        page_title=t.get("scraper_manage_title", "Scrapers"),
    )


@scrapers_manage_bp.route("/scraper-store")
def store():
    config, ui_lang, t = _ui()
    return render_template(
        "scraper_hub.html",
        config=config,
        t=t,
        app_version=get_current_version(),
        active_tab="store",
        page_title=t.get("scraper_store_title", "Magasin"),
    )


@scrapers_manage_bp.route("/api/scrapers/installed")
def api_installed():
    config = load_config()
    return jsonify({"success": True, **list_installed_payload(config)})


@scrapers_manage_bp.route("/api/scrapers/<scraper_id>/enable", methods=["POST"])
def api_enable(scraper_id):
    ok, msg, code = _set_disabled(scraper_id, False)
    if not ok:
        return jsonify({"success": False, "msg": msg}), code
    return jsonify({"success": True, "id": scraper_id.upper(), "enabled": True})


@scrapers_manage_bp.route("/api/scrapers/<scraper_id>/disable", methods=["POST"])
def api_disable(scraper_id):
    ok, msg, code = _set_disabled(scraper_id, True)
    if not ok:
        return jsonify({"success": False, "msg": msg}), code
    return jsonify({"success": True, "id": scraper_id.upper(), "enabled": False})


@scrapers_manage_bp.route("/api/scrapers/<scraper_id>", methods=["DELETE"])
def api_delete(scraper_id):
    sid = (scraper_id or "").strip().upper()
    scraper = ScraperRegistry.get(sid, include_disabled=True)
    if scraper is None:
        return jsonify({"success": False, "msg": "unknown scraper"}), 404
    src = ScraperRegistry.get_source_file(sid)
    if not src or is_core_filename(src):
        return jsonify({"success": False, "msg": "core scrapers cannot be deleted"}), 403
    try:
        delete_scraper_file(src)
    except PermissionError as e:
        return jsonify({"success": False, "msg": str(e)}), 403
    except ValueError as e:
        return jsonify({"success": False, "msg": str(e)}), 400
    except OSError as e:
        logging.error("[Scrapers] delete failed %s: %s", sid, e)
        return jsonify({"success": False, "msg": "delete failed"}), 500

    # Clear from disabled list if present
    with CONFIG_LOCK:
        config = load_config()
        current = get_disabled_scraper_ids(config)
        if sid in current:
            current.discard(sid)
            config["DISABLED_SCRAPERS"] = format_disabled_scrapers(current)
            save_config(config)

    ScraperRegistry.reload()
    return jsonify({"success": True, "id": sid, "deleted": True})


@scrapers_manage_bp.route("/api/scrapers/store")
def api_store():
    config = load_config()
    lang = config.get("UI_LANG", "fr")
    force = (request.args.get("refresh") or "").lower() in ("1", "true", "yes")
    try:
        payload = get_store_payload(lang=lang, force=force)
        return jsonify({"success": True, "catalog": payload})
    except StoreError as e:
        return jsonify({
            "success": False,
            "msg": e.message,
            "repo": "https://github.com/raukorim-bot/community-scraper-metakavita",
        }), e.status_code


@scrapers_manage_bp.route("/api/scrapers/store/install", methods=["POST"])
def api_store_install():
    data = request.get_json(silent=True) or {}
    scraper_id = data.get("id") or ""
    force = bool(data.get("force"))
    _, _, t = _ui()
    try:
        result = install_from_catalog(scraper_id, force=force)
        return jsonify({"success": True, **result})
    except StoreError as e:
        msg = e.message
        if "retired" in (msg or "").lower():
            msg = t.get("scraper_retired_blocked") or msg
        return jsonify({"success": False, "msg": msg}), e.status_code
    except PermissionError as e:
        return jsonify({"success": False, "msg": str(e)}), 403
    except Exception as e:
        logging.error("[Store] install failed: %s", e)
        return jsonify({"success": False, "msg": "install failed"}), 500
