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
    delete_pending_review,
    get_pending_review,
    record_manual_skip_telemetry,
    save_pending_review,
    update_pending_review,
    update_status,
)
from metadata_fetcher import merge_candidates

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


def create_review_from_candidates(
    series_id: int,
    series_name: str,
    candidates_payload: Dict[str, Any],
) -> str:
    """
    Crée une pending review `awaiting_pick`, passe le statut série à PENDING_REVIEW,
    émet `manual_review_queued` + compteur.

    Traduit les résumés candidats dès que la collecte est complète, pour que le
    pick UI soit lisible dans TARGET_LANG (sans attendre l'écriture Kavita).
    """
    review_id = str(uuid.uuid4())
    payload = candidates_payload if isinstance(candidates_payload, dict) else {
        "above": [],
        "below": [],
        "query": "",
    }
    try:
        payload, n_tr = translate_candidate_summaries(payload)
        if n_tr:
            logging.info(
                "[manual_review] %s résumé(s) traduit(s) avant pick (%s)",
                n_tr,
                series_name or series_id,
            )
    except Exception as exc:
        logging.warning(
            "[manual_review] traduction des résumés échouée pour %s : %s",
            series_name or series_id,
            exc,
        )
    save_pending_review(
        review_id=review_id,
        series_id=int(series_id),
        series_name=series_name or "",
        candidates_json=payload,
        state="awaiting_pick",
    )
    update_status(int(series_id), "PENDING_REVIEW")
    _safe_emit(
        "manual_review_queued",
        {
            "review_id": review_id,
            "series_id": int(series_id),
            "series_name": series_name or "",
            "above_count": len(payload.get("above") or []),
            "below_count": len(payload.get("below") or []),
        },
    )
    emit_pending_count()
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
    du toggle sidebar SMART_COMPLETION.

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
        logging.warning(
            "[manual_review] base_provider %s introuvable pour review %s",
            base_provider,
            review_id,
        )
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

    master = merge_candidates(ordered, smart_fusion=smart_fusion)
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
    """Skip : supprime la pending, remet le statut série, télémétrie skip."""
    review = get_pending_review(review_id)
    if not review:
        return False
    series_id = review["series_id"]
    delete_pending_review(review_id)
    update_status(int(series_id), new_status)
    record_manual_skip_telemetry()
    emit_pending_count()
    _safe_emit(
        "manual_review_skipped",
        {"review_id": review_id, "series_id": int(series_id)},
    )
    return True


def confirm_pending_review(review_id: str, new_status: str = "COMPLETED") -> bool:
    """
    Confirm soft : purge la pending + statut série.

    La télémétrie review / écriture Kavita sont gérées par l'appelant
    (phase apply) — ce helper ne fait que clôturer le parking.
    """
    review = get_pending_review(review_id)
    if not review:
        return False
    series_id = review["series_id"]
    delete_pending_review(review_id)
    update_status(int(series_id), new_status)
    emit_pending_count()
    _safe_emit(
        "manual_review_confirmed",
        {"review_id": review_id, "series_id": int(series_id)},
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
        except Exception:
            pass
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
