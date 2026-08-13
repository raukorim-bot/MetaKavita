"""
Les messages d'erreur des routes suivent la langue de l'interface (BF147).

Ces `error` / `msg` ne restent pas dans un journal : la review manuelle les
affiche dans un `alert()`, le Hub des scrapers dans un toast. Ils étaient écrits
en dur, et dans les deux sens — du français rendu à un utilisateur anglophone
côté review, de l'anglais rendu à un francophone côté scrapers. La route
`/skip`, dans le même fichier, montrait déjà la bonne façon de faire.
"""
from flask import Flask

import routes.manual_review as mr_routes
import routes.scrapers_manage as scrapers_routes
from routes.manual_review import manual_review_bp
from routes.scrapers_manage import scrapers_manage_bp
from translations import translations


def _client(blueprint):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blueprint)
    return app.test_client()


def _lang(mocker, module, lang):
    mocker.patch.object(module, "load_config", return_value={"UI_LANG": lang})


def test_une_review_sans_fournisseur_repond_dans_la_langue_de_l_interface(mocker, isolated_db):
    """Le message part directement dans un `alert()` : en anglais, l'utilisateur
    lisait « base_provider requis », nom de champ compris."""
    _lang(mocker, mr_routes, "en")

    body = _client(manual_review_bp).post("/api/manual-reviews/x/choice", json={}).get_json()

    assert body["error"] == translations["en"]["err_base_provider_required"]
    assert "requis" not in body["error"]


def test_une_review_introuvable_repond_dans_la_langue_de_l_interface(mocker, isolated_db):
    _lang(mocker, mr_routes, "en")

    res = _client(manual_review_bp).post(
        "/api/manual-reviews/inconnue/confirm", json={"base_provider": "MAL"}
    )

    assert res.status_code == 404
    assert res.get_json()["error"] == translations["en"]["err_review_not_found"]


def test_une_re_recherche_sans_titre_repond_dans_la_langue_de_l_interface(mocker, isolated_db):
    _lang(mocker, mr_routes, "en")

    body = _client(manual_review_bp).post("/api/manual-reviews/x/research", json={}).get_json()

    assert body["error"] == translations["en"]["err_query_required"]


def test_un_scraper_inconnu_repond_dans_la_langue_de_l_interface(mocker):
    """Symétrique du précédent : « unknown scraper » s'affichait tel quel en toast
    au milieu d'une interface française."""
    _lang(mocker, scrapers_routes, "fr")
    mocker.patch.object(
        scrapers_routes.ScraperRegistry, "get", lambda sid, include_disabled=False: None
    )

    res = _client(scrapers_manage_bp).post("/api/scrapers/NOPE/disable")

    assert res.status_code == 404
    assert res.get_json()["msg"] == translations["fr"]["err_scraper_unknown"]


def test_un_scraper_officiel_refuse_sa_suppression_dans_la_langue_de_l_interface(mocker):
    """La clé existait déjà (`scraper_core_no_delete`) — elle n'était juste pas
    utilisée par la route qui pose ce refus."""
    _lang(mocker, scrapers_routes, "fr")
    mocker.patch.object(
        scrapers_routes.ScraperRegistry,
        "get",
        lambda sid, include_disabled=False: object(),
    )
    mocker.patch.object(
        scrapers_routes.ScraperRegistry, "get_source_file", lambda sid: "anilist.py"
    )
    mocker.patch.object(scrapers_routes, "is_core_filename", lambda src: True)

    res = _client(scrapers_manage_bp).delete("/api/scrapers/ANILIST")

    assert res.status_code == 403
    assert res.get_json()["msg"] == translations["fr"]["scraper_core_no_delete"]
