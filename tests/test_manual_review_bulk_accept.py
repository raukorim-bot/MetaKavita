"""
POST /api/manual-reviews/bulk-accept : reprend le chemin « Confirmer sans
édition » (`apply_manual_review`) pour chaque review `awaiting_pick` dont le
TOP1 dépasse un seuil — pas une nouvelle automatisation, juste l'application en
masse d'un geste déjà possible un par un.
"""
from flask import Flask

import routes.manual_review as mr_routes
from routes.manual_review import manual_review_bp


def _seed_review(isolated_db, review_id, series_id, series_name, above, state="awaiting_pick"):
    isolated_db.park_pending_review(
        review_id,
        series_id,
        series_name,
        candidates_json={"above": above, "below": [], "query": series_name},
        state=state,
    )


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(manual_review_bp)
    return app.test_client()


def test_bulk_accept_confirms_only_reviews_above_threshold(mocker, isolated_db):
    calls = []

    def _fake_apply(review_id, base_provider, include_providers=None, **kwargs):
        calls.append((review_id, base_provider))
        return True, "Succès", {"series_id": 1}

    mocker.patch.object(mr_routes, "apply_manual_review", side_effect=_fake_apply)

    _seed_review(isolated_db, "r1", 1, "Strong Hit", [{"provider": "ANILIST", "score": 0.9}])
    _seed_review(isolated_db, "r2", 2, "Weak Hit", [{"provider": "ANILIST", "score": 0.3}])
    _seed_review(isolated_db, "r3", 3, "No Above Candidate", [])

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.6})
    body = res.get_json()

    assert res.status_code == 200
    assert body["accepted"] == 1
    assert body["skipped"] == 2
    assert calls == [("r1", "ANILIST")]


def test_bulk_accept_defaults_to_the_configured_threshold(mocker, isolated_db):
    mocker.patch.object(mr_routes, "apply_manual_review", return_value=(True, "Succès", {}))
    mocker.patch.object(mr_routes, "get_match_accept_threshold", return_value=0.6)

    _seed_review(isolated_db, "r1", 1, "Borderline", [{"provider": "ANILIST", "score": 0.6}])

    res = _client().post("/api/manual-reviews/bulk-accept", json={})
    body = res.get_json()

    assert body["accepted"] == 1
    assert body["threshold"] == 0.6


def test_bulk_accept_never_touches_a_review_already_being_edited(mocker, isolated_db):
    """awaiting_confirm = un preview déjà en cours de personnalisation par
    l'utilisateur — le bulk-accept ne doit jamais l'écraser silencieusement."""
    fake_apply = mocker.patch.object(mr_routes, "apply_manual_review")

    _seed_review(
        isolated_db, "r1", 1, "In Progress",
        [{"provider": "ANILIST", "score": 0.9}],
        state="awaiting_confirm",
    )

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.6})
    body = res.get_json()

    assert body["accepted"] == 0
    fake_apply.assert_not_called()


def test_bulk_accept_can_target_specific_review_ids(mocker, isolated_db):
    calls = []
    mocker.patch.object(
        mr_routes, "apply_manual_review",
        side_effect=lambda rid, p, **k: (calls.append(rid), (True, "ok", {}))[1],
    )

    _seed_review(isolated_db, "r1", 1, "One", [{"provider": "ANILIST", "score": 0.9}])
    _seed_review(isolated_db, "r2", 2, "Two", [{"provider": "ANILIST", "score": 0.9}])

    res = _client().post(
        "/api/manual-reviews/bulk-accept",
        json={"threshold": 0.6, "review_ids": ["r2"]},
    )
    body = res.get_json()

    assert body["accepted"] == 1
    assert calls == ["r2"]


def test_bulk_accept_reports_failures_without_crashing(mocker, isolated_db):
    mocker.patch.object(
        mr_routes, "apply_manual_review",
        return_value=(False, "Erreur Kavita.", None),
    )

    _seed_review(isolated_db, "r1", 1, "Fails", [{"provider": "ANILIST", "score": 0.9}])

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.6})
    body = res.get_json()

    assert body["accepted"] == 0
    assert body["failed"] == [{"review_id": "r1", "error": "Erreur Kavita."}]
