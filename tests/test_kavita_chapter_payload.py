"""
Écriture d'un chapitre Kavita : rien ne doit disparaître au passage.

`UpdateChapterDto` est un DTO de remplacement total. Le contrôleur Kavita
assigne chaque champ sans condition, donc un champ absent du corps JSON est un
champ effacé : crédits, genres, tags, classification d'âge, verrous — et
`sortOrder`, qui retomberait à 0 et effondrerait l'ordre de lecture de la série
entière, et les sept identifiants de correspondance externe, qui repartiraient à
zéro (BF139). C'est BF106 / BF122 (verrou de couverture omis, couverture
détruite), en plus large.

Le premier test de ce fichier est le garde-fou du chantier : un chapitre
entièrement rempli, une seule modification, et tout le reste identique.
"""
from __future__ import annotations

import pytest

from services.kavita_chapter_payload import (
    EMPTY_DATE,
    EXTERNAL_ID_KEYS,
    LOCK_KEYS,
    PEOPLE_KEYS,
    build_update_chapter_dto,
    credits_to_write,
    is_valid_isbn,
    normalize_release_date,
    split_written_fields,
)

# Les sept identifiants tels que Kavita les rend sur un chapitre apparié : c'est
# ce qui alimente notes, avis et métadonnées Kavita+ au niveau du chapitre.
MATCHED_EXTERNAL_IDS = {
    "aniListId": 30002,
    "malId": 13,
    "hardcoverId": 4587,
    "metronId": 91234,
    "comicVineId": "4000-12345",
    "mangaBakaId": 77821,
    "cbrId": 616,
}


def _full_chapter() -> dict:
    """Un ChapterDto où *tout* est renseigné, verrous compris."""
    chapter = {
        "id": 4242,
        "volumeId": 77,
        "minNumber": 3.0,
        "maxNumber": 3.0,
        "sortOrder": 3.5,
        "pages": 192,
        "isSpecial": False,
        "title": "3",
        "range": "3",
        "titleName": "Le Sceau du dragon",
        "summary": "Un résumé écrit à la main, que personne ne doit perdre.",
        "language": "fr",
        "webLinks": "https://exemple.test/a,https://exemple.test/b",
        "isbn": "9782505064077",
        "releaseDate": "2019-05-07T00:00:00",
        "ageRating": 12,
        "coverImage": "chapter4242.jpg",
        "coverImageLocked": True,
        "genres": [{"id": 1, "title": "Aventure"}, {"id": 2, "title": "Fantasy"}],
        "tags": [{"id": 9, "title": "Dragons"}],
    }
    for index, key in enumerate(PEOPLE_KEYS):
        chapter[key] = [{"id": 100 + index, "name": f"Personne {key}"}]
    for key in LOCK_KEYS:
        chapter[key] = True
    chapter.update(MATCHED_EXTERNAL_IDS)
    return chapter


def test_changing_one_field_leaves_every_other_one_untouched():
    """Le test qui protège les bibliothèques : on ne touche qu'au résumé."""
    current = _full_chapter()

    dto = build_update_chapter_dto(current, {"summary": "Nouveau résumé"})
    split_written_fields(dto)

    assert dto["summary"] == "Nouveau résumé"

    # L'ordre de lecture, d'abord : 0 renverrait le tome en tête de série.
    assert dto["sortOrder"] == 3.5

    assert dto["titleName"] == "Le Sceau du dragon"
    assert dto["language"] == "fr"
    assert dto["webLinks"] == "https://exemple.test/a,https://exemple.test/b"
    assert dto["isbn"] == "9782505064077"
    assert dto["releaseDate"] == "2019-05-07T00:00:00"
    assert dto["ageRating"] == 12

    assert dto["genres"] == [{"title": "Aventure"}, {"title": "Fantasy"}]
    assert dto["tags"] == [{"title": "Dragons"}]

    for key in PEOPLE_KEYS:
        assert dto[key] == [{"name": f"Personne {key}"}], f"{key} perdu en route"

    for key in LOCK_KEYS:
        assert dto[key] is True, f"{key} rouvert : le prochain scan écrasera le champ"

    for key, value in MATCHED_EXTERNAL_IDS.items():
        assert dto[key] == value, f"{key} perdu : correspondance Kavita+ détruite"


def test_a_matched_chapter_keeps_all_seven_external_ids():
    """Le piège : `UpdateChapterDto` porte les sept identifiants de correspondance
    externe, et le contrôleur appelle `SetExternalMetadataIds` sans condition, qui
    fait `entity.X = dto.X ?? 0`. Une clé absente du JSON n'est donc pas « laisse
    ce champ tranquille » mais « remets-le à zéro ». Kavita répond 200 : la perte
    est silencieuse, et une seule écriture de résumé de tome suffit à couper le
    chapitre de ses notes et avis Kavita+."""
    dto = build_update_chapter_dto(_full_chapter(), {"summary": "Nouveau résumé"})
    split_written_fields(dto)

    assert {key: dto[key] for key in EXTERNAL_ID_KEYS} == MATCHED_EXTERNAL_IDS


