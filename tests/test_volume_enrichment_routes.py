"""
Routes d'enrichissement par tome.

Deux garanties à tenir. La fonctionnalité est **éteinte par défaut** : elle
écrit dans Kavita unité par unité, elle ne doit pas se réveiller toute seule à
la mise à jour, ni depuis un onglet resté ouvert quand on l'a coupée. Et
l'aperçu **n'écrit rien** : c'est ce qui permet de le montrer avant d'agir.

L'écriture d'une série, elle, ne rend plus son résultat mais son démarrage : elle
tourne dans un thread, comme la passe de bibliothèque. Les tests attendent donc
la fin de la tâche (`_wait_idle`) avant de regarder ce qui est parti chez Kavita.
"""
from __future__ import annotations

import threading
import time

import pytest
from flask import Flask

import routes.volume_enrichment as routes_ve
from services.volume_enrichment import job


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(routes_ve.volume_enrichment_bp)
    return app.test_client()


def _enable(monkeypatch, **extra):
    config = {"UI_LANG": "en", "VOLUME_ENRICHMENT_ENABLED": True}
    config.update(extra)
    monkeypatch.setattr(routes_ve, "load_config", lambda: config)
    # Le thread d'écriture relit la configuration pour son compte : sans cela il
    # partirait sur la vraie, donc sur la vraie URL de Kavita.
    monkeypatch.setattr(job, "load_config", lambda: config)
    return config


