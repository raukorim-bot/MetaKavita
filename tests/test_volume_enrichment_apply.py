"""
Exécution d'un plan d'enrichissement.

Le point sensible : on relit le chapitre juste avant d'écrire. Le plan a pu être
construit il y a dix minutes, et `UpdateChapterDto` remplace tout — partir d'un
état périmé effacerait ce qui a été ajouté depuis. Un `GET` qui échoue doit donc
annuler l'écriture, jamais la laisser passer sur un dict vide.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.apply import apply_entry, apply_plan
from services.volume_enrichment.plan import build_plan


class FakeApi:
    """Kavita en mémoire : ce qu'on lui envoie est ce qu'on relit."""

    def __init__(self, chapters=None, fail_read=(), fail_write=()):
        self.chapters = chapters or {}
        self.fail_read = set(fail_read)
        self.fail_write = set(fail_write)
        self.written = []
        self.covers = []

    def get_chapter(self, chapter_id):
        if chapter_id in self.fail_read:
            return None
        return dict(self.chapters.get(chapter_id) or {"id": chapter_id})

    def update_chapter_metadata(self, dto):
        if dto["id"] in self.fail_write:
            return False, "Code 500"
        self.written.append(dto)
        self.chapters[dto["id"]] = dict(dto)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        self.covers.append((chapter_id, url, lock))
        return True, "ok"


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Le cache d'unités a ses propres tests ; ici il ne doit pas gêner."""
    saved = []
    monkeypatch.setattr(
        "services.volume_enrichment.apply.save_volume_unit_state",
        lambda *a, **kw: saved.append((a, kw)),
    )
    return saved


def _entry(chapter_id=42, **changes):
    base = {"title": "T", "summary": "S"}
    base.update(changes)
    return {
        "chapter_id": chapter_id,
        "volume_id": 7,
        "volume_number": 3,
        "chapter_number": None,
        "provider_ref": "4000-1",
        "changes": {
            field: {"proposed": value, "current": "", "write": True, "reason": ""}
            for field, value in base.items()
        },
        "write_count": len(base),
    }


def test_the_chapter_is_read_before_being_written():
    """Sans relecture, l'écriture effacerait les treize collections de personnes."""
    api = FakeApi({42: {"id": 42, "writers": [{"name": "Autrice"}], "sortOrder": 3.5}})

    result = apply_entry(api, 7, _entry())

    assert result["status"] == "DONE"
    sent = api.written[0]
    assert sent["writers"] == [{"name": "Autrice"}]
    assert sent["sortOrder"] == 3.5


def test_a_failed_read_cancels_the_write():
    """Un chapitre illisible et une écriture quand même partie, c'est un tome vidé."""
    api = FakeApi(fail_read={42})

    result = apply_entry(api, 7, _entry())

    assert result["status"] == "FAILED"
    assert result["error"] == "chapter-read-failed"
    assert api.written == []


def test_what_was_filled_since_the_preview_is_not_overwritten():
    """L'aperçu date d'il y a dix minutes ; l'utilisateur a pu écrire entretemps."""
    api = FakeApi({42: {"id": 42, "summary": "Écrit depuis l'aperçu"}})

    result = apply_entry(api, 7, _entry())

    assert api.written[0]["summary"] == "Écrit depuis l'aperçu"
    assert "summary" not in result["written"]
    assert "title" in result["written"]


def test_what_was_locked_since_the_preview_is_not_overwritten():
    api = FakeApi({42: {"id": 42, "summaryLocked": True}})

    apply_entry(api, 7, _entry())

    assert api.written[0]["summary"] == ""


def test_force_writes_over_what_appeared_since_the_preview():
    api = FakeApi({42: {"id": 42, "summary": "Ancien", "summaryLocked": True}})

    apply_entry(api, 7, _entry(), force=True)

    assert api.written[0]["summary"] == "S"


def test_a_write_failure_is_reported_and_not_counted_as_done():
    api = FakeApi(fail_write={42})

    result = apply_entry(api, 7, _entry())

    assert result["status"] == "FAILED"
    assert "500" in result["error"]


def test_the_cover_goes_through_its_own_endpoint():
    api = FakeApi()

    result = apply_entry(api, 7, _entry(cover_url="https://cdn.test/3.jpg"))

    assert api.covers == [(42, "https://cdn.test/3.jpg", True)]
    assert "cover" in result["written"]
    # La couverture ne passe pas dans le DTO texte : Kavita a un endpoint dédié.
    assert "cover_url" not in api.written[0]


def test_a_refused_cover_does_not_undo_the_text_already_written():
    api = FakeApi()
    api.upload_chapter_cover = lambda cid, url, lock=True: (False, "domaine refusé")

    result = apply_entry(api, 7, _entry(cover_url="https://evil.test/3.jpg"))

    assert result["status"] == "DONE"
    assert "summary" in result["written"]
    assert result["error"] == "domaine refusé"


