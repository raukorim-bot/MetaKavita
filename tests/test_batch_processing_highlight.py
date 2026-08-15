"""
Le liséré violet de la série en cours ne se déduit plus du journal.

C84 a changé le libellé live en `« Titre » (id)`. L'UI comparait encore ce
qui était entre crochets au texte de `.series-name` : plus aucune ligne ne
matchait, plus de bordure, plus de suivi. Le signal existe déjà
(`batch_progress`) : il porte maintenant `series_id`, et c'est cet
identifiant qui pose `is-processing` — y compris quand la liste virtuelle
recycle le DOM.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_live_log_no_longer_guesses_the_current_series():
    ws = _read("static/js/websocket.js")

    assert "is-processing" not in ws
    assert "matchStart" not in ws
    assert "Live Highlight" not in ws


def test_the_highlight_follows_the_series_id_on_batch_progress():
    batch = _read("static/js/batch.js")

    assert "function setBatchProcessingSeries" in batch
    assert "payload.series_id" in batch
    assert "data-series-id=" in batch
    assert "setProcessing" in batch


def test_the_virtual_list_keeps_the_highlight_across_recycle():
    virt = _read("static/js/series_list.js")

    assert "function setProcessing" in virt
    assert "is-processing" in virt
    assert "setProcessing: setProcessing" in virt
    assert "processingId" in virt


def test_the_progress_emit_includes_the_series_id(mocker):
    import services.background_tasks as bg

    emitted = []

    class _Sock:
        def emit(self, ev, payload):
            emitted.append((ev, payload))

    mocker.patch("extensions.socketio", _Sock(), create=True)
    bg.broadcast_batch_progress(3, active="One Piece", series_id=5605)

    assert emitted == [(
        "batch_progress",
        {
            "remaining": 3,
            "stopped": False,
            "active": "One Piece",
            "series_id": 5605,
        },
    )]
