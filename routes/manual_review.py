"""
Routes mode manuel C29 : liste / pick / confirm / skip des pending reviews.
"""

import json
import logging

from flask import Blueprint, request, jsonify

from auth_manager import companion_embed_scope, is_authenticated
from config_manager import load_config
from db_manager import list_pending_reviews, get_pending_review, count_pending_reviews, update_pending_review
from metadata_fetcher import candidate_card_for_ui
from scrapers.utils import get_match_accept_threshold
from secure_logging import safe_exc_str
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
from translations import translations

manual_review_bp = Blueprint("manual_review", __name__)

# Plancher du curseur « Tout accepter ≥ seuil » (`mrListThreshold`, min 0.30).
# Le respecter côté serveur aussi : un `threshold: 0` posté à la main viderait la
# file en acceptant le premier candidat de chaque série, quel que soit son score.
_BULK_ACCEPT_MIN_THRESHOLD = 0.30


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
    # Companion sans session : le jeton d'embed est émis pour une série précise,
    # depuis sa page Kavita. La file complète (noms des autres séries, volumétrie)
    # n'a pas à sortir par ce chemin — l'embed ne montrait déjà que sa série,
    # mais le filtre était côté client.
    embed_scope = None if is_authenticated() else companion_embed_scope()
    if embed_scope is not None:
        rows = [r for r in rows if str(r.get("series_id")) == str(embed_scope)]
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
            except Exception as e:
                logging.debug("pending list summary translation failed: %s", safe_exc_str(e))
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
            "library_id": r.get("library_id"),
            "above": _lite(cands.get("above")),
            "below": _lite(cands.get("below")),
            "query": cands.get("query") or "",
            "flow": cands.get("flow") or "",
            "streaming": bool(cands.get("streaming")),
            "preview": preview,
        })
    count = len(out) if embed_scope is not None else count_pending_reviews()
    return jsonify(success=True, reviews=out, count=count)


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
    # Missing key → None (restore Sources from preview). Present [] → clear.
    if "include_providers" in data:
        include_providers = data.get("include_providers")
        if not isinstance(include_providers, list):
            include_providers = [include_providers] if include_providers else []
    else:
        include_providers = None
    if not base_provider:
        return jsonify(success=False, error="base_provider requis"), 400

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
        force_cover_upload=bool(data.get("cover_picked") or data.get("force_cover_upload")),
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
    t = translations.get(load_config().get("UI_LANG", "fr"), translations["fr"])
    if not get_pending_review(review_id):
        return jsonify(success=False, error=t.get("err_review_not_found", "Review introuvable")), 404
    ok = skip_manual_review(review_id)
    if not ok:
        return jsonify(success=False, error=t.get("err_skip_failed", "Skip échoué")), 400
    return jsonify(success=True, count=count_pending_reviews())


@manual_review_bp.route("/api/manual-reviews/bulk-accept", methods=["POST"])
def api_manual_reviews_bulk_accept():
    """Accepte en masse le TOP1 de chaque review dont le score dépasse un seuil.

    Volontairement pas une nouvelle automatisation : reprend exactement le
    chemin « Confirmer sans édition » (`apply_manual_review` avec le seul
    `base_provider`, sans `include_providers` ni `edited_preview`) déjà utilisé
    par `/choice` quand `MANUAL_REVIEW_EDIT` est désactivé. `/batch-sync` reste
    le seul endroit qui scrape automatiquement ; ceci ne fait qu'appliquer des
    résultats déjà scrapés et déjà en attente d'un geste humain.

    Ne touche qu'aux reviews encore `awaiting_pick` : une review déjà en
    `awaiting_confirm` a un preview en cours de personnalisation par
    l'utilisateur (choix de fournisseur, édition de champs...) que ce bouton
    ne doit pas écraser silencieusement.

    Le seuil demandé s'applique aux deux bandes. Ne lire que `above` (les
    candidats au-dessus du seuil de match réel) contredisait le curseur, qui
    promet « tout ce qui dépasse ce score » et descend jusqu'à 30 % justement
    pour rattraper les correspondances faibles : une review dont le seul candidat
    était à 0,50 était comptée en « laissée en file » sans un mot. Deux
    garde-fous pour que l'acceptation en masse d'un match faible ne devienne pas
    un piège : le plancher du curseur vaut aussi ici (un `threshold: 0` posté à
    la main n'accepte pas la file entière), et l'acceptation d'un candidat de la
    bande basse est tracée comme un choix faible (`weak_pick`) puis comptée à
    part dans la réponse.

    Corps JSON optionnel : `{"threshold": 0.6, "review_ids": [...]}`. Sans
    `review_ids`, s'applique à toute la file `awaiting_pick`.
    """
    data = _parse_json()
    try:
        threshold = float(data.get("threshold", get_match_accept_threshold()))
    except (TypeError, ValueError):
        threshold = get_match_accept_threshold()
    threshold = max(_BULK_ACCEPT_MIN_THRESHOLD, min(1.0, threshold))

    wanted_ids = data.get("review_ids")
    if wanted_ids is not None and not isinstance(wanted_ids, list):
        wanted_ids = [wanted_ids]
    wanted_ids = set(str(rid) for rid in wanted_ids) if wanted_ids else None

    rows = list_pending_reviews(state="awaiting_pick", limit=2000)

    accepted, skipped, failed, weak = [], [], [], []
    for r in rows:
        review_id = r["review_id"]
        if wanted_ids is not None and str(review_id) not in wanted_ids:
            continue

        try:
            cands = json.loads(r.get("candidates_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            cands = {}
        above = (cands.get("above") if isinstance(cands, dict) else None) or []
        below = (cands.get("below") if isinstance(cands, dict) else None) or []

        # Les deux bandes sont déjà triées par score et toute la bande haute
        # domine la bande basse : les concaténer suffit à retrouver le meilleur.
        ranked = list(above) + list(below)
        top = ranked[0] if ranked else None
        is_weak = bool(top) and not above
        provider = (top or {}).get("provider")
        try:
            score = float((top or {}).get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        if not top or not provider or score < threshold:
            skipped.append(review_id)
            continue

        try:
            ok, msg, _detail = apply_manual_review(
                review_id, provider, include_providers=[], weak_pick=is_weak
            )
        except Exception as exc:
            logging.error("[manual_review] bulk-accept crash sur %s : %s", review_id, exc)
            ok, msg = False, str(exc)
        if ok:
            accepted.append(review_id)
            if is_weak:
                weak.append(review_id)
        else:
            failed.append({"review_id": review_id, "error": msg})

    if weak:
        logging.warning(
            "[manual_review] bulk-accept : %s correspondance(s) faible(s) acceptée(s) "
            "au seuil demandé de %.2f — %s",
            len(weak),
            threshold,
            ", ".join(str(rid) for rid in weak),
        )

    return jsonify(
        success=True,
        accepted=len(accepted),
        accepted_weak=len(weak),
        skipped=len(skipped),
        failed=failed,
        threshold=threshold,
        remaining=count_pending_reviews(),
    )


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