def test_an_entry_with_nothing_left_to_write_is_skipped_without_a_call():
    api = FakeApi({42: {"id": 42, "summary": "Déjà", "titleName": "Déjà"}})

    result = apply_entry(api, 7, _entry())

    assert result["status"] == "SKIPPED"
    assert api.written == []


def test_credits_are_only_fetched_when_asked():
    api = FakeApi()

    apply_entry(api, 7, _entry())
    assert "writers" not in api.written[0] or api.written[0]["writers"] == []

    api2 = FakeApi()
    apply_entry(
        api2,
        7,
        _entry(),
        credits_fetcher=lambda ref: {"writers": ["Brian K. Vaughan"]},
    )
    assert api2.written[0]["writers"] == [{"name": "Brian K. Vaughan"}]
    assert api2.written[0]["writerLocked"] is True


def test_a_credits_failure_does_not_lose_the_rest():
    api = FakeApi()

    def boom(ref):
        raise ConnectionError("fournisseur injoignable")

    result = apply_entry(api, 7, _entry(), credits_fetcher=boom)

    assert result["status"] == "DONE"
    assert "summary" in result["written"]


# ===== Crédits : la politique de comblement leur vaut aussi =====
#
# `ChapterController.UpdateChapterMetadata` n'inspecte AUCUN verrou : il assigne
# les treize collections de personnes telles qu'elles arrivent, puis répond 200.
# Contrairement au chemin série, rien côté serveur ne rattrape un payload trop
# généreux — la seule protection possible est de ne pas l'envoyer. `FakeApi` se
# comporte comme lui : ce qu'on lui écrit devient l'état du chapitre, verrous ou
# pas. C'est donc l'état relu qui fait foi dans ces tests, pas le payload.
#
# Le scénario réel : l'utilisateur corrige à la main les scénaristes d'un album
# dans Kavita et ferme `writerLocked`. La passe de crédits ajoutait
# `changes["people"]` APRÈS `changes_to_write()`, donc hors politique, hors filtre
# de verrous et hors cases cochées de l'aperçu — sa liste était remplacée par
# celle de ComicVine sans que rien ne l'ait annoncé.

CORRECTED_BY_HAND = [{"name": "Scénariste corrigé à la main"}]
FROM_PROVIDER = {"writers": ["Scénariste du fournisseur"]}


def test_locked_credits_are_never_replaced_by_the_provider():
    """Le verrou est la façon dont l'utilisateur a dit « ne touche plus à ça ».
    Kavita ne le lira pas : c'est ici qu'il doit être respecté."""
    api = FakeApi({42: {"id": 42, "writers": list(CORRECTED_BY_HAND), "writerLocked": True}})

    apply_entry(api, 7, _entry(), credits_fetcher=lambda ref: FROM_PROVIDER)

    assert api.chapters[42]["writers"] == CORRECTED_BY_HAND
    assert api.chapters[42]["writerLocked"] is True


def test_credits_already_filled_in_kavita_are_left_alone():
    """« On ne comble que les vides » vaut pour les collections comme pour le
    résumé : une liste non vide, même déverrouillée, vient de quelque part."""
    api = FakeApi({42: {"id": 42, "writers": list(CORRECTED_BY_HAND)}})

    apply_entry(api, 7, _entry(), credits_fetcher=lambda ref: FROM_PROVIDER)

    assert api.chapters[42]["writers"] == CORRECTED_BY_HAND


def test_credits_fill_an_empty_collection_and_lock_it():
    """Le cas pour lequel l'option existe : Kavita ne sait rien, le fournisseur
    si. Le verrou qui suit empêche le prochain scan de fichiers de l'écraser."""
    api = FakeApi({42: {"id": 42, "writers": [], "pencillers": []}})

    apply_entry(api, 7, _entry(), credits_fetcher=lambda ref: FROM_PROVIDER)

    assert api.chapters[42]["writers"] == [{"name": "Scénariste du fournisseur"}]
    assert api.chapters[42]["writerLocked"] is True
    assert api.chapters[42]["pencillers"] == []


def test_only_the_empty_collections_are_filled_when_others_are_locked():
    """Un album peut avoir des scénaristes verrouillés et pas de dessinateurs :
    le filtre est par collection, pas tout ou rien."""
    api = FakeApi({42: {"id": 42, "writers": list(CORRECTED_BY_HAND), "writerLocked": True}})

    apply_entry(
        api,
        7,
        _entry(),
        credits_fetcher=lambda ref: {
            "writers": ["Scénariste du fournisseur"],
            "pencillers": ["Dessinateur du fournisseur"],
        },
    )

    assert api.chapters[42]["writers"] == CORRECTED_BY_HAND
    assert api.chapters[42]["pencillers"] == [{"name": "Dessinateur du fournisseur"}]


def test_force_replaces_locked_credits_like_any_other_field():
    """`VOLUME_FORCE_OVERWRITE` lève la politique pour un run — c'est le seul
    chemin par lequel une collection verrouillée peut être remplacée."""
    api = FakeApi({42: {"id": 42, "writers": list(CORRECTED_BY_HAND), "writerLocked": True}})

    apply_entry(api, 7, _entry(), force=True, credits_fetcher=lambda ref: FROM_PROVIDER)

    assert api.chapters[42]["writers"] == [{"name": "Scénariste du fournisseur"}]


