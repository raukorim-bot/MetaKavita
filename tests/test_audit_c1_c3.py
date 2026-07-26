"""
Non-régression : allowlist URL (cover upload / proxy) + CSRF soft helpers.
"""
from url_allowlist import validate_proxied_image_url


def test_validate_rejects_non_http_scheme():
    ok, reason, _ = validate_proxied_image_url("file:///etc/passwd", ["example.com"])
    assert ok is False
    assert "Schéma" in reason or "schéma" in reason.lower() or "Schéma" in reason


def test_validate_rejects_localhost_even_if_listed():
    ok, reason, domain = validate_proxied_image_url("http://127.0.0.1/x.jpg", ["127.0.0.1"])
    assert ok is False
    assert domain == "127.0.0.1"


def test_validate_rejects_unknown_domain():
    ok, reason, domain = validate_proxied_image_url(
        "https://evil.internal/cover.jpg",
        ["cdn.mangadex.org", "uploads.mangadex.org"],
    )
    assert ok is False
    assert domain == "evil.internal"


def test_validate_accepts_allowlisted_subdomain():
    ok, reason, domain = validate_proxied_image_url(
        "https://uploads.mangadex.org/covers/abc.jpg",
        ["mangadex.org"],
    )
    assert ok is True
    assert domain == "uploads.mangadex.org"


def test_validate_rejects_userinfo():
    ok, _, _ = validate_proxied_image_url("https://user:pass@cdn.example.com/a.jpg", ["cdn.example.com"])
    assert ok is False


def test_validate_rejects_private_rfc1918_ip():
    ok, reason, domain = validate_proxied_image_url("http://192.168.1.10/cover.jpg", ["192.168.1.10"])
    assert ok is False
    assert domain == "192.168.1.10"
    assert "priv" in reason.lower() or "réserv" in reason.lower() or "reserv" in reason.lower()


def test_validate_rejects_ten_dot_private():
    ok, _, domain = validate_proxied_image_url("http://10.0.0.5/a.png", ["example.com"])
    assert ok is False
    assert domain == "10.0.0.5"


def test_fetch_with_safe_redirects_allows_allowlisted_hop(mocker):
    from url_allowlist import fetch_with_safe_redirects

    class FakeHeaders(dict):
        pass

    class FakeRes:
        def __init__(self, code, location=None, content=b"img"):
            self.status_code = code
            self.headers = FakeHeaders()
            if location:
                self.headers["Location"] = location
            self.content = content

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        assert kwargs.get("allow_redirects") is False
        if url.endswith("/start"):
            return FakeRes(302, location="https://cdn.example.com/final.jpg")
        return FakeRes(200)

    res, reason, final = fetch_with_safe_redirects(
        fake_get,
        "https://cdn.example.com/start",
        ["example.com"],
        max_hops=3,
        timeout=5,
    )
    assert reason == "ok"
    assert res is not None and res.status_code == 200
    assert final == "https://cdn.example.com/final.jpg"
    assert len(calls) == 2


def test_fetch_with_safe_redirects_blocks_private_hop(mocker):
    from url_allowlist import fetch_with_safe_redirects

    class FakeRes:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/secret"}
        content = b""

    res, reason, final = fetch_with_safe_redirects(
        lambda url, **kw: FakeRes(),
        "https://cdn.example.com/start",
        ["example.com"],
        max_hops=3,
    )
    assert res is None
    assert "127.0.0.1" in final or "local" in reason.lower() or "priv" in reason.lower() or "réserv" in reason.lower() or "Hôte" in reason


def test_safe_exc_str_redacts_api_key_query():
    from secure_logging import safe_exc_str, redact_secrets

    msg = "HTTPSConnectionPool(host='x', port=443): for url: https://kavita/api?apiKey=SUPERSECRET&pluginName=X"
    red = redact_secrets(msg)
    assert "SUPERSECRET" not in red
    assert "apiKey=***" in red or "apiKey=***".lower() in red.lower()
    assert "SUPERSECRET" not in safe_exc_str(RuntimeError(msg))


def test_external_ids_coercion_skips_garbage(mocker):
    """IDs non numériques ne doivent pas faire planter update_series_external_ids."""
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita:5000", "key")
    api.token = "tok"
    api.headers = {"Authorization": "Bearer tok"}
    mocker.patch.object(api, "get_series", return_value={
        "name": "One Piece",
        "sortName": "One Piece",
        "localizedName": "OP",
        "nameLocked": True,
        "sortNameLocked": True,
        "localizedNameLocked": True,
        "aniListId": 1,
        "malId": None,
        "mangaBakaId": None,
    })
    posted = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        posted["payload"] = json
        class R:
            status_code = 200
            text = "ok"
        return R()

    mocker.patch("kavita_api.requests.post", side_effect=fake_post)
    ok, msg = api.update_series_external_ids(42, anilist_id="not-a-number", mal_id=300)
    assert ok is True
    assert posted["payload"]["localizedName"] == "OP"
    assert posted["payload"]["localizedNameLocked"] is True
    assert posted["payload"]["name"] == "One Piece"
    assert posted["payload"]["malId"] == 300
    # anilist garbage ignored → conserve l'existant
    assert posted["payload"]["aniListId"] == 1


def test_external_ids_aborts_without_snapshot(mocker):
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita:5000", "key")
    api.token = "tok"
    mocker.patch.object(api, "get_series", return_value=None)
    post = mocker.patch("kavita_api.requests.post")
    ok, msg = api.update_series_external_ids(1, anilist_id=99)
    assert ok is False
    assert "sécurité" in msg.lower() or "Impossible" in msg
    post.assert_not_called()
