"""
`finalize_streaming_review()` ne doit pas écraser une décision utilisateur (BF125).

La collecte MR / Super Review parque une review vide (`begin_streaming_review`),
ajoute les cartes au fil des scrapers, puis appelle `finalize_streaming_review()`
avec le payload complet. Ce finalize reconstruisait la ligne inconditionnellement
(`state="awaiting_pick"`), sans regarder si la review existait encore ni dans quel
état l'utilisateur l'avait mise pendant que les scrapers tournaient :

* « Passer » (skip) pendant la collecte → la review disparaissait de la file puis
  RÉAPPARAISSAIT quelques secondes plus tard (park_pending_review remettait aussi
  la série en PENDING_REVIEW) ;
* choisir un fournisseur pendant la collecte (`choice_and_merge`, qui ne pose pas
  le verrou série) → la review repassait de `awaiting_confirm` à `awaiting_pick`,
  preview et fournisseur choisi perdus.
"""
from __future__ import annotations

import json

import pytest

from db_manager import get_pending_review, update_pending_review
from services.manual_review import (
    append_streaming_candidate,
    begin_streaming_review,
    finalize_streaming_review,
    skip_pending_review,
)


@pytest.fixture(autouse=True)
def _no_emit_no_network(monkeypatch):
    monkeypatch.setattr("services.manual_review._safe_emit", lambda *a, **k: None)
    monkeypatch.setattr("services.manual_review.emit_pending_count", lambda: 0)
    monkeypatch.setattr("translator.translate_text", lambda text, *a, **k: text)


def _final_payload():
    return {
        "above": [
            {
                "provider": "AniList",
                "score": 0.91,
                "title": "One Piece",
                "cover_url": "",
                "summary": "ok",
                "data": {"summary": "ok"},
            },
            {
                "provider": "MAL",
                "score": 0.80,
                "title": "One Piece",
                "cover_url": "",
                "summary": "ok2",
                "data": {"summary": "ok2"},
            },
        ],
        "below": [],
        "query": "One Piece",
        "streaming": True,
    }


def test_finalize_ne_ressuscite_pas_une_review_passee(isolated_db):
    """Skip pendant la collecte : la review ne doit pas revenir dans la file."""
    rid = begin_streaming_review(42, "One Piece", query="One Piece", library_id=1)
    append_streaming_candidate(
        rid,
        42,
        {"provider": "AniList", "score": 0.91, "title": "One Piece", "cover_url": "", "summary": ""},
        "above",
    )

    assert skip_pending_review(rid) is True
    assert get_pending_review(rid) is None

    finalize_streaming_review(rid, 42, "One Piece", _final_payload(), library_id=1)

    assert get_pending_review(rid) is None, (
        "la review passée par l'utilisateur a été ressuscitée par la fin du scrape"
    )
    assert isolated_db.get_all_cached_data().get(42, {}).get("status") != "PENDING_REVIEW"


def test_finalize_preserve_un_choix_utilisateur(isolated_db):
    """Pick pendant la collecte : l'état, le fournisseur et le preview survivent."""
    rid = begin_streaming_review(43, "Naruto", query="Naruto", library_id=2)
    append_streaming_candidate(
        rid,
        43,
        {"provider": "AniList", "score": 0.91, "title": "Naruto", "cover_url": "", "summary": ""},
        "above",
    )
    # L'utilisateur choisit un fournisseur pendant que les scrapers tournent :
    # `choice_and_merge` / `preview_manual_review` avancent la review.
    update_pending_review(
        rid,
        state="awaiting_confirm",
        base_provider="AniList",
        chosen_score=0.91,
        preview_json={"summary": "Résumé édité", "_provider_used": "AniList"},
    )

    finalize_streaming_review(rid, 43, "Naruto", _final_payload(), library_id=2)

    row = get_pending_review(rid)
    assert row is not None
    assert row["state"] == "awaiting_confirm", (
        "la fin du scrape a fait régresser la review vers awaiting_pick"
    )
    assert row["base_provider"] == "AniList"
    assert row["chosen_score"] == pytest.approx(0.91)
    preview = json.loads(row["preview_json"])
    assert preview["summary"] == "Résumé édité", "le preview de l'utilisateur a été perdu"
    # La liste de candidats est bien rafraîchie avec la collecte complète.
    payload = json.loads(row["candidates_json"])
    assert [c["provider"] for c in payload["above"]] == ["AniList", "MAL"]
    assert payload.get("streaming") in (None, False)


def test_finalize_normal_remet_la_review_en_awaiting_pick(isolated_db):
    """Contrôle : sans geste utilisateur, le finalize se comporte comme avant."""
    rid = begin_streaming_review(44, "Bleach", query="Bleach", library_id=3)

    finalize_streaming_review(rid, 44, "Bleach", _final_payload(), library_id=3)

    row = get_pending_review(rid)
    assert row is not None
    assert row["state"] == "awaiting_pick"
    payload = json.loads(row["candidates_json"])
    assert [c["provider"] for c in payload["above"]] == ["AniList", "MAL"]
    assert payload.get("streaming") in (None, False)
