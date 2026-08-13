"""
Chaîne complète : réponse Kavita → index fournisseur → DTO envoyé.

Les modules ont chacun leurs tests, mais c'est leur enchaînement qui écrit dans
Kavita. `UpdateChapterDto` est un remplacement total : un champ perdu entre le
plan et l'écriture ne se voit nulle part avant d'avoir vidé la fiche d'un tome —
et `sortOrder` retombé à zéro détruirait l'ordre de lecture de la série entière.

Ce fichier part donc de la réponse brute de `GET /api/Series/volumes` et vérifie
ce qui arrive réellement sur le fil.
"""
from __future__ import annotations

import copy

import pytest

from services.volume_enrichment.apply import apply_plan
from services.volume_enrichment.matching import units_from_volumes
from services.volume_enrichment.plan import build_plan

# Chapitre entièrement rempli : vingt verrous à vrai sauf celui du résumé,
# treize collections de personnes peuplées, un `sortOrder` non nul.
FULL_CHAPTER = {
    "id": 501,
    "titleName": "Le Sceau du dragon",
    "summary": "",
    "isbn": "9782205057782",
    "releaseDate": "1995-03-01T00:00:00",
    "sortOrder": 7.0,
    "minNumber": 7,
    "ageRating": 9,
    "language": "fr",
    "webLinks": "https://exemple/tome-7",
    "titleNameLocked": True,
    "summaryLocked": False,
    "isbnLocked": True,
    "releaseDateLocked": True,
    "ageRatingLocked": True,
    "languageLocked": True,
    "genresLocked": True,
    "tagsLocked": True,
    "writerLocked": True,
    "pencillerLocked": True,
    "coverArtistLocked": True,
    "genres": [{"id": 3, "title": "Aventure"}],
    "tags": [{"id": 8, "title": "Dragons"}],
    "writers": [{"id": 1, "name": "Van Hamme"}],
    "pencillers": [{"id": 2, "name": "Rosinski"}],
    "coverArtists": [{"id": 2, "name": "Rosinski"}],
    "colorists": [{"id": 4, "name": "Graza"}],
    "inkers": [],
    "letterers": [],
    "editors": [],
    "publishers": [{"id": 5, "name": "Le Lombard"}],
    "translators": [],
    "characters": [],
    "imprints": [],
    "teams": [],
    "locations": [],
}

VOLUMES = [
    {
        "id": 90,
        "minNumber": 7,
        "chapters": [copy.deepcopy(FULL_CHAPTER)],
    }
]

INDEX = {
    "7": {
        "title": "Un titre venu du fournisseur",
        "summary": "Thorgal affronte le Sceau du dragon.",
        "release_date": "2001-05-04",
        "isbn": "9782803616770",
        "cover_url": "https://exemple/couv7.jpg",
    }
}


class FakeApi:
    """Kavita en mémoire : rend le chapitre demandé et retient le DTO envoyé."""

    def __init__(self, chapter):
        self.chapter = copy.deepcopy(chapter)
        self.sent = []
        self.covers = []

    def get_chapter(self, chapter_id):
        return copy.deepcopy(self.chapter) if chapter_id == self.chapter["id"] else None

    def update_chapter_metadata(self, dto):
        self.sent.append(copy.deepcopy(dto))
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, cover_url, lock=True):
        self.covers.append((chapter_id, cover_url, lock))
        return True, "ok"


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Le cache d'unités a ses propres tests ; ici, il n'a rien à dire."""
    monkeypatch.setattr(
        "services.volume_enrichment.apply.save_volume_unit_state",
        lambda *a, **k: None,
    )


def _run(api, *, force=False, index=None):
    units = units_from_volumes(VOLUMES)
    plan = build_plan(units, index if index is not None else INDEX,
                      force=force, provider="TEST")
    return apply_plan(api, 42, plan, force=force)


# ===== Le test qui compte plus que les autres =====


def test_filling_the_summary_leaves_every_other_field_identical():
    """Le seul champ vide et déverrouillé est le résumé : rien d'autre ne doit
    bouger, et surtout pas `sortOrder`, qui porte l'ordre de lecture."""
    api = FakeApi(FULL_CHAPTER)

    _run(api)

    assert len(api.sent) == 1
    dto = api.sent[0]
    assert dto["summary"] == INDEX["7"]["summary"]
    assert dto["sortOrder"] == 7.0
    assert dto["titleName"] == "Le Sceau du dragon"
    assert dto["isbn"] == "9782205057782"
    assert dto["releaseDate"] == "1995-03-01T00:00:00"
    assert dto["ageRating"] == 9
    assert dto["language"] == "fr"
    assert dto["webLinks"] == "https://exemple/tome-7"


