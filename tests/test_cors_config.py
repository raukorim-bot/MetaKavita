"""
Non-régression : whitelist CORS Docker (`CORS_ALLOWED_ORIGINS`).

- Parseur CSV (strip, trailing slash, rejet de `*`)
- Headers HTTP uniquement pour une Origin whitelistée
- Preflight OPTIONS
"""
from flask import Flask, jsonify

from cors_config import (
    parse_cors_allowed_origins,
    parse_cors_allowed_origins_detailed,
    is_origin_allowed,
)


def test_parse_empty_and_whitespace():
    assert parse_cors_allowed_origins("") == []
    assert parse_cors_allowed_origins("   ") == []
    assert parse_cors_allowed_origins(", ,") == []


def test_parse_csv_strips_and_dedupes():
    raw = " https://a.example/ ,https://b.example, https://a.example "
    assert parse_cors_allowed_origins(raw) == [
        "https://a.example",
        "https://b.example",
    ]


def test_parse_rejects_star_and_flags_it():
    origins, star = parse_cors_allowed_origins_detailed(
        "*,https://ok.example, *"
    )
    assert origins == ["https://ok.example"]
    assert star is True


def test_is_origin_allowed_normalizes_trailing_slash():
    allowed = ["https://metakavita.home.local.ltd"]
    assert is_origin_allowed("https://metakavita.home.local.ltd/", allowed)
    assert is_origin_allowed("https://metakavita.home.local.ltd", allowed)
    assert not is_origin_allowed("https://evil.example", allowed)
    assert not is_origin_allowed(None, allowed)
    assert not is_origin_allowed("https://ok.example", [])


def _build_cors_test_app(allowed_origins):
    """Mini-app Flask reproduisant le middleware CORS de app.py (sans SocketIO)."""
    from cors_config import is_origin_allowed as _allowed
    from flask import request, make_response

    test_app = Flask(__name__)
    test_app.config["TESTING"] = True

    def apply_cors(response):
        origin = request.headers.get("Origin")
        if not _allowed(origin, allowed_origins):
            return response
        response.headers["Access-Control-Allow-Origin"] = origin.strip().rstrip("/")
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Requested-With"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers.add("Vary", "Origin")
        return response

    @test_app.before_request
    def handle_preflight():
        if request.method != "OPTIONS":
            return None
        if not _allowed(request.headers.get("Origin"), allowed_origins):
            return None
        return apply_cors(make_response(("", 204)))

    @test_app.after_request
    def add_headers(response):
        return apply_cors(response)

    @test_app.route("/api/ping")
    def ping():
        return jsonify(ok=True)

    return test_app


def test_cors_headers_for_whitelisted_origin():
    app = _build_cors_test_app(["https://metakavita.home.local.ltd"])
    client = app.test_client()
    res = client.get(
        "/api/ping",
        headers={"Origin": "https://metakavita.home.local.ltd"},
    )
    assert res.status_code == 200
    assert res.headers.get("Access-Control-Allow-Origin") == "https://metakavita.home.local.ltd"
    assert res.headers.get("Access-Control-Allow-Credentials") == "true"


def test_cors_headers_absent_for_unknown_origin():
    app = _build_cors_test_app(["https://metakavita.home.local.ltd"])
    client = app.test_client()
    res = client.get(
        "/api/ping",
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 200
    assert "Access-Control-Allow-Origin" not in res.headers


def test_cors_headers_absent_when_whitelist_empty():
    app = _build_cors_test_app([])
    client = app.test_client()
    res = client.get(
        "/api/ping",
        headers={"Origin": "https://metakavita.home.local.ltd"},
    )
    assert "Access-Control-Allow-Origin" not in res.headers


def test_cors_preflight_options():
    app = _build_cors_test_app(["https://metakavita.home.local.ltd"])
    client = app.test_client()
    res = client.open(
        "/api/ping",
        method="OPTIONS",
        headers={
            "Origin": "https://metakavita.home.local.ltd",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res.status_code == 204
    assert res.headers.get("Access-Control-Allow-Origin") == "https://metakavita.home.local.ltd"
    assert "POST" in res.headers.get("Access-Control-Allow-Methods", "")
