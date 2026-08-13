"""
Fixtures partagées pour la suite pytest de MetaKavita.

Principe directeur : ces tests ne doivent JAMAIS toucher au vrai dossier
`data/` du dépôt (config.json, cache.db, logs) ni effectuer de vrais appels
réseau vers Kavita ou les fournisseurs externes (AniList, MangaBaka, ...).
Chaque fixture qui touche à un état global mutable (fichiers, module-level
variables) le fait via `monkeypatch`/`tmp_path`, automatiquement annulé par
pytest à la fin de chaque test.
"""
import socket
import sys
import os
import time
import types
from urllib.parse import urlsplit

_TESTS_DIR = os.path.dirname(__file__)
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
sys.path.insert(0, _ROOT_DIR)
sys.path.insert(0, _TESTS_DIR)

import pytest

from flask_test_app import get_series_bp  # noqa: E402


# --- BARRIÈRE RÉSEAU ---------------------------------------------------------
# L'en-tête de ce fichier dit depuis toujours que les tests ne doivent JAMAIS
# émettre de vrai appel réseau. C'était une intention écrite, rien ne
# l'empêchait : un `fetch()` dont le mock est mal posé partait pour de bon chez
# le fournisseur, et une rafale de requêtes vers un site sans API (Bédéthèque,
# Planète BD) fait bannir l'IP de la machine qui lance la suite. Le préjudice
# est réel et non réversible à court terme, d'où une vraie barrière.
#
# Elle est posée à DEUX niveaux, parce qu'un seul ne couvre pas le parc :
#   - couche socket (`getaddrinfo`, `connect`, `create_connection`) pour tout ce
#     qui passe par le réseau Python : `requests`, `urllib`, `http.client` ;
#   - couche `curl_cffi`, qui NE PASSE PAS par le module `socket` — libcurl
#     ouvre sa connexion en C. Or c'est précisément la bibliothèque des
#     scrapers français protégés par Cloudflare (Bédéthèque, Planète BD,
#     Decitre, Babelio, LOCG, ANN, SensCritique, Manga News...), donc ceux qui
#     bannissent. Une barrière purement socket les aurait tous laissés passer.

_LOOPBACK_HOSTNAMES = frozenset({
    "", "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
})


def _is_local_host(host) -> bool:
    """Vrai pour la boucle locale et le « toutes interfaces » d'un bind.

    Les sockets de boucle locale restent autorisés : un serveur WSGI de test,
    un `socketpair()` (émulé par un connect sur 127.0.0.1 sous Windows) ou une
    base servie en local sont des usages légitimes. Une barrière qui casse ces
    cas-là serait désactivée à la première gêne, et ne protégerait plus rien.
    """
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", "replace")
        except Exception:
            return False
    if not isinstance(host, str):
        return False
    name = host.strip().strip("[]").lower()
    if name in _LOOPBACK_HOSTNAMES:
        return True
    if name in {"0.0.0.0", "::", "::1", "::ffff:127.0.0.1"}:
        return True
    return name.startswith("127.")


try:
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession
    from curl_cffi.requests import Session as _CurlSession

    _CURL_SESSION_CLASSES = (_CurlSession, _CurlAsyncSession)
except Exception:  # pragma: no cover - curl_cffi est une dépendance ferme
    _CURL_SESSION_CLASSES = ()


class RealNetworkAccessError(RuntimeError):
    """Levée quand un test tente d'ouvrir une connexion sortante réelle."""


# Refus survenus pendant le test en cours. Les scrapers enveloppent leurs
# requêtes dans un `except Exception: return None` : sans cette trace, un test
# qui attend `None` passerait au vert alors que la barrière vient d'arrêter une
# vraie sortie réseau, et le mock manquant resterait invisible. Le refus est
# donc aussi constaté au démontage, hors de portée du `try` du scraper.
_NETWORK_REFUSALS: list = []


def _refuse(host, origin: str):
    _NETWORK_REFUSALS.append(f"{origin} vers « {host} »")
    raise RealNetworkAccessError(
        f"Appel réseau réel interdit pendant les tests : {origin} vers « {host} ».\n"
        "Un test qui sort pour de vrai chez un fournisseur peut faire bannir "
        "l'IP de la machine (c'est déjà arrivé avec Bédéthèque).\n"
        "Que faire :\n"
        "  - mocker la couche HTTP du scraper (monkeypatch du module `requests` "
        "/ `curl_cffi.requests` importé par le scraper, ou de `_http_get`) ;\n"
        "  - si le test a VRAIMENT besoin du réseau, demander explicitement la "
        "fixture `real_network_access` — et ne jamais viser un fournisseur."
    )


