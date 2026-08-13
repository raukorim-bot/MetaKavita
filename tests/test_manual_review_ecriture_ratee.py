"""
Ce qui reste en base quand l'écriture Kavita rate — et quand elle réussit à
moitié (BF143, BF144).

Deux pièges symétriques encadrent l'appel à Kavita dans `apply_manual_review` :

* avant lui, `choice_and_merge` a déjà fait passer la review en
  `awaiting_confirm`. Si l'écriture échoue, la ligne reste dans un état qu'elle
  n'a jamais atteint — et « Tout accepter ≥ seuil », qui ne balaie que
  `awaiting_pick`, ne la voit plus : la série s'affiche dans la file sans que le
  bouton puisse rien en faire, à jamais ;
* après lui, la télémétrie et la diffusion des statistiques touchent SQLite
  avant la clôture de la review. Si la base est momentanément indisponible,
  Kavita a écrit mais la review reste en attente : l'utilisateur reconfirme et
  la même série repart chez Kavita une deuxième fois.
"""
from __future__ import annotations

import sqlite3

import pytest
from flask import Flask

import routes.manual_review as mr_routes
from routes.manual_review import manual_review_bp
from services import enrichment_engine
from services import manual_review as mr


def _config():
    return {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    }


@pytest.fixture(autouse=True)
def _no_socketio(monkeypatch):
    monkeypatch.setattr(mr, "_safe_emit", lambda *a, **k: None)
    monkeypatch.setattr(mr, "emit_pending_count", lambda: 0)


def _park(series_id, name="Série"):
    return mr.create_review_from_candidates(
        series_id,
        name,
        {
            "above": [
                {
                    "provider": "TOP",
                    "score": 0.91,
                    "title": name,
                    "data": {"summary": "résumé", "title": name},
                },
            ],
            "below": [],
            "query": name,
        },
    )


def _mock_kavita(mocker, write_result=(True, "ok", ["TOP"])):
    mocker.patch.object(enrichment_engine, "load_config", return_value=_config())
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)
    from kavita_api import KavitaAPI

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 1, "summary": ""})
    return mocker.patch(
        "services.enrichment_engine.apply_kavita_payload", return_value=write_result
    )


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(manual_review_bp)
    return app.test_client()


def test_une_ecriture_kavita_ratee_remet_la_review_a_l_ecran_de_choix(isolated_db, mocker):
    """
    Kavita refuse (redémarrage, auth expirée) : rien n'a été écrit, la review
    doit redevenir ce qu'elle était.

    Piège : le pick a été enregistré avant la tentative d'écriture. Sans retour
    en arrière la ligne reste `awaiting_confirm` sans preview — un état que
    l'utilisateur n'a jamais demandé, et qui la fait sortir du périmètre de
    l'acceptation en masse.
    """
    rid = _park(4001, "ÉchecKavita")
    _mock_kavita(mocker, write_result=(False, "Erreur Kavita.", []))

    ok, msg, _detail = enrichment_engine.apply_manual_review(rid, base_provider="TOP")

    assert ok is False
    row = isolated_db.get_pending_review(rid)
    assert row is not None, "l'échec d'écriture ne doit pas faire disparaître la review"
    assert row["state"] == "awaiting_pick", (
        "une review dont l'écriture a échoué reste bloquée hors du « Tout accepter ≥ seuil »"
    )


def test_une_edition_en_cours_survit_a_une_ecriture_kavita_ratee(isolated_db, mocker):
    """
    Le retour en arrière ne doit pas renvoyer à l'écran de choix un utilisateur
    qui était dans le panneau d'édition.

    Piège : là, l'état avancé est bien le sien. Le ramener à `awaiting_pick`
    ferait vider par `renderEdit` tout ce qu'il venait de retoucher — le même
    dégât que BF141, par un autre chemin.
    """
    rid = _park(4002, "ÉditionEnCours")
    isolated_db.update_pending_review(
        rid,
        state="awaiting_confirm",
        base_provider="TOP",
        preview_json={"summary": "Résumé retouché", "_provider_used": "TOP"},
    )
    _mock_kavita(mocker, write_result=(False, "Erreur Kavita.", []))

    enrichment_engine.apply_manual_review(rid, base_provider="TOP", include_providers=[])

    row = isolated_db.get_pending_review(rid)
    assert row["state"] == "awaiting_confirm"
    assert "Résumé retouché" in (row["preview_json"] or "")


def test_le_tout_accepter_rejoue_une_review_dont_l_ecriture_avait_echoue(isolated_db, mocker):
    """
    Deuxième clic sur « Tout accepter ≥ seuil », Kavita revenu : les séries
    tombées au premier passage doivent repartir.

    Piège : `awaiting_confirm` sans preview n'est pas un travail humain, c'est
    une écriture ratée. Le confondre avec une édition en cours rendait le bouton
    définitivement muet — « 0 accepté(s), 0 laissée(s) en file » avec trente
    lignes affichées à l'écran.
    """
    calls = []
    mocker.patch.object(
        mr_routes,
        "apply_manual_review",
        side_effect=lambda rid, provider, **k: (calls.append((rid, provider)), (True, "ok", {}))[1],
    )
    isolated_db.park_pending_review(
        "r-degradee",
        4003,
        "Dégradée",
        candidates_json={"above": [{"provider": "TOP", "score": 0.9}], "below": []},
        state="awaiting_confirm",
    )

    body = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.6}).get_json()

    assert body["accepted"] == 1, "la review dégradée est restée hors du périmètre du bouton"
    assert body["skipped"] == 0
    assert calls == [("r-degradee", "TOP")]


def test_une_telemetrie_qui_leve_ne_laisse_pas_la_review_ouverte(isolated_db, mocker):
    """
    Kavita a écrit, SQLite refuse la télémétrie : la review doit être close
    quand même.

    Piège : la mesure passait avant la clôture, sans filet. Base verrouillée par
    un batch et la série restait `PENDING_REVIEW` alors qu'elle venait d'être
    écrite. L'utilisateur reconfirme, Kavita est écrit deux fois — couverture
    ré-uploadée, compteurs comptés en double.
    """
    rid = _park(4004, "TélémétrieKO")
    write = _mock_kavita(mocker)
    mocker.patch.object(
        enrichment_engine,
        "record_manual_review_telemetry",
        side_effect=sqlite3.OperationalError("database is locked"),
    )

    ok, _msg, _detail = enrichment_engine.apply_manual_review(rid, base_provider="TOP")

    assert ok is True, "l'écriture Kavita a réussi : l'utilisateur ne doit pas être invité à rejouer"
    assert isolated_db.get_pending_review(rid) is None, (
        "review encore en attente après une écriture réussie : elle sera confirmée deux fois"
    )
    assert isolated_db.get_all_cached_data()[4004]["status"] == "COMPLETED"
    assert write.call_count == 1


def test_une_diffusion_de_stats_qui_leve_ne_laisse_pas_la_review_ouverte(isolated_db, mocker):
    """Même piège une ligne plus bas : `get_lifetime_stats` lit aussi SQLite."""
    rid = _park(4005, "StatsKO")
    _mock_kavita(mocker)
    mocker.patch.object(
        enrichment_engine,
        "get_lifetime_stats",
        side_effect=sqlite3.OperationalError("database is locked"),
    )

    ok, _msg, _detail = enrichment_engine.apply_manual_review(rid, base_provider="TOP")

    assert ok is True
    assert isolated_db.get_pending_review(rid) is None