def test_credits_alone_on_a_locked_collection_do_not_trigger_a_write():
    """Rien à écrire ne doit pas coûter un `POST /api/Chapter/update` : le DTO
    étant un remplacement total, chaque écriture inutile est un risque inutile."""
    api = FakeApi({
        42: {
            "id": 42,
            "titleName": "Déjà",
            "summary": "Déjà",
            "writers": list(CORRECTED_BY_HAND),
            "writerLocked": True,
        }
    })

    result = apply_entry(api, 7, _entry(), credits_fetcher=lambda ref: FROM_PROVIDER)

    assert result["status"] == "SKIPPED"
    assert api.written == []


# ===== Passe sur un plan entier =====


def _plan(count=3):
    units = [
        {
            "chapter_id": n,
            "volume_id": 100 + n,
            "volume_number": n,
            "chapter_number": None,
            "name": "",
            "is_special": False,
            "chapter": {"id": n},
        }
        for n in range(1, count + 1)
    ]
    index = {str(n): {"summary": f"Résumé {n}"} for n in range(1, count + 1)}
    return build_plan(units, index, provider="comicvine")


def test_a_plan_is_applied_unit_by_unit():
    api = FakeApi()

    result = apply_plan(api, 7, _plan())

    assert result["counts"]["done"] == 3
    assert len(api.written) == 3


def test_cancelling_stops_between_two_units():
    """L'annulation ne doit jamais couper une écriture en deux."""
    api = FakeApi()
    state = {"calls": 0}

    def cancel():
        state["calls"] += 1
        return state["calls"] > 2

    result = apply_plan(api, 7, _plan(5), should_cancel=cancel)

    assert len(api.written) == 2
    assert result["counts"]["done"] == 2


def test_one_unit_failing_does_not_stop_the_others():
    api = FakeApi(fail_write={2})

    result = apply_plan(api, 7, _plan())

    assert result["counts"]["done"] == 2
    assert result["counts"]["failed"] == 1


def test_an_unexpected_error_is_caught_and_counted():
    """Une exception d'un chapitre ne doit pas emporter la série entière."""
    api = FakeApi()

    def explode(chapter_id):
        if chapter_id == 2:
            raise RuntimeError("imprévu")
        return {"id": chapter_id}

    api.get_chapter = explode

    result = apply_plan(api, 7, _plan())

    assert result["counts"]["failed"] == 1
    assert result["counts"]["done"] == 2


def test_the_selection_restricts_units_and_fields():
    api = FakeApi()
    plan = _plan()

    apply_plan(api, 7, plan, selection={2: ["summary"]})

    assert [d["id"] for d in api.written] == [2]


def test_progress_is_reported_for_every_unit():
    api = FakeApi()
    seen = []

    apply_plan(api, 7, _plan(), on_progress=lambda pos, total, out: seen.append((pos, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_each_unit_records_its_state(_no_db):
    api = FakeApi(fail_write={2})

    apply_plan(api, 7, _plan())

    statuses = {call[0][1]: call[0][2] for call in _no_db}
    assert statuses == {1: "DONE", 2: "FAILED", 3: "DONE"}


# ===== Chronométrage =====
#
# « L'écriture prend une éternité » était le seul diagnostic disponible : rien ne
# disait si le temps partait dans la lecture du chapitre, dans l'écriture des
# métadonnées, dans le téléchargement de la couverture ou dans son envoi à
# Kavita. Au prochain « c'est lent », le journal doit désigner le coupable.


def test_chaque_unite_rend_le_temps_passe_par_etape():
    api = FakeApi()

    result = apply_entry(api, 7, _entry(cover_url="https://cdn.test/3.jpg"))

    assert set(result["timings"]) == {"read", "write", "cover"}
    assert all(seconds >= 0 for seconds in result["timings"].values())


def test_le_bilan_de_la_serie_additionne_les_etapes_de_ses_unites():
    api = FakeApi()

    result = apply_plan(api, 7, _plan(3))

    assert set(result["timings"]) == {"read", "write"}


def test_les_durees_sont_mesurees_sur_une_horloge_monotone():
    """`time.time()` recule quand l'horloge du conteneur est recalée (NTP, veille
    de l'hôte) : une étape afficherait alors une durée négative."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "services" / "volume_enrichment" / "apply.py"
    ).read_text(encoding="utf-8")

    assert "time.monotonic()" in source
    assert "time.time()" not in source


def test_a_database_failure_does_not_lose_the_write(monkeypatch):
    """Perdre la trace fait refaire l'unité à la passe suivante, ce qui est sans
    danger ; perdre l'écriture, non."""
    monkeypatch.setattr(
        "services.volume_enrichment.apply.save_volume_unit_state",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("sqlite verrouillé")),
    )
    api = FakeApi()

    result = apply_plan(api, 7, _plan(1))

    assert result["counts"]["done"] == 1
