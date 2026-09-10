"""BF202 — audit Auto-sync : réveil, reconnexion, fragmentation, vague, filet."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from services import background_tasks as bg
from services import kavita_hub as hub


# ===== Réveil : la frontière thread OS / greenthread =====


def test_wait_for_wake_returns_as_soon_as_the_item_lands():
    """Le `notify()` du hub ne traverse pas la frontière eventlet : seule
    l'expiration réveille. `_wait_for_wake` découpe donc l'attente, et doit
    rendre la main bien avant `max_wait`."""
    while not bg.auto_sync_wake_queue.empty():
        bg.auto_sync_wake_queue.get_nowait()

    def _producer():
        time.sleep(0.2)
        bg.auto_sync_wake_queue.put_nowait("scan")

    threading.Thread(target=_producer, daemon=True).start()
    started = time.time()
    reason = bg._wait_for_wake(max_wait=5.0, slice_s=0.05)
    elapsed = time.time() - started

    assert reason == "scan"
    assert elapsed < 2.0, f"réveil en {elapsed:.1f}s — l'attente n'est plus découpée"


def test_wait_for_wake_times_out_without_blocking_forever():
    while not bg.auto_sync_wake_queue.empty():
        bg.auto_sync_wake_queue.get_nowait()
    started = time.time()
    assert bg._wait_for_wake(max_wait=0.3, slice_s=0.05) == "timeout"
    assert time.time() - started < 3.0


def test_wake_slices_stay_well_under_the_total_wait():
    """Une tranche aussi longue que l'attente totale rendrait le découpage
    inopérant et ramènerait la latence d'un scan à trente secondes."""
    assert 0 < bg.WAKE_POLL_S <= bg.WAKE_MAX_WAIT_S / 10


# ===== Reconnexion du hub =====


def _run_loop_collecting_waits(monkeypatch, session_duration):
    waits = []

    class _Stop:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls > 4

        def wait(self, seconds):
            waits.append(round(seconds, 3))
            self.calls += 1
            return False

    def _session(_stop):
        if session_duration:
            monkeypatch.setattr(
                hub.time, "time", _advancing_clock(session_duration), raising=False
            )
        return None

    monkeypatch.setattr(hub, "_one_session", _session)
    monkeypatch.setattr(hub, "set_hub_status", lambda *a, **k: None)
    hub.run_websocket_loop(_Stop())
    return waits


def _advancing_clock(step):
    real = time.time
    state = {"n": 0}

    def _clock():
        state["n"] += 1
        return real() + step * state["n"]

    return _clock


def test_backoff_grows_when_sessions_die_instantly(monkeypatch):
    """`_one_session` rend la main sans lever sur une fermeture immédiate :
    réarmer le backoff faisait un negotiate + handshake par seconde, sans fin."""
    waits = _run_loop_collecting_waits(monkeypatch, session_duration=0)
    assert waits[:4] == [1.0, 2.0, 4.0, 8.0], waits


def test_session_stable_threshold_is_meaningful():
    assert hub.SESSION_STABLE_S >= 10.0


# ===== Frames WebSocket =====


def _frame(payload: bytes, opcode: int, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode, len(payload)])
    return head + payload


def test_ws_feed_exposes_the_fin_bit():
    frames, rest = hub._ws_feed(_frame(b"hello", 1, fin=False))
    assert rest == b""
    assert frames == [(False, 1, b"hello")]


def test_fragmented_message_is_reassembled():
    """Un message découpé — ce que fait volontiers un reverse proxy — arrivait
    tronqué, échouait au json.loads et emportait l'événement de scan."""
    raw = _frame(b'{"type":1,', 1, fin=False) + _frame(b'"target":"ScanSeries"}', 0, fin=True)
    frames, rest = hub._ws_feed(raw)
    assert rest == b""
    assert [(f, o) for f, o, _d in frames] == [(False, 1), (True, 0)]
    rebuilt = b"".join(d for _f, _o, d in frames)
    assert rebuilt == b'{"type":1,"target":"ScanSeries"}'