def test_a_chapter_without_external_ids_keeps_kavitas_own_zeroes():
    """Kavita rend `0` pour « pas d'identifiant », et `0 ?? 0` vaut `0` : la valeur
    lue se renvoie telle quelle. La transformer — en `None`, ou en l'omettant sur
    un `0` — n'apporterait rien et brouillerait la comparaison avec l'état lu."""
    unmatched = {key: 0 for key in EXTERNAL_ID_KEYS}
    unmatched["comicVineId"] = None

    dto = build_update_chapter_dto({"id": 7, **unmatched}, {})
    split_written_fields(dto)

    assert {key: dto[key] for key in EXTERNAL_ID_KEYS} == unmatched


def test_every_field_the_dto_carries_is_present_in_the_payload():
    """Un champ oublié est un champ effacé : la liste est vérifiée en entier."""
    dto = build_update_chapter_dto(_full_chapter(), {})
    split_written_fields(dto)

    expected = {
        "id",
        "summary",
        "titleName",
        "language",
        "webLinks",
        "isbn",
        "releaseDate",
        "ageRating",
        "sortOrder",
        "genres",
        "tags",
        *PEOPLE_KEYS,
        *LOCK_KEYS,
        *EXTERNAL_ID_KEYS,
    }
    assert expected <= set(dto), f"absents du payload : {sorted(expected - set(dto))}"


def test_an_empty_chapter_stays_empty_rather_than_becoming_null():
    """Kavita n'accepte pas `null` là où il attend une chaîne ou une liste."""
    dto = build_update_chapter_dto({"id": 7}, {})
    split_written_fields(dto)

    assert dto["summary"] == ""
    assert dto["titleName"] == ""
    assert dto["language"] == ""
    assert dto["webLinks"] == ""
    assert dto["isbn"] == ""
    assert dto["releaseDate"] == EMPTY_DATE
    assert dto["ageRating"] == 0
    assert dto["genres"] == []
    for key in PEOPLE_KEYS:
        assert dto[key] == []
    for key in LOCK_KEYS:
        assert dto[key] is False


def test_the_chapter_payload_does_not_carry_a_cover_image_lock():
    """`UpdateChapterDto` ne porte pas de `CoverImageLocked` et
    `ChapterController` ne touche jamais au verrou de couverture d'un chapitre :
    contrairement au chemin série (BF106 / BF122), l'omettre ne détruit rien. La
    clé était simplement ignorée — l'envoyer donnait l'illusion d'une protection.
    En lecture, `ChapterDto.CoverImageLocked` existe bien, et l'aperçu s'y fie."""
    dto = build_update_chapter_dto({"id": 42, "coverImageLocked": True}, {})
    split_written_fields(dto)

    assert "coverImageLocked" not in dto
    assert "coverImageLocked" not in LOCK_KEYS


class TestCreditsPolicy:
    """`ChapterController` n'inspecte AUCUN verrou avant d'assigner les treize
    collections de personnes : ce que MetaKavita envoie est écrit, et Kavita répond
    200. La politique « on ne comble que les vides » doit donc être appliquée avant
    l'envoi — c'est la seule écriture du module qu'aucun garde-fou serveur ne
    rattrape."""

    def test_an_empty_collection_is_filled(self):
        current = {"id": 42, "writers": []}

        assert credits_to_write(current, {"writers": ["Autrice"]}) == {"writers": ["Autrice"]}

    def test_a_locked_collection_is_left_alone(self):
        current = {"id": 42, "writers": [], "writerLocked": True}

        assert credits_to_write(current, {"writers": ["Autrice"]}) == {}

    def test_a_collection_kavita_already_filled_is_left_alone(self):
        current = {"id": 42, "writers": [{"name": "Corrigée à la main"}]}

        assert credits_to_write(current, {"writers": ["Autrice"]}) == {}

    def test_force_lifts_both_guards(self):
        current = {"id": 42, "writers": [{"name": "Corrigée à la main"}], "writerLocked": True}

        assert credits_to_write(current, {"writers": ["Autrice"]}, force=True) == {
            "writers": ["Autrice"]
        }

    def test_a_collection_the_chapter_does_not_carry_is_ignored(self):
        """`UpdateChapterDto` n'a que treize collections : une clé inventée par un
        fournisseur ne doit pas se retrouver dans le payload."""
        assert credits_to_write({"id": 42}, {"illustrators": ["Quelqu'un"]}) == {}

    def test_an_empty_proposal_is_not_an_erasure(self):
        """Un fournisseur qui ne connaît personne ne doit pas vider la liste."""
        assert credits_to_write({"id": 42}, {"writers": []}) == {}
        assert credits_to_write({"id": 42}, {"writers": [""]}) == {}

    def test_anything_that_is_not_a_mapping_is_ignored(self):
        assert credits_to_write({"id": 42}, None) == {}
        assert credits_to_write({"id": 42}, ["Autrice"]) == {}


def test_a_missing_sort_order_falls_back_on_the_chapter_number():
    """Un Kavita plus ancien peut ne pas remonter sortOrder ; envoyer 0
    replacerait le tome 12 avant le tome 1."""
    dto = build_update_chapter_dto({"id": 5, "minNumber": 12.0}, {})

    assert dto["sortOrder"] == 12.0


