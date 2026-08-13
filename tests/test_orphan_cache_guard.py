"""
Garde-fous contre la purge du cache déclenchée par un inventaire Kavita tronqué.

`series_cache` ne contient pas que du cache : id forcé, champs ciblés, préférence
éditeur et drapeau de couverture manuelle y vivent, et supprimer une ligne
supprime la review en attente associée. Or `get_all_series()` attrape ses erreurs
et rend une liste malgré tout : un `all-v2` qui ne répond pas (timeout de 10 s,
500 pendant un scan Kavita) renvoyait un inventaire tronqué que
`clean_orphaned_cache` prenait pour la vérité, effaçant des réglages saisis à la
main sans aucun moyen de les retrouver. Deux verrous sont testés ici : le signal
de complétude posé par `KavitaAPI`, et le refus défensif d'une purge sur
inventaire vide.
"""
import os

import pytest
from flask import Flask

from kavita_api import KavitaAPI


def _api():
    api = KavitaAPI("http://kavita.test", "key")
    api.token = "jwt"
    api.headers = {"Authorization": "Bearer jwt"}
    return api


class _Res:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


# --------------------------------------------------------------------------
# 1. Signal de complétude de l'inventaire
# --------------------------------------------------------------------------

def test_full_inventory_is_flagged_complete(mocker):
    api = _api()
    mocker.patch.object(KavitaAPI, "get_libraries", return_value=[{"id": 1, "type": 0}])
    mocker.patch(
        "kavita_api.requests.post",
        return_value=_Res(200, [{"id": 10, "name": "A", "libraryId": 1}]),
    )

    series = api.get_all_series()

    assert [s["id"] for s in series] == [10]
    assert api.last_inventory_complete is True


def test_an_http_error_on_the_inventory_call_marks_it_incomplete(mocker):
    """Cas réel : Kavita répond 500 sur `all-v2` pendant un de ses scans.

    L'inventaire tient désormais en un seul appel — `SeriesFilterV2Dto` n'a pas de
    `libraryId`, donc un appel par bibliothèque rendait N fois le même catalogue.
    Il n'y a donc plus de « bibliothèque muette » isolée : quand cet appel échoue,
    il n'y a plus d'inventaire du tout, et surtout pas de feu vert pour purger."""
    api = _api()
    mocker.patch.object(
        KavitaAPI, "get_libraries",
        return_value=[{"id": 1, "type": 0}, {"id": 2, "type": 0}],
    )
    mocker.patch("kavita_api.requests.post", return_value=_Res(500))

    assert api.get_all_series() == []
    assert api.last_inventory_complete is False


def test_series_from_an_unknown_library_never_validate_the_inventory(mocker):
    """L'appel unique rend tout le catalogue visible, y compris des séries d'une
    bibliothèque que `GET /api/Library/libraries` n'a pas listée (droits, filtre
    explicite). Non rattachables, elles ne sont pas typables : mieux vaut un
    inventaire vide et non complet qu'une liste que la purge croirait complète."""
    api = _api()
    mocker.patch.object(KavitaAPI, "get_libraries", return_value=[{"id": 1, "type": 0}])
    mocker.patch(
        "kavita_api.requests.post",
        return_value=_Res(200, [{"id": 77, "name": "Z", "libraryId": 9}]),
    )

    assert api.get_all_series() == []
    assert api.last_inventory_complete is False


def test_library_raising_marks_the_inventory_incomplete(mocker):
    api = _api()
    mocker.patch.object(KavitaAPI, "get_libraries", return_value=[{"id": 1, "type": 0}])
    mocker.patch("kavita_api.requests.post", side_effect=TimeoutError("boom"))

    assert api.get_all_series() == []
    assert api.last_inventory_complete is False


def test_a_filtered_inventory_is_never_complete(mocker):
    """Un inventaire d'une seule bibliothèque ne peut pas arbitrer les orphelines."""
    api = _api()
    mocker.patch.object(
        KavitaAPI, "get_libraries",
        return_value=[{"id": 1, "type": 0}, {"id": 2, "type": 0}],
    )
    mocker.patch(
        "kavita_api.requests.post",
        return_value=_Res(200, [{"id": 10, "name": "A", "libraryId": 1}]),
    )

    api.get_all_series(library_id=1)

    assert api.last_inventory_complete is False


def test_failed_authentication_leaves_the_inventory_incomplete(mocker):
    api = KavitaAPI("http://kavita.test", "key")
    mocker.patch.object(KavitaAPI, "authenticate", return_value=False)

    assert api.get_all_series() == []
    assert api.last_inventory_complete is False


# --------------------------------------------------------------------------
# 2. Refus défensif dans la purge
# --------------------------------------------------------------------------

def _seed(isolated_db):
    """Deux séries en cache, dont une portant des réglages saisis à la main."""
    from models import SeriesOverride

    isolated_db.update_status(502, "COMPLETED")
    isolated_db.save_series_override(
        SeriesOverride(series_id=501, forced_id="anilist:123", targeted_fields="summary"),
        status="COMPLETED",
    )


