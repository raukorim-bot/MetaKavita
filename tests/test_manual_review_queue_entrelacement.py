"""
`GET /api/manual-reviews` écrasait les candidats arrivés en streaming (BF142).

La route lisait `candidates_json`, traduisait les résumés — des appels DeepL,
donc autant de reprises eventlet — puis réécrivait la colonne entière à partir
de son instantané d'avant la traduction. Face à elle, `append_streaming_candidate`
fait le même lire-modifier-écrire sur le même blob, sans verrou ni version.

Le déclenchement était systématique : une carte streamée ne porte jamais le
marqueur `_summary_translated`, donc la condition de traduction était vraie à
chaque appel, et le front rappelle `loadQueue()` sur chaque `manual_review_queued`
/ `manual_review_pending_count`. Un candidat livré pendant la traduction
s'affichait à l'écran puis disparaissait de la base : le clic dessus se soldait
par « Fusion impossible (provider invalide) », et c'était souvent le meilleur
candidat.

Les tests fabriquent la fenêtre d'entrelacement en instrumentant la lecture ou
la traduction pour qu'elles modifient la base pendant leur exécution.
"""
from __future__ import annotations

import json

import pytest
from flask import Flask

import routes.manual_review as mr_routes
from db_manager import get_pending_review, update_pending_review
from services import manual_review as mr
from services.manual_review import (
    append_streaming_candidate,
    begin_streaming_review,
    choice_and_merge,
)


@pytest.fixture(autouse=True)
def _no_emit_no_network(monkeypatch):
    monkeypatch.setattr(mr, "_safe_emit", lambda *a, **k: None)
    monkeypatch.setattr(mr, "emit_pending_count", lambda: 0)
    monkeypatch.setattr("translator.translate_text", lambda text, *a, **k: "[FR] " + text)
    monkeypatch.setattr(
        "translator.translate_texts",
        lambda texts, *a, **k: ["[FR] " + text for text in texts],
    )


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(mr_routes.manual_review_bp)
    return app.test_client()


def _card(provider, score, summary="Résumé d'origine"):
    return {
        "provider": provider,
        "score": score,
        "title": "One Piece",
        "cover_url": "",
        "summary": summary,
        "data": {"title": "One Piece", "summary": summary},
    }


def _providers_in_db(review_id):
    payload = json.loads(get_pending_review(review_id)["candidates_json"])
    return [c["provider"] for band in ("above", "below") for c in payload.get(band) or []]


def test_un_candidat_livre_pendant_la_liste_reste_choisissable(isolated_db, client, monkeypatch):
    """
    Un scraper lent rend sa copie pendant que la route travaille.

    Piège : la route tient un instantané du blob et le réécrit à la fin. La
    carte arrivée entre-temps est bien annoncée à l'UI par son propre événement,
    mais elle a disparu de la base quand l'utilisateur la clique.
    """
    rid = begin_streaming_review(42, "One Piece", query="One Piece", library_id=1)
    append_streaming_candidate(rid, 42, _card("AniList", 0.55), "above")

    real_list = mr_routes.list_pending_reviews

    def list_then_scraper_delivers(**kwargs):
        rows = real_list(**kwargs)
        # La fenêtre : la route a son instantané, le scraper livre son candidat.
        append_streaming_candidate(rid, 42, _card("MangaDex", 0.93), "above")
        return rows

    monkeypatch.setattr(mr_routes, "list_pending_reviews", list_then_scraper_delivers)

    assert client.get("/api/manual-reviews").status_code == 200

    assert "MangaDex" in _providers_in_db(rid), (
        "le candidat livré pendant la liste a été effacé de la base"
    )
    assert choice_and_merge(rid, "MangaDex") is not None, (
        "la carte affichée n'est plus fusionnable (provider invalide)"
    )


def test_la_liste_ne_traduit_pas_une_review_en_cours_de_collecte(isolated_db, client, monkeypatch):
    """
    Aucune traduction sur le chemin de lecture tant que la collecte tourne.

    Les cartes streamées ne portent jamais `_summary_translated` : la route
    retraduisait donc toute la file — jusqu'à 200 reviews — à chaque événement
    socket, sur l'unique worker eventlet, uniquement pour réécrire un blob
    qu'elle risquait d'amputer. Le `finalize` traduit la collecte complète.
    """
    rid = begin_streaming_review(42, "One Piece", query="One Piece", library_id=1)
    append_streaming_candidate(rid, 42, _card("AniList", 0.55), "above")

    calls = []

    def spy_translate(payload, config=None):
        calls.append(payload)
        return payload, 0

    monkeypatch.setattr(mr_routes, "translate_candidate_summaries", spy_translate)

    assert client.get("/api/manual-reviews").status_code == 200

    assert calls == [], "la file en cours de collecte a été traduite sur le chemin de lecture"


def test_la_liste_ne_perd_pas_un_candidat_ajoute_pendant_la_traduction(
    isolated_db, client, monkeypatch
):
    """
    Collecte terminée : la traduction de rattrapage reste possible, mais son
    écriture doit être ciblée.

    Piège : entre la lecture et l'écriture de la route, DeepL a rendu la main
    autant de fois qu'il y a de résumés. Toute écriture du blob entier repose
    sur un instantané périmé — seuls les résumés doivent être reportés,
    fournisseur par fournisseur.
    """
    isolated_db.park_pending_review(
        "r-finalisee",
        42,
        "One Piece",
        candidates_json={"above": [_card("AniList", 0.55)], "below": [], "query": "One Piece"},
        state="awaiting_pick",
    )

    real_translate = mr.translate_candidate_summaries

    def translate_then_concurrent_write(payload, config=None):
        current = json.loads(get_pending_review("r-finalisee")["candidates_json"])
        current["above"].append(_card("MangaDex", 0.93))
        update_pending_review("r-finalisee", candidates_json=current)
        return real_translate(payload, config=config)

    monkeypatch.setattr(mr_routes, "translate_candidate_summaries", translate_then_concurrent_write)

    assert client.get("/api/manual-reviews").status_code == 200

    payload = json.loads(get_pending_review("r-finalisee")["candidates_json"])
    providers = [c["provider"] for c in payload["above"]]
    assert providers == ["AniList", "MangaDex"], (
        "l'écriture de la route a écrasé la carte ajoutée pendant la traduction"
    )
    anilist = payload["above"][0]
    assert anilist["summary"].startswith("[FR] "), "le résumé traduit n'a pas été enregistré"
    assert anilist[mr.SUMMARY_TRANSLATED_KEY] is True, (
        "sans le marqueur, la route retraduirait à chaque appel"
    )


def test_la_liste_borne_le_nombre_de_reviews_demande(isolated_db, client, monkeypatch):
    """`limit` vient de l'URL et n'était pas borné : `-1` veut dire « aucune
    limite » pour SQLite, soit toute la file (cartes et résumés compris) dans
    une seule réponse."""
    seen = []

    def spy_list(**kwargs):
        seen.append(kwargs.get("limit"))
        return []

    monkeypatch.setattr(mr_routes, "list_pending_reviews", spy_list)

    client.get("/api/manual-reviews?limit=-1")
    client.get("/api/manual-reviews?limit=99999")
    client.get("/api/manual-reviews?limit=50")

    assert seen == [1, 500, 50]
