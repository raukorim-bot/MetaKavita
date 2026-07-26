"""
Non-régression : KAVITA_EXTERNAL_URL (URL publique UI) vs KAVITA_URL (API).

En Docker, l'API peut viser http://kavita:5000 (réseau interne) tandis que les
liens navigateur doivent ouvrir https://kavita.domain.tld. Si EXTERNAL est vide,
repli historique sur KAVITA_URL.
"""
from config_manager import get_kavita_ui_url


def test_kavita_ui_url_prefers_external():
    assert get_kavita_ui_url({
        "KAVITA_URL": "http://kavita:5000",
        "KAVITA_EXTERNAL_URL": "https://kavita.domain.tld",
    }) == "https://kavita.domain.tld"


def test_kavita_ui_url_strips_trailing_slash():
    assert get_kavita_ui_url({
        "KAVITA_URL": "http://kavita:5000/",
        "KAVITA_EXTERNAL_URL": "https://kavita.domain.tld/",
    }) == "https://kavita.domain.tld"


def test_kavita_ui_url_falls_back_to_internal_when_external_empty():
    assert get_kavita_ui_url({
        "KAVITA_URL": "http://kavita:5000",
        "KAVITA_EXTERNAL_URL": "",
    }) == "http://kavita:5000"


def test_kavita_ui_url_falls_back_when_external_missing():
    assert get_kavita_ui_url({
        "KAVITA_URL": "https://kavita.example",
    }) == "https://kavita.example"


def test_kavita_ui_url_empty_config():
    assert get_kavita_ui_url({}) == ""
