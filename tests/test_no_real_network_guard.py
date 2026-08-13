"""La barrière réseau de `tests/conftest.py` fait-elle vraiment barrage ?

L'en-tête de conftest promettait « aucun appel réseau réel » sans rien poser :
un mock oublié partait pour de bon chez le fournisseur, et une rafale vers un
site sans API fait bannir l'IP. Ces tests vérifient que la promesse est tenue à
chacune des couches par lesquelles un scraper peut sortir.

Tous les hôtes utilisés ici sont volontairement inoffensifs : `example.invalid`
est un TLD réservé par la RFC 6761 qui ne résout jamais, et 192.0.2.1 est du
TEST-NET-1 non routable. Même si la barrière tombait, aucun fournisseur ne
serait touché par ce fichier.
"""
import socket
import threading

import pytest

from conftest import RealNetworkAccessError


@pytest.fixture(autouse=True)
def _refus_attendus(expected_network_refusals):
    """Ce fichier provoque des refus exprès : on le déclare à la barrière.

    Sans cela, son contrôle de démontage — celui qui rattrape les refus avalés
    par un `except Exception` de scraper — ferait échouer ces tests-ci.
    """
    return expected_network_refusals


def test_getaddrinfo_bloque_et_nomme_l_hote():
    with pytest.raises(RealNetworkAccessError) as excinfo:
        socket.getaddrinfo("example.invalid", 80)
    message = str(excinfo.value)
    assert "example.invalid" in message
    # Le message doit dire quoi faire, pas seulement interdire.
    assert "real_network_access" in message


def test_create_connection_bloquee():
    with pytest.raises(RealNetworkAccessError):
        socket.create_connection(("example.invalid", 80), timeout=1)


def test_connect_sur_ip_litterale_bloque():
    """Une IP en dur ne passe pas par `getaddrinfo` : `connect` doit filtrer aussi."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RealNetworkAccessError):
            sock.connect(("192.0.2.1", 80))
    finally:
        sock.close()


def test_curl_cffi_bloque():
    """`curl_cffi` ouvre sa connexion dans libcurl, hors du module `socket`.

    C'est la bibliothèque des scrapers protégés par Cloudflare — Bédéthèque en
    tête — donc exactement ceux qui bannissent. Une barrière qui ne couvrirait
    que les sockets Python les laisserait tous sortir.
    """
    from curl_cffi import requests as curl_requests

    with pytest.raises(RealNetworkAccessError):
        curl_requests.Session(impersonate="chrome110").get("https://example.invalid/")

    # Le helper de module construit sa propre `Session` : même barrage attendu.
    with pytest.raises(RealNetworkAccessError):
        curl_requests.get("https://example.invalid/")


def test_requests_bloque():
    import requests

    with pytest.raises(RealNetworkAccessError):
        requests.get("http://example.invalid/", timeout=1)


def test_boucle_locale_toujours_autorisee():
    """Un serveur WSGI de test doit continuer à fonctionner.

    Une barrière qui casse la boucle locale serait désactivée à la première
    gêne, et ne protégerait alors plus rien du tout.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepted = []

    def _accept():
        conn, _ = server.accept()
        accepted.append(conn)

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    try:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.close()
        thread.join(timeout=5)
        assert accepted, "la connexion de boucle locale n'a pas abouti"
    finally:
        for conn in accepted:
            conn.close()
        server.close()

    # `localhost` par son nom doit résoudre comme avant.
    assert socket.getaddrinfo("localhost", port)


def test_porte_de_sortie_nommee(real_network_access):
    """La fixture d'exception rend bien la pile réseau d'origine."""
    assert real_network_access is True
    assert socket.getaddrinfo.__name__ != "guarded_getaddrinfo"
    assert socket.create_connection.__name__ != "guarded_create_connection"
