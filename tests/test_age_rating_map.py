"""
BF53 — AGE_RATING_MAP doit viser l'enum Kavita réel, pas les content ratings
MangaDex (1–4). Avant le hotfix v1.6.2, safe→1 / suggestive→2 / erotica→3 /
pornographic→4 écrivaient Rating Pending / Early Childhood / Everyone / G,
avec ageRatingLocked=True — ce qui contournait les age restrictions Kavita.
"""
from kavita_constants import AGE_RATING_MAP


# Entiers Kavita (AgeRating.cs / GET /api/metadata/age-ratings).
_EVERYONE = 3
_TEEN = 8
_R18_PLUS = 12
_X18_PLUS = 14

# Anciennes valeurs dangereuses (MangaDex-shaped) — ne doivent plus apparaître.
_LEGACY_WRONG = {1, 2, 4}  # Rating Pending, Early Childhood, G


def test_age_rating_map_targets_kavita_enum():
    assert AGE_RATING_MAP["safe"] == _EVERYONE
    assert AGE_RATING_MAP["suggestive"] == _TEEN
    assert AGE_RATING_MAP["erotica"] == _R18_PLUS
    assert AGE_RATING_MAP["pornographic"] == _X18_PLUS


def test_age_rating_map_rejects_legacy_mangadex_ints():
    mapped = set(AGE_RATING_MAP.values())
    assert mapped.isdisjoint(_LEGACY_WRONG)


def test_age_rating_map_keys_are_scraper_contract():
    assert set(AGE_RATING_MAP) == {"safe", "suggestive", "erotica", "pornographic"}
