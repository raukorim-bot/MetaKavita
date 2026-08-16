"""
Non-régression : `/api/series/<id>/update-cover` (choix manuel d'une couverture,
voir routes/series.py::apply_series_cover) marque la provenance manuelle de la
couverture (`cover_manual`) pour la protéger d'un futur scraping automatique.

Deux effets de bord historiques sont couverts ici.

1. Le statut. La protection passait par `save_series_override()`, qui force
   TOUJOURS `status='PENDING'` en base (comportement voulu pour
   `/save-override`, où l'utilisateur fournit justement un meilleur indice pour
   relancer la recherche). Réutilisé tel quel par `apply_series_cover()`, cet
   effet de bord réinitialisait silencieusement le statut de la série :
   - une série IGNORED redevenait PENDING, donc réintégrée par le prochain
     auto-sync alors que l'utilisateur l'avait explicitement exclue ;
   - une série COMPLETED ou NOT_FOUND redevenait PENDING, faussant les
     statistiques et exposant la série à un re-scraping inutile.

2. Les champs ciblés. La protection retirait `cover` de `targeted_fields`, donc
   décochait une case dans la config de l'utilisateur sans le dire. C65 déplace
   la protection sur une colonne de provenance dédiée : `targeted_fields` doit
   désormais rester intact.
"""


def _seed_series(isolated_db, series_id, status, targeted_fields="ALL"):
    from models import SeriesOverride
    isolated_db.save_series_override(SeriesOverride(series_id=series_id, targeted_fields=targeted_fields))
    isolated_db.update_status(series_id, status)


def test_apply_cover_preserves_ignored_status(client, isolated_db, mock_kavita_api):
    _seed_series(isolated_db, 101, "IGNORED")

    response = client.post(
        "/api/series/101/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True

    cached = isolated_db.get_all_cached_data()[101]
    assert cached["status"] == "IGNORED", "Un choix de couverture manuelle ne doit jamais désignorer une série"
    assert cached["cover_manual"] is True


def test_apply_cover_keeps_targeted_fields_intact(client, isolated_db, mock_kavita_api):
    """C65 : la protection ne décoche plus `cover` dans le granulaire."""
    _seed_series(isolated_db, 104, "COMPLETED", targeted_fields="ALL")

    response = client.post(
        "/api/series/104/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )

    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()[104]
    assert cached["targeted_fields"] == "ALL"
    assert cached["cover_manual"] is True


def test_release_cover_hands_it_back_to_automatic(client, isolated_db, mock_kavita_api):
    """Clic sur la cartouche : la couverture redevient réécrasable."""
    _seed_series(isolated_db, 105, "COMPLETED")
    client.post(
        "/api/series/105/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )
    assert isolated_db.get_all_cached_data()[105]["cover_manual"] is True

    response = client.post("/api/series/105/release-cover")

    assert response.status_code == 200
    assert response.get_json()["cover_manual"] is False
    cached = isolated_db.get_all_cached_data()[105]
    assert cached["cover_manual"] is False
    assert cached["status"] == "COMPLETED"


def test_apply_cover_preserves_completed_status(client, isolated_db, mock_kavita_api):
    _seed_series(isolated_db, 102, "COMPLETED")

    response = client.post(
        "/api/series/102/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )

    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()[102]
    assert cached["status"] == "COMPLETED"


def test_apply_cover_preserves_not_found_status(client, isolated_db, mock_kavita_api):
    _seed_series(isolated_db, 103, "NOT_FOUND")

    response = client.post(
        "/api/series/103/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )

    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()[103]
    assert cached["status"] == "NOT_FOUND"


def test_apply_cover_defaults_to_pending_when_series_never_cached(client, isolated_db, mock_kavita_api):
    """Cas limite : une série jamais vue par MetaKavita (aucune ligne en base)
    doit tomber sur 'PENDING' plutôt que planter sur un statut absent."""
    response = client.post(
        "/api/series/999/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )

    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()[999]
    assert cached["status"] == "PENDING"
    assert cached["cover_manual"] is True


def test_apply_cover_log_names_the_series(client, isolated_db, mock_kavita_api, caplog):
    """Live Logs doivent porter le titre et l'id, pas seulement [101]."""
    import logging
    from secure_logging import series_label

    caplog.set_level(logging.INFO)
    _seed_series(isolated_db, 101, "COMPLETED")
    response = client.post(
        "/api/series/101/update-cover",
        json={
            "cover_url": "https://example.com/cover.jpg",
            "series_name": "One Piece",
        },
    )
    assert response.status_code == 200
    assert series_label("One Piece", 101) in caplog.text
    assert "[101]" not in caplog.text or "« One Piece » (101)" in caplog.text


def test_release_cover_log_names_the_series(client, isolated_db, mock_kavita_api, caplog):
    import logging
    from secure_logging import series_label

    caplog.set_level(logging.INFO)
    _seed_series(isolated_db, 105, "COMPLETED")
    client.post(
        "/api/series/105/update-cover",
        json={"cover_url": "https://example.com/cover.jpg", "series_name": "Vinland Saga"},
    )
    response = client.post(
        "/api/series/105/release-cover",
        json={"series_name": "Vinland Saga"},
    )
    assert response.status_code == 200
    assert series_label("Vinland Saga", 105) in caplog.text


def test_apply_cover_log_falls_back_to_kavita_name(client, isolated_db, mock_kavita_api, caplog):
    """Sans series_name dans le POST, le titre vient de Kavita — jamais l'id nu."""
    import logging
    from secure_logging import series_label

    caplog.set_level(logging.INFO)
    response = client.post(
        "/api/series/999/update-cover",
        json={"cover_url": "https://example.com/cover.jpg"},
    )
    assert response.status_code == 200
    # mock_kavita_api.get_series rend toujours « Test Series »
    assert series_label("Test Series", 999) in caplog.text
