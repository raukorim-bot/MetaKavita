"""
Appariement : un titre préfixe d'un autre n'est pas le même titre.

`calculate_similarity` accordait un plancher de 0,85 dès que l'un des deux titres
était préfixe de l'autre, sans regarder ce que l'autre contenait de plus. Le
barème de `score_candidate` étant ensuite invariable — malus « mot-clé en trop »
de 0,25, ancrage tome 1 de +0,10 — le score retombait systématiquement à 0,70,
soit au-dessus du seuil d'acceptation de 0,60. Quatre séries mesurées passaient
ainsi en mode automatique, donc sans revue manuelle : le résumé, la couverture,
les genres et l'`age_rating` d'une autre œuvre étaient écrits puis verrouillés
dans Kavita.

Le correctif tient en deux gestes : le plancher est conditionné à la couverture
`len(court)/len(long)` — le même seuil que la branche « sous-chaîne » juste en
dessous, un préfixe n'étant qu'un cas particulier de sous-chaîne — et
`find_title_relation_markers` + `relation_title_penalty`, qui existaient sans
être branchés, sont appliqués dans `score_candidate`.

Ce fichier vérifie les deux sens : les cas mesurés basculent du côté refus, et un
préfixe légitime (variante orthographique, suffixe court) reste accepté.
"""

from __future__ import annotations

import pytest

from scrapers.utils import (
    calculate_similarity,
    find_title_relation_markers,
    relation_title_penalty,
    score_candidate,
)

# Seuil d'acceptation par défaut de MetaKavita : en dessous, le candidat est
# écarté ou renvoyé en revue manuelle selon le mode.
SEUIL = 0.60


def _candidat(titre: str, **extra) -> dict:
    """Candidat minimal : ni auteur ni ISBN, pour n'observer que le titre.

    C'est le cas réel des fournisseurs HTML français et des recherches par titre
    sur les API : sans auteur côté Kavita, la protection anti-homonyme de
    `score_candidate` ne s'active pas et le titre décide seul.
    """
    candidat = {
        "title": titre,
        "alternative_titles": [],
        "summary": "Un résumé suffisamment long pour être considéré comme utile.",
        "genres": [],
        "tags": [],
    }
    candidat.update(extra)
    return candidat


# Les quatre cas mesurés comme ACCEPTÉS avant correctif, avec le titre du dossier
# Kavita à gauche et le candidat rendu par le fournisseur à droite.
CAS_A_REFUSER = [
    ("Monster", "Monster Musume no Iru Nichijou"),
    ("Naruto", "Naruto Gaiden"),
    ("Berserk", "Berserk Perfect Edition"),
    ("Sakamoto", "Sakamoto Days Spin-off"),
]


@pytest.mark.parametrize(("recherche", "candidat"), CAS_A_REFUSER)
def test_un_prefixe_dune_autre_oeuvre_passe_sous_le_seuil(recherche, candidat):
    score = score_candidate(_candidat(candidat), recherche, {})

    assert score < SEUIL, (
        f"« {recherche} » reçoit les métadonnées de « {candidat} » avec un score "
        f"de {score:.2f} : le plancher de préfixe le maintenait à 0,70, "
        "au-dessus du seuil, donc écrit et verrouillé sans revue manuelle"
    )


@pytest.mark.parametrize(("recherche", "candidat"), CAS_A_REFUSER)
def test_le_plancher_de_prefixe_ne_sapplique_plus_a_ces_cas(recherche, candidat):
    """Preuve à la source : sans condition de couverture, ces paires valaient
    exactement 0,85 quel que soit leur véritable écart."""
    assert calculate_similarity(recherche, candidat) < 0.85


def test_monster_musume_est_bien_le_cas_cite_en_commentaire(caplog):
    """`utils.py` donne « Monster » vs « Monster Musume » comme l'exemple que la
    pénalité doit attraper : c'est celui qui passait."""
    score = score_candidate(
        _candidat("Monster Musume no Iru Nichijou", genres=["Ecchi"], age_rating="Mature"),
        "Monster",
        {},
    )

    assert score < SEUIL


def test_le_bon_candidat_gagne_face_a_son_spin_off():
    """Ce qui compte en production n'est pas seulement le refus, c'est l'ordre :
    les deux candidats arrivent dans la même liste de résultats."""
    bon = score_candidate(_candidat("Berserk"), "Berserk", {})
    variante = score_candidate(_candidat("Berserk Perfect Edition"), "Berserk", {})

    assert bon >= SEUIL, "la série elle-même doit rester acceptée"
    assert bon > variante


# --- Sens inverse : pas de faux négatif sur un préfixe légitime ---


LEGITIMES = [
    # Même titre à une variante d'orthographe près : couverture ~0,96.
    ("Les Chevaliers d'Emeraude", "Les Chevaliers d'Emeraudes"),
    # Suffixe court sans marqueur d'édition ni mot-clé distinctif.
    ("Fullmetal Alchemist", "Fullmetal Alchemist 2"),
    # Article final absent du dossier Kavita.
    ("Kingdom Hearts", "Kingdom Hearts II"),
]


@pytest.mark.parametrize(("recherche", "candidat"), LEGITIMES)
def test_un_prefixe_a_forte_couverture_garde_son_plancher(recherche, candidat):
    assert calculate_similarity(recherche, candidat) >= 0.85, (
        "un titre quasi identique doit continuer à bénéficier du plancher : la "
        "condition de couverture ne doit pas transformer une variante "
        "orthographique en faux négatif"
    )


def test_un_titre_identique_reste_a_un():
    assert calculate_similarity("Monster", "Monster") == 1.0
    assert score_candidate(_candidat("Monster"), "Monster", {}) >= SEUIL


def test_la_penalite_de_relation_epargne_les_titres_de_meme_edition():
    """La pénalité vise l'écart de marqueurs, pas leur présence : deux fiches de
    la même édition ne doivent pas se pénaliser l'une l'autre, sinon brancher la
    fonction dans `score_candidate` casserait l'appariement des séries dont le
    titre officiel contient « Perfect Edition ».
    """
    perfect_a = find_title_relation_markers("berserk perfect edition")
    perfect_b = find_title_relation_markers("berserk perfect edition vol 1")
    nu = find_title_relation_markers("berserk")

    penalite_unilaterale, raisons = relation_title_penalty(nu, perfect_a)
    penalite_meme_edition, _ = relation_title_penalty(perfect_a, perfect_b)

    assert penalite_unilaterale > 0.0 and "edition_marker" in raisons
    assert penalite_meme_edition == 0.0
