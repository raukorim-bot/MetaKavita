"""Tests pour le bouton café et l'intégration du nagware supporter dans l'Atelier (/volumes)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
import pytest
from flask import Flask

from services.supporter_nag_policy import (
    VARIANT_IDS,
    pick_variant,
    should_show_for_event,
)
from translations import translations


@pytest.fixture
def client(monkeypatch, isolated_db):
    from routes.pages import pages_bp
    from routes.workshop import workshop_bp
    from routes.volume_enrichment import volume_enrichment_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(pages_bp)
    app.register_blueprint(workshop_bp)
    app.register_blueprint(volume_enrichment_bp)
    return app.test_client()


class FakeApi:
    def get_series(self, sid):
        return {
            "id": sid,
            "name": "Saga",
            "localizedName": "La Saga",
            "libraryId": 1,
            "libraryType": "Manga",
            "coverImage": "series1.jpg",
        }

    def get_series_metadata(self, sid):
        return {"summary": "Un résumé."}

    def get_series_volumes(self, sid):
        return []

    def get_all_series(self, library_id=None):
        return []

    def authenticate(self):
        return True


def _setup_config(monkeypatch, lang="fr"):
    import routes.pages as rp
    import routes.volume_enrichment as rve
    import routes.workshop as rw

    config = {
        "UI_LANG": lang,
        "VOLUME_ENRICHMENT_ENABLED": True,
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "secret-key",
    }
    monkeypatch.setattr(rw, "load_config", lambda: config)
    monkeypatch.setattr(rp, "load_config", lambda: config)
    monkeypatch.setattr(rve, "load_config", lambda: config)
    monkeypatch.setattr("services.workshop.load_config", lambda: config)
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: FakeApi())
    monkeypatch.setattr("routes.pages.get_kavita_ui_url", lambda cfg: "http://kavita.ui")
    return config


def test_workshop_coffee_button_rendered_fr(monkeypatch, client):
    _setup_config(monkeypatch, lang="fr")
    res = client.get("/volumes")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Bouton café dans la navbar
    assert 'id="workshopCoffeeBtn"' in html
    assert 'href="https://buymeacoffee.com/raukorim"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert 'class="workshop-btn-coffee bmc-link license"' in html
    assert 'aria-label="M&#39;offrir un café"' in html or 'aria-label="M\'offrir un café"' in html
    assert 'title="Offrir un café à l&#39;auteur pour soutenir MetaKavita ☕"' in html or 'title="Offrir un café à l\'auteur pour soutenir MetaKavita ☕"' in html
    assert '<span class="workshop-coffee-cup" aria-hidden="true">☕</span>' in html
    assert "M&#39;offrir un café" in html or "M'offrir un café" in html

    # Intégration du modal nagware supporter
    assert 'id="licenseNagOverlay"' in html
    assert 'license_nag.js' in html

    # Clés traduites injectées dans window.AppTranslations
    assert '"workshop_coffee_hint"' in html
    assert '"workshop_coffee_toast"' in html
    assert '"nag_kicker_workshop"' in html
    assert '"nag_title_workshop"' in html
    assert '"nag_body_workshop"' in html


def test_workshop_coffee_button_rendered_en(monkeypatch, client):
    _setup_config(monkeypatch, lang="en")
    res = client.get("/volumes")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Version anglaise
    assert 'id="workshopCoffeeBtn"' in html
    assert 'aria-label="Buy me a coffee"' in html
    assert 'title="Buy the author a coffee to support MetaKavita ☕"' in html
    assert '<span class="workshop-coffee-label">Buy me a coffee</span>' in html


def test_workshop_coffee_translations_parity():
    keys = [
        "workshop_coffee_hint",
        "workshop_coffee_toast",
        "nag_kicker_workshop",
        "nag_title_workshop",
        "nag_body_workshop",
    ]
    for k in keys:
        assert k in translations["fr"], f"Clé {k} manquante en FR"
        assert k in translations["en"], f"Clé {k} manquante en EN"
        assert len(translations["fr"][k].strip()) > 0
        assert len(translations["en"][k].strip()) > 0


def test_workshop_supporter_policy():
    store = {"mk_nag_first_visit": "2026-01-01"}
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    # 0 volume, 0 series => pas d'overlay
    assert not should_show_for_event(store, {"source": "workshop", "volumes_count": 0, "series_count": 0}, now)

    # 4 volumes sans historique => bloqué car en dessous du seuil d'activité (10)
    ctx_small = {"source": "workshop", "volumes_count": 4}
    assert not should_show_for_event(store, ctx_small, now)

    # Avec seuil d'activité atteint (>= 10) => overlay éligible
    store_active = {"mk_nag_first_visit": "2026-01-01", "mk_nag_lifetime_reviews": 10}
    ctx = {"source": "workshop", "volumes_count": 4}
    assert should_show_for_event(store_active, ctx, now)
    assert "workshop_craft" in VARIANT_IDS
    assert pick_variant(ctx, store_active) == "workshop_craft"