def test_the_thirteen_people_collections_come_back_intact():
    """Omettre `writers` d'un `UpdateChapterDto` efface tous les auteurs du tome."""
    api = FakeApi(FULL_CHAPTER)

    _run(api)

    dto = api.sent[0]
    assert [p["name"] for p in dto["writers"]] == ["Van Hamme"]
    assert [p["name"] for p in dto["pencillers"]] == ["Rosinski"]
    assert [p["name"] for p in dto["colorists"]] == ["Graza"]
    assert [p["name"] for p in dto["publishers"]] == ["Le Lombard"]
    assert [g["title"] for g in dto["genres"]] == ["Aventure"]
    assert [t["title"] for t in dto["tags"]] == ["Dragons"]


def test_the_locks_that_were_set_stay_set():
    """Un verrou retombé à faux rouvre le champ au prochain scan Kavita."""
    api = FakeApi(FULL_CHAPTER)

    _run(api)

    dto = api.sent[0]
    for lock in ("titleNameLocked", "isbnLocked", "releaseDateLocked",
                 "ageRatingLocked", "languageLocked", "genresLocked",
                 "tagsLocked", "writerLocked", "coverArtistLocked"):
        assert dto[lock] is True, f"{lock} est retombé"
    assert dto["summaryLocked"] is True, "le champ écrit doit être verrouillé"


# ===== Politique de comblement, vue de bout en bout =====


def test_a_locked_or_filled_field_is_not_rewritten():
    api = FakeApi(FULL_CHAPTER)

    _run(api)

    dto = api.sent[0]
    assert dto["titleName"] != INDEX["7"]["title"]
    assert dto["isbn"] != INDEX["7"]["isbn"]


def test_forcing_overrides_the_locks():
    """`VOLUME_FORCE_OVERWRITE` est l'échappatoire assumée du changement de
    fournisseur : sans elle, rien ne se réécrit jamais."""
    api = FakeApi(FULL_CHAPTER)

    _run(api, force=True)

    dto = api.sent[0]
    assert dto["titleName"] == INDEX["7"]["title"]
    assert dto["isbn"] == INDEX["7"]["isbn"]
    assert dto["releaseDate"].startswith("2001-05-04")
    # Même en forçant, l'ordre de lecture n'est pas un champ de métadonnées.
    assert dto["sortOrder"] == 7.0


def test_the_cover_travels_by_its_own_endpoint():
    """La couverture ne passe pas par `UpdateChapterDto` : c'est un upload."""
    api = FakeApi(FULL_CHAPTER)

    _run(api)

    assert api.covers == [(501, "https://exemple/couv7.jpg", True)]
    assert "cover_url" not in api.sent[0]


def test_a_special_volume_is_never_written():
    """Kavita range les hors-série dans le volume 100000 : les apparier par
    numéro donnerait au hors-série les métadonnées du tome… 100000."""
    volumes = [
        {
            "id": 91,
            "minNumber": 100_000,
            "isSpecial": True,
            "chapters": [{**copy.deepcopy(FULL_CHAPTER), "id": 777, "minNumber": 7}],
        }
    ]
    api = FakeApi({**FULL_CHAPTER, "id": 777})
    plan = build_plan(units_from_volumes(volumes), INDEX, force=True, provider="TEST")

    apply_plan(api, 42, plan, force=True)

    assert api.sent == []


def test_a_chapter_kavita_refuses_to_read_is_not_written_over():
    """Lire le chapitre est la condition de l'écriture : sans état courant, un
    DTO partiel effacerait tout ce que Kavita avait."""

    class Blind(FakeApi):
        def get_chapter(self, chapter_id):
            return None

    api = Blind(FULL_CHAPTER)

    result = _run(api)

    assert api.sent == []
    assert result["counts"]["failed"] == 1


def test_nothing_is_written_when_the_provider_knows_nothing():
    api = FakeApi(FULL_CHAPTER)

    result = _run(api, index={})

    assert api.sent == []
    assert api.covers == []
    assert result["counts"]["done"] == 0
