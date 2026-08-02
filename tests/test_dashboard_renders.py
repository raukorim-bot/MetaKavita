"""
Garde-fou anti-régression Jinja : le dashboard (`/`) doit continuer à se rendre
sans erreur 500 après une modification de template, même sur une installation
neuve (aucun Kavita configuré). Aurait attrapé la régression Jinja de la 1.6.1
(apostrophe non échappée dans `config_key_not_saved`, cf. CHANGELOG).
"""
import os

import pytest
from flask import Flask


@pytest.fixture
def pages_client(isolated_db):
    from routes.auth import auth_bp
    from routes.pages import pages_bp
    from routes.config import config_bp
    from routes.series import series_bp
    from routes.sync import sync_bp
    from routes.misc import misc_bp
    from routes.manual_review import manual_review_bp
    from routes.scrapers_manage import scrapers_manage_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"),
                static_folder=os.path.join(root, "static"))
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    for bp in (
        auth_bp, pages_bp, config_bp, series_bp, sync_bp, misc_bp,
        manual_review_bp, scrapers_manage_bp,
    ):
        app.register_blueprint(bp)
    return app.test_client()


def test_dashboard_renders_on_a_fresh_install(pages_client, isolated_db, monkeypatch):
    """Aucun Kavita configuré : le rendu ne doit tenter aucun appel réseau et ne
    doit pas planter (bannière « pas encore connecté » + modales incluses)."""
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})

    response = pages_client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "mrListPanel" in html
    assert "mrListThreshold" in html
    assert "account_current_password" in html or "Compte" in html


def test_dashboard_renders_in_english_too(pages_client, isolated_db, monkeypatch):
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "en"})

    response = pages_client.get("/")

    assert response.status_code == 200


def _sync_libraries_fragment(html):
    start = html.index('class="sync-libraries-list"')
    end = html.index("</div>", start)
    return html[start:end]


def test_deliberately_disabling_every_library_survives_a_reload(pages_client, isolated_db, monkeypatch):
    """Régression : `heal_total_library_denylist` tournait sur CHAQUE chargement
    du dashboard et ne pouvait pas distinguer un vieux wipe accidentel d'un choix
    délibéré de tout décocher — elle recochait donc tout au rechargement suivant.
    Le dashboard doit maintenant respecter une dénylist totale telle quelle."""
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
            "DISABLED_LIBRARIES": "1,2",
        },
    )

    class FakeKavita:
        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

        def get_libraries(self):
            return [{"id": 1, "name": "Manga"}, {"id": 2, "name": "Comics"}]

        def get_all_series(self, library_id=None):
            return []

    monkeypatch.setattr("routes.pages.KavitaAPI", FakeKavita)

    response = pages_client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    fragment = _sync_libraries_fragment(html)
    assert "checked" not in fragment, "les 2 bibliothèques doivent rester décochées"
