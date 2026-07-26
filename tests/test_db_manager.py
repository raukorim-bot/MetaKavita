"""
Non-régression : bug historique de la route `/save-override` où `publisher_pref`
était extrait du formulaire mais jamais transmis à `save_forced_overrides()`,
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


def test_save_forced_overrides_backward_compatible_wrapper_persists_publisher_pref(isolated_db):
    """save_forced_overrides() est l'API historique (arguments positionnels),
    conservée pour les appelants existants (ex: debug_concurrency.py). Elle doit
    rester un simple adaptateur vers save_series_override() et donc persister
    tous les champs, y compris publisher_pref."""
    isolated_db.save_forced_overrides(
        series_id=7,
        forced_id="",
        alt_title="",
        forced_provider="AUTO",
        targeted_fields="ALL",
        publisher_pref="ORIGINAL",
    )

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
