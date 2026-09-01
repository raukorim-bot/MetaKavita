"""Les séries qu'aucun fournisseur ne peut servir sont écartées avant l'appel.

Rien de ce qu'une cascade rend ne s'écrit sans clé d'appariement : l'index par
série, la cascade ISBN et la recherche titre + numéro indexent tous leurs
résultats, et sautent l'unité qui n'a pas de clé. Un one-shot — un fichier
unique, que Kavita range en feuille volante ou en hors-série — n'a pas de numéro
de tome. Il payait pourtant la recherche entière : jusqu'à deux minutes chez un
fournisseur HTML, un tour de cadence pour les suivants, et un aperçu vide connu
d'avance.

Restent deux bords à ne pas franchir :

* écarter une série dont on ne possède encore que le tome 1, qui est justement un
  cas où l'écriture par tome sert ;
* écarter un one-shot qui porte son ISBN, alors que l'ISBN désigne l'album avec
  plus de certitude qu'un numéro — il part par la cascade ISBN, et par elle
  seule, un index par série étant numéroté.
"""
from __future__ import annotations

import time

import pytest

from services.volume_enrichment import job
from services.volume_enrichment.matching import unmatchable_reason, units_from_volumes


def _units(volumes):
    return units_from_volumes(volumes)


# ===== Le prédicat, sans réseau ni base =====


def test_un_one_shot_range_en_hors_serie_est_ecarte():
    volumes = [{"id": 9, "minNumber": 100000,
                "chapters": [{"id": 1, "minNumber": -100000, "isSpecial": True}]}]

    assert unmatchable_reason(_units(volumes), "Le Photographe") == "oneshot"


def test_un_one_shot_range_en_feuille_volante_est_ecarte():
    """Le cas courant : « Titre.cbz » seul dans son dossier. Kavita met les deux
    sentinelles, il ne reste aucun numéro à confronter."""
    volumes = [{"id": 9, "minNumber": -100000, "chapters": [{"id": 1, "minNumber": -100000}]}]

    assert unmatchable_reason(_units(volumes), "Quai d'Orsay") == "oneshot"


def test_une_serie_qui_n_a_que_des_hors_serie_est_ecartee_aussi():
    """Même impasse, message différent : ce n'est pas un one-shot."""
    volumes = [
        {"id": 9, "minNumber": 100000, "chapters": [
            {"id": 1, "isSpecial": True}, {"id": 2, "isSpecial": True}, {"id": 3, "isSpecial": True},
        ]}
    ]

    assert unmatchable_reason(_units(volumes), "Artbooks") == "specials"


def test_une_serie_dont_on_ne_possede_que_le_tome_1_n_est_pas_ecartee():
    """La régression qu'il ne faut pas commettre : une collection en cours est
    pleine de séries à un seul tome, et c'est précisément là que l'écriture par
    tome a du travail. Un numéro suffit à décider — pas un compte d'unités."""
    volumes = [{"id": 9, "minNumber": 1, "chapters": [{"id": 101, "minNumber": 1}]}]

    assert unmatchable_reason(_units(volumes), "Blacksad") == ""


def test_une_serie_de_plusieurs_tomes_n_est_jamais_ecartee():
    volumes = [
        {"id": 9, "minNumber": n, "chapters": [{"id": 100 + n, "minNumber": n}]}
        for n in (1, 2, 3)
    ]

    assert unmatchable_reason(_units(volumes), "Blacksad") == ""


def test_une_serie_en_chapitres_n_est_pas_ecartee():
    """Les feuilles volantes portent de vrais numéros de chapitre : elles
    s'apparient, contrairement à la sentinelle."""
    volumes = [
        {"id": 9, "minNumber": -100000, "chapters": [
            {"id": 1, "minNumber": 1}, {"id": 2, "minNumber": 2},
        ]}
    ]

    assert unmatchable_reason(_units(volumes), "Berserk") == ""


def test_un_titre_ne_decide_jamais_rien():
    """Un nom n'est pas un identifiant. « One shot » dans un titre est aussi bien
    un nom de collection, et un recueil numéroté doit rester servi ; à l'inverse,
    une unité numérotée reste appariable quoi que dise son titre."""
    six_tomes = [
        {"id": 9, "minNumber": n, "chapters": [{"id": 100 + n, "minNumber": n}]}
        for n in range(1, 7)
    ]
    un_tome = [{"id": 9, "minNumber": 1,
                "chapters": [{"id": 101, "minNumber": 1, "titleName": "One shot"}]}]

    assert unmatchable_reason(_units(six_tomes), "Recueil de one shots") == ""
    assert unmatchable_reason(_units(un_tome), "Le Combat ordinaire (One-Shot)") == ""


