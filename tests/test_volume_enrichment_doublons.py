"""Deux fichiers pour un même album : l'aperçu doit le dire.

Cas réel, relevé sur une bibliothèque Blacksad. Kavita y détenait **onze**
fichiers pour **sept** albums : sept tomes correctement numérotés de 1 à 7, et
quatre fichiers restés « hors tome » — la sentinelle `-100000`, que le scanner
attribue à ce qu'il n'a pas su rattacher — dont les numéros de chapitre valaient
1, 4, 6 et 7.

Les deux familles s'apparient par des chemins différents et se rejoignent sur le
même album : les quatre fichiers hors tome partagent un même volume conteneur,
donc `unit_number` les apparie sur leur numéro de **chapitre** ; les sept tomes
n'ont qu'un chapitre chacun, donc ils s'apparient sur leur numéro de **tome**.
Les albums 1, 4, 6 et 7 étaient ainsi visés deux fois, et l'écriture partait deux
fois — couverture téléchargée et téléversée deux fois.

L'appariement n'a pas tort : les deux fichiers *sont* cet album. C'est
l'utilisateur qui doit trancher, et pour cela le voir.
"""
from __future__ import annotations

from services.volume_enrichment.matching import units_from_volumes
from services.volume_enrichment.plan import build_plan

SPECIAL_LOOSE = -100_000


def _chapitre(chapter_id: int, number, **extra):
    """Un `ChapterDto` réduit à ce que l'appariement lit."""
    return {"id": chapter_id, "minNumber": number, "range": str(number), **extra}


def _blacksad_volumes():
    """La structure exacte que Kavita rendait pour la série en cause.

    Un volume conteneur « hors tome » avec quatre chapitres numérotés 1, 4, 6, 7 ;
    puis sept tomes d'un chapitre chacun, dont les numéros de chapitre sont du
    bruit venu des noms de fichiers (2822, 3785, 3785, 25, …) — sans importance,
    puisqu'un tome d'un seul chapitre s'apparie sur son numéro de tome.
    """
    return [
        {
            "id": 900,
            "minNumber": SPECIAL_LOOSE,
            "chapters": [
                _chapitre(101, 1),
                _chapitre(104, 4),
                _chapitre(106, 6),
                _chapitre(107, 7),
            ],
        },
        {"id": 1, "minNumber": 1, "chapters": [_chapitre(201, 2822)]},
        {"id": 2, "minNumber": 2, "chapters": [_chapitre(202, 3785)]},
        {"id": 3, "minNumber": 3, "chapters": [_chapitre(203, 3785)]},
        {"id": 4, "minNumber": 4, "chapters": [_chapitre(204, 25)]},
        {"id": 5, "minNumber": 5, "chapters": [_chapitre(205, 4312)]},
        {"id": 6, "minNumber": 6, "chapters": [_chapitre(206, 3683)]},
        {"id": 7, "minNumber": 7, "chapters": [_chapitre(207, 1920)]},
    ]


def _index_de_sept_albums():
    return {
        str(n): {"summary": f"Résumé de l'album {n}.", "cover_url": f"https://ex.test/{n}.jpg"}
        for n in range(1, 8)
    }


def test_la_situation_blacksad_produit_bien_onze_unites():
    """Garde-fou : si ce chiffre change, le reste du test ne veut plus rien dire."""
    units = units_from_volumes(_blacksad_volumes())

    assert len(units) == 11
    hors_tome = [u for u in units if u.get("volume_number") is None]
    assert len(hors_tome) == 4
    # Les quatre partagent leur volume conteneur : c'est ce qui les fait
    # s'apparier sur leur numéro de chapitre et non sur celui du tome.
    assert all(u["sibling_count"] == 4 for u in hors_tome)


def test_les_albums_en_double_sont_marques():
    plan = build_plan(units_from_volumes(_blacksad_volumes()), _index_de_sept_albums())

    marquees = {e["chapter_id"]: e for e in plan["units"] if e.get("duplicate_of") is not None}

    # Albums 1, 4, 6, 7 : le fichier hors tome et le tome. Huit lignes au total.
    assert set(marquees) == {101, 104, 106, 107, 201, 204, 206, 207}
    assert plan["counts"]["duplicates"] == 8
    assert marquees[101]["duplicate_of"] == "1"
    assert marquees[201]["duplicate_of"] == "1"
    assert marquees[101]["duplicate_count"] == 2


def test_les_albums_uniques_ne_sont_pas_marques():
    plan = build_plan(units_from_volumes(_blacksad_volumes()), _index_de_sept_albums())

    par_chapitre = {e["chapter_id"]: e for e in plan["units"]}

    # Albums 2, 3 et 5 n'existent qu'en un seul fichier.
    for chapter_id in (202, 203, 205):
        assert "duplicate_of" not in par_chapitre[chapter_id]


def test_les_deux_lignes_d_un_doublon_restent_ecrivables():
    """Marquer n'est pas écarter.

    Les deux fichiers sont bien cet album : les priver de métadonnées serait pire
    que la redite. L'utilisateur décoche s'il le souhaite — c'est la décision
    prise pour ce comportement.
    """
    plan = build_plan(units_from_volumes(_blacksad_volumes()), _index_de_sept_albums())

    par_chapitre = {e["chapter_id"]: e for e in plan["units"]}

    assert par_chapitre[101]["write_count"] > 0
    assert par_chapitre[201]["write_count"] > 0
    assert plan["counts"]["writable"] == 11


def test_le_rang_distingue_la_premiere_ligne_des_redites():
    plan = build_plan(units_from_volumes(_blacksad_volumes()), _index_de_sept_albums())

    par_chapitre = {e["chapter_id"]: e for e in plan["units"]}

    # L'ordre d'appariement suit celui des unités : le hors tome vient d'abord,
    # puisque son volume conteneur est rendu en premier par Kavita.
    assert par_chapitre[101]["duplicate_rank"] == 1
    assert par_chapitre[201]["duplicate_rank"] == 2


def test_une_serie_sans_doublon_ne_compte_aucun_doublon():
    volumes = [
        {"id": 1, "minNumber": 1, "chapters": [_chapitre(201, 1)]},
        {"id": 2, "minNumber": 2, "chapters": [_chapitre(202, 2)]},
    ]

    plan = build_plan(units_from_volumes(volumes), _index_de_sept_albums())

    assert plan["counts"]["duplicates"] == 0
    assert all("duplicate_of" not in e for e in plan["units"])


def test_trois_fichiers_pour_un_album_sont_tous_marques():
    """Le marquage ne suppose pas des paires : un album peut avoir trois copies."""
    volumes = [
        {
            "id": 900,
            "minNumber": SPECIAL_LOOSE,
            "chapters": [_chapitre(101, 1), _chapitre(102, 1)],
        },
        {"id": 1, "minNumber": 1, "chapters": [_chapitre(201, 999)]},
    ]

    plan = build_plan(units_from_volumes(volumes), _index_de_sept_albums())

    assert plan["counts"]["duplicates"] == 3
    assert {e["duplicate_count"] for e in plan["units"]} == {3}
