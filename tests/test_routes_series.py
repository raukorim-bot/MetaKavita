"""
Test bout-en-bout (route Flask réelle -> db_manager -> SQLite temporaire) du
bug historique de `/save-override` : `publisher_pref` était lu depuis le
formulaire mais jamais transmis à la couche de persistance, et disparaissait
donc silencieusement à chaque sauvegarde d'override.
"""


def test_save_override_persists_publisher_pref_original(client, isolated_db):
    response = client.post("/save-override", data={
        "series_id": "42",
        "forced_id": "12345",
        "alternative_title": "One Piece VF",
        "forced_provider": "ANILIST",
        "targeted_fields": "summary,cover",
        "publisher_pref": "ORIGINAL",
    })

    assert response.status_code == 200

    cached = isolated_db.get_all_cached_data()
    assert 42 in cached
    assert cached[42]["publisher_pref"] == "ORIGINAL"
    assert cached[42]["forced_id"] == "12345"
    assert cached[42]["alternative_title"] == "One Piece VF"
    assert cached[42]["forced_provider"] == "ANILIST"
    assert cached[42]["targeted_fields"] == "summary,cover"


def test_save_override_defaults_publisher_pref_to_global_when_omitted(client, isolated_db):
    response = client.post("/save-override", data={"series_id": "7"})

    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()
    assert cached[7]["publisher_pref"] == "GLOBAL"


def test_toggle_ignore_flips_status(client, isolated_db):
    response = client.post("/toggle-ignore", data={"series_id": "5", "current_status": "PENDING"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "new_status": "IGNORED"}

    response = client.post("/toggle-ignore", data={"series_id": "5", "current_status": "IGNORED"})
    assert response.get_json()["new_status"] == "PENDING"