def _wait_idle(timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not job.get_volume_enrich_state()["running"]:
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def _no_pass_left_running():
    """Un thread encore vivant au démontage travaillerait avec des mocks que
    `monkeypatch` vient de retirer — donc sur la vraie configuration."""
    yield
    _wait_idle()
    with job._lock:
        job._state.update({"running": False, "cancelled": False, "done": 0, "total": 0})


class FakeApi:
    def __init__(self):
        self.written = []

    def get_series(self, sid):
        return {"id": sid, "name": "Saga", "libraryType": "Comic"}

    def get_library_type_for_series(self, sid):
        return "Comic"

    def get_series_volumes(self, sid):
        return [
            {"id": 900, "minNumber": 1, "chapters": [{"id": 1, "minNumber": 1}]},
            {"id": 901, "minNumber": 2, "chapters": [{"id": 2, "minNumber": 2}]},
        ]

    def get_chapter(self, chapter_id):
        return {"id": chapter_id}

    def update_chapter_metadata(self, dto):
        self.written.append(dto)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        return True, "ok"


@pytest.fixture
def wired(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(routes_ve, "_api", lambda: api)
    # Le plan et l'écriture vivent dans `job` : l'aperçu lui passe son client,
    # le thread d'écriture construit le sien.
    monkeypatch.setattr(job, "KavitaAPI", lambda url, key: api)
    monkeypatch.setattr(job, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(job, "credits_fetcher", lambda pid: None)
    monkeypatch.setattr(job, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(routes_ve, "get_volume_unit_states", lambda sid: {})
    # On remplace les appels réseau, pas `resolve_index` : c'est lui qui décide
    # de compléter un index de couvertures par la cascade ISBN, et ce choix doit
    # rester couvert par les tests de la route.
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: ("comicvine", {"1": {"summary": "Un"}, "2": {"summary": "Deux"}}),
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn", lambda units, **kw: {}
    )
    monkeypatch.setattr(
        "services.volume_enrichment.apply.save_volume_unit_state", lambda *a, **kw: None
    )
    return api


# ===== La garde =====


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/api/series/7/volume-enrich/preview"),
        ("post", "/api/series/7/volume-enrich/apply"),
        ("post", "/api/libraries/1/volume-enrich"),
    ],
)
def test_no_route_that_writes_answers_when_the_feature_is_off(client, monkeypatch, method, path):
    monkeypatch.setattr(
        routes_ve, "load_config", lambda: {"UI_LANG": "en", "VOLUME_ENRICHMENT_ENABLED": False}
    )

    res = getattr(client, method)(path, json={})

    assert res.status_code == 403
    assert res.get_json()["disabled"] is True


@pytest.mark.parametrize(
    "method, path",
    [("get", "/api/volume-enrich/status"), ("post", "/api/volume-enrich/cancel")],
)
def test_watching_and_stopping_stay_reachable_when_the_feature_is_off(
    client, monkeypatch, method, path
):
    """Éteindre l'interrupteur pendant une passe ne doit pas rendre cette passe
    impossible à voir et à arrêter : les boutons disparaissent avec le drapeau,
    et si l'API disparaît aussi, il ne reste plus que le redémarrage du
    conteneur. Ni l'une ni l'autre de ces deux routes ne peut écrire."""
    monkeypatch.setattr(
        routes_ve, "load_config", lambda: {"UI_LANG": "en", "VOLUME_ENRICHMENT_ENABLED": False}
    )

    res = getattr(client, method)(path, json={})

    assert res.status_code != 403
    assert not res.get_json().get("disabled")


def test_the_feature_is_off_on_a_config_that_never_heard_of_it(client, monkeypatch):
    """Une installation existante ne doit pas se mettre à écrire dans ses tomes
    au premier redémarrage après la mise à jour."""
    monkeypatch.setattr(routes_ve, "load_config", lambda: {"UI_LANG": "en"})

    assert client.post("/api/series/7/volume-enrich/apply", json={}).status_code == 403


def test_the_default_config_ships_the_switch_off():
    from config_manager import load_config

    assert load_config().get("VOLUME_ENRICHMENT_ENABLED", False) is False


# ===== Indépendance vis-à-vis de l'Inventaire =====
#
# L'aperçu tome par tome s'ouvre depuis la modale de rapport de tomes, qui
# appartient au blueprint de l'Inventaire. Tant que sa garde coupait tout,
# décocher l'Inventaire rendait l'enrichissement injoignable alors que son
# propre interrupteur était allumé — trois cases de la sidebar ne commandaient
# plus rien, sans un mot à l'écran.


@pytest.fixture
def audit_client(monkeypatch):
    import routes.library_audit as routes_la

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(routes_la.library_audit_bp)

    api = FakeApi()
    monkeypatch.setattr(routes_la, "_api", lambda: api)
    monkeypatch.setattr(routes_la, "get_volume_report_cache", lambda sid: {})
    monkeypatch.setattr(routes_la, "save_volume_report_cache", lambda *a, **kw: None)
    monkeypatch.setattr(routes_la, "get_catalog_expected_override", lambda sid: None)
    monkeypatch.setattr(routes_la, "get_inventory_excluded_ids", lambda: set())
    return app.test_client(), routes_la


def _config(monkeypatch, routes_la, *, inventory, volumes):
    config = {
        "UI_LANG": "en",
        "LIBRARY_INVENTORY_ENABLED": inventory,
        "VOLUME_ENRICHMENT_ENABLED": volumes,
    }
    monkeypatch.setattr(routes_la, "load_config", lambda: config)
    monkeypatch.setattr(routes_ve, "load_config", lambda: config)


def test_the_volume_detail_survives_an_inventory_switched_off(audit_client, monkeypatch):
    """Le détail tome par tome se reconstruit depuis Kavita seul : aucun appel
    de fournisseur, aucun attendu de catalogue. Rien de ce que la garde de
    l'Inventaire protège."""
    client, routes_la = audit_client
    _config(monkeypatch, routes_la, inventory=False, volumes=True)

    res = client.get("/api/series/7/volume-report/units")

    assert res.status_code == 200
    assert res.get_json()["success"] is True


def test_the_detail_closes_again_when_neither_feature_is_on(audit_client, monkeypatch):
    client, routes_la = audit_client
    _config(monkeypatch, routes_la, inventory=False, volumes=False)

    res = client.get("/api/series/7/volume-report/units")

    assert res.status_code == 403
    assert res.get_json()["disabled"] is True


def test_what_costs_a_provider_call_stays_behind_the_inventory(audit_client, monkeypatch):
    """L'exemption porte sur la seule route qui lit Kavita. Le rapport complet
    interroge la cascade pour son attendu de catalogue : l'ouvrir reviendrait à
    laisser tourner en fond ce que l'utilisateur a précisément coupé."""
    client, routes_la = audit_client
    _config(monkeypatch, routes_la, inventory=False, volumes=True)

    assert client.get("/api/series/7/volume-report").status_code == 403
    assert client.post("/api/libraries/1/hygiene-scan", json={}).status_code == 403


# ===== Aperçu =====


def test_the_preview_returns_a_plan(client, monkeypatch, wired):
    _enable(monkeypatch)

    res = client.post("/api/series/7/volume-enrich/preview", json={})

    body = res.get_json()
    assert res.status_code == 200
    assert body["plan"]["counts"]["writable"] == 2
    assert body["plan"]["provider"] == "comicvine"
    assert body["plan"]["series_name"] == "Saga"


def test_the_preview_writes_nothing(client, monkeypatch, wired):
    _enable(monkeypatch)

    client.post("/api/series/7/volume-enrich/preview", json={})

    assert wired.written == []


def test_a_series_with_no_volumes_previews_empty_rather_than_failing(
    client, monkeypatch, wired
):
    _enable(monkeypatch)
    wired.get_series_volumes = lambda sid: []

    res = client.post("/api/series/7/volume-enrich/preview", json={})

    assert res.status_code == 200
    assert res.get_json()["plan"]["counts"]["matched"] == 0


def test_a_provider_failure_becomes_a_500_not_a_stack_trace(client, monkeypatch, wired):
    _enable(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("fournisseur en vrac")

    monkeypatch.setattr("services.volume_enrichment.index_cache.resolve_index", boom)

    res = client.post("/api/series/7/volume-enrich/preview", json={})

    assert res.status_code == 500
    assert res.get_json()["success"] is False


# ===== Application =====
#
# La route rendait le résultat de l'écriture, qu'elle menait de bout en bout dans
# le greenlet de la requête : reconstruction du plan (donc réinterrogation du
# fournisseur, que l'aperçu venait de payer), puis par tome une lecture, une
# écriture et un téléversement de couverture. Sur l'unique worker eventlet, la
# requête durait des minutes sans rien dire. Elle rend désormais un démarrage.


def test_applying_writes_the_volumes(client, monkeypatch, wired):
    _enable(monkeypatch)

    res = client.post("/api/series/7/volume-enrich/apply", json={})

    assert res.get_json()["started"] is True
    assert _wait_idle()
    assert len(wired.written) == 2
    assert job.get_volume_enrich_state()["counts"]["done"] == 2


def test_l_ecriture_repond_avant_d_avoir_ecrit(client, monkeypatch, wired):
    """Le tout de la fonctionnalité : la réponse HTTP ne doit plus attendre
    Kavita. Le premier tome est retenu à sa lecture, et la route répond quand
    même — c'est ce qui rendait le worker eventlet indisponible pendant des
    minutes."""
    _enable(monkeypatch)
    reading = threading.Event()
    hold = threading.Event()

    def held_read(chapter_id):
        reading.set()
        hold.wait(5)
        return {"id": chapter_id}

    monkeypatch.setattr(wired, "get_chapter", held_read)
    try:
        res = client.post("/api/series/7/volume-enrich/apply", json={})

        assert res.status_code == 200
        assert reading.wait(5), "le thread doit avoir commencé à écrire"
        assert wired.written == [], "la réponse est partie avant la première écriture"
    finally:
        hold.set()
    assert _wait_idle()
    assert len(wired.written) == 2


def test_applying_honours_the_ticked_boxes(client, monkeypatch, wired):
    """Décocher une ligne dans l'aperçu doit vouloir dire quelque chose."""
    _enable(monkeypatch)

    client.post("/api/series/7/volume-enrich/apply", json={"selection": {"2": ["summary"]}})
    assert _wait_idle()

    assert [d["id"] for d in wired.written] == [2]


def test_la_progression_est_a_la_maille_du_tome(client, monkeypatch, wired):
    """À la maille de la série, une série unique afficherait « 0 / 1 » puis
    « 1 / 1 » : quelqu'un qui attend quarante albums n'en apprendrait rien."""
    _enable(monkeypatch)
    seen = []
    monkeypatch.setattr(
        job,
        "_emit",
        lambda event, payload: seen.append((event, payload.get("done"), payload.get("total"),
                                            payload.get("running"), payload.get("series_id"))),
    )

    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()

    progress = [s for s in seen if s[0] == "volume_enrich_progress"]
    assert [(done, total) for _e, done, total, _r, _s in progress] == [(0, 2), (1, 2), (2, 2), (2, 2)]
    assert progress[-1][3] is False, "la fin doit se dire"
    # Sans l'identifiant, l'interface ne saurait pas quel bouton remettre en
    # progression, ni si elle compte des tomes ou des séries.
    assert all(s[4] == 7 for s in progress)


def test_la_selection_borne_le_total_annonce(client, monkeypatch, wired):
    """Le total vient de la sélection, pas du plan : annoncer « 1 / 2 » pour un
    seul tome coché laisserait une barre à moitié pleine sur une écriture finie."""
    _enable(monkeypatch)
    seen = []
    monkeypatch.setattr(
        job, "_emit", lambda event, payload: seen.append((payload.get("done"), payload.get("total")))
    )

    client.post("/api/series/7/volume-enrich/apply", json={"selection": {"2": None}})
    assert _wait_idle()

    assert seen[0] == (0, 1)
    assert seen[-1] == (1, 1)


def test_force_comes_from_the_persistent_switch_when_the_request_is_silent(
    client, monkeypatch, wired
):
    """`VOLUME_FORCE_OVERWRITE` est l'échappatoire de masse : elle doit valoir
    sans qu'on la répète à chaque requête."""
    _enable(monkeypatch, VOLUME_FORCE_OVERWRITE=True)
    wired.get_chapter = lambda cid: {"id": cid, "summary": "Déjà là", "summaryLocked": True}

    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()

    assert wired.written[0]["summary"] == "Un"


def test_the_request_can_override_the_persistent_switch(client, monkeypatch, wired):
    _enable(monkeypatch, VOLUME_FORCE_OVERWRITE=True)
    wired.get_chapter = lambda cid: {"id": cid, "summary": "Déjà là"}

    client.post("/api/series/7/volume-enrich/apply", json={"force": False})
    assert _wait_idle()

    assert job.get_volume_enrich_state()["counts"]["done"] == 0


def test_credits_are_only_requested_when_the_switch_is_on(client, monkeypatch, wired):
    _enable(monkeypatch)
    asked = []
    monkeypatch.setattr(job, "credits_fetcher", lambda pid: asked.append(pid))

    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()
    assert asked == []

    _enable(monkeypatch, VOLUME_ENRICH_CREDITS=True)
    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()
    assert asked == ["comicvine"]


def test_annuler_arrete_l_ecriture_d_une_serie(client, monkeypatch, wired):
    """L'écriture d'une série passe par l'état global : le bouton Annuler de la
    barre d'outils doit l'arrêter, sinon la tâche de fond serait une tâche sans
    frein."""
    _enable(monkeypatch)
    reading = threading.Event()
    hold = threading.Event()

    def held_read(chapter_id):
        reading.set()
        hold.wait(5)
        return {"id": chapter_id}

    monkeypatch.setattr(wired, "get_chapter", held_read)
    try:
        client.post("/api/series/7/volume-enrich/apply", json={})
        assert reading.wait(5)
        assert client.post("/api/volume-enrich/cancel").get_json()["cancelled"] is True
    finally:
        hold.set()

    assert _wait_idle()
    assert len(wired.written) == 1, "l'annulation est prise entre deux tomes"
    assert job.get_volume_enrich_state()["was_cancelled"] is True


# ===== Passe de bibliothèque =====


def test_the_library_pass_starts_in_the_background(client, monkeypatch):
    _enable(monkeypatch)
    started = {}

    def fake_start(library_id, series_ids=None, **kwargs):
        started.update({"library_id": library_id, "ids": series_ids, **kwargs})
        return {"success": True, "started": True}

    monkeypatch.setattr(routes_ve, "start_volume_enrich", fake_start)

    res = client.post("/api/libraries/3/volume-enrich", json={})

    assert res.status_code == 200
    assert started["library_id"] == "3"
    assert started["resume"] is True


def test_a_second_pass_is_refused_with_409(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        routes_ve, "start_volume_enrich", lambda *a, **kw: {"success": False, "busy": True}
    )

    res = client.post("/api/libraries/3/volume-enrich", json={})

    assert res.status_code == 409
    assert res.get_json()["busy"] is True


def test_status_and_cancel_answer(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(routes_ve, "get_volume_enrich_state", lambda: {"running": False})
    monkeypatch.setattr(routes_ve, "cancel_volume_enrich", lambda: {"success": True})

    assert client.get("/api/volume-enrich/status").get_json()["running"] is False
    assert client.post("/api/volume-enrich/cancel").get_json()["success"] is True


def test_cancelling_nothing_is_a_conflict_like_starting_twice(client, monkeypatch):
    """Le démarrage rend 409 quand une passe tourne déjà. Annuler ce qui ne
    tourne pas est le même genre de conflit d'état, et le 200 précédent
    obligeait l'appelant à lire le corps pour s'en apercevoir."""
    _enable(monkeypatch)
    monkeypatch.setattr(
        routes_ve, "cancel_volume_enrich", lambda: {"success": False, "running": False}
    )

    res = client.post("/api/volume-enrich/cancel")

    assert res.status_code == 409
    assert res.get_json()["error"]


def test_a_pass_that_could_not_start_does_not_claim_one_is_running(client, monkeypatch):
    """`start_volume_enrich` échoue de deux façons : une passe tourne déjà, ou
    le thread n'a pas démarré. Le second cas répondait « Une passe est déjà en
    cours » avec un 409 — le message de la route écrasait la raison réelle,
    déployée avant lui — et l'utilisateur cherchait une passe fantôme que ni
    `/status` ni Annuler ne montraient."""
    _enable(monkeypatch)
    monkeypatch.setattr(
        routes_ve,
        "start_volume_enrich",
        lambda *a, **kw: {"success": False, "error": "can't start new thread"},
    )

    res = client.post("/api/libraries/3/volume-enrich", json={})

    assert res.status_code == 500
    body = res.get_json()
    assert body["success"] is False
    assert body.get("busy") is not True
    assert "thread" in body["error"]


# ===== Sérialisation des écritures =====
#
# L'application unitaire écrit dans Kavita depuis le greenlet de la requête.
# Elle n'était sérialisée avec rien : ni avec la passe de bibliothèque, qui
# traversait peut-être la même série, ni avec elle-même. Un double-clic sur
# « Appliquer » récupérait les crédits deux fois, téléversait la couverture deux
# fois et enregistrait deux verdicts concurrents pour la même unité. Le verrou
# par série existe déjà (services/enrichment_engine.py) — précisément parce que
# « l'un écraserait silencieusement le travail de l'autre ».


def test_applying_while_the_series_is_already_being_written_is_refused(
    client, monkeypatch, wired
):
    _enable(monkeypatch)
    from services.enrichment_engine import _processing_lock, _processing_series_ids

    with _processing_lock:
        _processing_series_ids.add(7)
    try:
        res = client.post("/api/series/7/volume-enrich/apply", json={})
    finally:
        with _processing_lock:
            _processing_series_ids.discard(7)

    assert res.status_code == 409
    assert res.get_json()["series_busy"] is True
    assert _wait_idle(), "le refus ne doit pas laisser d'état « en cours »"
    assert wired.written == [], "aucune écriture concurrente vers Kavita"


def test_un_double_clic_ne_lance_qu_une_ecriture(client, monkeypatch, wired):
    """La fenêtre : le second clic arrive pendant que la tâche de fond écrit.
    Sans refus, les crédits étaient récupérés deux fois et la couverture
    téléversée deux fois."""
    _enable(monkeypatch)
    reading = threading.Event()
    hold = threading.Event()

    def held_read(chapter_id):
        reading.set()
        hold.wait(5)
        return {"id": chapter_id}

    monkeypatch.setattr(wired, "get_chapter", held_read)
    try:
        first = client.post("/api/series/7/volume-enrich/apply", json={})
        assert reading.wait(5)
        second = client.post("/api/series/7/volume-enrich/apply", json={})
    finally:
        hold.set()

    assert first.get_json()["started"] is True
    assert second.status_code == 409, "le second clic doit être refusé, pas doublé"
    assert _wait_idle()
    assert len(wired.written) == 2, "deux tomes, deux écritures — pas quatre"


def test_une_passe_de_bibliotheque_en_cours_refuse_l_ecriture_d_une_serie(
    client, monkeypatch, wired
):
    """L'état de progression est global : deux passes s'y écraseraient, et
    l'utilisateur ne saurait plus laquelle il regarde ni laquelle il annule."""
    _enable(monkeypatch)
    with job._lock:
        job._state["running"] = True
    try:
        res = client.post("/api/series/7/volume-enrich/apply", json={})
    finally:
        with job._lock:
            job._state["running"] = False

    assert res.status_code == 409
    assert res.get_json()["busy"] is True
    assert res.get_json().get("series_busy") is not True
    assert wired.written == []


def test_the_claim_is_released_when_the_apply_is_over(client, monkeypatch, wired):
    """Un verrou qui fuit rendrait la série inaccessible jusqu'au redémarrage."""
    _enable(monkeypatch)
    from services.enrichment_engine import _processing_series_ids

    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()

    assert 7 not in _processing_series_ids
    assert client.post("/api/series/7/volume-enrich/apply", json={}).status_code == 200


def test_la_reservation_est_relachee_meme_quand_l_ecriture_explose(
    client, monkeypatch, wired
):
    _enable(monkeypatch)
    from services.enrichment_engine import _processing_series_ids

    def boom(*args, **kwargs):
        raise RuntimeError("fournisseur en vrac")

    monkeypatch.setattr("services.volume_enrichment.index_cache.resolve_index", boom)

    # L'écriture est partie : l'échec ne se voit plus dans le code HTTP mais dans
    # l'état de la tâche, que `/api/volume-enrich/status` publie.
    assert client.post("/api/series/7/volume-enrich/apply", json={}).status_code == 200
    assert _wait_idle()
    assert 7 not in _processing_series_ids
    assert job.get_volume_enrich_state()["error"]


# ===== Mémoïsation de l'index fournisseur =====
#
# L'écriture reconstruisait le plan entier, index compris, alors que l'aperçu
# venait de le bâtir quelques secondes plus tôt. Avec la cadence appliquée à
# chaque requête, c'était plusieurs secondes jetées — et sur Bédéthèque ou
# Planète BD, qui coûtent une requête par album, bien davantage.


def _counting_index(calls):
    def fetch(name, **kwargs):
        calls.append(name)
        return "comicvine", {"1": {"summary": "Un"}, "2": {"summary": "Deux"}}

    return fetch


def test_l_ecriture_ne_reinterroge_pas_le_fournisseur_apres_un_apercu(
    client, monkeypatch, wired
):
    _enable(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index", _counting_index(calls)
    )

    preview = client.post("/api/series/7/volume-enrich/preview", json={})
    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()

    assert preview.get_json()["plan"]["index_cached"] is False
    assert calls == ["Saga"], "un seul appel fournisseur pour l'aperçu et l'écriture"
    assert len(wired.written) == 2, "et les tomes sont écrits quand même"


def test_deux_apercus_de_suite_ne_paient_qu_une_fois(client, monkeypatch, wired):
    _enable(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index", _counting_index(calls)
    )

    client.post("/api/series/7/volume-enrich/preview", json={})
    second = client.post("/api/series/7/volume-enrich/preview", json={})

    assert len(calls) == 1
    assert second.get_json()["plan"]["index_cached"] is True


def test_un_apercu_force_ne_reutilise_pas_l_index_d_un_apercu_normal(
    client, monkeypatch, wired
):
    """Deux réglages différents ne partagent pas d'entrée : c'est la règle qui
    évite qu'un changement dans la sidebar reste sans effet visible."""
    _enable(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index", _counting_index(calls)
    )

    client.post("/api/series/7/volume-enrich/preview", json={"force": False})
    client.post("/api/series/7/volume-enrich/preview", json={"force": True})

    assert len(calls) == 2


def test_l_index_memoise_ne_dispense_pas_de_relire_kavita(client, monkeypatch, wired):
    """L'invariant à ne pas perdre : ce qui est retenu est l'index du
    fournisseur, pas l'état de Kavita. `apply_entry` relit le chapitre juste
    avant d'écrire et réapplique la politique sur cet état frais — sans quoi un
    tome rempli à la main entre l'aperçu et le clic se ferait écraser, puisque
    `UpdateChapterDto` remplace tout."""
    _enable(monkeypatch)

    client.post("/api/series/7/volume-enrich/preview", json={})
    # L'utilisateur écrit lui-même le résumé du tome 1 dans Kavita.
    monkeypatch.setattr(
        wired,
        "get_chapter",
        lambda cid: {"id": cid, "summary": "Écrit à la main"} if cid == 1 else {"id": cid},
    )
    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()

    assert [d["id"] for d in wired.written] == [2]


def test_la_remise_a_zero_oublie_l_index_de_la_serie(client, monkeypatch, wired):
    """Remettre une série à la reprise, c'est demander à la refaire pour de bon :
    la refaire à partir de l'index d'il y a dix minutes serait une remise à zéro
    en trompe-l'œil."""
    _enable(monkeypatch)
    monkeypatch.setattr(routes_ve, "clear_volume_unit_states", lambda sid: None)
    calls = []
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index", _counting_index(calls)
    )

    client.post("/api/series/7/volume-enrich/preview", json={})
    res = client.post("/api/series/7/volume-enrich/reset", json={})
    client.post("/api/series/7/volume-enrich/preview", json={})

    assert res.get_json()["index_forgotten"] == 1
    assert len(calls) == 2


# ===== Remise à zéro d'une série =====


def test_resetting_a_series_hands_it_back_to_the_resume(client, monkeypatch):
    """Seule sortie de secours quand une série a été fermée à tort :
    `clear_volume_unit_states` n'était exposée par aucune route."""
    _enable(monkeypatch)
    cleared = []
    monkeypatch.setattr(routes_ve, "clear_volume_unit_states", cleared.append)

    res = client.post("/api/series/7/volume-enrich/reset", json={})

    assert res.status_code == 200
    assert res.get_json()["reset"] is True
    assert cleared == [7]


def test_the_reset_route_is_closed_when_the_feature_is_off(client, monkeypatch):
    monkeypatch.setattr(
        routes_ve, "load_config", lambda: {"UI_LANG": "en", "VOLUME_ENRICHMENT_ENABLED": False}
    )

    assert client.post("/api/series/7/volume-enrich/reset", json={}).status_code == 403


def test_a_refused_cover_shows_up_in_the_answer(client, monkeypatch, wired):
    """Une unité peut réussir son texte et se faire refuser sa couverture : son
    état reste `DONE`. Ne collecter les erreurs que sur `FAILED` laissait cet
    échec dans les seuls journaux, et l'utilisateur repartait convaincu que la
    couverture était posée. Depuis que l'écriture est une tâche de fond,
    l'avertissement voyage dans l'état publié, plus dans la réponse HTTP."""
    _enable(monkeypatch)
    monkeypatch.setattr(
        wired, "upload_chapter_cover", lambda cid, url, lock=True: (False, "413 trop lourde")
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: (
            "comicvine",
            {"1": {"summary": "Un", "cover_url": "https://cdn.test/1.jpg"}},
        ),
    )

    client.post("/api/series/7/volume-enrich/apply", json={})
    assert _wait_idle()
    state = job.get_volume_enrich_state()

    # Le résumé est bien passé : c'est tout l'intérêt du cas, l'unité est
    # comptée comme réussie et l'échec de la couverture pourrait se taire.
    assert state["counts"]["done"] == 1
    assert state["counts"]["failed"] == 0
    assert any("413" in str(e) for e in state["errors"])


def test_the_blueprint_is_registered_in_the_app():
    """Une route jamais montée est une fonctionnalité invisible.

    Lu dans la source plutôt qu'en important `app`, qui monte eventlet et tout
    le reste de l'application pour vérifier deux lignes.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    assert "from routes.volume_enrichment import volume_enrichment_bp" in source
    assert "app.register_blueprint(volume_enrichment_bp)" in source
