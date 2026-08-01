"""
Non-régression : bug historique de la route `/save-override` où `publisher_pref`
était extrait du formulaire mais jamais transmis à la persistance d'override,
et disparaissait donc silencieusement du cache local (voir CHANGELOG).

Ces tests verrouillent le comportement de persistance de db_manager.py
indépendamment de la couche HTTP (voir test_routes_series.py pour le test
bout-en-bout via la vraie route Flask).
"""
from models import SeriesOverride


def test_save_series_override_roundtrip_persists_publisher_pref(isolated_db):
    override = SeriesOverride(
        series_id=42,
        forced_id="12345",
        alternative_title="Alt Title",
        forced_provider="ANILIST",
        targeted_fields="summary,cover",
        publisher_pref="ORIGINAL",
    )

    isolated_db.save_series_override(override)

    cached = isolated_db.get_all_cached_data()
    assert 42 in cached
    entry = cached[42]
    assert entry["forced_id"] == "12345"
    assert entry["alternative_title"] == "Alt Title"
    assert entry["forced_provider"] == "ANILIST"
    assert entry["targeted_fields"] == "summary,cover"
    assert entry["publisher_pref"] == "ORIGINAL"


def test_save_series_override_named_fields_persists_publisher_pref(isolated_db):
    """Named SeriesOverride fields (vs historical positional args) must all
    round-trip, including publisher_pref — the field that was silently dropped."""
    isolated_db.save_series_override(SeriesOverride(
        series_id=7,
        forced_id="",
        alternative_title="",
        forced_provider="AUTO",
        targeted_fields="ALL",
        publisher_pref="ORIGINAL",
    ))

    cached = isolated_db.get_all_cached_data()
    assert cached[7]["publisher_pref"] == "ORIGINAL"


def test_save_series_override_update_preserves_new_publisher_pref(isolated_db):
    """Un deuxième appel sur la même série doit bien écraser publisher_pref
    (ON CONFLICT DO UPDATE) et non le laisser sur son ancienne valeur."""
    isolated_db.save_series_override(SeriesOverride(series_id=1, publisher_pref="GLOBAL"))
    isolated_db.save_series_override(SeriesOverride(series_id=1, publisher_pref="ORIGINAL"))

    cached = isolated_db.get_all_cached_data()
    assert cached[1]["publisher_pref"] == "ORIGINAL"


def test_default_publisher_pref_is_global(isolated_db):
    isolated_db.save_series_override(SeriesOverride(series_id=99))

    cached = isolated_db.get_all_cached_data()
    assert cached[99]["publisher_pref"] == "GLOBAL"


def test_save_series_override_roundtrip_persists_alt_title_langs(isolated_db):
    override = SeriesOverride(
        series_id=42,
        publisher_pref="GLOBAL",
        alt_title_langs="en, ja-ro",
    )
    isolated_db.save_series_override(override)

    cached = isolated_db.get_all_cached_data()
    assert cached[42]["alt_title_langs"] == "en, ja-ro"


def test_save_series_override_persists_alt_title_langs(isolated_db):
    isolated_db.save_series_override(SeriesOverride(
        series_id=8,
        forced_id="",
        alternative_title="",
        forced_provider="AUTO",
        targeted_fields="ALL",
        publisher_pref="GLOBAL",
        alt_title_langs="ja",
    ))
    assert isolated_db.get_all_cached_data()[8]["alt_title_langs"] == "ja"


def test_default_alt_title_langs_is_empty(isolated_db):
    isolated_db.save_series_override(SeriesOverride(series_id=11))
    assert isolated_db.get_all_cached_data()[11]["alt_title_langs"] == ""
