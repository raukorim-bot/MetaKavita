"""
Mémoïsation de l'index fournisseur, entre l'aperçu et l'écriture.

Ce qu'elle achète : l'écriture d'une série ne réinterroge plus le fournisseur que
l'aperçu vient d'interroger. Ce qu'elle risque : servir un index périmé, ou —
bien pire — servir l'index d'un *autre* réglage. D'où deux familles de tests, la
seconde plus fournie que la première : ce qui est retenu, et ce qui ne doit
jamais se partager une entrée.

Ce qui n'est pas en jeu ici : la fraîcheur des données Kavita. Les tomes sont
relus à chaque plan et `apply_entry` relit le chapitre juste avant d'écrire (voir
`test_volume_enrichment_apply.py`). C'est l'index du fournisseur qui est retenu,
pas l'état de Kavita.
"""
from __future__ import annotations

import threading
import types

import pytest

from services.volume_enrichment import index_cache


@pytest.fixture
def counted(monkeypatch):
    """Compte les appels au fournisseur et rend un index reconnaissable."""
    calls = []

    def fake_resolve(series_name, units, **kwargs):
        calls.append(series_name)
        return "comicvine", {"1": {"summary": f"appel {len(calls)}"}}

    monkeypatch.setattr(index_cache, "resolve_index", fake_resolve)
    return calls


def _units(count=2):
    return [{"chapter_id": n, "volume_number": n} for n in range(1, count + 1)]


def _resolve(series_id=7, name="Blacksad", units=None, **kwargs):
    options = {"library_type": "Comic", "config": {}}
    options.update(kwargs)
    return index_cache.resolve_index_cached(
        series_id, name, units if units is not None else _units(), **options
    )


# ===== Ce qui est retenu =====


def test_le_second_appel_ne_repaie_pas_le_fournisseur(counted):
    first = _resolve()
    second = _resolve()

    assert counted == ["Blacksad"]
    assert first[:2] == second[:2], "le même index, au champ près"
    assert first[2] is False and second[2] is True, "le second dit qu'il vient du cache"


def test_une_entree_expiree_fait_repartir_chez_le_fournisseur(counted, monkeypatch):
    """Dix minutes, pas plus : c'est un pont entre un aperçu et le clic qui suit,
    pas un cache de métadonnées."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        index_cache, "time", types.SimpleNamespace(monotonic=lambda: clock["now"])
    )

    _resolve()
    clock["now"] += index_cache._TTL_SECONDS - 1
    assert _resolve()[2] is True, "juste avant l'expiration, l'entrée sert encore"

    clock["now"] += 2
    assert _resolve()[2] is False
    assert len(counted) == 2


def test_l_index_rendu_est_une_copie(counted):
    """L'appelant traduit les résumés et bâtit un plan avec : une entrée mutée
    resservirait du texte déjà traduit à un run qui a changé de langue cible."""
    _provider, index, _cached = _resolve()
    index["1"]["summary"] = "abîmé"
    index["9"] = {"summary": "intrus"}

    _provider2, again, from_cache = _resolve()

    assert from_cache is True
    assert again["1"]["summary"] == "appel 1"
    assert "9" not in again


def test_la_table_est_bornee(counted):
    """Une table sans plafond garderait tout ce qu'un conteneur voit passer."""
    for series_id in range(index_cache._MAX_ENTRIES + 5):
        _resolve(series_id=series_id)

    assert len(index_cache._CACHE) == index_cache._MAX_ENTRIES
    # La plus ancienne est partie, la plus récente est là.
    assert _resolve(series_id=0)[2] is False
    assert _resolve(series_id=index_cache._MAX_ENTRIES + 4)[2] is True


def test_un_index_obtenu_sous_annulation_n_est_pas_retenu(monkeypatch):
    """La cascade s'arrête entre deux fournisseurs : l'index est partiel par
    construction, et le retenir ferait écrire ce tronçon au clic suivant."""
    calls = []

    def fake_resolve(series_name, units, **kwargs):
        calls.append(series_name)
        return "comicvine", {"1": {"summary": "moitié"}}

    monkeypatch.setattr(index_cache, "resolve_index", fake_resolve)

    _resolve(should_cancel=lambda: True)
    _resolve(should_cancel=lambda: True)

    assert len(calls) == 2
    assert not index_cache._CACHE


# ===== Ce qui ne doit jamais partager une entrée =====


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param({"series_id": 8}, id="autre série"),
        pytest.param({"name": "Blacksad Intégrale"}, id="série renommée"),
        pytest.param({"library_type": "Manga"}, id="autre type de bibliothèque"),
        pytest.param({"force": True}, id="écrasement forcé"),
        pytest.param({"forced_id": "4050-2127"}, id="identifiant forcé"),
        pytest.param({"forced_provider": "COMICVINE"}, id="fournisseur forcé"),
        pytest.param({"experimental": True}, id="recherche par titre et numéro"),
        pytest.param({"units": [{"chapter_id": 1}]}, id="un tome de moins"),
        pytest.param(
            {"units": [{"chapter_id": 1, "volume_number": 1}, {"chapter_id": 2, "volume_number": 41}]},
            id="même effectif, autres numéros",
        ),
        pytest.param(
            {"config": {"COMIC_PROVIDER_1": "BEDETHEQUE"}}, id="ordre de cascade"
        ),
    ],
)
def test_un_reglage_different_reinterroge_le_fournisseur(counted, changed):
    _resolve(config={"COMIC_PROVIDER_1": "COMICVINE"})
    again = _resolve(**{"config": {"COMIC_PROVIDER_1": "COMICVINE"}, **changed})

    assert again[2] is False
    assert len(counted) == 2


def test_purger_une_serie_oublie_toutes_ses_entrees(counted):
    """Une série peut avoir plusieurs entrées — un aperçu normal, un aperçu
    forcé, un identifiant saisi entretemps : la purge n'en laisse aucune."""
    _resolve(series_id=7)
    _resolve(series_id=7, force=True)
    _resolve(series_id=8)

    forgotten = index_cache.forget_series(7)

    assert forgotten == 2
    assert _resolve(series_id=8)[2] is True, "la voisine n'est pas concernée"
    assert _resolve(series_id=7)[2] is False


def test_deux_ecrivains_concurrents_ne_cassent_pas_la_table(counted):
    """La passe de bibliothèque tourne dans un vrai thread, pas dans un
    greenlet : la table est partagée entre lui et le greenlet de la requête."""
    errors = []

    def hammer(offset):
        try:
            for n in range(20):
                _resolve(series_id=offset * 100 + n)
        except Exception as exc:  # pragma: no cover - c'est ce qu'on veut éviter
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert errors == []
    assert len(index_cache._CACHE) <= index_cache._MAX_ENTRIES