def test_an_empty_inventory_never_purges_the_cache(isolated_db):
    _seed(isolated_db)

    assert isolated_db.clean_orphaned_cache(set()) == 0

    cached = isolated_db.get_all_cached_data()
    assert set(cached) == {501, 502}
    assert cached[501]["forced_id"] == "anilist:123", \
        "les réglages manuels doivent survivre à un inventaire vide"


def test_a_real_inventory_still_purges(isolated_db):
    """Le garde-fou ne doit pas neutraliser le nettoyage légitime."""
    _seed(isolated_db)

    assert isolated_db.clean_orphaned_cache({502}) == 1
    assert set(isolated_db.get_all_cached_data()) == {502}


# --------------------------------------------------------------------------
# 3. Les deux appelants respectent le signal
# --------------------------------------------------------------------------

class _FakeKavita:
    """Kavita dont la deuxième bibliothèque ne répond pas."""

    inventory_complete = False

    def __init__(self, *a, **k):
        self.last_inventory_complete = self.__class__.inventory_complete

    def authenticate(self):
        return True

    def get_libraries(self):
        return [{"id": 1, "name": "Manga"}, {"id": 2, "name": "Comics"}]

    def get_all_series(self, library_id=None):
        return [{"id": 502, "name": "Keep", "libraryId": 1}]


@pytest.fixture
def pages_client(isolated_db):
    from routes.auth import auth_bp
    from routes.pages import pages_bp
    from routes.config import config_bp
    from routes.sync import sync_bp
    from routes.misc import misc_bp
    from routes.manual_review import manual_review_bp
    from routes.scrapers_manage import scrapers_manage_bp
    from flask_test_app import get_series_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"),
                static_folder=os.path.join(root, "static"))
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    for bp in (auth_bp, pages_bp, config_bp, get_series_bp(), sync_bp, misc_bp,
               manual_review_bp, scrapers_manage_bp):
        app.register_blueprint(bp)
    return app.test_client()


@pytest.fixture
def _kavita_configured(monkeypatch):
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://kavita.test", "KAVITA_API_KEY": "key"},
    )


def test_dashboard_does_not_purge_on_an_incomplete_inventory(
    pages_client, isolated_db, monkeypatch, _kavita_configured
):
    """Régression : un rafraîchissement de page pendant un scan Kavita suffisait
    à effacer les réglages manuels des séries des bibliothèques muettes."""
    _seed(isolated_db)
    _FakeKavita.inventory_complete = False
    monkeypatch.setattr("routes.pages.KavitaAPI", _FakeKavita)

    assert pages_client.get("/").status_code == 200
    assert set(isolated_db.get_all_cached_data()) == {501, 502}


def test_dashboard_purges_on_a_complete_inventory(
    pages_client, isolated_db, monkeypatch, _kavita_configured
):
    _seed(isolated_db)
    _FakeKavita.inventory_complete = True
    monkeypatch.setattr("routes.pages.KavitaAPI", _FakeKavita)

    assert pages_client.get("/").status_code == 200
    assert set(isolated_db.get_all_cached_data()) == {502}


class _StopLoop(Exception):
    """Sort de la boucle `while True` de l'auto-sync après un seul tour."""


def _run_one_auto_sync_pass(bg, monkeypatch):
    """Exécute une seule itération de la boucle auto-sync.

    La boucle réelle est un `while True` terminé par `time.sleep(30)` : le sleep
    patché lève, ce qui sort de la boucle sans traverser le `except Exception`
    interne (celui-ci n'entoure que le corps métier).
    """
    monkeypatch.setattr(
        bg, "load_config",
        lambda: {
            "UI_LANG": "fr", "AUTO_SYNC_INTERVAL": 1,
            "KAVITA_URL": "http://kavita.test", "KAVITA_API_KEY": "key",
        },
    )

    def _sleep(_seconds):
        raise _StopLoop()

    monkeypatch.setattr(bg.time, "sleep", _sleep)
    with pytest.raises(_StopLoop):
        bg._auto_sync_worker()


def test_auto_sync_does_not_purge_on_an_incomplete_inventory(isolated_db, monkeypatch):
    import services.background_tasks as bg

    _seed(isolated_db)
    _FakeKavita.inventory_complete = False
    monkeypatch.setattr(bg, "KavitaAPI", _FakeKavita)
    purged = []
    monkeypatch.setattr(bg, "clean_orphaned_cache", lambda ids: purged.append(ids))

    _run_one_auto_sync_pass(bg, monkeypatch)

    assert purged == [], "aucune purge ne doit être tentée sur un inventaire tronqué"


def test_auto_sync_purges_on_a_complete_inventory(isolated_db, monkeypatch):
    import services.background_tasks as bg

    _seed(isolated_db)
    _FakeKavita.inventory_complete = True
    monkeypatch.setattr(bg, "KavitaAPI", _FakeKavita)
    purged = []
    monkeypatch.setattr(bg, "clean_orphaned_cache", lambda ids: purged.append(ids))

    _run_one_auto_sync_pass(bg, monkeypatch)

    assert purged == [{502}]
