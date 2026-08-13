"""
Politique de comblement et aperçu.

La promesse faite à l'utilisateur tient en une phrase : *on ne comble que les
vides*. Un résumé écrit à la main, un champ verrouillé, un tome déjà renseigné
par un autre outil — rien de tout cela ne bouge. Ces tests sont la formulation
exécutable de cette promesse, et de la seule exception : `VOLUME_FORCE_OVERWRITE`.

L'aperçu, lui, doit être exact *sans rien écrire* : c'est ce qui permet de le
montrer avant d'agir.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.plan import (
    SKIP_FILLED,
    SKIP_INVALID,
    SKIP_LOCKED,
    build_plan,
    changes_to_write,
    plan_unit,
)


def _unit(chapter=None, **extra):
    unit = {
        "chapter_id": 42,
        "volume_id": 7,
        "volume_number": 3,
        "chapter_number": None,
        "name": "",
        "is_special": False,
        "chapter": chapter if chapter is not None else {"id": 42},
    }
    unit.update(extra)
    return unit


PAYLOAD = {
    "title": "Le Sceau du dragon",
    "summary": "Un résumé venu du fournisseur.",
    "release_date": "2019-05-07",
    "isbn": "9782505064077",
    "cover_url": "https://cdn.test/3.jpg",
}


def test_an_empty_volume_receives_everything():
    entry = plan_unit(_unit(), PAYLOAD)

    assert entry["write_count"] == 5
    assert changes_to_write(entry) == {
        "title": "Le Sceau du dragon",
        "summary": "Un résumé venu du fournisseur.",
        "release_date": "2019-05-07T00:00:00",
        "isbn": "9782505064077",
        "cover_url": "https://cdn.test/3.jpg",
    }


def test_a_field_already_filled_is_left_alone():
    """Le cœur de la promesse : ce qui est écrit reste écrit."""
    chapter = {"id": 42, "summary": "Écrit à la main, et j'y tiens."}

    entry = plan_unit(_unit(chapter), PAYLOAD)

    assert entry["changes"]["summary"]["write"] is False
    assert entry["changes"]["summary"]["reason"] == SKIP_FILLED
    assert entry["changes"]["summary"]["current"] == "Écrit à la main, et j'y tiens."
    assert "summary" not in changes_to_write(entry)


def test_the_thumbnail_kavita_generates_does_not_pass_for_a_real_cover():
    """Kavita découpe toujours une vignette dans la première page et la range
    dans `coverImage`. La lire comme un champ rempli classait *toutes* les
    couvertures en « déjà là » : l'option existait, s'affichait, et n'écrivait
    jamais rien."""
    chapter = {"id": 42, "coverImage": "chapter-42_cover.png"}

    entry = plan_unit(_unit(chapter), PAYLOAD)

    assert entry["changes"]["cover_url"]["write"] is True
    assert changes_to_write(entry)["cover_url"] == "https://cdn.test/3.jpg"


def test_a_cover_the_user_locked_stays_in_place():
    """Le verrou est le seul signal qui distingue une couverture choisie d'une
    vignette automatique — et c'est aussi ce qui empêche la passe suivante de
    réenvoyer celle qu'on vient de poser."""
    chapter = {"id": 42, "coverImage": "à-moi.png", "coverImageLocked": True}

    entry = plan_unit(_unit(chapter), PAYLOAD)

    assert entry["changes"]["cover_url"]["reason"] == SKIP_LOCKED
    assert "cover_url" not in changes_to_write(entry)


def test_the_preview_does_not_show_kavitas_internal_file_name():
    """« Actuel : chapter-42_cover.png » ne dit rien à personne."""
    entry = plan_unit(_unit({"id": 42, "coverImage": "chapter-42_cover.png"}), PAYLOAD)

    assert entry["changes"]["cover_url"]["current"] == ""


def test_a_locked_field_is_left_alone_even_when_empty():
    """Le verrou dit « ne touche plus à ça », y compris pour combler un vide."""
    chapter = {"id": 42, "summary": "", "summaryLocked": True}

    entry = plan_unit(_unit(chapter), PAYLOAD)

    assert entry["changes"]["summary"]["reason"] == SKIP_LOCKED
    assert "summary" not in changes_to_write(entry)


