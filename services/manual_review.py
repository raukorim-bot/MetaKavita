"""
Helpers mode manuel C29 (Phase 1–2) : park candidats → pick/merge → skip/confirm.

Le worker scrape sans bloquer ; l'UI consomme `pending_reviews` via Socket.IO.
L'écriture Kavita (apply) reste hors de ce module jusqu'aux phases UI/preview.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence

from db_manager import (
    count_pending_reviews,
    close_pending_review,
    park_pending_review,
    get_pending_review,
    update_pending_review,
)
from metadata_fetcher import merge_candidates
from secure_logging import safe_exc_str
from translations import get_ui_translations

# Marqueur interne : résumé déjà passé par translate_text (évite double trad. à l'apply).
SUMMARY_TRANSLATED_KEY = "_summary_translated"


def candidate_summaries_need_translation(candidates_payload: Any) -> bool:
    """True si au moins un résumé non vide n'est pas encore marqué traduit."""
    if not isinstance(candidates_payload, dict):
        return False
    for band in ("above", "below"):
        for card in candidates_payload.get(band) or []:
            if not isinstance(card, dict):
                continue
            data = card.get("data") if isinstance(card.get("data"), dict) else {}
            if data.get(SUMMARY_TRANSLATED_KEY) or card.get(SUMMARY_TRANSLATED_KEY):
                continue
            summary = data.get("summary") or card.get("summary") or ""
            if isinstance(summary, str) and summary.strip():
                return True
    return False


def translate_candidate_summaries(
    candidates_payload: Dict[str, Any],
    config: Optional[dict] = None,
) -> tuple:
    """
    Traduit les résumés de tous les candidats vers TARGET_LANG (moteur config).

    Appelé dès que la file de candidats est complète, *avant* le pick UI, pour
    que l'utilisateur choisisse en comprenant le texte. Idempotent via
    `_summary_translated`. Déduplique les appels API sur texte identique.

    Retourne (payload, n_appels) — n = appels translate_text effectués.
    """
    from config_manager import load_config
    from translator import translate_text

    if not isinstance(candidates_payload, dict):
        return candidates_payload, 0

    cfg = config if isinstance(config, dict) else load_config()
    target_lang = cfg.get("TARGET_LANG", "FR")
    deepl_key = cfg.get("DEEPL_API_KEY")
    cache: Dict[str, str] = {}
    translated_calls = 0

    for band in ("above", "below"):
        cards = candidates_payload.get(band) or []
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            data = card.get("data") if isinstance(card.get("data"), dict) else None
            already = bool(
                (data and data.get(SUMMARY_TRANSLATED_KEY))
                or card.get(SUMMARY_TRANSLATED_KEY)
            )
            if already:
                synced = ""
                if data and isinstance(data.get("summary"), str):
                    synced = data["summary"]
                elif isinstance(card.get("summary"), str):
                    synced = card["summary"]
                if synced:
                    card["summary"] = synced
                    card["summary_excerpt"] = synced[:280]
                    if data is not None:
                        data["summary"] = synced
                        data[SUMMARY_TRANSLATED_KEY] = True
                card[SUMMARY_TRANSLATED_KEY] = True
                continue

            raw = None
            if data and isinstance(data.get("summary"), str) and data.get("summary").strip():
                raw = data["summary"]
            elif isinstance(card.get("summary"), str) and card.get("summary").strip():
                raw = card["summary"]

            if not raw:
                if data is not None:
                    data[SUMMARY_TRANSLATED_KEY] = True
                card[SUMMARY_TRANSLATED_KEY] = True
                continue

            if raw in cache:
                out = cache[raw]
            else:
                out = translate_text(raw, deepl_key, target_lang)
                if not isinstance(out, str) or not out:
                    out = raw
                cache[raw] = out
                translated_calls += 1

            if data is not None:
                data["summary"] = out
                data[SUMMARY_TRANSLATED_KEY] = True
            card["summary"] = out
            card["summary_excerpt"] = out[:280]
            card[SUMMARY_TRANSLATED_KEY] = True

    return candidates_payload, translated_calls


