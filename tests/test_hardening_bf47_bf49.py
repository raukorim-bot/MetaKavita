"""
Non-régression du lot de durcissement BF47–BF49 (issue #15).

Three independent hardening changes, tested here together because they ship
together:

- **BF47** `/api/proxy-image` refuses anything over 5 MB, and refuses it while
  streaming rather than after the whole body is already in memory.
- **BF48** the webhook accepts its token from the `X-Webhook-Token` header, while
  the historical `?token=` query form keeps working.
- **BF63** Config/docs prefer the header; `?token=` stays accepted (legacy) and
  emits a once-per-process warning when used without the header.
- **BF49** `config.json` is written 0600.

Comme le reste de la suite (voir tests/conftest.py), ces tests n'importent
jamais `app.py` : celui-ci démarre des threads de fond et charge tous les
scrapers à l'import. On enregistre donc uniquement le blueprint testé sur une
app Flask ad hoc.
"""
import io
import os
import stat

import pytest
from flask import Flask

from routes.misc import misc_bp, _MAX_PROXY_IMAGE_BYTES
from routes.sync import sync_bp


# --------------------------------------------------------------------------
# Doubles de test
# --------------------------------------------------------------------------

class FakeStreamedResponse:
    """Réponse `requests` minimale en mode `stream=True`.

    Enregistre si `close()` a été appelée : le proxy tient une connexion ouverte
    tant que le corps n'est pas lu, donc « la réponse est bien fermée sur CHAQUE
    chemin de sortie » fait partie du contrat testé, pas d'un détail interne.
    """

    def __init__(self, *, status_code=200, headers=None, chunks=(), body=None):
        self.status_code = status_code
        self.headers = headers if headers is not None else {"Content-Type": "image/jpeg"}
        self._chunks = list(chunks) if body is None else [body]
        self.closed = False
        self.consumed = 0

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            self.consumed += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


@pytest.fixture
def proxy_client(monkeypatch):
    """App Flask ad hoc exposant `/api/proxy-image`, réseau et scrapers neutralisés."""
    import routes.misc as misc

    monkeypatch.setattr(
        misc.ScraperRegistry, "get_all_proxy_domains", staticmethod(lambda: ["cdn.example"])
    )
    # C61: proxy-image calls get_all(include_disabled=True).
    monkeypatch.setattr(
        misc.ScraperRegistry, "get_all", staticmethod(lambda **kwargs: [])
    )

    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(misc_bp)
    return test_app.test_client()


def _patch_fetch(monkeypatch, response):
    """Remplace le fetch réseau du proxy par une réponse fabriquée."""
    import routes.misc as misc

    def fake_fetch(get_fn, url, allowed_domains, **kwargs):
        fake_fetch.kwargs = kwargs
        return response, "ok", url

    fake_fetch.kwargs = {}
    monkeypatch.setattr(misc, "fetch_with_safe_redirects", fake_fetch)
    return fake_fetch


# --------------------------------------------------------------------------
# BF47 — plafond 5 Mo sur /api/proxy-image
# --------------------------------------------------------------------------

def test_proxy_image_serves_a_normal_cover(proxy_client, monkeypatch):
    payload = b"\xff\xd8\xff" + b"x" * 2048
    response = FakeStreamedResponse(body=payload)
    _patch_fetch(monkeypatch, response)

    res = proxy_client.get("/api/proxy-image?url=https://cdn.example/cover.jpg")

    assert res.status_code == 200
    assert res.data == payload
    assert res.mimetype == "image/jpeg"
    assert response.closed, "la réponse streamée doit être fermée après un succès"


def test_proxy_image_rejects_oversized_content_length_without_downloading(
    proxy_client, monkeypatch
):
    """Content-Length annoncé au-dessus du plafond : refus AVANT tout téléchargement.

    C'est l'intérêt du contrôle en deux temps — quand l'hôte annonce honnêtement
    une taille excessive, on n'a aucune raison de dépenser la bande passante.
    """
    response = FakeStreamedResponse(
        headers={
            "Content-Type": "image/jpeg",
            "Content-Length": str(_MAX_PROXY_IMAGE_BYTES + 1),
        },
        chunks=[b"z" * 1024],
    )
    _patch_fetch(monkeypatch, response)

    res = proxy_client.get("/api/proxy-image?url=https://cdn.example/huge.jpg")

    assert res.status_code == 413
    assert response.consumed == 0, "aucun octet ne doit être lu quand l'en-tête suffit à refuser"
    assert response.closed


