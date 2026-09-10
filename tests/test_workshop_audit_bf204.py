"""BF204 — Audit de l'Atelier : brouillons réglés, pastilles d'état, refus.

Huit correctifs issus d'un audit en lecture seule de l'Atelier, vérifiés ici un
par un. Le fil rouge est le même partout : un envoi qui n'avait rien à écrire
n'est pas un envoi raté, et le seul `DONE` ne suffisait pas à dire qu'une carte
était réglée.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from db_manager import (
    get_volume_unit_overrides,
    get_workshop_series_override,
    save_volume_unit_override,
    save_workshop_series_override,
)
from kavita_api import KavitaRefusal
from services.workshop import (
    confirm_volume_review,
    reset_workshop,
    send_selection,
    send_series,
    send_volume,
    workshop_payload,
)
from tests.test_workshop_volume_fixes import DummyKavita

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def free_writes(monkeypatch):
    """Aucune passe en cours, verrou de série toujours accordé."""
    monkeypatch.setattr(
        "services.volume_enrichment.job.claim_series_write", lambda sid: True
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.release_series_write", lambda sid: None
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.get_volume_enrich_state",
        lambda: {"running": False},
    )


# ---------------------------------------------------------------------------
# 1. Fiche série : un envoi sans objet consomme le brouillon
# ---------------------------------------------------------------------------

def test_send_series_noop_consumes_draft(isolated_db, free_writes):
    """Rien à écrire = plus rien à garder : sinon la fiche restait « modifiée ».

    Le brouillon survivait au retour anticipé, `workshop_payload` le renvoyait en
    `series.override`, et l'interface remarquait la carte à chaque rechargement —
    sans qu'aucun envoi ne puisse jamais la nettoyer.
    """
    dummy = DummyKavita()
    save_workshop_series_override(1, {"summary": "Original series summary"})

    res = send_series(dummy, 1, {"summary": "Original series summary"}, force=True)

    assert res["noop"] is True
    assert res["settled"] is True
    assert get_workshop_series_override(1) is None
    assert workshop_payload(dummy, 1)["series"]["override"] == {}


def test_send_series_refusal_keeps_draft(isolated_db, free_writes):
    """Un refus structurel (BF203) est l'exception : le brouillon reste éditable."""

    class Refusing(DummyKavita):
        def update_series_general(self, series_id, **kwargs):
            return False, KavitaRefusal(
                "Une autre série de cette bibliothèque utilise déjà ce nom",
                "localized_name_exists",
            ), False

    dummy = Refusing()
    save_workshop_series_override(1, {"localizedName": "Collision"})

    res = send_series(dummy, 1, {"localizedName": "Collision"}, force=True)

    assert res["noop"] is True
    assert res["settled"] is False
    assert res["warning"]
    assert get_workshop_series_override(1) is not None


# ---------------------------------------------------------------------------
# 2. Tome : `_staged` levé dès que Kavita détient ce que la carte promettait
# ---------------------------------------------------------------------------

def test_send_volume_noop_settles_staged_override(isolated_db, free_writes):
    """Un tome stagé dont l'envoi n'écrit rien cesse d'être un brouillon.

    Tant que `_staged` subsistait, la carte restait marquée modifiée ET
    `overlay_overrides` écartait l'override de la passe automatique.
    """
    dummy = DummyKavita()
    save_volume_unit_override(
        1,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/ref",
        payload={"title": "Romance Dawn", "_staged": True},
    )

    res = send_volume(dummy, 1, 10, edits={"title": "Romance Dawn"}, force=True)

    assert res["noop"] is True
    assert res["settled"] is True
    assert "_staged" not in (get_volume_unit_overrides(1)[10]["payload"])
    assert workshop_payload(dummy, 1)["units"][0]["override"]["payload"].get("_staged") is None


def test_settling_an_empty_override_drops_the_row(isolated_db, free_writes):
    """Un override qui ne portait que son drapeau disparaît au lieu de survivre vide."""
    dummy = DummyKavita()
    save_volume_unit_override(1, 10, payload={"_staged": True})

    send_volume(dummy, 1, 10, edits={}, force=True)

    assert 10 not in get_volume_unit_overrides(1)