def _safe_emit(event: str, payload: dict) -> None:
    try:
        from extensions import socketio
        socketio.emit(event, payload)
        # Eventlet : force le flush WS (même pattern que covers stream).
        # Le worker batch tourne en thread — sans yield, l'UI peut ne jamais
        # recevoir `manual_review_queued` à temps pour ouvrir la modal.
        try:
            socketio.sleep(0)
        except Exception:
            pass
    except Exception as exc:
        logging.debug("manual_review emit %s skipped: %s", event, exc)


def emit_pending_count() -> int:
    """Émet le compteur de reviews en file (`manual_review_pending_count`)."""
    n = count_pending_reviews()
    _safe_emit("manual_review_pending_count", {"count": n})
    return n


def begin_streaming_review(
    series_id: int,
    series_name: str,
    query: str = "",
    library_id: Optional[int] = None,
) -> str:
    """
    Park an empty `awaiting_pick` review immediately so Companion can open the
    modal while scrapers are still running. Cards arrive via
    `append_streaming_candidate` / `manual_review_candidate` events.
    """
    review_id = str(uuid.uuid4())
    payload = {
        "above": [],
        "below": [],
        "query": query or "",
        "streaming": True,
    }
    park_pending_review(
        review_id=review_id,
        series_id=int(series_id),
        series_name=series_name or "",
        candidates_json=payload,
        state="awaiting_pick",
        library_id=library_id,
    )
    _safe_emit(
        "manual_review_queued",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "series_name": series_name or "",
            "above_count": 0,
            "below_count": 0,
            "library_id": library_id,
            "streaming": True,
        },
    )
    emit_pending_count()
    return review_id


