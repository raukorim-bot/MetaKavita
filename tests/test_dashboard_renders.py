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
    from routes.pages import pages_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"),
                static_folder=os.path.join(root, "static"))
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(pages_bp)
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