def test_send_volume_refused_cover_is_not_a_noop(isolated_db, free_writes, monkeypatch):
    """Une jaquette refusée n'est pas « rien à modifier ».

    `apply_entry` rend `SKIPPED` avec un motif quand le texte n'avait rien à
    écrire et que le téléversement a échoué. Le compter comme un envoi sans objet
    annonçait un succès et effaçait le brouillon à rejouer.
    """
    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "SKIPPED", "written": [], "error": "cover refused"},
    )
    dummy = DummyKavita()
    save_volume_unit_override(
        1, 10, payload={"cover_url": "https://example.com/c.jpg", "_staged": True}
    )

    res = send_volume(dummy, 1, 10, edits={}, force=True)

    assert res["success"] is False
    assert res["noop"] is False
    assert res["settled"] is False
    assert get_volume_unit_overrides(1)[10]["payload"]["_staged"] is True


def test_send_volume_written_cover_settles(isolated_db, free_writes, monkeypatch):
    """La jaquette posée : la carte est réglée et sa jaquette stagée s'efface."""
    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "DONE", "written": ["cover"], "error": ""},
    )
    dummy = DummyKavita()
    save_volume_unit_override(
        1,
        10,
        payload={"title": "T1", "cover_url": "https://example.com/c.jpg", "_staged": True},
    )

    res = send_volume(dummy, 1, 10, edits={}, force=True)

    assert res["settled"] is True
    payload = get_volume_unit_overrides(1)[10]["payload"]
    assert "cover_url" not in payload and "_staged" not in payload


# ---------------------------------------------------------------------------
# 3. Origine de run : seulement sur une écriture Kavita
# ---------------------------------------------------------------------------

def test_send_selection_without_write_does_not_record_run_origin(
    isolated_db, free_writes, monkeypatch
):
    """Invariant de l'atelier, que la sélection enfreignait sans condition."""
    origins = []
    monkeypatch.setattr("services.workshop.record_run_origin", origins.append)
    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "SKIPPED", "written": [], "error": ""},
    )

    send_selection(DummyKavita(), 1, [{"chapter_id": 10, "edits": {}}], force=True)
    assert origins == []

    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "DONE", "written": ["title"], "error": ""},
    )
    send_selection(DummyKavita(), 1, [{"chapter_id": 10, "edits": {}}], force=True)
    assert origins == ["workshop"]


# ---------------------------------------------------------------------------
# 4. Réinitialisation : le seul chemin Meta qui n'était pas verrouillé
# ---------------------------------------------------------------------------

def test_reset_refuses_while_a_pass_writes_the_same_series(isolated_db, monkeypatch):
    """Effacer `volume_unit_cache` sous une passe lui retirait sa reprise en plein vol."""
    monkeypatch.setattr(
        "services.volume_enrichment.job.get_volume_enrich_state",
        lambda: {"running": True, "series_id": 1},
    )
    res = reset_workshop(DummyKavita(), 1)
    assert res["success"] is False
    assert res["busy"] is True


def test_reset_ignores_a_pass_on_another_series(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.job.get_volume_enrich_state",
        lambda: {"running": True, "series_id": 99},
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.claim_series_write", lambda sid: True
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.release_series_write", lambda sid: None
    )
    assert reset_workshop(DummyKavita(), 1)["success"] is True


# ---------------------------------------------------------------------------
# 5. Le candidat de Review vient du corps de la requête : il se valide
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hostile", ["javascript:alert(1)", "file:///etc/passwd", "  "])
def test_confirm_volume_review_rejects_non_http_urls(isolated_db, hostile):
    """`provider_ref` finit en `href`, `cover_url` en appel sortant du serveur."""
    res = confirm_volume_review(
        None,
        42,
        10,
        {"title": "T1", "cover_url": hostile, "provider_ref": hostile, "provider": "X"},
    )

    assert res["cover_url"] == ""
    ov = get_volume_unit_overrides(42)[10]
    assert ov["provider_ref"] == ""
    assert "cover_url" not in ov["payload"]


def test_confirm_volume_review_keeps_http_urls(isolated_db):
    res = confirm_volume_review(
        None,
        42,
        10,
        {
            "title": "T1",
            "cover_url": "https://example.com/c.jpg",
            "provider_ref": "https://example.com/item",
        },
    )
    assert res["cover_url"] == "https://example.com/c.jpg"
    assert get_volume_unit_overrides(42)[10]["provider_ref"] == "https://example.com/item"