@pytest.fixture
def real_network_access():
    """À demander par un test qui a réellement besoin d'une sortie réseau.

    Désactive la barrière `_no_real_network` ci-dessous. Aucun test de la suite
    ne l'utilise aujourd'hui, et viser un fournisseur avec reste proscrit : la
    porte existe pour un besoin légitime (un serveur local non-loopback, par
    exemple), pas pour contourner un mock manquant.
    """
    return True


@pytest.fixture
def expected_network_refusals():
    """Réservée aux tests de la barrière elle-même (test_no_real_network_guard).

    Ils provoquent des refus exprès : sans cette déclaration, le contrôle de
    démontage les prendrait pour des mocks manquants.
    """
    return _NETWORK_REFUSALS


@pytest.fixture(autouse=True)
def _no_real_network(request, monkeypatch):
    if "real_network_access" in request.fixturenames:
        yield
        return

    orig_getaddrinfo = socket.getaddrinfo
    orig_create_connection = socket.create_connection
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if not _is_local_host(host):
            _refuse(host, "résolution DNS")
        return orig_getaddrinfo(host, port, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, (tuple, list)) and address else address
        if not _is_local_host(host):
            _refuse(host, "ouverture de connexion")
        return orig_create_connection(address, *args, **kwargs)

    def _check_sock_address(sock, address, origin):
        # Seules les familles IP sont filtrées : AF_UNIX et les sockets
        # exotiques n'ont pas d'hôte distant et ne sortent pas de la machine.
        if getattr(sock, "family", None) not in (socket.AF_INET, socket.AF_INET6):
            return
        host = address[0] if isinstance(address, (tuple, list)) and address else address
        if not _is_local_host(host):
            _refuse(host, origin)

    def guarded_connect(self, address):
        _check_sock_address(self, address, "connect() de socket")
        return orig_connect(self, address)

    def guarded_connect_ex(self, address):
        _check_sock_address(self, address, "connect_ex() de socket")
        return orig_connect_ex(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)

    def _guard_curl(cls):
        def wrap(name, url_index):
            # `Session.get` & co. sont des `partialmethod(request, "GET")` :
            # elles ont capturé la fonction `request` à la création de la
            # classe, donc patcher `request` seul ne les intercepte PAS. Chaque
            # verbe doit être enveloppé pour son propre compte — et `.get()` est
            # justement le chemin qu'emprunte `BaseScraper._http_get`.
            original = getattr(cls, name)

            def guarded(self, *args, **kwargs):
                url = kwargs.get("url")
                if url is None and len(args) > url_index:
                    url = args[url_index]
                host = urlsplit(str(url or "")).hostname
                if not _is_local_host(host):
                    _refuse(host, f"curl_cffi {cls.__name__}.{name}()")
                return original(self, *args, **kwargs)

            monkeypatch.setattr(cls, name, guarded)

        wrap("request", 1)
        for verb in ("get", "post", "head", "put", "patch", "delete", "options"):
            wrap(verb, 0)

    # Les classes sont capturées à l'import de ce conftest, pas relues ici : un
    # test qui réaffecte `curl_cffi.requests.Session` par un bouchon ne doit pas
    # pouvoir désarmer la barrière pour les autres. Les helpers de module
    # (`curl_cffi.requests.get/post/...`) construisent une `Session` puis
    # appellent `Session.request` : ils sont couverts par là.
    for session_cls in _CURL_SESSION_CLASSES:
        _guard_curl(session_cls)

    _NETWORK_REFUSALS.clear()
    yield
    refusals = list(_NETWORK_REFUSALS)
    _NETWORK_REFUSALS.clear()
    if refusals and "expected_network_refusals" not in request.fixturenames:
        pytest.fail(
            "La barrière réseau a arrêté "
            f"{len(refusals)} sortie(s) que ce test a avalées sans le dire :\n  - "
            + "\n  - ".join(dict.fromkeys(refusals))
            + "\nLe scraper a rendu son résultat de repli (souvent `None`) sur "
            "une exception de la barrière, pas sur les données du test : il "
            "manque un mock HTTP.",
            pytrace=False,
        )


@pytest.fixture
def real_translator():
    """À demander par un test qui veut le vrai `translator.translate_text`.

    Aucun test ne le fait aujourd'hui, et un tel test devrait de toute façon
    mocker sa couche HTTP : la porte existe pour rester symétrique du reste.
    """
    return True


