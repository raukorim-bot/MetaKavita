"""
Routes mode manuel C29 : liste / pick / confirm / skip des pending reviews.
"""

from flask import Blueprint, request, jsonify

from config_manager import load_config
from db_manager import list_pending_reviews, get_pending_review, count_pending_reviews, update_pending_review
from metadata_fetcher import candidate_card_for_ui
from services.enrichment_engine import (
    apply_manual_review,
    preview_manual_review,
    skip_manual_review,
    research_manual_review,
)
from services.manual_review import (
    candidate_summaries_need_translation,
    translate_candidate_summaries,
)

manual_review_bp = Blueprint("manual_review", __name__)


def _parse_json():
    return request.get_json(silent=True) or {}


@manual_review_bp.route("/api/manual-reviews", methods=["GET"])
def api_list_manual_reviews():
    state = request.args.get("state") or None
    limit = request.args.get("limit", 200)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    rows = list_pending_reviews(state=state, limit=limit)
    config = load_config()
    # Ne pas renvoyer le blob data brut de chaque candidat (lourd) — résumé UI
    out = []
    for r in rows:
        import json
        try:
            cands = json.loads(r.get("candidates_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            cands = {"above": [], "below": []}
        # File déjà en attente avant la trad. au park : rattrapage one-shot.
        if candidate_summaries_need_translation(cands):
            try:
                cands, _n = translate_candidate_summaries(cands, config=config)
                update_pending_review(r["review_id"], candidates_json=cands)
            except Exception:
                pass
        preview = None
        if r.get("preview_json"):
            try:
                preview = json.loads(r["preview_json"]) if isinstance(r["preview_json"], str) else r["preview_json"]
            except (TypeError, ValueError, json.JSONDecodeError):
                preview = None

        def _lite(cards):
            lite = []
            for card in cards or []:
                ui = candidate_card_for_ui(card)
                if ui:
                    lite.append(ui)
            return lite

        out.append({
            "review_id": r["review_id"],
            "series_id": r["series_id"],
            "series_name": r["series_name"],
            "state": r["state"],
            "created_at": r["created_at"],
            "base_provider": r.get("base_provider"),
            "chosen_score": r.get("chosen_score"),
            "above": _lite(cands.get("above")),
            "below": _lite(cands.get("below")),
            "query": cands.get("query") or "",
            "preview": preview,
        })
    return jsonify(success=True, reviews=out, count=count_pending_reviews())


@manual_review_bp.route("/api/manual-reviews/<review_id>/choice", methods=["POST"])
def api_manual_review_choice(review_id):
    data = _parse_json()
    base_provider = (data.get("base_provider") or "").strip()
    include_providers = data.get("include_providers") or []
    if not base_provider:
        return jsonify(success=False, error="base_provider requis"), 400
    if not isinstance(include_providers, list):
        include_providers = [include_providers]

    if not get_pending_review(review_id):
        return jsonify(success=False, error="Review introuvable"), 404

    config = load_config()
    # Préférence UI (évite le décalage si saveConfig n'a pas encore flush)
    if "prefer_edit" in data:
        use_edit = bool(data.get("prefer_edit"))
    else:
        use_edit = bool(config.get("MANUAL_REVIEW_EDIT", True))

    if use_edit:
        ok, preview_or_err, _built = preview_manual_review(
            review_id, base_provider, include_providers=include_providers
        )
        if not ok:
            return jsonify(success=False, error=preview_or_err), 400
        return jsonify(
            success=True,
            mode="preview",
            preview=preview_or_err,
            base_provider=base_provider,
            include_providers=include_providers,
        )

    ok, msg, detail = apply_manual_review(
        review_id,
        base_provider,
        include_providers=include_providers,
        edited_preview=None,
        field_edits=0,
        fused=bool(data.get("fused")) if "fused" in data else None,
        weak_pick=bool(data.get("weak_pick")),
        super_review=bool(data.get("super_review")),
    )
    if not ok:
        return jsonify(success=False, error=msg), 400
    return jsonify(success=True, mode="applied", message=msg, detail=detail)


@manual_review_bp.route("/api/manual-reviews/<review_id>/confirm", methods=["POST"])
def api_manual_review_confirm(review_id):
    data = _parse_json()
    review = get_pending_review(review_id)
    if not review:
        return jsonify(success=False, error="Review introuvable"), 404

    base_provider = (data.get("base_provider") or review.get("base_provider") or "").strip()
    include_providers = data.get("include_providers") or []
    if not base_provider:
        return jsonify(success=False, error="base_provider requis"), 400
    if not isinstance(include_providers, list):
        include_providers = [include_providers]

    edited_fields = data.get("edited_fields") or data.get("edited_preview") or None
    try:
        field_edits = int(data.get("field_edits") or 0)
    except (TypeError, ValueError):
        field_edits = 0

    ok, msg, detail = apply_manual_review(
        review_id,
        base_provider,
        include_providers=include_providers,
        edited_preview=edited_fields,
        field_edits=field_edits,
        fused=bool(data.get("fused")) if "fused" in data else None,
        weak_pick=bool(data.get("weak_pick")),
        super_review=bool(data.get("super_review")),
    )
    if not ok:
        return jsonify(success=False, error=msg), 400
    return jsonify(success=True, message=msg, detail=detail)


@manual_review_bp.route("/api/manual-reviews/<review_id>/research", methods=["POST"])
def api_manual_review_research(review_id):
    """Re-scrape avec un nouveau titre (écrase les candidats de cette review)."""
    data = _parse_json()
    query = (data.get("query") or data.get("title") or data.get("alternative_title") or "").strip()
    if not query:
        return jsonify(success=False, error="query requis"), 400
    if not get_pending_review(review_id):
        return jsonify(success=False, error="Review introuvable"), 404

    ok, msg, detail = research_manual_review(review_id, query)
    if not ok:
        return jsonify(success=False, error=msg, detail=detail), 400
    return jsonify(success=True, message=msg, review=detail)


@manual_review_bp.route("/api/manual-reviews/<review_id>/skip", methods=["POST"])
def api_manual_review_skip(review_id):
    if not get_pending_review(review_id):
        return jsonify(success=False, error="Review introuvable"), 404
    ok = skip_manual_review(review_id)
    if not ok:
        return jsonify(success=False, error="Skip échoué"), 400
    return jsonify(success=True, count=count_pending_reviews())


@manual_review_bp.route("/api/manual-reviews/purge", methods=["POST"])
def api_manual_reviews_purge():
    """Vide toute la file de reviews manuelles (séries → PENDING)."""
    from services.manual_review import purge_all_reviews

    result = purge_all_reviews(reset_status="PENDING")
    return jsonify(
        success=True,
        deleted=int(result.get("deleted") or 0),
        series_ids=result.get("series_ids") or [],
        count=count_pending_reviews(),
    )
