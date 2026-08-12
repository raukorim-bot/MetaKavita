"""
Inventaire : une série dont l'analyse échoue ne doit pas être étiquetée.

Sur le chemin d'exception, le scan conservait le `has_ext = False` d'entrée de
boucle et l'écrivait en base (`series_audit_flags`) : une série qui a pourtant
un ID AniList se retrouvait dans le filtre « sans id externe », badge « — »,
alors que le compteur `no_external_id` (incrémenté seulement quand l'analyse
aboutit) disait l'inverse — l'affichage se contredisait. Même chose après une
annulation : les flags partiels étaient écrits AVANT la garde qui protège les
compteurs de bibliothèque et les doublons.
"""

from __future__ import annotations

import pytest

from services.library_audit import hygiene_scan as hs


class _FakeKavita:
    """Deux séries : la seconde fait échouer la lecture des métadonnées."""

    def __init__(self, *args, **kwargs):
        pass

    def get_all_series(self, library_id=None):
        return [{"id": 1, "name": "Berserk"}, {"id": 2, "name": "Vinland Saga"}]

    def get_series(self, series_id):
        return {"id": int(series_id), "name": f"Série {series_id}"}

    def get_library_type_for_series(self, series_id):
        return "Manga"

    def get_series_metadata(self, series_id):
        if int(series_id) == 2:
            raise RuntimeError("Kavita 503")
        return {"summary": "résumé"}

    def get_series_volumes(self, series_id):
        return []


@pytest.fixture
def scan_env(monkeypatch):
    """Isole `_run_scan` : ni réseau Kavita, ni base, ni socket."""
    written_flags = {}
    events = []

    monkeypatch.setattr(hs, "KavitaAPI", _FakeKavita)
    monkeypatch.setattr(hs, "load_config", lambda: {})
    monkeypatch.setattr(hs, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(hs, "get_inventory_excluded_ids", lambda: set())
    monkeypatch.setattr(hs, "merge_series_identity", lambda *a, **k: {"ids": {"anilist": "30002"}})
    monkeypatch.setattr(hs, "identity_has_external_id", lambda identity: True)
    monkeypatch.setattr(
        hs,
        "build_volume_report",
        lambda *a, **k: {
            "badge": "3/3",
            "completion": {"state": "complete", "missing_count": 0},
            "unit_mode": "volumes",
            "publication_status": "FINISHED",
            "stats": {"primary_count": 3},
        },
    )
    monkeypatch.setattr(hs, "save_volume_report_cache", lambda *a, **k: None)
    monkeypatch.setattr(hs, "get_volume_report_cache", lambda sid: None)
    monkeypatch.setattr(hs, "get_catalog_expected_override", lambda sid: None)
    monkeypatch.setattr(hs, "apply_catalog_override", lambda catalog, override: catalog)
    monkeypatch.setattr(hs, "list_dismissed_group_keys", lambda library_id: [])
    monkeypatch.setattr(hs, "get_dup_accept_threshold", lambda config: 0.8)
    monkeypatch.setattr(hs, "cluster_duplicate_series", lambda *a, **k: [])
    monkeypatch.setattr(hs, "save_duplicate_groups_cache", lambda *a, **k: None)
    monkeypatch.setattr(hs, "set_hygiene_library_meta", lambda *a, **k: None)
    monkeypatch.setattr(hs, "set_series_external_id_flags", written_flags.update)
    monkeypatch.setattr(hs, "_emit_progress", events.append)

    for key, value in (("done", 0), ("total", 0), ("cancelled", False), ("running", True)):
        monkeypatch.setitem(hs._state, key, value)

    return {"flags": written_flags, "events": events}


def _series_events(events):
    return [e for e in events if e.get("series_id")]


def test_une_serie_en_echec_ne_recoit_aucun_flag_id_externe(scan_env):
    hs._run_scan("1", [], False, "full")

    assert scan_env["flags"] == {1: True}, (
        "la série en échec ne doit pas être écrite « sans id externe » : "
        "son analyse n'a rien conclu, l'ancien flag reste valable"
    )


def test_la_progression_dune_serie_en_echec_naffirme_aucun_verdict(scan_env):
    hs._run_scan("1", [], False, "full")

    failed = [e for e in _series_events(scan_env["events"]) if e["series_id"] == 2]
    assert len(failed) == 1, "la série en échec doit tout de même faire avancer la barre"
    event = failed[0]
    # « — » est truthy côté JS : la ligne de la série serait réécrite avec un
    # badge vide et has_external_id=false (voir library_audit.js::_onHygieneProgress).
    assert not event.get("badge"), "badge « — » émis pour une analyse qui a échoué"
    assert event.get("has_external_id") is None, (
        "has_external_id=false émis alors que rien n'a été vérifié"
    )
    assert event.get("failed") is True


def test_une_annulation_necrit_aucun_flag_partiel(scan_env, monkeypatch):
    """La garde d'annulation protège déjà compteurs et doublons : les flags
    d'id externe, écrits avant elle, échappaient au même raisonnement."""
    calls = {"n": 0}

    def _cancel_after_first_series():
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(hs, "_cancel_requested", _cancel_after_first_series)

    hs._run_scan("1", [], False, "full")

    assert scan_env["flags"] == {}, "flags partiels écrits malgré l'annulation"
