"""
« Tout accepter ≥ seuil » : le curseur doit valoir aussi pour la bande basse.

Le curseur promet « toutes les reviews dont le meilleur candidat dépasse N % »,
descend jusqu'à 30 % et sert précisément à rattraper les correspondances faibles.
Seule la bande haute (`above`, au-dessus du seuil de match réel) était lue : une
review dont le seul candidat était à 0,50 — sous le seuil réel de 0,70, mais très
au-dessus des 0,30 demandés — était comptée en « laissée en file », sans un mot.

Le geste reste tracé comme un choix faible (`weak_pick`, télémétrie) et le seuil
demandé est plancherisé côté serveur : on ne peut pas accepter la file entière au
score zéro en postant `threshold: 0`.
"""
from flask import Flask

import routes.manual_review as mr_routes
from routes.manual_review import manual_review_bp


def _seed(isolated_db, review_id, series_id, name, above, below, state="awaiting_pick"):
    isolated_db.park_pending_review(
        review_id,
        series_id,
        name,
        candidates_json={"above": above, "below": below, "query": name},
        state=state,
    )


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(manual_review_bp)
    return app.test_client()


def test_un_candidat_faible_au_dessus_du_seuil_demande_est_accepte(mocker, isolated_db):
    calls = []

    def _fake_apply(review_id, base_provider, include_providers=None, **kwargs):
        calls.append((review_id, base_provider, bool(kwargs.get("weak_pick"))))
        return True, "Succès", {"series_id": 1}

    mocker.patch.object(mr_routes, "apply_manual_review", side_effect=_fake_apply)

    _seed(isolated_db, "r1", 1, "Bande basse", [], [{"provider": "KITSU", "score": 0.5}])
    _seed(isolated_db, "r2", 2, "Trop faible", [], [{"provider": "KITSU", "score": 0.2}])

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.3})
    body = res.get_json()

    assert body["accepted"] == 1, (
        "le curseur à 30 % laissait en file un candidat à 50 % : l'interface "
        "promettait le contraire"
    )
    assert body["skipped"] == 1
    assert calls == [("r1", "KITSU", True)], (
        "une acceptation en masse sous le seuil de match doit rester tracée "
        "comme un choix faible"
    )
    assert body["accepted_weak"] == 1


def test_la_bande_haute_reste_prioritaire(mocker, isolated_db):
    """Le meilleur candidat reste le TOP1 de la bande haute, jamais un faible."""
    calls = []
    mocker.patch.object(
        mr_routes,
        "apply_manual_review",
        side_effect=lambda rid, p, **k: (
            calls.append((rid, p, bool(k.get("weak_pick")))),
            (True, "ok", {}),
        )[1],
    )

    _seed(
        isolated_db, "r1", 1, "Les deux bandes",
        [{"provider": "ANILIST", "score": 0.88}],
        [{"provider": "KITSU", "score": 0.55}],
    )

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.3})

    assert calls == [("r1", "ANILIST", False)]
    assert res.get_json()["accepted_weak"] == 0


def test_le_retour_ecran_distingue_les_correspondances_faibles():
    """Fondre les faibles dans le total d'acceptations rendrait le garde-fou
    invisible : la modale doit les compter à part (`static/js/manual_review.js`)."""
    import os

    js_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "static", "js", "manual_review.js")
    )
    with open(js_path, encoding="utf-8") as fh:
        js = fh.read()

    assert "data.accepted_weak" in js
    assert "mr_list_bulk_weak" in js

    from translations import translations

    for lang in ("fr", "en"):
        assert translations[lang]["mr_list_bulk_weak"]


def test_le_seuil_demande_ne_peut_pas_tomber_sous_le_plancher(mocker, isolated_db):
    """Un `threshold: 0` accepterait n'importe quoi sur toute la file : le
    plancher du curseur (30 %) vaut aussi côté serveur."""
    fake_apply = mocker.patch.object(
        mr_routes, "apply_manual_review", return_value=(True, "ok", {})
    )

    _seed(isolated_db, "r1", 1, "Presque rien", [], [{"provider": "KITSU", "score": 0.12}])

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0})
    body = res.get_json()

    assert body["threshold"] == 0.30
    assert body["accepted"] == 0
    fake_apply.assert_not_called()