def test_proxy_image_rejects_oversized_body_when_content_length_lies(
    proxy_client, monkeypatch
):
    """Pas de Content-Length (ou mensonger) : c'est le total courant qui tranche.

    Le cas qui compte vraiment : un hôte allowlisté compromis peut simplement
    omettre l'en-tête, ou utiliser un encodage chunked où il n'existe pas. Le
    plafond doit tenir sans lui.
    """
    oversized_chunks = [b"z" * (1024 * 1024)] * 8  # 8 Mo > 5 Mo
    response = FakeStreamedResponse(
        headers={"Content-Type": "image/png"}, chunks=oversized_chunks
    )
    _patch_fetch(monkeypatch, response)

    res = proxy_client.get("/api/proxy-image?url=https://cdn.example/lying.png")

    assert res.status_code == 413
    # Le dépassement est borné par un chunk : on ne lit jamais les 8 Mo.
    assert response.consumed <= _MAX_PROXY_IMAGE_BYTES + (1024 * 1024)
    assert response.consumed < 8 * 1024 * 1024
    assert response.closed


def test_proxy_image_ignores_unparseable_content_length(proxy_client, monkeypatch):
    """Un Content-Length illisible ne doit ni faire planter ni court-circuiter le plafond."""
    payload = b"\x89PNG" + b"y" * 512
    response = FakeStreamedResponse(
        headers={"Content-Type": "image/png", "Content-Length": "not-a-number"},
        body=payload,
    )
    _patch_fetch(monkeypatch, response)

    res = proxy_client.get("/api/proxy-image?url=https://cdn.example/weird.png")

    assert res.status_code == 200
    assert res.data == payload
    assert response.closed


def test_proxy_image_requests_a_streaming_fetch(proxy_client, monkeypatch):
    """`stream=True` est ce qui rend le plafond possible — le perdre le viderait de son sens.

    Sans lui, `requests` a déjà bufferisé tout le corps au retour de l'appel, et
    tout refus ultérieur arrive trop tard. D'où ce test explicite : une
    régression silencieuse ici ne casserait aucun autre test.
    """
    fake_fetch = _patch_fetch(monkeypatch, FakeStreamedResponse(body=b"img"))

    proxy_client.get("/api/proxy-image?url=https://cdn.example/a.jpg")

    assert fake_fetch.kwargs.get("stream") is True


def test_proxy_image_closes_response_on_non_image_content_type(proxy_client, monkeypatch):
    response = FakeStreamedResponse(
        headers={"Content-Type": "text/html"}, body=b"<html>nope</html>"
    )
    _patch_fetch(monkeypatch, response)

    res = proxy_client.get("/api/proxy-image?url=https://cdn.example/page.html")

    assert res.status_code == 415
    assert response.closed


def test_proxy_image_still_refuses_domains_outside_the_allowlist(proxy_client):
    res = proxy_client.get("/api/proxy-image?url=https://evil.example/cover.jpg")
    assert res.status_code == 403


def test_safe_redirects_closes_each_intermediate_hop():
    """Chaque hop de redirect doit être fermé avant de suivre le suivant.

    Inoffensif tant que l'appelant ne streamait pas ; avec `stream=True` un hop
    abandonné garde sa connexion ouverte — et sous le worker eventlet unique,
    une greenthread avec elle.
    """
    from url_allowlist import fetch_with_safe_redirects

    hop = FakeStreamedResponse(
        status_code=302,
        headers={"Location": "https://cdn.example/final.jpg"},
    )
    final = FakeStreamedResponse(body=b"img")
    responses = [hop, final]

    def fake_get(url, **kwargs):
        return responses.pop(0)

    res, reason, final_url = fetch_with_safe_redirects(
        fake_get, "https://cdn.example/start.jpg", ["cdn.example"], stream=True
    )

    assert res is final
    assert reason == "ok"
    assert hop.closed, "le hop intermédiaire doit être fermé avant de suivre le redirect"
    assert not final.closed, "la réponse finale appartient à l'appelant"


