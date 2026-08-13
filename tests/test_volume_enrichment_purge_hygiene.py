"""Après une écriture par tome, le rapport d'inventaire doit cesser de mentir.

Le rapport de tomes de l'Inventaire sert son analyse depuis un cache, et rien
dans l'enrichissement par tome ne l'invalidait : `purge_series_hygiene_cache`
n'était appelée que depuis `routes/library_audit.py`.

Le symptôme, relevé sur une capture d'écran : l'encart de tête annonçait
« sans résumé : 11 / 11 » pendant que la ligne du tableau juste en dessous
affichait la coche du résumé fraîchement écrit. Les deux se contredisaient à
l'écran, et l'utilisateur jugeait le résultat de son écriture sur une photo
d'avant — au point de croire qu'elle n'avait pas eu lieu.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.apply import apply_plan


class FakeApi:
    def __init__(self, fail_write=()):
        self.fail_write = set(fail_write)
        self.written = []

    def get_chapter(self, chapter_id):
        return {"id": chapter_id}

    def update_chapter_metadata(self, dto):
        if dto["id"] in self.fail_write:
            return False, "Code 500"
        self.written.append(dto)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):  # pragma: no cover
        return True, "ok"


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.apply.save_volume_unit_state", lambda *a, **kw: None
    )


@pytest.fixture
def purges(monkeypatch):
    """Recense les appels de purge, avec leurs arguments."""
    calls = []
    monkeypatch.setattr(
        "services.volume_enrichment.apply.purge_series_hygiene_cache",
        lambda series_id, **kw: calls.append((series_id, kw)),
    )
    return calls


def _plan(*chapter_ids, writable=True):
    return {
        "provider": "COMICVINE",
        "units": [
            {
                "chapter_id": cid,
                "volume_id": 1,
                "volume_number": 1,
                "chapter_number": None,
                "changes": {
                    "summary": {
                        "proposed": "Un résumé",
                        "current": "",
                        "write": writable,
                        "reason": "" if writable else "locked",
                    }
                },
                "write_count": 1 if writable else 0,
            }
            for cid in chapter_ids
        ],
    }


def test_une_ecriture_reussie_purge_le_cache(purges):
    apply_plan(FakeApi(), 77, _plan(1, 2))

    assert purges == [(77, {"keep_overrides": True})]


def test_la_purge_n_a_lieu_qu_une_fois_pour_toute_la_serie(purges):
    """Purger par tome ferait recalculer l'analyse quarante fois pour rien."""
    apply_plan(FakeApi(), 77, _plan(1, 2, 3, 4, 5))

    assert len(purges) == 1


def test_l_attendu_force_et_l_exclusion_survivent_a_la_purge(purges):
    """`keep_overrides` n'est pas un détail : ce sont des décisions de l'utilisateur.

    L'attendu forcé et « exclure de l'inventaire » sont saisis à la main dans ce
    même rapport. Une écriture de métadonnées n'a aucune raison de les effacer.
    """
    apply_plan(FakeApi(), 77, _plan(1))

    assert purges[0][1]["keep_overrides"] is True


def test_sans_rien_ecrit_le_cache_reste_en_place(purges):
    """Rien n'a changé côté Kavita : recalculer l'analyse serait du travail pur perte."""
    apply_plan(FakeApi(), 77, _plan(1, 2, writable=False))

    assert purges == []


def test_une_ecriture_entierement_en_echec_ne_purge_pas(purges):
    apply_plan(FakeApi(fail_write={1}), 77, _plan(1))

    assert purges == []


def test_une_ecriture_partielle_purge_quand_meme(purges):
    """Un seul tome écrit suffit à périmer l'analyse de la série."""
    apply_plan(FakeApi(fail_write={1}), 77, _plan(1, 2))

    assert purges == [(77, {"keep_overrides": True})]


def test_une_purge_en_echec_ne_perd_pas_l_ecriture(monkeypatch):
    """Un rapport périmé se rafraîchit d'un clic ; une écriture perdue, non.

    La base peut être verrouillée une seconde par un lot en cours : l'écriture est
    déjà chez Kavita à ce stade, et lever ici la ferait passer pour un échec.
    """
    def _explose(series_id, **kw):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(
        "services.volume_enrichment.apply.save_volume_unit_state", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "services.volume_enrichment.apply.purge_series_hygiene_cache", _explose
    )
    api = FakeApi()

    result = apply_plan(api, 77, _plan(1))

    assert result["counts"]["done"] == 1
    assert len(api.written) == 1
