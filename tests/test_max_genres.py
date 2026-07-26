"""
Non-régression : MAX_GENRES (plafond de genres poussés vers Kavita, défaut 5).
Pas d'UI — env / config.json uniquement.
"""
from config_manager import get_max_genres


def test_get_max_genres_from_config_dict():
    assert get_max_genres({"MAX_GENRES": 10}) == 10


def test_get_max_genres_defaults_when_missing():
    assert get_max_genres({}) == 5


def test_get_max_genres_clamps_out_of_range():
    assert get_max_genres({"MAX_GENRES": 0}) == 5
    assert get_max_genres({"MAX_GENRES": 51}) == 5
    assert get_max_genres({"MAX_GENRES": "nope"}) == 5


def test_get_max_genres_accepts_string():
    assert get_max_genres({"MAX_GENRES": "8"}) == 8


def test_genre_list_truncation_matches_helper():
    """Miroir du slice utilisé dans les scrapers (genres[:get_max_genres()])."""
    genres = [f"genre-{i}" for i in range(20)]
    limit = get_max_genres({"MAX_GENRES": 3})
    assert genres[:limit] == genres[:3]
    assert len(genres[:get_max_genres({"MAX_GENRES": 5})]) == 5


def test_engine_genre_payload_slice_mirrors_helper():
    """Miroir du slice enrichment_engine : genres[:get_max_genres(config)]."""
    genres = [f"g-{i}" for i in range(12)]
    config = {"MAX_GENRES": 4}
    payload = [{"id": 0, "title": g} for g in genres[:get_max_genres(config)]]
    assert len(payload) == 4
    assert payload[-1]["title"] == "g-3"