def append_streaming_candidate(
    review_id: str,
    series_id: int,
    card: Dict[str, Any],
    band: str = "above",
) -> None:
    """Merge one candidate card into a streaming review and emit to the UI."""
    if not review_id or not isinstance(card, dict):
        return
    band_key = "below" if band == "below" else "above"
    row = get_pending_review(review_id)
    if not row:
        return
    try:
        payload = json.loads(row.get("candidates_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {"above": [], "below": [], "query": ""}
    if not isinstance(payload, dict):
        payload = {"above": [], "below": [], "query": ""}
    provider = card.get("provider")
    for other in ("above", "below"):
        cards = payload.get(other) or []
        if not isinstance(cards, list):
            continue
        payload[other] = [
            c for c in cards
            if not (isinstance(c, dict) and provider and c.get("provider") == provider)
        ]
    bucket = payload.get(band_key)
    if not isinstance(bucket, list):
        bucket = []
        payload[band_key] = bucket
    bucket.append(card)
    payload["streaming"] = True
    update_pending_review(review_id, candidates_json=payload)
    from metadata_fetcher import candidate_card_for_ui

    lite = candidate_card_for_ui(card) or {
        "provider": provider,
        "score": card.get("score"),
        "title": card.get("title"),
        "cover_url": card.get("cover_url"),
    }
    _safe_emit(
        "manual_review_candidate",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "band": band_key,
            "card": lite,
            "above_count": len(payload.get("above") or []),
            "below_count": len(payload.get("below") or []),
        },
    )


def _payload_keeps_chosen_provider(payload: Any, base_provider: Optional[str]) -> bool:
    """True si le fournisseur déjà choisi par l'utilisateur figure encore dans `payload`."""
    if not base_provider:
        return True
    return base_provider in _cards_by_provider(payload if isinstance(payload, dict) else {})


def finalize_streaming_review(
    review_id: str,
    series_id: int,
    series_name: str,
    candidates_payload: Dict[str, Any],
    library_id: Optional[int] = None,
) -> str:
    """
    Replace the streaming payload with the final (translated) candidates and
    emit `manual_review_scrape_complete`.

    La collecte tourne pendant que l'utilisateur peut déjà agir dans la modale
    (le verrou série de `enrichment_engine` ne couvre ni `/skip` ni le pick
    `choice_and_merge`). Ce finalize est donc un *rafraîchissement* de la liste
    de candidats, jamais une reconstruction : il ne ressuscite pas une review
    passée/purgée entre-temps, et ne fait pas régresser un état déjà avancé par
    l'utilisateur (`awaiting_confirm` garde son état, son fournisseur et son
    preview).
    """
    t = get_ui_translations()
    row = get_pending_review(review_id)
    if not row:
        # Skip / purge pendant la collecte : re-parker recréerait la review ET
        # remettrait la série en PENDING_REVIEW (park_pending_review est atomique).
        logging.info(
            t.get(
                "log_mr_finalize_dropped",
                "[manual_review] review {0} disparue pendant la collecte ({1}) — résultats abandonnés",
            ).format(review_id, series_name or series_id)
        )
        return review_id

    payload = candidates_payload if isinstance(candidates_payload, dict) else {
        "above": [],
        "below": [],
        "query": "",
    }
    try:
        payload, n_tr = translate_candidate_summaries(payload)
        if n_tr:
            logging.info(
                t.get(
                    "log_mr_summaries_translated",
                    "[manual_review] {0} résumé(s) traduit(s) avant pick ({1})",
                ).format(n_tr, series_name or series_id)
            )
    except Exception as exc:
        logging.warning(
            t.get(
                "log_mr_summaries_fail",
                "[manual_review] traduction des résumés échouée pour {0} : {1}",
            ).format(series_name or series_id, exc)
        )
    if isinstance(payload, dict):
        payload.pop("streaming", None)

    state = row.get("state") or "awaiting_pick"
    fields: Dict[str, Any] = {
        "series_name": series_name or "",
        "library_id": library_id,
    }
    if state == "awaiting_pick":
        fields["candidates_json"] = payload
        fields["state"] = "awaiting_pick"
    elif _payload_keeps_chosen_provider(payload, row.get("base_provider")):
        # État avancé : on rafraîchit la liste (résumés traduits, providers arrivés
        # après le pick) sans toucher à state / preview_json / base_provider.
        fields["candidates_json"] = payload
    else:
        # Le fournisseur choisi n'est plus dans la collecte finale : écraser la
        # liste rendrait le confirm impossible (`choice_and_merge` ne le
        # trouverait plus). On garde les cartes sur lesquelles l'utilisateur a
        # travaillé.
        logging.info(
            t.get(
                "log_mr_finalize_keeps_cards",
                "[manual_review] review {0} : candidats conservés (fournisseur choisi absent du résultat final)",
            ).format(review_id)
        )
    update_pending_review(review_id, **fields)

    # Compteurs annoncés à l'UI = ce qui est réellement en base après ce finalize.
    stored = fields.get("candidates_json")
    if stored is None:
        try:
            stored = json.loads(row.get("candidates_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            stored = {}
    if not isinstance(stored, dict):
        stored = {}
    _safe_emit(
        "manual_review_scrape_complete",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "series_name": series_name or "",
            "above_count": len(stored.get("above") or []),
            "below_count": len(stored.get("below") or []),
            "library_id": library_id,
            "state": state,
        },
    )
    emit_pending_count()
    return review_id


def create_review_from_candidates(
    series_id: int,
    series_name: str,
    candidates_payload: Dict[str, Any],
    library_id: Optional[int] = None,
) -> str:
    """
    Crée une pending review `awaiting_pick`, passe le statut série à PENDING_REVIEW,
    émet `manual_review_queued` + compteur.

    Traduit les résumés candidats dès que la collecte est complète, pour que le
    pick UI soit lisible dans TARGET_LANG (sans attendre l'écriture Kavita).

    `library_id` : ID de bibliothèque Kavita de la série, pour le lien de
    vérification affiché dans le pick UI (voir `get_cached_library_id`). `None`
    si pas encore résolu — le lien est alors simplement omis côté UI.
    """
    review_id = str(uuid.uuid4())
    t = get_ui_translations()
    payload = candidates_payload if isinstance(candidates_payload, dict) else {
        "above": [],
        "below": [],
        "query": "",
    }
    try:
        payload, n_tr = translate_candidate_summaries(payload)
        if n_tr:
            logging.info(t.get("log_mr_summaries_translated", "[manual_review] {0} résumé(s) traduit(s) avant pick ({1})").format(n_tr, series_name or series_id))
    except Exception as exc:
        logging.warning(t.get("log_mr_summaries_fail", "[manual_review] traduction des résumés échouée pour {0} : {1}").format(series_name or series_id, exc))
    park_pending_review(
        review_id=review_id,
        series_id=int(series_id),
        series_name=series_name or "",
        candidates_json=payload,
        state="awaiting_pick",
        library_id=library_id,
    )
    _safe_emit(
        "manual_review_queued",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "series_name": series_name or "",
            "above_count": len(payload.get("above") or []),
            "below_count": len(payload.get("below") or []),
            "library_id": library_id,
        },
    )
    emit_pending_count()
    return review_id


def create_confirm_from_auto(
    series_id: int,
    series_name: str,
    provider_data: Dict[str, Any],
    preview_fields: Dict[str, Any],
    *,
    actual_provider: str,
    fusion_providers: Optional[Sequence[str]] = None,
    chosen_score: Any = None,
    query: str = "",
    force_update: bool = False,
    library_id: Optional[int] = None,
) -> str:
    """
    Park auto-batch result as `awaiting_confirm` (pas de pick).

    Réutilise la file `pending_reviews` + panneau d'édition UI. Le worker
    continue ; l'écriture Kavita attend `/confirm`.
    """
    import copy

    from metadata_fetcher import build_candidate_card

    review_id = str(uuid.uuid4())
    t = get_ui_translations()
    provider = (actual_provider or "Inconnu").strip() or "Inconnu"
    data = copy.deepcopy(provider_data) if isinstance(provider_data, dict) else {}
    data["_provider_used"] = provider
    fusions = [p for p in (fusion_providers or []) if p and p != provider]
    if fusions:
        data["_fusion_providers"] = list(fusions)

    card = build_candidate_card(provider, data, below_threshold=False)
    try:
        score_f = float(chosen_score) if chosen_score is not None else None
    except (TypeError, ValueError):
        score_f = None
    if score_f is not None:
        card["score"] = score_f

    payload: Dict[str, Any] = {
        "above": [card],
        "below": [],
        "query": query or series_name or "",
        "flow": "auto_confirm",
        "force_update": bool(force_update),
    }

    preview = dict(preview_fields or {}) if isinstance(preview_fields, dict) else {}
    preview["_provider_used"] = provider
    preview["_fusion_providers"] = list(fusions)
    preview["_flow"] = "auto_confirm"

    park_pending_review(
        review_id=review_id,
        series_id=int(series_id),
        series_name=series_name or "",
        candidates_json=payload,
        preview_json=preview,
        state="awaiting_confirm",
        base_provider=provider,
        chosen_score=score_f,
        library_id=library_id,
    )
    _safe_emit(
        "manual_review_queued",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "series_name": series_name or "",
            "above_count": 1,
            "below_count": 0,
            "flow": "auto_confirm",
            "state": "awaiting_confirm",
            "library_id": library_id,
        },
    )
    emit_pending_count()
    logging.info(t.get("log_confirm_parked", "[{0}] ✏️ CONFIRM_BEFORE_WRITE — preview parkée (provider={1})").format(series_name or series_id, provider))
    return review_id