def test_un_one_shot_qui_porte_son_isbn_n_est_pas_ecarte():
    """L'ISBN est une clé, et la plus sûre : il désigne une édition, là où un
    numéro suppose qu'on parle bien de la même série."""
    volumes = [{"id": 9, "minNumber": -100000, "chapters": [
        {"id": 1, "minNumber": -100000, "isbn": "9782800148519"}]}]

    assert unmatchable_reason(_units(volumes), "Quai d'Orsay") == ""


def test_un_hors_serie_a_isbn_reste_ecarte():
    """Un hors-série n'est jamais apparié — c'est la règle de `match_units`, et la
    décision prise avant l'appel doit porter sur le même ensemble, sans quoi on
    paierait une cascade ISBN pour des unités que l'appariement refusera."""
    volumes = [{"id": 9, "minNumber": 100000, "chapters": [
        {"id": 1, "isSpecial": True, "isbn": "9782800148519"}]}]

    assert unmatchable_reason(_units(volumes), "Artbook") == "oneshot"


def test_une_serie_sans_unite_ecrivable_n_est_pas_du_ressort_du_predicat():
    """Le chemin « aucun tome » existe déjà chez l'appelant, avec son propre
    message : le prédicat n'a pas à le doubler."""
    assert unmatchable_reason([], "Vide") == ""


# ===== Dans la passe : aucun appel réseau du tout =====


class FakeApi:
    def __init__(self, series, volumes):
        self.series = series
        self.volumes = volumes

    def get_all_series(self, library_id=None):
        return list(self.series)

    def get_series(self, sid):
        return next((s for s in self.series if s["id"] == sid), None)

    def get_library_type_for_series(self, sid):
        return "Comic"

    def get_series_volumes(self, sid):
        return self.volumes.get(sid, [])

    def fetch_series_volumes(self, sid):
        return self.volumes.get(sid, []), None

    def get_chapter(self, chapter_id):
        return {"id": chapter_id}

    def update_chapter_metadata(self, dto):
        raise AssertionError("un one-shot ne doit rien écrire")

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        raise AssertionError("un one-shot ne doit rien téléverser")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Une passe complète, dont tout appel fournisseur est une erreur."""
    import db_manager
    from services.volume_enrichment import index_cache

    index_cache.reset_cache()

    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "test.db"))
    db_manager.init_db()

    api = FakeApi(
        [{"id": 1, "name": "Quai d'Orsay"}],
        {1: [{"id": 9, "minNumber": -100000, "chapters": [{"id": 1, "minNumber": -100000}]}]},
    )
    appels = []

    def _interdit(*a, **kw):
        appels.append(a)
        raise AssertionError("aucun fournisseur ne doit être interrogé")

    monkeypatch.setattr("services.volume_enrichment.providers.fetch_index", _interdit)
    monkeypatch.setattr("services.volume_enrichment.providers.fetch_by_isbn", _interdit)
    monkeypatch.setattr("services.volume_enrichment.providers.fetch_by_title_volume", _interdit)
    monkeypatch.setattr(job, "load_config", lambda: {"KAVITA_URL": "u", "KAVITA_API_KEY": "k"})
    monkeypatch.setattr(job, "KavitaAPI", lambda url, key: api)
    monkeypatch.setattr(job, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(job, "credits_fetcher", lambda pid: None)
    monkeypatch.setattr(job, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(job, "list_enriched_series_ids", db_manager.list_enriched_series_ids)
    return api, db_manager, appels


def _wait_idle(timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not job.get_volume_enrich_state()["running"]:
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    with job._lock:
        job._state.update({"running": False, "cancelled": False, "done": 0, "total": 0})


def test_la_passe_traverse_un_one_shot_sans_interroger_personne(wired):
    _api, db_manager, appels = wired

    assert job.start_volume_enrich("all", series_ids=[1])["started"] is True
    assert _wait_idle(), "la passe doit se terminer"

    etat = job.get_volume_enrich_state()
    assert not appels, "aucun appel fournisseur ne devrait avoir eu lieu"
    assert etat["error"] is None
    assert etat["counts"]["nothing"] == 1
    assert etat["counts"]["done"] == 0
    # Close pour la reprise : la question est tranchée sans appel, il n'y a rien à
    # réessayer à la passe suivante.
    assert 1 in db_manager.list_enriched_series_ids()


def test_l_apercu_d_un_one_shot_repond_sans_attendre(wired):
    api, _db, appels = wired

    plan = job.build_series_plan(api, 1, config={})

    assert not appels
    assert plan["skipped_reason"] == "oneshot"
    assert plan["units"] == []
    assert plan["provider"] == ""
    assert plan["series_name"] == "Quai d'Orsay"


def test_un_one_shot_a_isbn_part_par_l_isbn_et_par_lui_seul(monkeypatch, wired):
    """La cascade ISBN, oui ; l'index par série, non — il est numéroté, il n'a
    rien à quoi s'apparier ici, et la recherche titre + numéro n'a pas de numéro
    à chercher. `fetch_index` reste donc l'appel interdit du test."""
    api, _db, appels = wired
    api.volumes[1] = [{"id": 9, "minNumber": -100000, "chapters": [
        {"id": 1, "minNumber": -100000, "isbn": "9782800148519"}]}]
    vus = []

    def _par_isbn(units, **kw):
        vus.append([u["chapter_id"] for u in units])
        return {"isbn:9782800148519": {"summary": "Le résumé de l'album"}}

    monkeypatch.setattr("services.volume_enrichment.providers.fetch_by_isbn", _par_isbn)

    plan = job.build_series_plan(api, 1, config={})

    assert not appels, "l'index par série ne devait pas être demandé"
    assert vus == [[1]]
    assert plan.get("skipped_reason") is None
    assert plan["provider"] == "ISBN"
    assert len(plan["units"]) == 1
    assert plan["units"][0]["changes"]["summary"]["proposed"] == "Le résumé de l'album"
    assert plan["units"][0]["matched_key"] == "isbn:9782800148519"
    # La colonne « Tome » ne doit pas afficher la clé : elle n'a pas de numéro.
    assert plan["units"][0]["matched_on"] is None


