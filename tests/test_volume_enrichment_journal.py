"""Ce que le journal d'une passe par tome doit dire, et sous quelle forme.

Le journal était écrit pour la base de données, pas pour la personne qui regarde
passer sa bibliothèque : « série 6429 : écriture de 11 unité(s) ». Personne ne
connaît par cœur le numéro Kavita de ses séries, et une passe qui prend une minute
par série n'ouvrait aucune ligne avant son bilan — impossible de savoir laquelle
était en cours, ni si l'attente venait du fournisseur, de la traduction ou de
l'écriture.

Deux règles sont vérifiées ici. Une série se nomme par son titre **et** son
identifiant Kavita (`« Blacksad » (1)`) ; l'identifiant seul n'est qu'un repli
annoncé comme tel. Et chaque phase longue porte une ligne d'ouverture *et* une
ligne de clôture avec sa durée, faute de quoi une phase bloquée est
indiscernable d'une phase jamais démarrée.
"""
from __future__ import annotations

import logging
import re
import time

import pytest

from secure_logging import series_label
from services.volume_enrichment import job
from services.volume_enrichment.apply import apply_plan
from services.volume_enrichment.matching import units_from_volumes
from services.volume_enrichment.plan import build_plan, unit_label

#: L'ancienne forme : « série 6429 : ... ». Ce qu'aucune ligne ne doit reprendre.
IDENTIFIANT_NU = re.compile(r"série \d+ :")


class FakeApi:
    def __init__(self, series, volumes=None):
        self.series = series
        self.volumes = volumes or {}
        self.written = []

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
        self.written.append(dto)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        return True, "ok"


def _volumes(series_id, count=2):
    return [
        {
            "id": 900 + n,
            "minNumber": n,
            "chapters": [{"id": series_id * 100 + n, "minNumber": n}],
        }
        for n in range(1, count + 1)
    ]


