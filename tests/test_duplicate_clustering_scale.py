"""
Coût du regroupement des doublons, et ce qu'il ne doit pas coûter en qualité.

Le seau de comparaison était formé sur le **premier mot distinctif** du titre :
dès qu'une partie de la bibliothèque le partage — une collection, un éditeur, un
univers étendu — le seau redevenait quadratique. Mesuré sous eventlet avec un
vrai serveur WSGI : 33,5 s pour 1 500 séries dont la moitié partagent leur
premier mot, 152,8 s quand toutes le partagent. C'est du calcul pur, sans un
seul point de bascule : pendant tout ce temps l'application entière est muette,
à la fin de **chaque** scan.

Le seau est donc formé sur l'ensemble complet des mots distinctifs, et non plus
sur le premier. Ce n'est pas un compromis de qualité au seuil par défaut :
`score_candidate` retire 0,35 dès qu'un mot-clé majeur manque d'un côté, et le
meilleur bonus qu'il puisse rendre vaut 0,25 — une paire dont les mots
distinctifs diffèrent plafonne à 0,90, sous le seuil de 0,92. C'est ce que
vérifie `test_the_word_set_key_only_drops_pairs_the_score_would_reject`.
"""
from __future__ import annotations

import pytest

from services.library_audit import duplicates as dup
from services.library_audit.duplicates import (
    cluster_duplicate_series,
    score_duplicate_pair,
)


def _series(sid, name, **extra):
    return {"id": sid, "name": name, "libraryId": 1, "libraryType": "Comic", **extra}


@pytest.fixture
def counted(monkeypatch):
    """Compte les paires réellement scorées : c'est là qu'est le temps."""
    calls = {"n": 0}
    original = dup.score_duplicate_pair

    def counting(a, b):
        calls["n"] += 1
        return original(a, b)

    monkeypatch.setattr(dup, "score_duplicate_pair", counting)
    return calls


def _collection(count=300):
    """Une collection : toutes les séries partagent leur premier mot distinctif."""
    return [_series(i, f"Chroniques opus{i}") for i in range(1, count + 1)]


def test_a_shared_first_word_no_longer_makes_the_bucket_quadratic(counted):
    library = _collection(300)

    cluster_duplicate_series(library, library_id=1, threshold=0.92)

    naive = len(library) * (len(library) - 1) // 2
    assert naive > 40_000, "le cas de référence doit bien être quadratique"
    assert counted["n"] < 500, (
        f"{counted['n']} paires scorées : le seau « premier mot » est revenu"
    )


def test_the_duplicates_of_that_collection_are_still_found(counted):
    library = _collection(300)
    library += [_series(9001, "Chroniques jumelles"), _series(9002, "Chroniques jumelles")]

    groups = cluster_duplicate_series(library, library_id=1, threshold=0.92)

    assert [g["series_ids"] for g in groups] == [[9001, 9002]]
    assert counted["n"] < 500


def test_the_worst_case_stops_at_the_first_grouping(counted):
    """Toutes les séries portent le même titre : le regroupement est acquis dès
    qu'elles sont réunies, et comparer les paires restantes ne peut plus rien y
    changer. C'est le cas à 152 s."""
    library = [_series(i, "Série numéro un") for i in range(1, 301)]

    groups = cluster_duplicate_series(library, library_id=1, threshold=0.92)

    assert len(groups) == 1
    assert len(groups[0]["series_ids"]) == 300
    assert counted["n"] < 1_000, f"{counted['n']} paires scorées pour 300 séries"


def test_the_word_set_key_only_drops_pairs_the_score_would_reject():
    """L'invariant qui rend la clé sans perte au seuil par défaut : deux titres
    dont les mots distinctifs diffèrent ne peuvent pas atteindre 0,92."""
    apart = [
        ("Chroniques du Dragon", "Chroniques de l'Ivoire"),
        ("Naruto", "Naruto Gaiden"),
        ("Berserk", "Berserk Perfect Edition"),
        ("Atlas boreal", "Atlas jade"),
        ("Série numéro un", "Série numéro deux"),
    ]
    for name_a, name_b in apart:
        score = score_duplicate_pair(
            _series(1, name_a), _series(2, name_b)
        )["score"]
        assert score <= 0.90, f"{name_a} / {name_b} : {score}"


def test_a_shared_isbn_still_groups_two_series_named_differently():
    """Un ISBN partagé vaut identité quels que soient les titres : les mots
    distinctifs ne doivent pas les séparer."""
    library = [
        _series(1, "Thorgal", isbn="9782803616770"),
        _series(2, "Thorgal Integrale", isbn="9782803616770"),
    ]

    groups = cluster_duplicate_series(library, library_id=1, threshold=0.92)

    assert [g["series_ids"] for g in groups] == [[1, 2]]


def test_a_lowered_threshold_keeps_the_wider_comparison():
    """Sous 0,90 la démonstration ne tient plus : on retombe sur le seau formé
    au premier mot, dont l'utilisateur a explicitement demandé la largeur.

    « Atlas boreal » et « Atlas boreale » marquent 0,71 : des mots distinctifs
    différents, donc hors d'atteinte au seuil par défaut, mais un doublon que
    l'utilisateur veut voir quand il descend son seuil à 0,70."""
    library = [_series(1, "Atlas boreal"), _series(2, "Atlas boreale")]

    assert cluster_duplicate_series(library, library_id=1, threshold=0.92) == []
    groups = cluster_duplicate_series(library, library_id=1, threshold=0.70)

    assert [g["series_ids"] for g in groups] == [[1, 2]]


def test_the_clustering_hands_the_worker_back_between_pairs(monkeypatch):
    """Sans point de bascule, le scan rendait l'application muette jusqu'à deux
    minutes à la fin de chaque analyse."""
    yields = {"n": 0}
    monkeypatch.setattr(dup, "yield_to_worker", lambda: yields.__setitem__("n", yields["n"] + 1))

    library = [_series(i, "Série numéro un") for i in range(1, 401)]
    cluster_duplicate_series(library, library_id=1, threshold=0.92)

    assert yields["n"] > 0