def test_deux_fichiers_du_meme_one_shot_sont_signales_comme_doublons(monkeypatch, wired):
    """Le marquage des doublons existe pour ce cas ; il fallait qu'il voie la clé
    ISBN, sinon deux fichiers d'un même album s'écrivaient deux fois en silence."""
    api, _db, _appels = wired
    api.volumes[1] = [{"id": 9, "minNumber": -100000, "chapters": [
        {"id": 1, "minNumber": -100000, "isbn": "9782800148519"},
        {"id": 2, "minNumber": -100000, "isbn": "9782800148519"},
    ]}]
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn",
        lambda units, **kw: {"isbn:9782800148519": {"summary": "Un"}},
    )

    plan = job.build_series_plan(api, 1, config={})

    assert plan["counts"]["duplicates"] == 2
    assert [u["duplicate_of"] for u in plan["units"]] == ["9782800148519"] * 2


def test_une_serie_appariable_continue_d_interroger_le_fournisseur(monkeypatch, wired):
    """Le raccourci ne doit pas devenir la règle : une série numérotée passe."""
    api, _db, appels = wired
    api.volumes[1] = [{"id": 9, "minNumber": 1, "chapters": [{"id": 101, "minNumber": 1}]}]
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: ("comicvine", {"1": {"summary": "Un"}}),
    )

    plan = job.build_series_plan(api, 1, config={})

    assert plan.get("skipped_reason") is None
    assert plan["provider"] == "comicvine"
    assert len(plan["units"]) == 1


def test_une_liste_d_unites_vide_ne_ferme_pas_l_index_par_serie(monkeypatch):
    """« L'appelant ne dit rien de la série » n'est pas « la série n'a pas de
    numéro ». Des outils et l'aperçu d'un seul tome appellent `resolve_index`
    sans unités, et c'est déjà la convention de `_covers_enough` : ne rien savoir
    ne doit pas court-circuiter l'index par série."""
    from services.volume_enrichment import providers as prov

    monkeypatch.setattr(prov, "fetch_index", lambda name, **kw: ("COMICVINE", {"1": {"summary": "Un"}}))
    monkeypatch.setattr(prov, "fetch_by_isbn", lambda units, **kw: {})

    assert prov.resolve_index("Saga", [], library_type="Comic")[0] == "COMICVINE"


# ===== Ce que l'interface en dit =====


def test_l_apercu_distingue_ce_vide_des_autres():
    """L'écriture est dans l'atelier : un one-shot ne doit pas se lire comme
    « le fournisseur n'a rien trouvé » ni comme des hors-série."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "volumes.js").read_text(
        encoding="utf-8"
    )

    assert "skipped_reason" in js
    assert "vol_preview_oneshot" in js
    assert "vol_preview_specials" in js


@pytest.mark.parametrize(
    "cle",
    ["vol_preview_oneshot", "vol_preview_oneshot_hint",
     "vol_preview_specials", "vol_preview_specials_hint"],
)
def test_les_messages_existent_dans_les_deux_langues(cle):
    from translations import translations

    for lang in ("fr", "en"):
        assert translations[lang].get(cle), f"{lang} : {cle} manquant"