@pytest.fixture
def wired(monkeypatch, tmp_path):
    import db_manager

    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "test.db"))
    db_manager.init_db()

    series = [{"id": 1, "name": "Blacksad"}, {"id": 7, "name": ""}]
    api = FakeApi(series, {1: _volumes(1), 7: _volumes(7)})

    monkeypatch.setattr(job, "load_config", lambda: {"KAVITA_URL": "u", "KAVITA_API_KEY": "k"})
    monkeypatch.setattr(job, "KavitaAPI", lambda url, key: api)
    monkeypatch.setattr(job, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: ("comicvine", {"1": {"summary": "Un"}, "2": {"summary": "Deux"}}),
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn", lambda units, **kw: {}
    )
    monkeypatch.setattr(job, "credits_fetcher", lambda pid: None)
    monkeypatch.setattr(job, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(job, "list_enriched_series_ids", db_manager.list_enriched_series_ids)
    return api


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


def _lignes(caplog):
    return [record.getMessage() for record in caplog.records if "[Tomes]" in record.getMessage()]


# ===== Le nom, pas l'identifiant =====


def test_une_passe_nomme_ses_series(wired, caplog):
    caplog.set_level(logging.INFO)

    job.start_volume_enrich("all", series_ids=[1])
    assert _wait_idle(), "la passe doit se terminer"

    lignes = _lignes(caplog)
    assert any("« Blacksad » (1)" in ligne for ligne in lignes), lignes
    assert not [ligne for ligne in lignes if IDENTIFIANT_NU.search(ligne)], (
        "aucune ligne ne doit désigner une série par son seul identifiant"
    )


def test_une_serie_sans_titre_est_annoncee_comme_telle(wired, caplog):
    """Le repli doit se lire comme un repli : « série 7 », pas « 7 ».

    Un titre vide arrive pour de vrai — une série que Kavita vient de perdre, ou
    dont le scan n'a pas fini. La passe l'écarte alors (chercher « 7 » chez un
    fournisseur ramènerait l'album d'une autre œuvre), et c'est justement cette
    ligne-là qui doit nommer la série sans faire passer son numéro pour un titre.
    """
    caplog.set_level(logging.INFO)

    job.start_volume_enrich("all", series_ids=[7])
    assert _wait_idle()

    lignes = _lignes(caplog)
    assert any("« série 7 »" in ligne for ligne in lignes), lignes


def test_le_bilan_d_ecriture_nomme_la_serie(wired, caplog):
    """La ligne que l'utilisateur a vue avec un identifiant, sans passer par un thread."""
    caplog.set_level(logging.INFO)
    api = wired
    units = units_from_volumes(_volumes(1))
    plan = build_plan(units, {"1": {"summary": "Un"}}, provider="comicvine")
    plan["series_name"] = "Blacksad"

    apply_plan(api, 1, plan)

    lignes = _lignes(caplog)
    assert any("« Blacksad » (1) : écriture" in ligne for ligne in lignes), lignes
    assert any("« Blacksad » (1) : 1 tome(s) traité(s)" in ligne for ligne in lignes), lignes
    assert not [ligne for ligne in lignes if IDENTIFIANT_NU.search(ligne)]


def test_sans_nom_dans_le_plan_l_identifiant_reste_le_repli(wired, caplog):
    """`apply_plan` lit le nom dans le plan : un plan bâti à la main n'en a pas,
    et la ligne doit rester lisible plutôt que de mentir sur l'œuvre."""
    caplog.set_level(logging.INFO)
    plan = build_plan(units_from_volumes(_volumes(1)), {"1": {"summary": "Un"}})

    apply_plan(wired, 42, plan)

    assert any("« série 42 »" in ligne for ligne in _lignes(caplog))


# ===== Ouverture et clôture de chaque phase longue =====


def test_chaque_phase_annonce_son_debut_et_sa_fin(wired, caplog):
    """Une passe peut tenir une minute sur une série : le journal doit dire ce
    qu'elle fait pendant ce temps, pas seulement ce qu'elle a fait."""
    caplog.set_level(logging.INFO)

    job.start_volume_enrich("all", series_ids=[1])
    assert _wait_idle()

    lignes = _lignes(caplog)
    ouverture_recherche = [l for l in lignes if "recherche des albums" in l]
    cloture_recherche = [l for l in lignes if "album(s) trouvé(s)" in l]
    ouverture_ecriture = [l for l in lignes if ": écriture de" in l]
    cloture_ecriture = [l for l in lignes if "tome(s) traité(s) en" in l]

    assert ouverture_recherche, lignes
    assert cloture_recherche, lignes
    assert ouverture_ecriture, lignes
    assert cloture_ecriture, lignes
    # Une durée dans chaque clôture : c'est ce qui permet de dire *où* le temps
    # est passé quand une passe paraît interminable.
    assert re.search(r"en \d+\.\d+ s", cloture_recherche[0]), cloture_recherche[0]
    assert re.search(r"en \d+\.\d+ s", cloture_ecriture[0]), cloture_ecriture[0]


def test_la_passe_elle_meme_est_encadree(wired, caplog):
    caplog.set_level(logging.INFO)

    job.start_volume_enrich("all", series_ids=[1])
    assert _wait_idle()

    lignes = _lignes(caplog)
    assert any("▶ Passe sur 1 série(s) sélectionnée(s)" in ligne for ligne in lignes), lignes
    assert any("Passe terminée en" in ligne for ligne in lignes), lignes


def test_une_passe_annulee_le_dit_dans_son_bilan(wired, caplog):
    """Un bilan qui affiche une coche verte après une annulation ferait croire
    que tout a été écrit."""
    caplog.set_level(logging.INFO)
    job.start_volume_enrich("all", series_ids=[1])
    job.cancel_volume_enrich()
    assert _wait_idle()

    bilan = [ligne for ligne in _lignes(caplog) if "Passe terminée" in ligne]
    assert bilan, _lignes(caplog)
    if job.get_volume_enrich_state().get("was_cancelled"):
        assert "⛔" in bilan[0]


# ===== Les étiquettes elles-mêmes =====


def test_l_etiquette_de_serie_porte_le_titre_et_l_identifiant():
    assert series_label("Blacksad", 6429) == "« Blacksad » (6429)"
    assert series_label("  Blacksad  ", 6429) == "« Blacksad » (6429)"
    assert series_label("Blacksad") == "« Blacksad »"
    assert series_label("", 6429) == "« série 6429 »"
    assert series_label(None) == "« série inconnue »"


def test_l_etiquette_de_tome_parle_de_tomes_pas_de_chapitres():
    """Le numéro que l'utilisateur lit sur la tranche, pas celui de la base."""
    assert unit_label({"matched_on": "3", "chapter_id": 45821}) == "tome 3"
    assert unit_label({"volume_number": 12, "chapter_id": 45821}) == "tome 12"
    assert unit_label({"chapter_number": "3.5", "chapter_id": 45821}) == "chapitre 3.5"
    assert unit_label({"chapter_id": 45821}) == "chapitre 45821"
    assert unit_label({}) == "tome inconnu"
