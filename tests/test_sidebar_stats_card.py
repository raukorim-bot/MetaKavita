"""L'encart statistiques doit rendre compte de tous les états, sans écart.

Deux défauts couverts ici. D'abord la carte n'affichait que cinq des six
statuts que le moteur écrit en cache : `NEEDS_RELOCK` — les séries dont les
métadonnées sont écrites mais les verrous Kavita non posés, donc à risque
d'écrasement au prochain scan — n'apparaissait nulle part, alors que le total
les comptait. La somme des lignes ne retombait donc pas sur le total, sans que
rien ne l'explique. Ensuite les cinq tuiles étaient posées en `flex-wrap` :
avec cinq éléments, la dernière partait seule à la ligne.

Le garde-fou utile est celui de la cohérence : si un nouveau statut apparaît
dans le moteur sans être ajouté à la carte, le total cesse de correspondre à la
somme des lignes et ces tests échouent.
"""
import os
import re

import pytest
from flask import Flask

# Statuts réellement écrits en cache (cf. services/stats_service.py).
ENGINE_STATUSES = [
    "COMPLETED",
    "NOT_FOUND",
    "NEEDS_RELOCK",
    "PENDING",
    "PENDING_REVIEW",
    "IGNORED",
]

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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

    app = Flask(
        __name__,
        template_folder=os.path.join(ROOT, "templates"),
        static_folder=os.path.join(ROOT, "static"),
    )
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    for bp in (
        auth_bp, pages_bp, config_bp, get_series_bp(), sync_bp, misc_bp,
        manual_review_bp, scrapers_manage_bp,
    ):
        app.register_blueprint(bp)
    return app.test_client()


def _stats_card(html):
    """Isole la carte statistiques, du titre au bouton de la page détaillée."""
    start = html.index('class="card sidebar-stats-card')
    end = html.index("btn-open-stats", start)
    return html[start:end]


def _legend_rows(card):
    """[(statut, valeur, classes), …] dans l'ordre d'affichage."""
    rows = []
    for match in re.finditer(
        r'<button type="button" class="(stats-legend-row[^"]*)".*?'
        r"filterSeriesByStatus\('([A-Z_]+)'\).*?"
        r'<span class="stats-legend-val">(\d+)</span>',
        card,
        re.S,
    ):
        rows.append((match.group(2), int(match.group(3)), match.group(1)))
    return rows


def _seed_one_per_status(isolated_db, extra_completed=0):
    for index, status in enumerate(ENGINE_STATUSES, start=1):
        isolated_db.update_status(100 + index, status)
    for index in range(extra_completed):
        isolated_db.update_status(500 + index, "COMPLETED")


def test_every_status_written_by_the_engine_is_listed(pages_client, isolated_db, monkeypatch):
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    _seed_one_per_status(isolated_db)

    card = _stats_card(pages_client.get("/").get_data(as_text=True))
    rows = _legend_rows(card)

    assert [status for status, _, _ in rows] == ENGINE_STATUSES
    assert all(value == 1 for _, value, _ in rows)


def test_the_listed_states_add_up_to_the_displayed_total(pages_client, isolated_db, monkeypatch):
    """Le total est l'ancrage des pourcentages : un écart le rendrait mensonger."""
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    _seed_one_per_status(isolated_db, extra_completed=7)

    card = _stats_card(pages_client.get("/").get_data(as_text=True))
    total = int(re.search(r'<span class="stats-total">(\d+)</span>', card).group(1))

    assert total == 13
    assert sum(value for _, value, _ in _legend_rows(card)) == total


def test_a_state_at_zero_stays_listed_but_steps_back(pages_client, isolated_db, monkeypatch):
    """Savoir qu'aucune série n'attend de review est une information : on la
    garde à l'écran, en retrait, plutôt que de faire disparaître la ligne."""
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    isolated_db.update_status(1, "COMPLETED")

    card = _stats_card(pages_client.get("/").get_data(as_text=True))
    rows = {status: (value, classes) for status, value, classes in _legend_rows(card)}

    assert len(rows) == len(ENGINE_STATUSES)
    assert "is-zero" not in rows["COMPLETED"][1]
    for status in ENGINE_STATUSES:
        if status != "COMPLETED":
            assert rows[status] == (0, "stats-legend-row is-zero")


def test_a_marginal_state_still_gets_a_visible_segment(pages_client, isolated_db, monkeypatch):
    """Une série en attente sur mille, c'est 0,1% de large : le segment doit
    exister dans le HTML, la largeur plancher étant posée en CSS."""
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    for index in range(999):
        isolated_db.update_status(1000 + index, "COMPLETED")
    isolated_db.update_status(1, "PENDING")

    card = _stats_card(pages_client.get("/").get_data(as_text=True))
    widths = re.findall(r'class="stats-bar-seg" style="--seg: ([^;]+); width: ([\d.]+)%', card)

    # Deux segments seulement : les états à zéro n'en produisent aucun.
    assert len(widths) == 2
    assert float(widths[1][1]) > 0
    assert "min-width: 3px" in open(
        os.path.join(ROOT, "static", "css", "style.css"), encoding="utf-8"
    ).read().split(".stats-bar-seg")[1]


def test_an_empty_library_does_not_divide_by_zero(pages_client, isolated_db, monkeypatch):
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})

    card = _stats_card(pages_client.get("/").get_data(as_text=True))

    assert '<span class="stats-total">0</span>' in card
    assert "stats-bar-seg" not in card


def test_clicking_the_ignored_row_actually_reveals_them(pages_client, isolated_db, monkeypatch):
    """Les ignorées sont masquées par défaut : filtrer dessus sans décocher le
    masquage aurait donné une liste vide, donc un raccourci qui ne marche pas."""
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    card = _stats_card(pages_client.get("/").get_data(as_text=True))
    assert "filterSeriesByStatus('IGNORED')" in card

    batch = open(os.path.join(ROOT, "static", "js", "batch.js"), encoding="utf-8").read()
    body = batch.split("function filterSeriesByStatus")[1].split("\nfunction ")[0]

    assert "hideIgnoredCb" in body
    assert "checked = false" in body
    assert "filterSeries()" in body


def test_the_card_is_translated_in_both_languages(pages_client, isolated_db, monkeypatch):
    from translations import translations

    for key in ("stats_needs_relock", "stats_total_label", "stats_filter_hint"):
        assert translations["fr"].get(key), key
        assert translations["en"].get(key), key

    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "en"})
    card = _stats_card(pages_client.get("/").get_data(as_text=True))

    assert translations["en"]["stats_needs_relock"] in card
    assert translations["en"]["stats_total_label"] in card