@pytest.fixture(autouse=True)
def _no_real_translation(request, monkeypatch):
    """`translate_text` sortait POUR DE VRAI pendant la suite.

    La barrière réseau l'a révélé : seize tests d'enrichissement et de revue
    manuelle appelaient `translator.translate_text` sans le mocker. Le module
    tente DeepL avec la clé bidon du test, échoue, puis bascule d'office sur
    Google Translate — deux appels sortants par test, à chaque exécution de la
    suite, et un résumé dont le contenu dépendait de ce que Google renvoyait ce
    jour-là. Les échecs étaient invisibles : `translate_text` journalise et
    rend le texte d'origine, donc les assertions passaient quand même.

    L'identité est le comportement que ces tests attendaient déjà (c'est ce que
    rend `translate_text` quand tous les moteurs échouent) ; les tests qui
    vérifient la traduction posent leur propre mock, appliqué après celui-ci.
    """
    if "real_translator" in request.fixturenames:
        return

    def _identity(text, *_args, **_kwargs):
        return text

    def _identity_batch(texts, *_args, **_kwargs):
        return [text if isinstance(text, str) else "" for text in (texts or [])]

    import translator

    monkeypatch.setattr(translator, "translate_text", _identity)
    # L'envoi groupé est une porte de sortie réseau de plus : la neutraliser ici
    # évite de refaire, par un autre chemin, les seize sorties réelles décrites
    # ci-dessus.
    monkeypatch.setattr(translator, "translate_texts", _identity_batch)
    # `services/kavita_payload.py` fait `from translator import translate_text`
    # au chargement : le nom y est déjà lié, patcher le module source ne suffit
    # pas. Les autres appelants importent dans le corps de la fonction.
    try:
        import services.kavita_payload as kavita_payload
    except Exception:  # pragma: no cover - module en travaux côté autre agent
        return
    monkeypatch.setattr(kavita_payload, "translate_text", _identity, raising=False)


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


@pytest.fixture(autouse=True)
def _clean_volume_index_memo():
    """`_CACHE` (services/volume_enrichment/index_cache.py) est un global de
    module : il sert de pont entre l'aperçu d'une série et l'écriture qui suit,
    avec dix minutes de durée de vie. Sans reset, un test qui bâtit un plan
    laisserait son index à celui d'après — lequel croirait avoir interrogé un
    fournisseur qu'il a en réalité mocké autrement, voire pas mocké du tout."""
    from services.volume_enrichment.index_cache import reset_cache

    reset_cache()
    yield
    reset_cache()


@pytest.fixture(autouse=True)
def _clean_provider_throttle():
    """`LAST_REQUEST_TIMES`/`_THROTTLE_LOCKS` (services/provider_throttle.py) sont
    des globaux de module partagés par l'enrichissement, le diagnostic scrapers,
    l'inventaire et la recherche de couvertures : sans reset, un test qui appelle
    un fournisseur factice déjà « appelé » par un test précédent dormirait
    réellement le temps de son `rate_limit`."""
    from services.provider_throttle import reset_throttle_state

    reset_throttle_state()
    yield
    reset_throttle_state()


@pytest.fixture
def real_provider_throttle_sleep():
    """À demander pour mesurer une attente RÉELLE de `throttle_provider()`.

    Désactive le garde-fou `_no_real_provider_throttle_sleep` ci-dessous, qui
    interdit par défaut de dormir pour de vrai pendant la suite.
    """
    return True


@pytest.fixture(autouse=True)
def _no_real_provider_throttle_sleep(request, monkeypatch):
    """Depuis que `BaseScraper._http_get` applique la cadence à CHAQUE requête,
    un seul `fetch()` de scraper émet six à vingt-cinq appels throttlés : la
    suite dormirait réellement plusieurs minutes sans rien vérifier de plus. On
    neutralise donc la seule attente, sans toucher au reste du cycle
    lire-dormir-écrire ni aux verrous par scraper, dont les tests dédiés ont
    besoin. Les tests qui mesurent la cadence demandent soit
    `real_provider_throttle_sleep`, soit leur propre horloge simulée."""
    if "real_provider_throttle_sleep" in request.fixturenames:
        return
    from services import provider_throttle

    monkeypatch.setattr(
        provider_throttle,
        "time",
        types.SimpleNamespace(time=time.time, sleep=lambda _seconds: None),
    )


@pytest.fixture(autouse=True)
def _clean_kavita_series_caches():
    """`_series_lib_type_cache`/`_series_library_id_cache` (kavita_api.py) sont
    des attributs de CLASSE partagés par toutes les instances de `KavitaAPI` :
    sans reset, un test réutilisant un `series_id` déjà vu par un test précédent
    lirait silencieusement une valeur périmée au lieu de refaire l'appel HTTP mocké."""
    from kavita_api import KavitaAPI

    KavitaAPI._series_lib_type_cache.clear()
    KavitaAPI._series_library_id_cache.clear()
    yield
    KavitaAPI._series_lib_type_cache.clear()
    KavitaAPI._series_library_id_cache.clear()


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

    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(get_series_bp())
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
