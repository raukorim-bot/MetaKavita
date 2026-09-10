"""Pubs supporter v1 — caps, honeymoon, honor, cooldown BMC (sans licence)."""

from datetime import datetime, timedelta, timezone

from services.supporter_nag_policy import (
    BMC_COOLDOWN_SECONDS,
    HONOR_SNOOZE_DAYS,
    HONEYMOON_DAYS,
    MAX_NAGS_PER_DAY,
    MIN_ACTIVITY_THRESHOLD,
    VARIANT_IDS,
    can_show_overlay,
    eligible_variants,
    has_minimum_activity,
    honor_snoozed,
    in_honeymoon,
    is_rich_mr_session,
    lifetime_activity,
    mark_bmc_click,
    nags_today,
    pick_variant,
    record_nag_shown,
    set_honor_snooze,
    should_show_for_event,
)


def _now(day_offset=0, hour=12):
    base = datetime(2026, 7, 30, hour, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(days=day_offset)


def test_honeymoon_seven_days():
    store = {}
    assert in_honeymoon(store, _now(0)) is True
    # first visit day 0
    assert store["mk_nag_first_visit"] == "2026-07-30"
    assert in_honeymoon(store, _now(6)) is True
    assert in_honeymoon(store, _now(7)) is False


def test_honor_snooze_thirty_days():
    store = {}
    set_honor_snooze(store, _now(0))
    assert honor_snoozed(store, _now(0)) is True
    assert honor_snoozed(store, _now(HONOR_SNOOZE_DAYS - 1)) is True
    assert honor_snoozed(store, _now(HONOR_SNOOZE_DAYS) + timedelta(hours=1)) is False


def test_bmc_cooldown_blocks_overlay():
    store = {"mk_nag_first_visit": "2026-01-01", "mk_nag_lifetime_series": 10}
    assert can_show_overlay(store, _now(0)) is True
    mark_bmc_click(store, _now(0))
    assert can_show_overlay(store, _now(0)) is False
    later = _now(0) + timedelta(seconds=BMC_COOLDOWN_SECONDS + 1)
    assert can_show_overlay(store, later) is True


def test_daily_cap_max_two():
    store = {"mk_nag_first_visit": "2026-01-01", "mk_nag_lifetime_series": 10}
    assert MAX_NAGS_PER_DAY == 2
    record_nag_shown(store, variant="batch_hero", source="batch", now=_now(0))
    assert nags_today(store, _now(0)) == 1
    assert can_show_overlay(store, _now(0)) is True
    record_nag_shown(store, variant="mr_craft", source="mr_recap", now=_now(0))
    assert nags_today(store, _now(0)) == 2
    assert can_show_overlay(store, _now(0)) is False
    # jour suivant reset
    assert can_show_overlay(store, _now(1)) is True


def test_rich_mr_session_gate():
    assert is_rich_mr_session({"done": 2}) is False
    assert is_rich_mr_session({"done": 8}) is True
    assert is_rich_mr_session({"done": 5, "edits": 1, "fusions": 1}) is True
    assert is_rich_mr_session({"done": 4, "achievement_id": "sprinter"}) is True
    assert is_rich_mr_session({"done": 4, "achievement_id": "empty_session"}) is False


def test_activity_threshold_gate():
    store = {"mk_nag_first_visit": "2026-01-01"}
    # 0 activité => bloqué même après la lune de miel
    assert lifetime_activity(store) == 0
    assert has_minimum_activity(store) is False
    assert can_show_overlay(store, _now(0)) is False

    # Moins de 10 actions dans le store => bloqué
    store["mk_nag_lifetime_series"] = 6
    store["mk_nag_lifetime_reviews"] = 3  # total 9 < 10
    assert lifetime_activity(store) == 9
    assert has_minimum_activity(store) is False
    assert can_show_overlay(store, _now(0)) is False

    # Seuil 10 atteint => débloqué
    store["mk_nag_lifetime_reviews"] = 4  # total 10 >= 10
    assert lifetime_activity(store) == 10
    assert has_minimum_activity(store) is True
    assert can_show_overlay(store, _now(0)) is True

    # Détection dynamique avec le context
    store_empty = {"mk_nag_first_visit": "2026-01-01"}
    assert has_minimum_activity(store_empty, {"series_count": 10}) is True
    assert has_minimum_activity(store_empty, {"volumes_count": 10}) is True
    assert has_minimum_activity(store_empty, {"done": 10}) is True
    assert has_minimum_activity(store_empty, {"series_count": 5}) is False


def test_should_show_batch_and_mr():
    store = {"mk_nag_first_visit": "2026-01-01"}
    # Batch de 10 séries => atteint le seuil d'activité et est éligible
    assert should_show_for_event(store, {"source": "batch", "series_count": 10}, _now(0))
    # Batch de 0 série => bloqué
    assert not should_show_for_event(store, {"source": "batch", "series_count": 0}, _now(0))
    # Batch de 5 séries sans historique => bloqué car total 5 < 10
    assert not should_show_for_event(store, {"source": "batch", "series_count": 5}, _now(0))
    # Batch arrêté => bloqué
    assert not should_show_for_event(store, {"source": "batch", "series_count": 15, "stopped": True}, _now(0))

    # MR session avec store ayant déjà 10 actions
    store_ready = {"mk_nag_first_visit": "2026-01-01", "mk_nag_lifetime_reviews": 10}
    assert not should_show_for_event(store_ready, {"source": "mr_recap", "done": 1}, _now(0))
    assert should_show_for_event(store_ready, {"source": "mr_recap", "done": 8}, _now(0))


def test_pick_variant_avoids_repeat():
    store = {"mk_nag_last_variant": "batch_hero"}
    ctx = {"source": "batch", "series_count": 12, "super_enabled": True}
    eligible = eligible_variants(ctx)
    assert "batch_hero" in eligible
    assert "super_glow" in eligible
    picked = pick_variant(ctx, store)
    assert picked != "batch_hero"
    assert picked in VARIANT_IDS


def test_honor_blocks_even_after_honeymoon():
    store = {"mk_nag_first_visit": "2026-01-01", "mk_nag_lifetime_series": 10}
    set_honor_snooze(store, _now(0))
    assert can_show_overlay(store, _now(0)) is False


def test_workshop_source_policy():
    store = {"mk_nag_first_visit": "2026-01-01", "mk_nag_lifetime_reviews": 10}
    # 0 volume, 0 series => blocked
    assert not should_show_for_event(store, {"source": "workshop", "volumes_count": 0, "series_count": 0}, _now(0))
    # >= 1 volume avec seuil atteint => allowed
    assert should_show_for_event(store, {"source": "workshop", "volumes_count": 5}, _now(0))
    # >= 1 series avec seuil atteint => allowed
    assert should_show_for_event(store, {"source": "workshop", "series_count": 1}, _now(0))

    ctx = {"source": "workshop", "volumes_count": 3}
    eligible = eligible_variants(ctx)
    assert "workshop_craft" in eligible
    assert "time_saved" in eligible
    assert pick_variant(ctx, store) == "workshop_craft"


def test_constants_match_plan():
    assert HONEYMOON_DAYS == 7
    assert HONOR_SNOOZE_DAYS == 30
    assert MAX_NAGS_PER_DAY == 2
    assert MIN_ACTIVITY_THRESHOLD == 10
    assert set(VARIANT_IDS) == {
        "time_saved",
        "batch_hero",
        "mr_craft",
        "super_glow",
        "achievement_echo",
        "workshop_craft",
    }


def test_js_supporter_nag_activity_threshold_integrity():
    from pathlib import Path
    js = Path("static/js/license_nag.js").read_text(encoding="utf-8")
    assert "var MIN_ACTIVITY_THRESHOLD = 10;" in js
    assert "function lifetimeActivity()" in js
    assert "function hasMinimumActivity()" in js
    assert "if (!hasMinimumActivity()) return false;" in js
    assert "lifetimeActivity: lifetimeActivity" in js
    assert "hasMinimumActivity: hasMinimumActivity" in js
    assert "MIN_ACTIVITY_THRESHOLD: MIN_ACTIVITY_THRESHOLD" in js
