"""
Non-régression : KAVITA_HTTP_TIMEOUT (écritures Kavita, défaut 60s).
"""
from config_manager import _parse_positive_int, get_kavita_http_timeout


def test_parse_positive_int_default_on_invalid():
    assert _parse_positive_int("nope", default=60) == 60
    assert _parse_positive_int(None, default=60) == 60


def test_parse_positive_int_clamps_out_of_range():
    assert _parse_positive_int(2, default=60, minimum=5, maximum=600) == 60
    assert _parse_positive_int(9999, default=60, minimum=5, maximum=600) == 60


def test_parse_positive_int_accepts_valid():
    assert _parse_positive_int(90, default=60) == 90
    assert _parse_positive_int("120", default=60) == 120


def test_get_kavita_http_timeout_from_config_dict():
    assert get_kavita_http_timeout({"KAVITA_HTTP_TIMEOUT": 90}) == 90


def test_get_kavita_http_timeout_defaults_when_missing():
    assert get_kavita_http_timeout({}) == 60
