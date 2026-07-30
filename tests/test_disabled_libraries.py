"""Tests filtre bibliothèques Kavita (DISABLED_LIBRARIES)."""
from unittest.mock import MagicMock, patch

from config_manager import (
    parse_library_id_list,
    get_disabled_library_ids,
    is_library_enabled,
    filter_enabled_libraries,
    format_disabled_libraries,
)


def test_parse_library_id_list_empty():
    assert parse_library_id_list("") == set()
    assert parse_library_id_list(None) == set()
    assert parse_library_id_list("  ") == set()


def test_parse_library_id_list_variants():
    assert parse_library_id_list("1,3,5") == {"1", "3", "5"}
    assert parse_library_id_list("1; 3 ;5") == {"1", "3", "5"}
    assert parse_library_id_list([1, "2", 3]) == {"1", "2", "3"}


def test_format_disabled_libraries_sorts_numerically():
    assert format_disabled_libraries({"10", "2", "1"}) == "1,2,10"


def test_empty_denylist_enables_all():
    cfg = {"DISABLED_LIBRARIES": ""}
    assert get_disabled_library_ids(cfg) == set()
    assert is_library_enabled(1, cfg) is True
    assert is_library_enabled("99", cfg) is True
    libs = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    assert filter_enabled_libraries(libs, cfg) == libs


def test_denylist_filters_libraries():
    cfg = {"DISABLED_LIBRARIES": "2,5"}
    assert is_library_enabled(1, cfg) is True
    assert is_library_enabled(2, cfg) is False
    assert is_library_enabled("5", cfg) is False
    libs = [
        {"id": 1, "name": "Manga"},
        {"id": 2, "name": "Comics"},
        {"id": 5, "name": "Books"},
    ]
    enabled = filter_enabled_libraries(libs, cfg)
    assert [lib["id"] for lib in enabled] == [1]


def test_heal_total_library_denylist_resets_when_all_disabled(tmp_path, monkeypatch):
    """Wipe accidentel : denylist == tous les IDs → reset + save."""
    import config_manager as cm

    monkeypatch.setattr(cm, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cm, "CONFIG_FILE", str(tmp_path / "config.json"))
    cm.save_config({
        "SECRET_KEY": "s",
        "WEBHOOK_TOKEN": "w",
        "DISABLED_LIBRARIES": "1,2,3",
    })
    config = cm.load_config()
    libs = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}]

    healed_cfg, healed = cm.heal_total_library_denylist(config, libs)
    assert healed is True
    assert healed_cfg["DISABLED_LIBRARIES"] == ""
    assert cm.get_disabled_library_ids(healed_cfg) == set()
    on_disk = cm.load_config()
    assert not (on_disk.get("DISABLED_LIBRARIES") or "").strip()


def test_heal_total_library_denylist_skips_partial_denylist(tmp_path, monkeypatch):
    import config_manager as cm

    monkeypatch.setattr(cm, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cm, "CONFIG_FILE", str(tmp_path / "config.json"))
    cm.save_config({
        "SECRET_KEY": "s",
        "WEBHOOK_TOKEN": "w",
        "DISABLED_LIBRARIES": "2",
    })
    config = cm.load_config()
    libs = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}]

    healed_cfg, healed = cm.heal_total_library_denylist(config, libs)
    assert healed is False
    assert cm.get_disabled_library_ids(healed_cfg) == {"2"}


def test_get_all_series_skips_disabled_library():
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita.test", "key")
    api.token = "fake"
    libs = [
        {"id": 1, "name": "Manga", "type": 0},
        {"id": 2, "name": "Comics", "type": 1},
    ]

    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = [{"id": 10, "name": "Serie A", "libraryId": 1}]

    with patch.object(api, "get_libraries", return_value=libs):
        with patch("kavita_api.filter_enabled_libraries", side_effect=lambda libs, config=None: [libs[0]]):
            with patch("kavita_api.is_library_enabled", return_value=True):
                with patch("kavita_api.requests.post", return_value=mock_res) as post:
                    series = api.get_all_series()
                    assert len(series) == 1
                    assert series[0]["id"] == 10
                    post.assert_called_once()
                    assert post.call_args.kwargs["json"]["libraryId"] == 1


def test_get_all_series_explicit_disabled_id_returns_empty():
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita.test", "key")
    api.token = "fake"

    with patch.object(api, "get_libraries", return_value=[{"id": 2, "name": "Comics", "type": 1}]):
        with patch("kavita_api.filter_enabled_libraries", return_value=[]):
            with patch("kavita_api.is_library_enabled", return_value=False):
                assert api.get_all_series(library_id=2) == []


def test_get_all_series_respect_disabled_filter_false():
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita.test", "key")
    api.token = "fake"
    libs = [{"id": 2, "name": "Comics", "type": 1}]
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = [{"id": 99, "name": "X", "libraryId": 2}]

    with patch.object(api, "get_libraries", return_value=libs):
        with patch("kavita_api.requests.post", return_value=mock_res) as post:
            series = api.get_all_series(respect_disabled_filter=False)
            assert len(series) == 1
            post.assert_called_once()