def test_writing_a_field_locks_it():
    """Sans verrou, le prochain scan de fichiers reprend la main."""
    dto = build_update_chapter_dto(
        {"id": 5},
        {
            "title": "Tome 3",
            "summary": "Résumé",
            "release_date": "2019-05-07",
            "isbn": "9782505064077",
        },
    )
    written = split_written_fields(dto)

    assert set(written) == {"title", "summary", "release_date", "isbn"}
    assert dto["titleNameLocked"] is True
    assert dto["summaryLocked"] is True
    assert dto["releaseDateLocked"] is True
    assert dto["isbnLocked"] is True
    # Les verrous des champs qu'on n'écrit pas restent fermés.
    assert dto["genresLocked"] is False
    assert dto["writerLocked"] is False


def test_workshop_extras_land_on_the_dto_without_erasing_the_rest():
    current = _full_chapter()
    dto = build_update_chapter_dto(
        current,
        {
            "language": "en",
            "webLinks": "https://exemple.test/c",
            "ageRating": 8,
            "genres": ["Horreur"],
            "people": {"writers": ["Moi"]},
        },
    )
    written = split_written_fields(dto)
    assert set(written) >= {"language", "webLinks", "ageRating", "genres", "writers"}
    assert dto["language"] == "en"
    assert dto["languageLocked"] is True
    assert dto["webLinks"] == "https://exemple.test/c"
    assert dto["ageRating"] == 8
    assert dto["genres"] == [{"title": "Horreur"}]
    assert dto["writers"] == [{"name": "Moi"}]
    assert dto["pencillers"] == [{"name": "Personne pencillers"}]
    assert dto["summary"] == current["summary"]
    assert dto["sortOrder"] == current["sortOrder"]
    for key, value in MATCHED_EXTERNAL_IDS.items():
        assert dto[key] == value


def test_an_invalid_isbn_is_dropped_instead_of_being_announced():
    """Kavita refuse silencieusement un ISBN à clé fausse : annoncer l'écriture
    afficherait un succès pour un champ resté vide."""
    dto = build_update_chapter_dto({"id": 5, "isbn": ""}, {"isbn": "9782505064078"})
    written = split_written_fields(dto)

    assert "isbn" not in written
    assert dto["isbn"] == ""
    assert dto["isbnLocked"] is False


@pytest.mark.parametrize(
    "value, valid",
    [
        ("9782505064077", True),
        ("978-2-505-06407-7", True),
        ("2505064075", True),
        ("080442957X", True),
        ("9782505064078", False),
        ("2505064076", False),
        ("", False),
        (None, False),
        ("pas-un-isbn", False),
    ],
)
def test_isbn_check_digits(value, valid):
    assert is_valid_isbn(value) is valid


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2019-05-07", "2019-05-07T00:00:00"),
        ("2019-05", "2019-05-01T00:00:00"),
        ("2019", "2019-01-01T00:00:00"),
        (2019, "2019-01-01T00:00:00"),
        ("2019-05-07T00:00:00", "2019-05-07T00:00:00"),
        ("0001-01-01T00:00:00", None),
        ("", None),
        (None, None),
        ("bientôt", None),
        ("3019-05-07", None),
    ],
)
def test_release_date_normalisation(value, expected):
    assert normalize_release_date(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2019-02-30",       # le 30 février n'existe pas, même en année bissextile
        "2019-04-31",
        "2019-13-01",
        "Tome 2 à paraître",  # contient un « T » sans être un horodatage
        "2019-05-07T",
        "2019-02-30T00:00:00",
        "0000-01-01",
    ],
)
def test_a_date_kavita_could_not_deserialise_is_never_sent(value):
    """Le piège : `releaseDate` part dans un `DateTime` non nullable. Ce que .NET
    ne sait pas désérialiser fait rendre 400 à Kavita sur la requête entière —
    donc le titre et le résumé du même DTO sont perdus avec la date. Les anciens
    contrôles laissaient passer toute chaîne contenant un « T », et validaient le
    jour par `1 <= jour <= 31`, ce qui accepte le 30 février."""
    assert normalize_release_date(value) is None


def test_an_invalid_date_does_not_take_the_rest_of_the_chapter_down_with_it():
    """La conséquence côté utilisateur : une date incohérente ne doit pas coûter
    le résumé et le titre, qui partent dans le même DTO."""
    dto = build_update_chapter_dto(
        {"id": 42},
        {"title": "Le Sceau du dragon", "summary": "Un résumé", "release_date": "2019-02-30"},
    )
    written = split_written_fields(dto)

    assert dto["titleName"] == "Le Sceau du dragon"
    assert dto["summary"] == "Un résumé"
    assert dto["releaseDate"] == EMPTY_DATE
    assert "release_date" not in written
    assert dto["releaseDateLocked"] is False


def test_a_chapter_without_id_is_refused():
    """Sans id, Kavita répondrait « chapter doesn't exist » — autant le dire ici."""
    with pytest.raises(ValueError):
        build_update_chapter_dto({"summary": "x"}, {})
