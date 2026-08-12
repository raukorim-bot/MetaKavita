"""
Handlers Socket.IO : le gate HTTP (`login_gate`) ne couvre pas le handshake
WebSocket, tout se joue donc ici. Deux propriétés vérifiées :

1. une connexion sans session ni jeton est refusée (`connect_error`), et le flux
   temps réel — logs, progression, couvertures — reste fermé ;
2. une connexion Companion est bornée à la série de son jeton : elle ne reçoit
   pas la file de review des autres séries au `connect`, et ne peut pas lancer
   une recherche de couvertures sur une autre série en changeant le `series_id`
   de l'événement.

Ce module n'avait aucun test direct avant ce fichier.
"""
import pytest
from flask import Flask

from extensions import socketio
from services import companion_embed_auth as cea


@pytest.fixture(scope="module")
def socket_app():
    """Une seule application pour tout le module.

    `extensions.socketio` est un singleton : réinitialiser l'instance à chaque
    test laisse les clients suivants connectés mais sourds (aucun paquet reçu).
    L'isolation qui compte ici est celle de la base, portée par `isolated_db`.
    """
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    socketio.init_app(app, cors_allowed_origins="*")
    # Import tardif : les handlers se déclarent en décorant l'instance partagée.
    import sockets.handlers  # noqa: F401

    return app


@pytest.fixture(autouse=True)
def _clear_tokens():
    cea.clear_all_embed_tokens()
    yield
    cea.clear_all_embed_tokens()


def _park(isolated_db, series_id, name):
    payload = {"above": [{"provider": "A", "score": 0.9, "title": name, "data": {}}],
               "below": [], "query": name}
    isolated_db.park_pending_review(
        review_id=f"rev-{series_id}", series_id=series_id, series_name=name,
        candidates_json=payload, base_provider="A", chosen_score=0.9,
    )


def test_a_connection_without_session_or_token_is_refused(socket_app, isolated_db):
    client = socketio.test_client(socket_app)

    assert client.is_connected() is False


def test_a_companion_token_connects_and_only_sees_its_own_series(socket_app, isolated_db):
    _park(isolated_db, 7, "Ma série")
    _park(isolated_db, 99, "Série privée")
    token = cea.issue_embed_token(7)

    client = socketio.test_client(
        socket_app, query_string=f"embed_token={token}&series_id=7"
    )

    assert client.is_connected() is True
    events = {e["name"]: e["args"][0] for e in client.get_received()}
    assert events["manual_review_pending_count"]["count"] == 1
    summary = events["manual_review_queue_summary"]["reviews"]
    assert [r["series_id"] for r in summary] == [7]
    assert all("privée" not in r["series_name"] for r in summary)


def test_a_companion_token_cannot_stream_covers_for_another_series(socket_app, isolated_db, monkeypatch):
    token = cea.issue_embed_token(7)
    jobs_built = []
    monkeypatch.setattr(
        "sockets.handlers.iter_cover_jobs",
        lambda *a, **k: jobs_built.append(a) or [],
    )

    client = socketio.test_client(
        socket_app, query_string=f"embed_token={token}&series_id=7"
    )
    client.get_received()

    client.emit("fetch_covers_stream", {"series_id": 99, "query": "autre série"})

    assert jobs_built == [], "aucune recherche ne doit partir pour la série 99"
    assert client.get_received() == []


def test_a_companion_token_can_stream_covers_for_its_own_series(socket_app, isolated_db, monkeypatch):
    token = cea.issue_embed_token(7)
    monkeypatch.setattr("sockets.handlers.iter_cover_jobs", lambda *a, **k: [])
    monkeypatch.setattr(
        "sockets.handlers.KavitaAPI.get_library_type_for_series",
        lambda self, sid: "Manga",
    )
    monkeypatch.setattr(
        "sockets.handlers.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://k.test", "KAVITA_API_KEY": "k"},
    )

    client = socketio.test_client(
        socket_app, query_string=f"embed_token={token}&series_id=7"
    )
    client.get_received()

    client.emit("fetch_covers_stream", {"series_id": 7, "query": "ma série"})

    received = [e["name"] for e in client.get_received()]
    assert "cover_stream_complete" in received, "aucun job : la fin de flux doit être annoncée"


def test_a_revoked_token_stops_working_immediately(socket_app, isolated_db, monkeypatch):
    """La portée est relue à chaque événement : révoquer un jeton coupe l'accès
    sans attendre que le client se reconnecte."""
    token = cea.issue_embed_token(7)
    jobs_built = []
    monkeypatch.setattr(
        "sockets.handlers.iter_cover_jobs",
        lambda *a, **k: jobs_built.append(a) or [],
    )

    client = socketio.test_client(
        socket_app, query_string=f"embed_token={token}&series_id=7"
    )
    assert client.is_connected() is True
    client.get_received()

    cea.revoke_embed_token(token)
    client.emit("fetch_covers_stream", {"series_id": 7, "query": "ma série"})

    assert jobs_built == []
    fresh = socketio.test_client(
        socket_app, query_string=f"embed_token={token}&series_id=7"
    )
    assert fresh.is_connected() is False
