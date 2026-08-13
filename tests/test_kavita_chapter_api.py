"""
Appels Kavita au niveau chapitre : lecture, écriture, couverture.

La lecture est la moitié qui compte : `UpdateChapterDto` remplace tout, donc un
`GET /api/Chapter` qui échoue et qu'on ignorerait mènerait droit à un chapitre
vidé de ses crédits et sorti de son ordre de lecture.
"""
from __future__ import annotations

import pytest

from kavita_api import KavitaAPI


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.content = b"\xff\xd8\xff" + b"img"

    def json(self):
        return self._payload


@pytest.fixture
def api():
    client = KavitaAPI("http://kavita.test", "key")
    client.token = "jwt"
    client.headers = {"Authorization": "Bearer jwt"}
    return client


def test_get_chapter_returns_the_dto(api, monkeypatch):
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        return FakeResponse(200, {"id": 42, "titleName": "Tome 3"})

    monkeypatch.setattr("kavita_api.requests.get", fake_get)

    assert api.get_chapter(42) == {"id": 42, "titleName": "Tome 3"}
    assert calls["url"] == "http://kavita.test/api/Chapter?chapterId=42"


@pytest.mark.parametrize("status", [401, 404, 500])
def test_a_failed_read_returns_none_rather_than_an_empty_dict(api, monkeypatch, status):
    """Un dict vide passerait pour un chapitre sans métadonnées, et l'écriture
    qui suit effacerait tout ce que Kavita avait."""
    monkeypatch.setattr("kavita_api.requests.get", lambda url, **kw: FakeResponse(status))
    # Sur 401, `get_chapter` retente une authentification : sans ce mock, le
    # test sortait pour de vrai vers l'URL Kavita factice.
    monkeypatch.setattr(KavitaAPI, "authenticate", lambda self: False)

    assert api.get_chapter(42) is None


def test_a_network_error_on_read_returns_none(api, monkeypatch):
    def boom(url, **kwargs):
        raise ConnectionError("kavita injoignable")

    monkeypatch.setattr("kavita_api.requests.get", boom)

    assert api.get_chapter(42) is None


def test_update_posts_the_payload_as_is(api, monkeypatch):
    sent = {}

    def fake_post(url, json=None, **kwargs):
        sent["url"] = url
        sent["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr("kavita_api.requests.post", fake_post)

    ok, _msg = api.update_chapter_metadata({"id": 42, "summary": "x", "sortOrder": 3.0})

    assert ok is True
    assert sent["url"] == "http://kavita.test/api/Chapter/update"
    assert sent["json"]["sortOrder"] == 3.0


def test_update_refuses_a_payload_without_id(api, monkeypatch):
    """Kavita répondrait « chapter doesn't exist » ; autant ne pas partir."""
    def fake_post(url, **kwargs):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("aucune requête ne doit partir")

    monkeypatch.setattr("kavita_api.requests.post", fake_post)

    ok, msg = api.update_chapter_metadata({"summary": "x"})

    assert ok is False
    assert "id" in msg.lower()


def test_update_reports_the_http_failure(api, monkeypatch):
    monkeypatch.setattr(
        "kavita_api.requests.post",
        lambda url, **kw: FakeResponse(400, text="chapter-doesnt-exist"),
    )

    ok, msg = api.update_chapter_metadata({"id": 42})

    assert ok is False
    assert "400" in msg


def test_chapter_cover_upload_sends_base64_and_the_lock(api, monkeypatch):
    sent = {}

    monkeypatch.setattr(KavitaAPI, "_download_cover_base64", lambda self, url: ("QUJD", ""))

    def fake_post(url, json=None, **kwargs):
        sent["url"] = url
        sent["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr("kavita_api.requests.post", fake_post)

    ok, _msg = api.upload_chapter_cover(42, "https://cdn.test/c.jpg")

    assert ok is True
    assert sent["url"] == "http://kavita.test/api/Upload/chapter"
    assert sent["json"] == {"id": 42, "url": "QUJD", "lockCover": True}


def test_a_refused_cover_url_never_reaches_kavita(api, monkeypatch):
    """L'allowlist de domaines doit valoir pour le chemin tome comme pour le
    chemin série, sinon elle devient contournable."""
    monkeypatch.setattr(
        KavitaAPI, "_download_cover_base64", lambda self, url: (None, "domaine refusé")
    )

    def fake_post(url, **kwargs):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("aucun upload ne doit partir")

    monkeypatch.setattr("kavita_api.requests.post", fake_post)

    ok, msg = api.upload_chapter_cover(42, "https://evil.test/c.jpg")

    assert ok is False
    assert msg == "domaine refusé"


def test_the_series_cover_upload_still_goes_through_the_same_helper(api, monkeypatch):
    """La factorisation ne doit pas avoir changé le contrat de l'upload série."""
    sent = {}

    monkeypatch.setattr(KavitaAPI, "_download_cover_base64", lambda self, url: ("QUJD", ""))

    def fake_post(url, json=None, **kwargs):
        sent["url"] = url
        sent["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr("kavita_api.requests.post", fake_post)

    ok, _msg = api.upload_series_cover(7, "https://cdn.test/s.jpg")

    assert ok is True
    assert sent["url"] == "http://kavita.test/api/Upload/series"
    assert sent["json"] == {"id": 7, "url": "QUJD", "lockCover": True}