def test_force_overwrite_lifts_both_rules():
    chapter = {
        "id": 42,
        "summary": "Ancien résumé",
        "summaryLocked": True,
        "titleName": "Ancien titre",
    }

    entry = plan_unit(_unit(chapter), PAYLOAD, force=True)

    written = changes_to_write(entry)
    assert written["summary"] == "Un résumé venu du fournisseur."
    assert written["title"] == "Le Sceau du dragon"


def test_an_identical_value_is_not_rewritten():
    """Réécrire à l'identique coûterait un appel Kavita pour rien."""
    chapter = {"id": 42, "titleName": "Le Sceau du dragon"}

    entry = plan_unit(_unit(chapter), PAYLOAD)

    assert entry["changes"]["title"]["write"] is False


def test_an_empty_release_date_counts_as_empty():
    """Kavita stocke « pas de date » comme le 1er janvier de l'an 1."""
    chapter = {"id": 42, "releaseDate": "0001-01-01T00:00:00"}

    entry = plan_unit(_unit(chapter), PAYLOAD)

    assert entry["changes"]["release_date"]["write"] is True


def test_an_invalid_isbn_is_shown_but_never_written():
    """Kavita le refuserait sans le dire : l'annoncer serait mentir."""
    entry = plan_unit(_unit(), {"isbn": "9782505064078"})

    assert entry["changes"]["isbn"]["write"] is False
    assert entry["changes"]["isbn"]["reason"] == SKIP_INVALID
    assert changes_to_write(entry) == {}


def test_an_unparsable_release_date_is_dropped_silently():
    entry = plan_unit(_unit(), {"release_date": "bientôt"})

    assert entry["changes"] == {}


def test_a_field_the_provider_does_not_have_is_not_proposed():
    entry = plan_unit(_unit(), {"summary": "Un résumé."})

    assert set(entry["changes"]) == {"summary"}


def test_the_selection_narrows_what_is_written():
    """L'aperçu a des cases à cocher : décocher doit vouloir dire quelque chose."""
    entry = plan_unit(_unit(), PAYLOAD)

    assert set(changes_to_write(entry, ["summary", "cover_url"])) == {"summary", "cover_url"}
    assert changes_to_write(entry, []) == {}


def test_the_plan_separates_what_the_provider_does_not_know():
    units = [
        _unit(chapter_id=1, volume_number=1),
        _unit(chapter_id=2, volume_number=2),
        _unit(chapter_id=3, volume_number=9),
    ]
    index = {"1": {"summary": "Un"}, "2": {"summary": "Deux"}}

    plan = build_plan(units, index, provider="comicvine")

    assert plan["counts"] == {
        "matched": 2,
        "unmatched": 1,
        "writable": 2,
        "fields": 2,
        "duplicates": 0,
    }
    assert plan["unmatched"][0]["volume_number"] == 9
    assert plan["provider"] == "comicvine"


def test_a_plan_where_nothing_can_be_written_says_so():
    """Une série déjà complète doit rendre un aperçu vide, pas une erreur."""
    units = [_unit(chapter_id=1, volume_number=1, chapter={"id": 1, "summary": "Déjà là"})]

    plan = build_plan(units, {"1": {"summary": "Autre"}})

    assert plan["counts"]["matched"] == 1
    assert plan["counts"]["writable"] == 0


def test_building_a_plan_writes_nothing(monkeypatch):
    """L'aperçu ne doit toucher ni Kavita ni la base : c'est sa raison d'être."""
    import db_manager
    import kavita_api

    def explode(*args, **kwargs):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("l'aperçu n'écrit rien")

    monkeypatch.setattr(db_manager, "save_volume_unit_state", explode)
    monkeypatch.setattr(kavita_api.KavitaAPI, "update_chapter_metadata", explode)
    monkeypatch.setattr(kavita_api.KavitaAPI, "upload_chapter_cover", explode)

    plan = build_plan([_unit(chapter_id=1, volume_number=1)], {"1": PAYLOAD})

    assert plan["counts"]["writable"] == 1


@pytest.mark.parametrize("field", ["title", "summary", "release_date", "isbn", "cover_url"])
def test_every_advertised_field_can_actually_be_planned(field):
    entry = plan_unit(_unit(), PAYLOAD)

    assert field in entry["changes"]
