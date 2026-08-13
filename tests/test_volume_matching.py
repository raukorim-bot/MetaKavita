"""
Appariement tome Kavita ↔ album fournisseur.

Deux façons de tout casser ici : prendre une sentinelle Kavita (-100000 pour les
chapitres sans tome, 100000 pour les hors-série) pour un numéro d'album, et
rater un appariement parce que l'un dit `3.0` et l'autre `"03"`. La première
écrirait les métadonnées du tome 1 sur un hors-série, la seconde n'écrirait
rien du tout.
"""
from __future__ import annotations

import pytest

from scrapers.base import BaseScraper
from services.volume_enrichment.matching import (
    LOOSE_VOL,
    SPECIAL_VOL,
    is_sentinel,
    is_special_number,
    match_units,
    normalize_index,
    number_key,
    unit_number,
    units_from_volumes,
)


def _unit(chapter_id, volume_number=None, chapter_number=None, **extra):
    unit = {
        "chapter_id": chapter_id,
        "volume_id": 100 + chapter_id,
        "volume_number": volume_number,
        "chapter_number": chapter_number,
        "is_special": False,
    }
    unit.update(extra)
    return unit


@pytest.mark.parametrize(
    "raw, expected",
    [(3, "3"), (3.0, "3"), ("3", "3"), ("03", "3"), (" 3 ", "3"), ("3,5", "3.5"), (3.5, "3.5")],
)
def test_the_same_volume_written_three_ways_gets_one_key(raw, expected):
    assert number_key(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "hors-série", "tome 3", True, float("nan")])
def test_a_number_that_is_not_one_has_no_key(raw):
    assert number_key(raw) is None


@pytest.mark.parametrize("raw", [SPECIAL_VOL, LOOSE_VOL, -100000.0, "100000"])
def test_kavita_sentinels_are_recognised(raw):
    assert is_sentinel(raw) is True
    assert number_key(raw) is None, "une sentinelle ne doit jamais servir de clé"


@pytest.mark.parametrize("raw", [0, 1, 3.5, 999])
def test_a_real_volume_number_is_not_a_sentinel(raw):
    assert is_sentinel(raw) is False


def test_a_chapter_based_series_matches_on_its_chapter_number():
    """Kavita loge ces chapitres sous le volume -100000 : le numéro utile est
    celui du chapitre."""
    unit = _unit(1, volume_number=None, chapter_number=12)

    assert unit_number(unit) == "12"


def test_the_loose_leaf_sentinel_does_not_shadow_the_chapter_number():
    """Le rapport d'inventaire nettoie déjà la sentinelle, mais une unité venue
    directement de Kavita la porte encore."""
    unit = _unit(1, volume_number=LOOSE_VOL, chapter_number=12)

    assert unit_number(unit) == "12"


def test_a_volume_holding_several_chapters_matches_on_the_chapter():
    """Le cas comics : Kavita range tout un run sous le volume 1 et fait de
    chaque numéro un chapitre. Apparier sur le tome donnerait l'album #1 aux
    cinquante issues, chacune verrouillée sur le résumé et la couverture du
    premier numéro."""
    unit = _unit(1, volume_number=1, chapter_number=7, sibling_count=50)

    assert unit_number(unit) == "7"


def test_a_volume_holding_a_single_file_matches_on_the_volume():
    """Le cas manga : un fichier par tome. Kavita donne au chapitre unique le
    numéro 1 quel que soit le tome — s'y fier écrirait l'album 1 partout."""
    unit = _unit(1, volume_number=7, chapter_number=1, sibling_count=1)

    assert unit_number(unit) == "7"


def test_the_chapter_ref_survives_the_index_cleanup():
    """`provider_ref` est l'adresse de l'album chez le fournisseur, dont la
    passe crédits a besoin. Le nettoyage l'a longtemps jeté, ce qui rendait
    l'option « crédits par album » sans effet visible."""
    index = normalize_index({"1": {"title": "Premier", "provider_ref": "4000-42"}})

    assert index["1"]["provider_ref"] == "4000-42"


def test_a_reference_without_any_metadata_is_not_an_album():
    """Une entrée qui ne porte que son adresse n'a rien à écrire : l'afficher
    promettrait un tome enrichi qui repartirait vide."""
    assert normalize_index({"1": {"provider_ref": "4000-42"}}) == {}


def test_normalising_an_index_drops_what_cannot_be_placed():
    index = {
        "1": {"title": "Premier"},
        "hors-série": {"title": "Perdu"},
        SPECIAL_VOL: {"title": "Hors-série"},
        "3": {},
        "4": "pas un dict",
    }

    assert normalize_index(index) == {"1": {"title": "Premier"}}


def test_normalising_keeps_the_richest_of_two_entries_on_one_number():
    index = {
        "1": {"title": "Court"},
        1.0: {"title": "Complet", "summary": "s", "release_date": "2019"},
    }

    assert normalize_index(index)["1"]["title"] == "Complet"