# --------------------------------------------------------------------------
# BF48 — jeton webhook en en-tête
# --------------------------------------------------------------------------

@pytest.fixture
def webhook_client(monkeypatch):
    """App Flask ad hoc exposant le blueprint `sync`, avec un WEBHOOK_TOKEN connu."""
    import routes.sync as sync

    monkeypatch.setattr(
        sync, "load_config", lambda: {"WEBHOOK_TOKEN": "s3cret-token", "UI_LANG": "fr"}
    )

    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(sync_bp)
    return test_app.test_client()


def test_webhook_accepts_the_header_token(webhook_client):
    """400 (champs manquants) et non 401 : l'authentification est passée."""
    res = webhook_client.post("/webhook", headers={"X-Webhook-Token": "s3cret-token"}, json={})
    assert res.status_code == 400


def test_webhook_still_accepts_the_legacy_query_token(webhook_client):
    """Régression : les URLs `?token=` déjà collées dans Kavita doivent survivre."""
    res = webhook_client.post("/webhook?token=s3cret-token", json={})
    assert res.status_code == 400


def test_webhook_rejects_a_wrong_header_token(webhook_client):
    res = webhook_client.post("/webhook", headers={"X-Webhook-Token": "wrong"}, json={})
    assert res.status_code == 401


def test_webhook_rejects_a_wrong_query_token(webhook_client):
    res = webhook_client.post("/webhook?token=wrong", json={})
    assert res.status_code == 401


def test_webhook_rejects_a_missing_token(webhook_client):
    res = webhook_client.post("/webhook", json={})
    assert res.status_code == 401


def test_webhook_header_wins_over_the_query_parameter(webhook_client):
    """En-tête prioritaire : un `?token=` périmé dans une URL enregistrée ne doit pas
    invalider une intégration qui envoie correctement l'en-tête."""
    res = webhook_client.post(
        "/webhook?token=stale", headers={"X-Webhook-Token": "s3cret-token"}, json={}
    )
    assert res.status_code == 400


def test_webhook_non_ascii_token_is_rejected_not_a_500(webhook_client):
    """`secrets.compare_digest` lève TypeError sur des `str` non-ASCII.

    Sans la comparaison en octets, un jeton accentué transformait un échec
    d'authentification en 500 — et un 500 sur un chemin d'auth est une fuite
    d'information autant qu'un bug.
    """
    res = webhook_client.post("/webhook", headers={"X-Webhook-Token": "mot-de-passé-é"}, json={})
    assert res.status_code == 401


def test_webhook_empty_configured_token_rejects_everything(monkeypatch):
    """Fail closed : WEBHOOK_TOKEN vide ne doit jamais laisser passer un jeton vide."""
    import routes.sync as sync

    monkeypatch.setattr(sync, "load_config", lambda: {"WEBHOOK_TOKEN": "", "UI_LANG": "fr"})
    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(sync_bp)
    client = test_app.test_client()

    assert client.post("/webhook", json={}).status_code == 401
    assert client.post("/webhook?token=", json={}).status_code == 401
    assert client.post("/webhook", headers={"X-Webhook-Token": ""}, json={}).status_code == 401


def test_webhook_query_token_warns_once_when_header_absent(webhook_client, monkeypatch, caplog):
    """BF63: legacy ?token= still authenticates, but warns once (noise-low) when no header."""
    import logging
    import routes.sync as sync

    monkeypatch.setattr(sync, "_webhook_query_token_warned", False)
    with caplog.at_level(logging.WARNING, logger="root"):
        first = webhook_client.post("/webhook?token=s3cret-token", json={})
        second = webhook_client.post("/webhook?token=s3cret-token", json={})

    assert first.status_code == 400
    assert second.status_code == 400
    legacy_msgs = [r for r in caplog.records if "?token=" in r.getMessage() and "legacy" in r.getMessage()]
    assert len(legacy_msgs) == 1