def _cards_by_provider(candidates_payload: Dict[str, Any]) -> Dict[str, dict]:
    by_provider: Dict[str, dict] = {}
    for band in ("above", "below"):
        for card in candidates_payload.get(band) or []:
            if not isinstance(card, dict):
                continue
            provider = card.get("provider")
            if provider and provider not in by_provider:
                by_provider[provider] = card
    return by_provider


def choice_and_merge(
    review_id: str,
    base_provider: str,
    include_providers: Optional[Sequence[str]] = None,
    smart_fusion: bool = False,
) -> Optional[dict]:
    """
    Merge selon le choix UI : `base_provider` = master.

    `include_providers` (ordre conservé, hors base) comblent les champs vides
    du master lorsque `smart_fusion=True`. En mode review manuelle, l'appelant
    active `smart_fusion` dès qu'au moins une source est cochée — indépendamment
    du toggle sidebar SMART_COMPLETION. Contrairement à l'Auto (BF69), les
    Sources MR peuvent aussi combler ``age_rating`` (choix explicite).

    Met à jour la review en `awaiting_confirm` (preview_json laissé vide —
    construit plus tard par la couche apply/preview).
    """
    review = get_pending_review(review_id)
    if not review:
        return None

    try:
        candidates_payload = json.loads(review["candidates_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        candidates_payload = {"above": [], "below": []}

    by_provider = _cards_by_provider(candidates_payload)
    if base_provider not in by_provider:
        logging.warning(get_ui_translations().get("log_mr_provider_missing", "[manual_review] base_provider {0} introuvable pour review {1}").format(base_provider, review_id))
        return None

    ordered: List[tuple] = [(base_provider, by_provider[base_provider].get("data") or {})]
    seen = {base_provider}
    for provider in include_providers or []:
        if not provider or provider in seen:
            continue
        card = by_provider.get(provider)
        if not card:
            continue
        ordered.append((provider, card.get("data") or {}))
        seen.add(provider)

    # MR Sources = max info (tout âge). Auto SMART_COMPLETION : fill_age_rating=False
    # → BF102 non-adult only (voir metadata_fetcher._fusion_can_fill).
    master = merge_candidates(
        ordered, smart_fusion=smart_fusion, fill_age_rating=bool(smart_fusion)
    )
    if not master:
        return None

    chosen_score = by_provider[base_provider].get("score")
    try:
        chosen_score = float(chosen_score) if chosen_score is not None else None
    except (TypeError, ValueError):
        chosen_score = None

    update_pending_review(
        review_id,
        state="awaiting_confirm",
        base_provider=base_provider,
        chosen_score=chosen_score,
    )
    return master


def skip_pending_review(review_id: str, new_status: str = "PENDING") -> bool:
    """Skip : purge atomique review + statut série + télémétrie skip."""
    review = close_pending_review(review_id, new_status, skip_telemetry=True)
    if not review:
        return False
    series_id = review["series_id"]
    emit_pending_count()
    _safe_emit(
        "manual_review_skipped",
        {"review_id": review_id, "series_id": int(series_id)},
    )
    return True


def confirm_pending_review(review_id: str, new_status: str = "COMPLETED") -> bool:
    """
    Confirm soft : purge atomique la pending + statut série.

    La télémétrie review / écriture Kavita sont gérées par l'appelant
    (phase apply) — ce helper ne fait que clôturer le parking.
    """
    review = close_pending_review(review_id, new_status, skip_telemetry=False)
    if not review:
        return False
    series_id = review["series_id"]
    emit_pending_count()
    _safe_emit(
        "manual_review_confirmed",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "status": new_status or "COMPLETED",
        },
    )
    return True


def purge_all_reviews(reset_status: str = "PENDING") -> dict:
    """
    Vide toute la file de reviews manuelles.

    Remet les séries encore en PENDING_REVIEW à `reset_status` (défaut PENDING).
    N'incrémente pas la télémétrie skip (purge ≠ passer une review).
    """
    from db_manager import purge_all_pending_reviews, record_manual_purge_telemetry

    result = purge_all_pending_reviews(reset_status=reset_status)
    deleted = int(result.get("deleted") or 0)
    if deleted > 0:
        try:
            record_manual_purge_telemetry(deleted)
        except Exception as e:
            logging.debug("manual purge telemetry failed: %s", safe_exc_str(e))
    emit_pending_count()
    _safe_emit(
        "manual_review_purged",
        {
            "deleted": deleted,
            "series_ids": result.get("series_ids") or [],
            "reset_status": reset_status,
        },
    )
    return result


def purge_auto_confirm_reviews(reset_status: str = "PENDING") -> dict:
    """
    Purge uniquement les parks `flow=auto_confirm` (confirm-before-write).

    Laisse intactes les reviews Manual Review (pick).
    """
    from db_manager import list_pending_reviews

    deleted = 0
    series_ids: List[int] = []
    for row in list_pending_reviews(limit=5000) or []:
        try:
            payload = json.loads(row.get("candidates_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict) or payload.get("flow") != "auto_confirm":
            continue
        rid = row.get("review_id")
        if not rid:
            continue
        closed = close_pending_review(rid, reset_status, skip_telemetry=True)
        if closed:
            deleted += 1
            try:
                series_ids.append(int(closed["series_id"]))
            except (TypeError, ValueError, KeyError):
                pass

    if deleted:
        emit_pending_count()
        _safe_emit(
            "manual_review_purged",
            {
                "deleted": deleted,
                "series_ids": series_ids,
                "reset_status": reset_status,
                "flow": "auto_confirm",
            },
        )
    return {"deleted": deleted, "series_ids": series_ids, "reset_status": reset_status}