def test_normalising_a_non_dict_index_yields_nothing():
    assert normalize_index(None) == {}
    assert normalize_index([{"title": "x"}]) == {}


def test_matching_pairs_units_with_their_album():
    units = [_unit(1, volume_number=1), _unit(2, volume_number=2), _unit(3, volume_number=9)]
    index = {"1": {"title": "Un"}, "2": {"title": "Deux"}}

    matched, unmatched = match_units(units, index)

    assert [(u["chapter_id"], p["title"]) for u, p in matched] == [(1, "Un"), (2, "Deux")]
    assert [u["chapter_id"] for u in unmatched] == [3]


def test_a_special_never_receives_another_volumes_metadata():
    """Le hors-série porte le numéro 100000 ; l'apparier au « tome 100000 »
    n'aurait pas de sens, et l'apparier au tome 1 serait un désastre."""
    units = [_unit(1, volume_number=1), _unit(2, volume_number=SPECIAL_VOL, is_special=True)]
    index = {"1": {"title": "Un"}, "100000": {"title": "Piège"}}

    matched, unmatched = match_units(units, index)

    assert [u["chapter_id"] for u, _ in matched] == [1]
    assert unmatched == [], "un hors-série n'est pas « non apparié », il est hors sujet"


@pytest.mark.parametrize("raw", [SPECIAL_VOL, 100000.0, "100000"])
def test_the_special_sentinel_is_enough_to_conclude(raw):
    assert is_special_number(raw) is True


@pytest.mark.parametrize("raw", [LOOSE_VOL, 0, 1, 3.5, 999, None, "", "hors-série"])
def test_nothing_else_is_taken_for_a_special(raw):
    """La feuille volante en particulier : ses chapitres portent de vrais
    numéros et doivent continuer à s'apparier."""
    assert is_special_number(raw) is False


def test_a_special_volume_stays_special_when_kavita_omits_the_flag():
    """Le cas mesuré : Kavita ne garantit pas `isSpecial` dans la réponse, mais
    le volume 100000 est déjà, à lui seul, la définition du hors-série. Sans
    cette lecture, l'unité retombait sur son numéro de chapitre — un compteur
    ordinaire — et le hors-série recevait le titre, le résumé et la couverture
    du tome 2, verrous Kavita compris."""
    volumes = [
        {"id": 10, "minNumber": 1, "chapters": [{"id": 100, "minNumber": 1}]},
        {"id": 11, "minNumber": 2, "chapters": [{"id": 200, "minNumber": 1}]},
        {"id": 12, "minNumber": SPECIAL_VOL, "chapters": [{"id": 300, "minNumber": 2}]},
    ]
    index = {"1": {"title": "Un"}, "2": {"title": "Deux"}}

    units = units_from_volumes(volumes)
    matched, unmatched = match_units(units, index)

    # Le hors-série s'appariait sur « 2 », le numéro de son chapitre : le tome 2
    # se retrouvait écrit deux fois, une fois au bon endroit.
    assert [(u["chapter_id"], p["title"]) for u, p in matched] == [(100, "Un"), (200, "Deux")]
    assert [unit_number(u) for u, _p in matched] == ["1", "2"]
    assert [u["is_special"] for u in units] == [False, False, True]
    assert unmatched == [], "un hors-série n'est pas « non apparié », il est hors sujet"


def test_a_flagged_special_is_still_recognised_without_the_sentinel():
    """L'ancienne lecture — le seul drapeau — reste valable : certains
    hors-série sont numérotés à la suite de la série."""
    volumes = [{"id": 20, "minNumber": 4, "isSpecial": True, "chapters": [{"id": 400, "minNumber": 1}]}]

    units = units_from_volumes(volumes)
    matched, unmatched = match_units(units, {"4": {"title": "Piège"}})

    assert units[0]["is_special"] is True
    assert (matched, unmatched) == ([], [])


def test_loose_leaf_chapters_are_not_mistaken_for_specials():
    """Le volume -100000 n'est pas un hors-série : c'est le fourre-tout des
    chapitres sans tome, qui s'apparient sur leur propre numéro."""
    volumes = [
        {
            "id": 30,
            "minNumber": LOOSE_VOL,
            "chapters": [{"id": 501, "minNumber": 11}, {"id": 502, "minNumber": 12}],
        }
    ]
    index = {"11": {"title": "Onze"}, "12": {"title": "Douze"}}

    units = units_from_volumes(volumes)
    matched, unmatched = match_units(units, index)

    assert [u["is_special"] for u in units] == [False, False]
    assert [(u["chapter_id"], p["title"]) for u, p in matched] == [(501, "Onze"), (502, "Douze")]
    assert unmatched == []


