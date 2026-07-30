"""Pubs supporter v1 — caps, honeymoon, honor, cooldown BMC (sans licence)."""

from datetime import datetime, timedelta, timezone

from services.supporter_nag_policy import (
    BMC_COOLDOWN_SECONDS,
    HONOR_SNOOZE_DAYS,
    HONEYMOON_DAYS,
    MAX_NAGS_PER_DAY,
    VARIANT_IDS,
    can_show_overlay,
    eligible_variants,
    honor_snoozed,
    in_honeymoon,
    is_rich_mr_session,
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
    store = {"mk_nag_first_visit": "2026-01-01"}
    assert can_show_overlay(store, _now(0)) is True
    mark_bmc_click(store, _now(0))
    assert can_show_overlay(store, _now(0)) is False
    later = _now(0) + timedelta(seconds=BMC_COOLDOWN_SECONDS + 1)
    assert can_show_overlay(store, later) is True


def test_daily_cap_max_two():
    store = {"mk_nag_first_visit": "2026-01-01"}
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


def test_should_show_batch_and_mr():
    store = {"mk_nag_first_visit": "2026-01-01"}
    assert should_show_for_event(store, {"source": "batch", "series_count": 10}, _now(0))
    assert not should_show_for_event(store, {"source": "batch", "series_count": 0}, _now(0))
    assert not should_show_for_event(store, {"source": "batch", "series_count": 5, "stopped": True}, _now(0))
    assert not should_show_for_event(store, {"source": "mr_recap", "done": 1}, _now(0))
    assert should_show_for_event(store, {"source": "mr_recap", "done": 8}, _now(0))


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
    store = {"mk_nag_first_visit": "2026-01-01"}
    set_honor_snooze(store, _now(0))
    assert can_show_overlay(store, _now(0)) is False


def test_constants_match_plan():
    assert HONEYMOON_DAYS == 7
    assert HONOR_SNOOZE_DAYS == 30
    assert MAX_NAGS_PER_DAY == 2
    assert set(VARIANT_IDS) == {
        "time_saved",
        "batch_hero",
        "mr_craft",
        "super_glow",
        "achievement_echo",
    }