def test_send_volume_never_fetches_a_non_http_cover(isolated_db, free_writes):
    """`upload_chapter_cover` va chercher l'image : l'URL se filtre avant l'envoi."""
    seen = {}

    class Api(DummyKavita):
        def upload_chapter_cover(self, chapter_id, url, lock=True):
            seen["url"] = url
            return True, "ok"

    res = send_volume(Api(), 1, 10, edits={}, cover_url="javascript:alert(1)", force=True)
    assert "url" not in seen
    # Une URL écartée n'est pas une jaquette en attente : la carte se solde quand même.
    assert res["settled"] is True


# ---------------------------------------------------------------------------
# 6. Contrats de surface : ce que le front lit doit exister
# ---------------------------------------------------------------------------

def test_volume_card_reads_the_persisted_unit_state():
    """`u.status` n'a jamais existé : le payload porte `state`."""
    js = (ROOT / "static" / "js" / "volumes.js").read_text(encoding="utf-8")
    assert "u.state && u.state.status" in js
    assert "u.status ||" not in js
    # Chaîne française en dur, servie telle quelle à l'interface anglaise.
    assert "status_stage" not in js
    assert "'Brouillon'" not in js


def test_unit_status_keys_exist_in_both_languages():
    from translations import translations

    keys = [
        "workshop_unit_staged",
        "workshop_unit_done",
        "workshop_unit_pending",
        "workshop_unit_failed",
        "workshop_unit_skipped",
        "workshop_unit_nothing",
    ]
    for key in keys:
        assert translations["fr"].get(key), key
        assert translations["en"].get(key), key
        # Le gabarit de l'atelier n'exporte que certains préfixes.
        assert key.startswith("workshop_")


def test_every_unit_status_has_a_chip_style():
    js = (ROOT / "static" / "js" / "volumes.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "workshop" / "_volume-cards.css").read_text(
        encoding="utf-8"
    )
    block = re.search(r"UNIT_STATUS_KEYS\s*=\s*\{(.*?)\}", js, re.S).group(1)
    for status in re.findall(r"^\s*([A-Z_]+):", block, re.M):
        assert f".workshop-status-chip--{status.lower()}" in css, status


def test_volume_review_hides_every_series_footer_button():
    """La revue de tome emprunte la modale de série : rien de son pied ne doit rester."""
    modal = (ROOT / "templates" / "partials" / "_manual_review_modal.html").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "static" / "css" / "workshop" / "_modals.css").read_text(encoding="utf-8")
    footer = modal.split('class="modal-footer mr-footer"', 1)[1]
    buttons = set(re.findall(r'id="(mr[A-Za-z]+)"', footer))
    kept = {"mrVolumeConfirmBtn"}
    for button in buttons - kept:
        assert f'#manualReviewModal[data-kind="volume"] #{button}' in css, button


def test_volume_actions_report_network_failures():
    """Magic et Réinitialiser partaient sans filet : une coupure ne disait rien."""
    js = (ROOT / "static" / "js" / "volumes.js").read_text(encoding="utf-8")
    for marker in ("/workshop/magic", "/volume-enrich/reset"):
        block = js.split(marker, 1)[1][:1400]
        assert ".catch(" in block, marker


def test_disabled_pick_button_looks_disabled():
    """Sans candidat, `openVolumeReview` désactive Choisir — il faut que ça se voie."""
    css = (ROOT / "static" / "css" / "workshop" / "_modals.css").read_text(encoding="utf-8")
    block = css.split("#mrVolumeConfirmBtn:disabled", 1)
    assert len(block) == 2, "aucune règle :disabled sur le bouton Choisir"
    assert "cursor: not-allowed" in block[1][:200]


def test_volume_history_uses_volume_field_labels():
    """« Résumé de la série » sous « T. 5 » : le journal d'un tome a ses libellés."""
    js = (ROOT / "static" / "js" / "volumes.js").read_text(encoding="utf-8")
    assert "function unitFieldLabel(key)" in js
    assert "h.chapter_id == null ? fieldLabel : unitFieldLabel" in js