def test_a_chapter_carrying_the_special_sentinel_matches_nothing():
    """Le hors-série rangé dans un tome ordinaire : son numéro de chapitre est
    la sentinelle, il n'y a aucun album 100000 chez le fournisseur."""
    volumes = [
        {
            "id": 40,
            "minNumber": 1,
            "chapters": [{"id": 601, "minNumber": 1}, {"id": 602, "minNumber": SPECIAL_VOL}],
        }
    ]
    index = {"1": {"title": "Un"}, "100000": {"title": "Piège"}}

    matched, unmatched = match_units(units_from_volumes(volumes), index)

    assert [u["chapter_id"] for u, _ in matched] == [601]
    assert [u["chapter_id"] for u in unmatched] == [602]


def test_matching_does_not_copy_the_albums_the_series_cannot_hold():
    """Un scraper tiers peut annoncer des dizaines de milliers d'albums quand la
    série n'en possède qu'un : nettoyer tout l'index coûtait sa mémoire entière
    (87 Mo mesurés pour 20 000 entrées) pour un seul payload utile."""
    touched: list = []

    class Watched(dict):
        def __init__(self, number, payload):
            super().__init__(payload)
            self.number = number

        def get(self, key, default=None):
            touched.append(self.number)
            return super().get(key, default)

    index = {str(n): Watched(str(n), {"title": f"Album {n}"}) for n in range(1, 501)}

    matched, _unmatched = match_units([_unit(1, volume_number=2)], index)

    assert [p["title"] for _u, p in matched] == ["Album 2"]
    assert set(touched) == {"2"}


def test_pruning_the_index_keeps_only_the_wanted_numbers():
    index = {"1": {"title": "Un"}, "2": {"title": "Deux"}, "3": {"title": "Trois"}}

    assert normalize_index(index, keys={"2"}) == {"2": {"title": "Deux"}}
    assert normalize_index(index, keys=set()) == {}
    assert normalize_index(index, keys=None) == normalize_index(index)


def test_a_volume_without_chapter_is_skipped():
    """Les métadonnées vivent sur le chapitre : un tome vide n'a rien où écrire."""
    units = [{"chapter_id": None, "volume_number": 1, "is_special": False}]

    matched, unmatched = match_units(units, {"1": {"title": "Un"}})

    assert matched == []
    assert unmatched == []


def test_the_same_chapter_listed_twice_is_written_once():
    units = [_unit(1, volume_number=1), _unit(1, volume_number=1)]

    matched, _ = match_units(units, {"1": {"title": "Un"}})

    assert len(matched) == 1


def test_matching_survives_an_empty_index():
    units = [_unit(1, volume_number=1)]

    matched, unmatched = match_units(units, {})

    assert matched == []
    assert [u["chapter_id"] for u in unmatched] == [1]


def test_kavita_volumes_carry_how_many_chapters_they_hold():
    """C'est ce comptage qui décide sur quel numéro apparier : sans lui, un run
    de comics rangé sous un seul tome recevrait cinquante fois le même album."""
    from services.volume_enrichment.matching import units_from_volumes

    volumes = [
        {
            "id": 10,
            "number": 1,
            "chapters": [
                {"id": 100, "number": "1"},
                {"id": 101, "number": "2"},
                {"number": "3"},  # sans identifiant : rien où écrire
            ],
        },
        {"id": 11, "number": 2, "chapters": [{"id": 200, "number": "1"}]},
    ]

    units = units_from_volumes(volumes)

    counts = {u["chapter_id"]: u["sibling_count"] for u in units}
    assert counts[100] == 2 and counts[101] == 2
    assert counts[200] == 1
    assert [unit_number(u) for u in units if u["chapter_id"] in (100, 101)] == ["1", "2"]
    assert [unit_number(u) for u in units if u["chapter_id"] == 200] == ["2"]


def test_the_index_contract_exists_and_defaults_to_none():
    """Un scraper communautaire qui ne l'implémente pas ne doit rien casser."""

    class Silent(BaseScraper):
        id = "silent"

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

    scraper = Silent()

    assert scraper.fetch_volume_index("Naruto") is None
    assert scraper.fetch_volume("Naruto", volume_number=3) is None


def test_the_volume_scope_returns_the_loaded_volume_providers():
    """`get_by_scope('volume')` est l'unique source de fournisseurs de la passe.

    Ce test tolérait une liste vide, du temps où aucun fournisseur n'avait
    basculé : il restait vert alors que la fonctionnalité était morte faute de
    scrapers capables de lister les tomes (BF143). La couverture détaillée de la
    divergence image ↔ data/scrapers vit dans
    `tests/test_core_scrapers_volume_scope.py`.
    """
    from scrapers import ScraperRegistry

    providers = ScraperRegistry.get_by_scope("volume", include_disabled=True)
    assert isinstance(providers, list)
    assert providers, "Aucun fournisseur ne déclare le scope 'volume' dans le registre chargé."
