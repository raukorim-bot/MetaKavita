"""C96 — logique Auto-sync (flags, snapshot, filet)."""

from __future__ import annotations

import logging
import time

from config_manager import (
    clamp_auto_sync_catchup_hours,
    is_library_enabled,
    normalize_auto_sync_mode,
    normalize_auto_sync_trigger,
)


def normalize_mode(raw) -> str:
    return normalize_auto_sync_mode(raw)


def normalize_trigger(raw) -> str:
    return normalize_auto_sync_trigger(raw)


def clamp_catchup_hours(raw, default=24) -> int:
    return clamp_auto_sync_catchup_hours(raw, default)


def job_flags(config) -> dict:
    """Overrides one-shot pour `make_sync_item` selon AUTO_SYNC_MODE.

    Auto écrit même si la barre latérale a Review / Confirmer avant écriture.
    Review / Super parquent, sans force_update.
    """
    mode = normalize_mode((config or {}).get("AUTO_SYNC_MODE"))
    if mode == "super":
        return {
            "force_auto": False,
            "force_update": False,
            "super_review": True,
            "manual_review_override": False,
        }
    if mode == "review":
        return {
            "force_auto": False,
            "force_update": False,
            "super_review": False,
            "manual_review_override": True,
        }
    return {
        "force_auto": True,
        "force_update": bool((config or {}).get("AUTO_SYNC_FORCE_UPDATE")),
        "super_review": False,
        "manual_review_override": False,
    }


def _series_id(series) -> int | None:
    if not isinstance(series, dict):
        return None
    try:
        return int(series.get("id"))
    except (TypeError, ValueError):
        return None


def fetch_complete_inventory(kavita):
    """`get_all_series()` ; None si l'inventaire n'est pas complet."""
    series = kavita.get_all_series()
    if not getattr(kavita, "last_inventory_complete", False):
        return None
    return list(series or [])


def seed_known_from_inventory(series_list) -> int:
    """Écrit le snapshot, n'enfile personne. Rend 0."""
    replace_snapshot(series_list)
    return 0


def diff_added(series_list, known_ids) -> list:
    known = set()
    for raw in known_ids or []:
        try:
            known.add(int(raw))
        except (TypeError, ValueError):
            continue
    added = []
    for series in series_list or []:
        sid = _series_id(series)
        if sid is not None and sid not in known:
            added.append(series)
    return added


def filter_enqueueable(series_list, cached, queued, config) -> list:
    queued_ids = set()
    for raw in queued or []:
        try:
            queued_ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    cached = cached or {}
    out = []
    for series in series_list or []:
        sid = _series_id(series)
        if sid is None:
            continue
        if not is_library_enabled(series.get("libraryId"), config):
            continue
        row = cached.get(sid) or cached.get(str(sid)) or {}
        status = row.get("status")
        if status in ("IGNORED", "PENDING_REVIEW"):
            continue
        if sid in queued_ids:
            continue
        out.append(series)
    return out


def enqueue_auto(series_list, config) -> int:
    from services.background_tasks import (
        broadcast_auto_sync_report,
        make_sync_item,
        put_sync,
    )

    flags = job_flags(config)
    prepared = []
    for series in series_list or []:
        sid = _series_id(series)
        if sid is None:
            continue
        name = series.get("name") or str(sid)
        prepared.append((sid, name, make_sync_item(
            sid,
            name,
            flags["force_update"],
            origin="auto",
            force_auto=flags["force_auto"],
            super_review=flags["super_review"],
            manual_review_override=flags["manual_review_override"],
        )))
    if not prepared:
        return 0
    from db_manager import begin_auto_sync_run

    begin_auto_sync_run(
        normalize_trigger((config or {}).get("AUTO_SYNC_TRIGGER")),
        [(sid, name) for sid, name, _item in prepared],
    )
    for _sid, _name, item in prepared:
        put_sync(item)
    broadcast_auto_sync_report()
    return len(prepared)


