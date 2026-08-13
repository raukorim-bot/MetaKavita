"""Tests filtre bibliothèques Kavita (DISABLED_LIBRARIES)."""
from unittest.mock import MagicMock, patch

from config_manager import (
    parse_library_id_list,
    get_disabled_library_ids,
    is_library_enabled,
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


def test_denylist_filters_via_is_library_enabled():
    cfg = {"DISABLED_LIBRARIES": "2,5"}
    assert is_library_enabled(1, cfg) is True
    assert is_library_enabled(2, cfg) is False
    assert is_library_enabled("5", cfg) is False
    assert is_library_enabled(None, cfg) is True
    assert is_library_enabled("", cfg) is True


def test_get_all_series_never_filters_disabled_libraries():
    """Couche API neutre : dashboard / batch / export voient tout, dénylist ignorée."""
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita.test", "key")
    api.token = "fake"
    libs = [
        {"id": 1, "name": "Manga", "type": 0},
        {"id": 2, "name": "Comics", "type": 1},
    ]
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = [
        {"id": 10, "name": "A", "libraryId": 1},
        {"id": 20, "name": "B", "libraryId": 2},
    ]

    with patch.object(api, "get_libraries", return_value=libs):
        with patch("kavita_api.requests.post", return_value=mock_res) as post:
            with patch("config_manager.get_disabled_library_ids") as denylist:
                series = api.get_all_series()

    assert {s["id"] for s in series} == {10, 20}
    # Un seul appel pour tout l'inventaire : `SeriesFilterV2Dto` n'a pas de
    # `libraryId`, donc un appel par bibliothèque rendait N fois le même catalogue.
    post.assert_called_once()
    denylist.assert_not_called()
    assert {s["id"]: s["libraryId"] for s in series} == {10: 1, 20: 2}
    assert {s["id"]: s["libraryType"] for s in series} == {10: "Manga", 20: "ComicFlexible"}


def test_get_all_series_asks_for_the_whole_catalog_once_and_sorts_locally():
    """Le corps `{"libraryId": …}` qu'on postait n'existe pas sur
    `SeriesFilterV2Dto` : System.Text.Json l'ignorait et `all-v2` rendait tout le
    catalogue visible, une fois par bibliothèque. Le filtre explicite doit donc
    s'appliquer localement, sur `SeriesDto.libraryId`, sans prétendre filtrer côté
    serveur."""
    from kavita_api import KavitaAPI

    api = KavitaAPI("http://kavita.test", "key")
    api.token = "fake"
    libs = [
        {"id": 1, "name": "Manga", "type": 0},
        {"id": 2, "name": "Comics", "type": 1},
    ]
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = [
        {"id": 10, "name": "A", "libraryId": 1},
        {"id": 99, "name": "X", "libraryId": 2},
    ]

    with patch.object(api, "get_libraries", return_value=libs):
        with patch("kavita_api.requests.post", return_value=mock_res) as post:
            series = api.get_all_series(library_id=2)
            assert [s["id"] for s in series] == [99]
            post.assert_called_once()
            assert post.call_args.kwargs["json"] == {}
    # Inventaire partiel : jamais un feu vert pour purger le cache d'orphelines.
    assert api.last_inventory_complete is False


def test_auto_sync_candidates_skip_disabled_libraries():
    """Seul chemin filtré : le polling auto-sync."""
    from services.background_tasks import select_auto_sync_candidates

    all_series = [
        {"id": 10, "name": "A", "libraryId": 1},
        {"id": 20, "name": "B", "libraryId": 2},
    ]
    candidates = select_auto_sync_candidates(
        all_series, cached={}, config={"DISABLED_LIBRARIES": "2"}
    )
    assert [s["id"] for s in candidates] == [10]


def test_auto_sync_candidates_keep_new_and_pending_only():
    from services.background_tasks import select_auto_sync_candidates

    all_series = [
        {"id": 10, "name": "New", "libraryId": 1},
        {"id": 20, "name": "Pending", "libraryId": 1},
        {"id": 30, "name": "Done", "libraryId": 1},
    ]
    cached = {20: {"status": "PENDING"}, 30: {"status": "COMPLETED"}}
    candidates = select_auto_sync_candidates(
        all_series, cached, config={"DISABLED_LIBRARIES": ""}
    )
    assert [s["id"] for s in candidates] == [10, 20]
