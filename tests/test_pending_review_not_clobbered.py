"""
Un re-scrape non demandé ne doit pas détruire une review manuelle en cours.

Chemin du bug : le batch avec sélection explicite (`routes/sync.py`) et le
webhook Kavita n'excluent pas les séries en `PENDING_REVIEW`. La garde de
`enrich_series` ne sautait la série que si Kavita avait déjà un `summary` — or
une série est justement en review parce qu'elle n'en a pas. Le mode manuel parke
alors une review vide AVANT même de scraper (`begin_streaming_review`), et
`park_pending_review` supprime toute review existante de la série : l'utilisateur
qui avait la modale ouverte recevait « Review introuvable » au moment de
confirmer, son travail remplacé par une review au nouvel identifiant.

Le re-scrape volontaire (bouton de la série, `force=true`, Companion) reste lui
un remplacement légitime : c'est `force_update` qui les distingue.
"""

from __future__ import annotations

import services.manual_review as mr
from kavita_api import KavitaAPI
from services import enrichment_engine

_PREVIEW = {
    "title": "Vinland Saga",
    "summary": "Résumé choisi par l'utilisateur",
    "year": 2005,
    "genres": "Seinen",
    "tags": "",
    "publisher": "Kodansha",
    "staff": "Yukimura",
    "cover_url": "",
    "localized_name": "",
    "status": "",
    "age_rating": "",
    "format": "",
}


def _config(**overrides):
    cfg = {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "fake",
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "MANUAL_REVIEW_MODE": True,
        "PROVIDER_1": "NONE",
        "PROVIDER_2": "NONE",
        "PROVIDER_3": "NONE",
        "SMART_COMPLETION": False,
        "SMART_SCORING": False,
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    }
    cfg.update(overrides)
    return cfg


def _park_review_in_progress(series_id=555):
    """Review déjà pointée par l'utilisateur (panneau d'édition ouvert)."""
    return mr.create_confirm_from_auto(
        series_id,
        "Vinland Saga",
        {"title": "Vinland Saga", "summary": "Résumé choisi par l'utilisateur"},
        _PREVIEW,
        actual_provider="MANGAUPDATES",
        chosen_score=0.87,
        query="Vinland Saga",
    )


def _patch_kavita(mocker, isolated_db, **config_overrides):
    scrapes = []

    def _fake_fetch(query, providers_list, *args, **kwargs):
        scrapes.append(query)
        card = {
            "provider": "ANILIST",
            "title": "Vinland Saga",
            "summary": "Autre résumé",
            "genres": [],
            "tags": [],
            "staff": [],
            "_match_score": 0.9,
        }
        return {"above": [card], "below": [], "query": query}, ["ANILIST"]

    mocker.patch.object(
        enrichment_engine, "load_config", return_value=_config(**config_overrides)
    )
    mocker.patch.object(
        enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data
    )
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("metadata_fetcher.fetch_metadata", side_effect=_fake_fetch)
    # Le park final traduit les résumés candidats : pas d'appel DeepL réel ici.
    mocker.patch.object(mr, "translate_candidate_summaries", side_effect=lambda p: (p, 0))
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    # Série en review : pas de résumé côté Kavita, c'est le cas typique.
    mocker.patch.object(
        KavitaAPI,
        "get_series_metadata",
        return_value={"seriesId": 555, "summary": "", "genres": [], "tags": []},
    )
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_cached_library_id", return_value=1)
    mocker.patch.object(
        KavitaAPI,
        "get_series_deep_metadata",
        return_value={
            "isbn": None, "authors": [], "publisher": None, "year": None,
            "genres": [], "localized_name": None,
        },
    )
    return scrapes


def test_un_batch_non_force_ne_detruit_pas_une_review_en_cours(isolated_db, mocker):
    rid = _park_review_in_progress()
    scrapes = _patch_kavita(mocker, isolated_db)

    ok, msg, used = enrichment_engine.enrich_series(555, "Vinland Saga", force_update=False)

    assert ok is True
    assert msg == "PENDING_REVIEW"
    assert scrapes == [], "la série parquée a été re-scrapée sans qu'on le demande"
    row = isolated_db.get_pending_review(rid)
    assert row is not None, "la review en cours d'examen a été supprimée"
    assert row["state"] == "awaiting_confirm"
    assert isolated_db.count_pending_reviews() == 1
    preview = __import__("json").loads(row["preview_json"])
    assert preview["summary"] == "Résumé choisi par l'utilisateur"


def test_une_review_en_attente_de_choix_est_aussi_protegee(isolated_db, mocker):
    """Même sans travail déjà saisi, la modale ouverte pointe cet identifiant."""
    rid = mr.create_review_from_candidates(
        555,
        "Vinland Saga",
        {
            "above": [{"provider": "MAL", "score": 0.9, "title": "Vinland Saga", "data": {}}],
            "below": [],
            "query": "Vinland Saga",
        },
    )
    _patch_kavita(mocker, isolated_db)

    ok, msg, used = enrichment_engine.enrich_series(555, "Vinland Saga", force_update=False)

    assert (ok, msg) == (True, "PENDING_REVIEW")
    assert isolated_db.get_pending_review(rid) is not None


def test_un_re_scrape_volontaire_remplace_toujours_la_review(isolated_db, mocker):
    """Bouton de la série / webhook `force=true` : le remplacement est demandé."""
    rid = _park_review_in_progress()
    scrapes = _patch_kavita(mocker, isolated_db)

    ok, msg, used = enrichment_engine.enrich_series(555, "Vinland Saga", force_update=True)

    assert (ok, msg) == (True, "PENDING_REVIEW")
    assert scrapes, "un scrape forcé doit bien repartir"
    assert isolated_db.get_pending_review(rid) is None
    assert isolated_db.count_pending_reviews() == 1, "une seule review par série"


def test_le_remplacement_dune_review_non_resolue_laisse_une_trace(isolated_db, caplog):
    """Dernier filet : si un appelant remplace malgré tout une review non
    résolue, la perte ne doit pas être silencieuse."""
    rid = _park_review_in_progress(606)

    with caplog.at_level("WARNING"):
        isolated_db.park_pending_review(
            "nouvelle-review",
            606,
            "Vinland Saga",
            {"above": [], "below": [], "query": "Vinland Saga"},
        )

    assert isolated_db.get_pending_review(rid) is None
    assert isolated_db.get_pending_review("nouvelle-review") is not None
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "606" in messages and "awaiting_confirm" in messages, (
        "aucune trace du remplacement d'une review non résolue"
    )
