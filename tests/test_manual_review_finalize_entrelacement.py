"""
`finalize_streaming_review()` décide d'après un instantané périmé (BF141).

La correction BF125 regarde bien l'état de la review avant d'écrire, mais elle
le lit *avant* `translate_candidate_summaries`, qui part sur DeepL : sous
eventlet, chaque appel réseau rend la main, et le greenlet de l'UI traite dans
cette fenêtre le pick de l'utilisateur (`choice_and_merge` → `awaiting_confirm`)
ou son skip. Le finalize reprenait ensuite son instantané d'avant la traduction,
et son `UPDATE` aveugle ramenait la review à `awaiting_pick` : la modale
renvoyait l'utilisateur à l'écran de choix et `renderEdit` vidait au re-pick
tout ce qu'il venait de retoucher.

Ces tests fabriquent la fenêtre en instrumentant la traduction pour qu'elle
modifie la base pendant son exécution — c'est exactement ce que fait eventlet.
"""
from __future__ import annotations

import json

import pytest

from db_manager import get_pending_review, update_pending_review
from services import manual_review as mr
from services.manual_review import (
    append_streaming_candidate,
    begin_streaming_review,
    finalize_streaming_review,
    skip_pending_review,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr("translator.translate_text", lambda text, *a, **k: text)


@pytest.fixture
def emitted(monkeypatch):
    """Capture les événements Socket.IO au lieu de les émettre."""
    events = []
    monkeypatch.setattr(mr, "_safe_emit", lambda event, payload: events.append((event, payload)))
    monkeypatch.setattr(mr, "emit_pending_count", lambda: 0)
    return events


def _final_payload():
    return {
        "above": [
            {
                "provider": "AniList",
                "score": 0.91,
                "title": "One Piece",
                "cover_url": "",
                "summary": "résumé AniList",
                "data": {"summary": "résumé AniList"},
            },
            {
                "provider": "MAL",
                "score": 0.80,
                "title": "One Piece",
                "cover_url": "",
                "summary": "résumé MAL",
                "data": {"summary": "résumé MAL"},
            },
        ],
        "below": [],
        "query": "One Piece",
        "streaming": True,
    }


def _translate_while(monkeypatch, action):
    """Remplace la traduction par une version qui exécute `action` en cours de route."""

    def fake_translate(payload, config=None):
        action()
        return payload, 1

    monkeypatch.setattr(mr, "translate_candidate_summaries", fake_translate)


def test_un_pick_fait_pendant_la_traduction_survit_au_finalize(isolated_db, monkeypatch, emitted):
    """
    L'utilisateur choisit un fournisseur pendant les appels DeepL du finalize.

    Piège : l'état lu avant la traduction dit encore `awaiting_pick`. Écrire
    d'après lui fait régresser la review et détruit le preview en cours
    d'édition — sans le moindre message.
    """
    rid = begin_streaming_review(42, "One Piece", query="One Piece", library_id=1)
    append_streaming_candidate(
        rid,
        42,
        {"provider": "AniList", "score": 0.91, "title": "One Piece", "cover_url": "", "summary": ""},
        "above",
    )

    def user_picks_anilist():
        update_pending_review(
            rid,
            state="awaiting_confirm",
            base_provider="AniList",
            chosen_score=0.91,
            preview_json={"summary": "Résumé retouché à la main", "_provider_used": "AniList"},
        )

    _translate_while(monkeypatch, user_picks_anilist)

    finalize_streaming_review(rid, 42, "One Piece", _final_payload(), library_id=1)

    row = get_pending_review(rid)
    assert row is not None
    assert row["state"] == "awaiting_confirm", (
        "le finalize a ramené à l'écran de choix une review choisie pendant la traduction"
    )
    assert row["base_provider"] == "AniList"
    assert json.loads(row["preview_json"])["summary"] == "Résumé retouché à la main"
    # L'événement annonce l'état réel, sinon l'UI se recale sur un état périmé.
    complete = [p for e, p in emitted if e == "manual_review_scrape_complete"]
    assert complete and complete[-1]["state"] == "awaiting_confirm"


def test_un_skip_fait_pendant_la_traduction_ne_declenche_pas_de_fin_de_scrape(
    isolated_db, monkeypatch, emitted
):
    """
    L'utilisateur passe la review pendant les appels DeepL du finalize.

    La ligne n'existe plus : l'`UPDATE` ne ressuscite rien, mais annoncer une
    fin de collecte pour une review disparue relance un `loadQueue()` complet et
    fait clignoter la file. Le finalize doit renoncer, comme lorsque la review a
    déjà disparu avant la traduction.
    """
    rid = begin_streaming_review(43, "Naruto", query="Naruto", library_id=2)
    append_streaming_candidate(
        rid,
        43,
        {"provider": "AniList", "score": 0.91, "title": "Naruto", "cover_url": "", "summary": ""},
        "above",
    )

    _translate_while(monkeypatch, lambda: skip_pending_review(rid))

    finalize_streaming_review(rid, 43, "Naruto", _final_payload(), library_id=2)

    assert get_pending_review(rid) is None
    assert not [e for e, _p in emitted if e == "manual_review_scrape_complete"], (
        "fin de collecte annoncée pour une review passée pendant la traduction"
    )


def test_un_pick_arrive_apres_la_relecture_bloque_encore_le_retour_au_choix(
    isolated_db, monkeypatch, emitted
):
    """
    Cas extrême : le pick tombe entre la relecture d'état et l'`UPDATE`.

    Aucune relecture, aussi tardive soit-elle, ne ferme cette fenêtre — seule la
    base peut trancher. L'écriture est donc conditionnée à l'état attendu
    (`... WHERE review_id = ? AND state = 'awaiting_pick'`) et le finalize
    recalcule sur l'état réel quand elle ne prend pas. Ici la relecture est
    forcée à mentir : elle rend un `awaiting_pick` déjà périmé.
    """
    rid = begin_streaming_review(44, "Bleach", query="Bleach", library_id=3)
    update_pending_review(
        rid,
        state="awaiting_confirm",
        base_provider="AniList",
        chosen_score=0.91,
        preview_json={"summary": "Édition en cours", "_provider_used": "AniList"},
    )

    real_get = mr.get_pending_review
    calls = {"n": 0}

    def stale_get(review_id):
        calls["n"] += 1
        row = real_get(review_id)
        # 2e appel = la relecture d'après traduction : elle voit l'état d'avant
        # le pick, qui vient d'être écrit par le greenlet de l'UI.
        if calls["n"] == 2 and row:
            row = dict(row, state="awaiting_pick", base_provider=None, chosen_score=None)
        return row

    monkeypatch.setattr(mr, "get_pending_review", stale_get)

    finalize_streaming_review(rid, 44, "Bleach", _final_payload(), library_id=3)

    row = real_get(rid)
    assert row is not None
    assert row["state"] == "awaiting_confirm", (
        "l'écriture du finalize n'était pas conditionnée à l'état attendu"
    )
    assert row["base_provider"] == "AniList"
    assert json.loads(row["preview_json"])["summary"] == "Édition en cours"
    # La liste de candidats est quand même rafraîchie : le fournisseur choisi y est.
    payload = json.loads(row["candidates_json"])
    assert [c["provider"] for c in payload["above"]] == ["AniList", "MAL"]
