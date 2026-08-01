"""
GET /api/manual-reviews : la file consommée par manual_review.js doit exposer
`library_id` pour que le pick UI puisse afficher un lien de vérification vers
la fiche série Kavita (updateKavitaLink) sans appel réseau supplémentaire.
"""
from flask import Flask

from routes.manual_review import manual_review_bp


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(manual_review_bp)
    return app.test_client()


def test_queue_exposes_the_library_id_when_resolved(isolated_db):
    isolated_db.park_pending_review(
        "r1", 1, "Series With Link",
        candidates_json={"above": [], "below": [], "query": "Series With Link"},
        library_id=5,
    )

    res = _client().get("/api/manual-reviews")
    body = res.get_json()

    assert res.status_code == 200
    assert body["reviews"][0]["library_id"] == 5


def test_queue_exposes_a_null_library_id_when_never_resolved(isolated_db):
    """Série parkée avant que get_library_type_for_series n'ait tourné (ou
    créée avant la migration `library_id`) : le champ doit rester `None`
    plutôt que planter — le front omet alors simplement le lien."""
    isolated_db.park_pending_review(
        "r2", 2, "Series Without Link",
        candidates_json={"above": [], "below": [], "query": "Series Without Link"},
    )

    res = _client().get("/api/manual-reviews")
    body = res.get_json()

    assert body["reviews"][0]["library_id"] is None
