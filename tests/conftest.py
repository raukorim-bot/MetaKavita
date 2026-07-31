"""
Fixtures partagées pour la suite pytest de MetaKavita.

Principe directeur : ces tests ne doivent JAMAIS toucher au vrai dossier
`data/` du dépôt (config.json, cache.db, logs) ni effectuer de vrais appels
réseau vers Kavita ou les fournisseurs externes (AniList, MangaBaka, ...).
Chaque fixture qui touche à un état global mutable (fichiers, module-level
variables) le fait via `monkeypatch`/`tmp_path`, automatiquement annulé par
pytest à la fin de chaque test.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest


@pytest.fixture(autouse=True)
def _clean_batch_inventory_cache():
    """Le cache d'inventaire de `/batch-sync` est un global de module (voir
    `routes/sync.py::_get_batch_inventory`) : sans reset, un test qui n'envoie
    pas `resume_enqueue=true` pourrait silencieusement lire l'inventaire laissé
    par un test précédent utilisant la même URL/clé factices."""
    import routes.sync as sync_routes

    sync_routes._batch_inventory_cache.clear()
    yield
    sync_routes._batch_inventory_cache.clear()


@pytest.fixture(autouse=True)
def _clean_batch_progress_counters():
    """`_batch_total`/`_batch_done` (services/background_tasks.py) sont des
    globaux de module utilisés par la barre de progression batch : sans reset,
    un test pourrait lire un total laissé par un test précédent."""
    import services.background_tasks as bg

    bg.reset_batch_progress()
    yield
    bg.reset_batch_progress()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Redirige db_manager vers une base SQLite temporaire et jetable.

    db_manager.py référence son fichier de base (`DB_FILE`) comme variable
    globale de module, relue à chaque appel de fonction : la patcher ici
    suffit à isoler TOUTES les fonctions de db_manager (y compris celles
    importées par nom ailleurs, ex: `from db_manager import save_series_override`
    dans routes/series.py), sans jamais écrire dans le `data/cache.db` réel.
    """
    import db_manager

    db_file = tmp_path / "cache_test.db"
    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(db_file))
    db_manager.init_db()
    return db_manager


@pytest.fixture
def flask_app(isolated_db):
    """Application Flask minimale n'enregistrant que le blueprint 'series'.

    On évite volontairement d'importer app.py tel quel : celui-ci démarre au
    chargement du module de vrais threads de fond (services/background_tasks.py),
    initialise le logging fichier et charge tous les scrapers - autant d'effets
    de bord indésirables et lents pour une suite de tests unitaires. Construire
    une appli Flask ad hoc et n'y enregistrer que le blueprint nécessaire donne
    une couverture équivalente de la couche HTTP testée (routes/series.py) tout
    en restant rapide et isolé.
    """
    from flask import Flask
    from routes.series import series_bp

    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(series_bp)
    return test_app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def mock_kavita_api(mocker):
    """Mock des méthodes réseau de KavitaAPI les plus utilisées par le moteur
    d'enrichissement et les routes HTTP, pour ne jamais dépendre d'un vrai
    serveur Kavita pendant les tests.
    """
    from kavita_api import KavitaAPI

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series", return_value={
        "id": 1,
        "name": "Test Series",
        "sortName": "Test Series",
        "localizedName": None,
        "nameLocked": False,
        "sortNameLocked": False,
        "localizedNameLocked": False,
    })
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "Succès", True))
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "Succès", True))
    mocker.patch.object(KavitaAPI, "upload_series_cover", return_value=(True, "OK"))
    mocker.patch.object(KavitaAPI, "seal_series_locks", return_value=(True, "Verrous posés"))
    return KavitaAPI