def replace_snapshot(series_list) -> None:
    from db_manager import replace_auto_sync_known_ids

    ids = []
    for series in series_list or []:
        sid = _series_id(series)
        if sid is not None:
            ids.append(sid)
    replace_auto_sync_known_ids(ids)


def needs_seed(config, previous_trigger=None) -> bool:
    """True si le trigger scan n'a pas encore de snapshot, ou vient d'être choisi."""
    if normalize_trigger((config or {}).get("AUTO_SYNC_TRIGGER")) != "scan":
        return False
    if previous_trigger is not None and normalize_trigger(previous_trigger) != "scan":
        return True
    from db_manager import get_auto_sync_known_ids
    return not get_auto_sync_known_ids()


def catchup_due(last_ts, hours) -> bool:
    hours = clamp_catchup_hours(hours)
    if hours <= 0:
        return False
    if last_ts is None:
        return True
    try:
        elapsed = time.time() - float(last_ts)
    except (TypeError, ValueError):
        return True
    return elapsed >= hours * 3600


def _bg():
    from services import background_tasks as bg
    return bg


def _auth_kavita(config):
    bg = _bg()
    kavita = bg.KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    if not kavita.authenticate():
        return None
    return kavita


def run_scan_fire(config, t) -> int:
    """Un GET après un lot Kavita : n'enfile que les IDs absents du snapshot."""
    kavita = _auth_kavita(config)
    if kavita is None:
        return 0
    series = fetch_complete_inventory(kavita)
    if series is None:
        logging.warning(
            t.get(
                "log_orphans_skipped",
                "🧹 Nettoyage des orphelines ignoré : inventaire Kavita incomplet.",
            )
        )
        return 0

    from db_manager import get_auto_sync_known_ids

    bg = _bg()
    added = diff_added(series, get_auto_sync_known_ids())
    to_q = filter_enqueueable(
        added, bg.get_all_cached_data(), bg.queued_series_ids(), config
    )
    enqueued = enqueue_auto(to_q, config)
    replace_snapshot(series)
    return enqueued


def run_interval_or_catchup(config, t) -> int:
    """Poll minutes (intervalle) ou filet heures (scan). Inventaire incomplet → 0."""
    from db_manager import get_auto_sync_known_ids

    bg = _bg()
    kavita = _auth_kavita(config)
    if kavita is None:
        return 0

    logging.info(t.get("log_auto_sync_start", "🤖 [Auto-Sync] Démarrage du scan automatique..."))
    series = fetch_complete_inventory(kavita)
    if series is None:
        logging.warning(
            t.get(
                "log_orphans_skipped",
                "🧹 Nettoyage des orphelines ignoré : inventaire Kavita incomplet.",
            )
        )
        return 0

    active_ids = {sid for sid in (_series_id(s) for s in series) if sid is not None}
    bg.clean_orphaned_cache(active_ids)

    cached = bg.get_all_cached_data()
    already = bg.queued_series_ids()
    trigger = normalize_trigger((config or {}).get("AUTO_SYNC_TRIGGER"))

    added = []
    if trigger == "scan":
        added = diff_added(series, get_auto_sync_known_ids())
        replace_snapshot(series)

    candidates = bg.select_auto_sync_candidates(series, cached, config)
    by_id = {}
    for item in list(candidates) + list(added):
        sid = _series_id(item)
        if sid is not None:
            by_id[sid] = item
    to_process = filter_enqueueable(list(by_id.values()), cached, already, config)
    if not to_process:
        return 0

    skipped = len(by_id) - len(to_process)
    if skipped:
        logging.info(
            t.get(
                "log_auto_sync_already_queued",
                "⏭️ [Auto-Sync] {0} série(s) déjà en file d'attente, non réenfilée(s).",
            ).format(skipped)
        )
    logging.info(
        t.get("log_auto_sync_found", "🤖 [Auto-Sync] {0} série(s) à traiter.").format(
            len(to_process)
        )
    )
    return enqueue_auto(to_process, config)
