"""
`static/js/websocket.js` devinait le badge live d'une série en testant des
mots-clés TRADUITS dans le texte brut du log ("réussi", "déjà à jour",
"introuvable", "PENDING_REVIEW"...) — fragile, et desynchronisable de la vraie
langue des logs ou d'un wording qui change. `services/enrichment_engine.py`
émet désormais `_emit_series_status(series_id, status, series_name)` pour
CHAQUE issue d'`enrich_series`, exactement comme il le faisait déjà pour
COMPLETED/NEEDS_RELOCK (voir `services/kavita_payload.py`). Ces tests
verrouillent les émissions qui manquaient : NOT_FOUND, PENDING_REVIEW, et le
court-circuit "déjà à jour".
"""
from services import enrichment_engine
from kavita_api import KavitaAPI

from test_comic_flexible import _base_config, _patch_kavita_basics, _ComicFake, _MangaFake


def test_not_found_emits_a_typed_series_status(mocker, isolated_db):
    """Bibliothèque Flexible : Comic ET le fallback Manga ratent tous les deux —
    doit finir en NOT_FOUND et émettre le statut typé correspondant."""
    mocker.patch.object(enrichment_engine, "load_config", return_value=_base_config())
    _patch_kavita_basics(mocker, isolated_db)
    emit = mocker.patch.object(enrichment_engine, "_emit_series_status")

    comic = _ComicFake()
    manga = _MangaFake()

    def _get(pid):
        return {"COMIC_FAKE": comic, "MANGA_FAKE": manga}.get(pid)

    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=_get)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[comic])
    mocker.patch("metadata_fetcher.fetch_metadata", return_value=(None, []))

    ok, msg, used = enrichment_engine.enrich_series(50, "Nowhere Series", force_update=True)

    assert ok is False
    assert msg == "Introuvable."
    emit.assert_called_once_with(50, "NOT_FOUND", "Nowhere Series")


def test_pending_review_emits_a_typed_series_status_in_manual_mode(mocker, isolated_db):
    def _fake_fetch(query, providers_list, *args, **kwargs):
        card = {
            "provider": "MANGA_FAKE",
            "title": "One Piece",
            "summary": "Pirate king",
            "genres": ["Action"],
            "tags": [],
            "staff": [],
            "_match_score": 0.9,
        }
        return {"above": [card], "below": [], "query": query}, ["MANGA_FAKE"]

    mocker.patch.object(
        enrichment_engine, "load_config",
        return_value=_base_config(MANUAL_REVIEW_MODE=True),
    )
    _patch_kavita_basics(mocker, isolated_db)
    emit = mocker.patch.object(enrichment_engine, "_emit_series_status")

    comic = _ComicFake()
    manga = _MangaFake()

    def _get(pid):
        return {"COMIC_FAKE": comic, "MANGA_FAKE": manga}.get(pid)

    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=_get)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[comic])
    mocker.patch("metadata_fetcher.fetch_metadata", side_effect=_fake_fetch)
    mocker.patch("services.manual_review.create_review_from_candidates")

    ok, msg, used = enrichment_engine.enrich_series(51, "One Piece", force_update=True)

    assert ok is True
    assert msg == "PENDING_REVIEW"
    emit.assert_called_once_with(51, "PENDING_REVIEW", "One Piece")


def test_already_up_to_date_emits_a_typed_completed_status(mocker, isolated_db):
    """Court-circuit « déjà à jour » (résumé Kavita déjà présent, pas de
    force_update) : ne passe jamais par `apply_kavita_payload`, donc n'aurait
    jamais émis de `series_status` sans ce fix — le badge live restait bloqué
    sur l'ancien statut jusqu'au prochain rechargement de page."""
    mocker.patch.object(enrichment_engine, "load_config", return_value=_base_config())
    _patch_kavita_basics(mocker, isolated_db)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "Already has a summary", "genres": [], "tags": [], "webLinks": "", "language": "",
    })
    emit = mocker.patch.object(enrichment_engine, "_emit_series_status")

    ok, msg, used = enrichment_engine.enrich_series(52, "Already Done", force_update=False)

    assert ok is True
    assert msg == "Déjà à jour."
    emit.assert_called_once_with(52, "COMPLETED", "Already Done")