def test_webhook_header_path_does_not_emit_legacy_query_warning(webhook_client, monkeypatch, caplog):
    """Preferred path: X-Webhook-Token alone must not trip the query deprecation warning."""
    import logging
    import routes.sync as sync

    monkeypatch.setattr(sync, "_webhook_query_token_warned", False)
    with caplog.at_level(logging.WARNING, logger="root"):
        res = webhook_client.post(
            "/webhook", headers={"X-Webhook-Token": "s3cret-token"}, json={}
        )

    assert res.status_code == 400
    assert not any("?token=" in r.getMessage() and "legacy" in r.getMessage() for r in caplog.records)


def test_webhook_header_with_stale_query_skips_legacy_warning(webhook_client, monkeypatch, caplog):
    """Header present ⇒ no legacy warning even if a stale ?token= is also in the URL."""
    import logging
    import routes.sync as sync

    monkeypatch.setattr(sync, "_webhook_query_token_warned", False)
    with caplog.at_level(logging.WARNING, logger="root"):
        res = webhook_client.post(
            "/webhook?token=stale",
            headers={"X-Webhook-Token": "s3cret-token"},
            json={},
        )

    assert res.status_code == 400
    assert not any("?token=" in r.getMessage() and "legacy" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------
# BF49 — permissions de config.json
# --------------------------------------------------------------------------

@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirige config_manager vers un config.json temporaire."""
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    return config_manager


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows n'applique pas les bits de permission POSIX ; le chmod y est best-effort.",
)
def test_save_config_writes_the_file_0600(isolated_config):
    isolated_config.save_config({"SECRET_KEY": "abc", "WEBHOOK_TOKEN": "def"})

    mode = stat.S_IMODE(os.stat(isolated_config.CONFIG_FILE).st_mode)
    assert mode == 0o600, f"attendu 0600, obtenu {oct(mode)}"


@pytest.mark.skipif(os.name == "nt", reason="cf. ci-dessus")
def test_save_config_repairs_permissions_of_an_existing_loose_file(isolated_config):
    """Réappliqué à chaque sauvegarde, pas seulement à la création.

    Un config.json restauré depuis une sauvegarde, copié depuis une autre machine
    ou écrit par une version antérieure arrive en 0644 : sans réapplication il
    garderait ce mode indéfiniment.
    """
    isolated_config.save_config({"SECRET_KEY": "abc"})
    os.chmod(isolated_config.CONFIG_FILE, 0o644)

    isolated_config.save_config({"SECRET_KEY": "abc", "KAVITA_API_KEY": "xyz"})

    assert stat.S_IMODE(os.stat(isolated_config.CONFIG_FILE).st_mode) == 0o600


def test_save_config_survives_a_chmod_failure(isolated_config, monkeypatch):
    """Le durcissement ne doit jamais coûter la configuration de l'utilisateur.

    chmod échoue sur certains montages CIFS/SMB et FAT. Perdre le durcissement y
    est acceptable ; perdre la sauvegarde ne l'est pas.
    """
    def boom(*args, **kwargs):
        raise OSError("Operation not permitted")

    monkeypatch.setattr(os, "chmod", boom)

    isolated_config.save_config({"SECRET_KEY": "abc", "WEBHOOK_TOKEN": "def"})

    import json
    with open(isolated_config.CONFIG_FILE, "r", encoding="utf-8") as f:
        assert json.load(f)["WEBHOOK_TOKEN"] == "def"


def test_save_config_still_writes_expected_content(isolated_config):
    """Garde-fou : le durcissement ne change rien au contenu écrit."""
    import json

    payload = {"SECRET_KEY": "abc", "MAX_TAGS": 15, "SMART_SCORING": True}
    isolated_config.save_config(payload)

    with open(isolated_config.CONFIG_FILE, "r", encoding="utf-8") as f:
        assert json.load(f) == payload
