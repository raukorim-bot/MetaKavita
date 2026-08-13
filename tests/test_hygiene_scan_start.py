"""
Inventaire : un thread qui ne démarre pas ne doit pas condamner la fonction.

`_state["running"]` était posé AVANT `t.start()`, sans filet. Un conteneur à
court de threads rendait donc un 500 non géré, puis tous les clics suivants sur
« Analyser » répondaient 409 pour toujours : `cancel_hygiene_scan()` ne répare
rien (il exige `running`), et seul un redémarrage du conteneur débloquait. Le
module frère traite exactement ce cas et documente pourquoi — voir
`services/volume_enrichment/job.py::start_volume_enrich`.
"""
from __future__ import annotations

import threading

import pytest

from services.library_audit import hygiene_scan as hs


@pytest.fixture(autouse=True)
def _idle_state():
    """L'état du scan est un global de module partagé par toute la suite."""
    with hs._lock:
        hs._state.update({"running": False, "error": None, "cancelled": False})
    yield
    with hs._lock:
        hs._state.update({"running": False, "error": None, "cancelled": False})


@pytest.fixture
def no_thread_available(monkeypatch):
    def refuse(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuse)


def test_a_scan_that_cannot_start_says_so_instead_of_raising(no_thread_available):
    result = hs.start_hygiene_scan("1")

    assert result["success"] is False
    assert "thread" in result["error"]


def test_a_scan_that_could_not_start_leaves_the_button_usable(no_thread_available):
    """Le symptôme : le 409 définitif. Sans remise à zéro de `running`, plus
    aucune analyse n'était acceptée avant un redémarrage."""
    hs.start_hygiene_scan("1")

    assert hs.get_hygiene_scan_state()["running"] is False
    assert hs.cancel_hygiene_scan() == {"success": False, "running": False}


def test_the_reason_is_readable_from_the_state(no_thread_available):
    hs.start_hygiene_scan("1")

    assert hs.get_hygiene_scan_state()["error"]


def test_a_scan_that_starts_is_still_reported_as_started(monkeypatch):
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name))

    result = hs.start_hygiene_scan("1", mode="incremental")

    assert result == {"success": True, "started": True, "mode": "incremental"}
    assert started == ["hygiene-scan"]
    assert hs.get_hygiene_scan_state()["running"] is True
