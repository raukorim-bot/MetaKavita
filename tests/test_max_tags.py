"""
Non-régression : MAX_TAGS (plafond de tags poussés vers Kavita, défaut 15).
Pas d'UI — env / config.json uniquement.
"""
from config_manager import get_max_tags


def test_get_max_tags_from_config_dict():
    assert get_max_tags({"MAX_TAGS": 25}) == 25


def test_get_max_tags_defaults_when_missing():
    assert get_max_tags({}) == 15


def test_get_max_tags_clamps_out_of_range():
    assert get_max_tags({"MAX_TAGS": 0}) == 15
    assert get_max_tags({"MAX_TAGS": 101}) == 15
    assert get_max_tags({"MAX_TAGS": "nope"}) == 15


def test_get_max_tags_accepts_string():
    assert get_max_tags({"MAX_TAGS": "30"}) == 30


def test_tag_list_truncation_matches_helper():
    """Miroir du slice utilisé dans enrichment_engine + scrapers."""
    tags = [f"tag-{i}" for i in range(40)]
    limit = get_max_tags({"MAX_TAGS": 12})
    assert tags[:limit] == tags[:12]
    assert len(tags[:get_max_tags({"MAX_TAGS": 15})]) == 15