def test_oversized_frame_is_refused():
    """La longueur est annoncée sur 64 bits par le pair : sans plafond, le
    tampon grossit jusqu'à épuisement mémoire."""
    header = bytes([0x81, 127]) + (hub.MAX_FRAME_BYTES + 1).to_bytes(8, "big")
    with pytest.raises(RuntimeError, match="too large"):
        hub._ws_feed(header)


def test_accept_key_matches_rfc6455_vector():
    # Vecteur de la RFC 6455 §1.3.
    assert hub._ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


# ===== Rapport de vague =====


def test_enqueue_and_finish_cannot_interleave(isolated_db, monkeypatch):
    """Ouvrir la vague puis l'enfiler doit être indivisible : une clôture
    tombant entre les deux fermait la vague à peine née, et chaque résultat
    était ensuite jeté faute de vague ouverte."""
    from db_manager import get_auto_sync_report_badge
    from services.auto_sync import enqueue_auto

    closed_during_enqueue = []
    real_put = bg.put_sync

    def _put_then_try_close(item):
        real_put(item)
        # Un autre thread tente de clore pendant que l'enfilage tient le verrou.
        done = threading.Event()

        def _closer():
            closed_during_enqueue.append(bg.try_finish_auto_sync_run(from_worker=True))
            done.set()

        threading.Thread(target=_closer, daemon=True).start()
        assert not done.wait(0.4), "la clôture n'a pas été bloquée par le verrou"

    # `enqueue_auto` importe `put_sync` depuis background_tasks à l'appel.
    monkeypatch.setattr(bg, "put_sync", _put_then_try_close)

    enqueue_auto([{"id": 4242, "name": "Vague", "libraryId": 1}], {"AUTO_SYNC_TRIGGER": "scan"})

    badge = get_auto_sync_report_badge()
    assert badge.get("running") or badge.get("counts", {}).get("pending"), badge


# ===== Filet horaire =====


def test_catchup_timestamp_survives_a_restart(isolated_db):
    """Gardé en mémoire de processus, il repartait à « jamais » à chaque
    démarrage et relançait une passe complète de l'inventaire."""
    from db_manager import get_auto_sync_catchup_at, set_auto_sync_catchup_at
    from services.auto_sync import catchup_due

    assert get_auto_sync_catchup_at() is None
    now = time.time()
    set_auto_sync_catchup_at(now)
    assert abs(get_auto_sync_catchup_at() - now) < 1.0

    # Simule un redémarrage : le module oublie, la base se souvient.
    bg._last_catchup_at = None
    bg._catchup_loaded = False
    assert catchup_due(bg._catchup_at(), 24) is False


def test_catchup_marks_and_persists(isolated_db):
    from db_manager import get_auto_sync_catchup_at

    bg._last_catchup_at = None
    bg._catchup_loaded = False
    bg._mark_catchup_done()
    assert get_auto_sync_catchup_at() is not None


# ===== Rapport côté navigateur =====


def test_report_escape_fallback_still_escapes():
    """Le repli rendait la valeur brute quand `escapeHtmlText` manquait, et le
    résultat part dans `innerHTML`."""
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "auto_sync_report.js").read_text(
        encoding="utf-8"
    )
    body = js.split("function _asrEsc(value) {", 1)[1].split("\n}", 1)[0]
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in body, f"repli sans échappement : {entity} manquant"


def test_inventory_incomplete_log_key_is_its_own():
    """Le message parlait d'un nettoyage d'orphelines qui n'était pas en jeu."""
    from translations import translations

    for lang in ("fr", "en"):
        assert "log_auto_sync_inventory_incomplete" in translations[lang]

    src = (Path(__file__).resolve().parent.parent / "services" / "auto_sync.py").read_text(
        encoding="utf-8"
    )
    assert "log_orphans_skipped" not in src


def test_wake_queue_documents_the_boundary():
    """L'invariant est invisible : rien n'empêchait de « simplifier »
    `_wait_for_wake` en un `get()` sans délai, ce qui figerait l'auto-sync."""
    src = (Path(__file__).resolve().parent.parent / "services" / "background_tasks.py").read_text(
        encoding="utf-8"
    )
    head = src.split("auto_sync_wake_queue = queue.Queue()", 1)[0]
    assert "greenthread" in head and "notify" in head
