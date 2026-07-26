"""
Non-régression : `/api/series/<id>/update-cover` (choix manuel d'une couverture,
voir routes/series.py::apply_series_cover) appelle `save_series_override()` pour
retirer 'cover' de `targeted_fields` et protéger ce choix contre un futur
scraping automatique (voir tests/test_scoring_threshold.py et CODE_REVIEW.md).

Or `save_series_override()` force TOUJOURS `status='PENDING'` en base (voir
db_manager.py — comportement voulu pour `/save-override`, où l'utilisateur
fournit justement un meilleur indice pour relancer la recherche). Réutilisé tel
quel par `apply_series_cover()`, cet effet de bord réinitialisait
silencieusement le statut de la série à chaque choix de couverture manuelle :

- une série IGNORED redevenait PENDING, donc réintégrée par le prochain
  auto-sync alors que l'utilisateur l'avait explicitement exclue ;
- une série COMPLETED ou NOT_FOUND redevenait PENDING, faussant les statistiques
  et exposant la série à un re-scraping inutile (voire à l'écrasement d'autres
  champs si un force_update survient entre-temps).

Le correctif restaure explicitement le statut d'origine juste après l'appel à
save_series_override().
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
    assert "cover" not in cached["targeted_fields"].split(",")


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
    assert "cover" not in cached["targeted_fields"].split(",")
