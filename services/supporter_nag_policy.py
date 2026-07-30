"""Politique pubs supporter MetaKavita (v1 — sans licence).

Miroir des règles côté client (`static/js/license_nag.js`) pour tests unitaires.
Les overlays sont purement client ; ce module documente le contrat.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

HONEYMOON_DAYS = 7
MAX_NAGS_PER_DAY = 2
HONOR_SNOOZE_DAYS = 30
BMC_COOLDOWN_SECONDS = 10 * 60
CONTINUE_DELAY_MS = 2500

VARIANT_IDS = (
    "time_saved",
    "batch_hero",
    "mr_craft",
    "super_glow",
    "achievement_echo",
)

BMC_URL = "https://buymeacoffee.com/raukorim"

# Milestones lifetime (1 pub « haut-fait » rare)
MILESTONE_SERIES = 100
MILESTONE_REVIEWS = 50


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def calendar_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).date().isoformat()


def ensure_first_visit(store: dict[str, Any], now: datetime | None = None) -> str:
    """Retourne la date ISO de 1ère visite ; l'écrit si absente."""
    key = "mk_nag_first_visit"
    existing = store.get(key)
    if existing:
        return str(existing)[:10]
    day = calendar_day(now)
    store[key] = day
    return day


def in_honeymoon(store: dict[str, Any], now: datetime | None = None) -> bool:
    first = ensure_first_visit(store, now)
    start = _parse_iso_date(first)
    if not start:
        return True
    today = _parse_iso_date(calendar_day(now))
    assert today is not None
    return (today - start).days < HONEYMOON_DAYS


def honor_snoozed(store: dict[str, Any], now: datetime | None = None) -> bool:
    until = _parse_iso_datetime(store.get("mk_nag_honor_until"))
    if not until:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now < until


def set_honor_snooze(store: dict[str, Any], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    until = now + timedelta(days=HONOR_SNOOZE_DAYS)
    iso = until.isoformat()
    store["mk_nag_honor_until"] = iso
    return iso


def bmc_cooldown_active(store: dict[str, Any], now: datetime | None = None) -> bool:
    last = _parse_iso_datetime(store.get("mk_nag_bmc_clicked_at"))
    if not last:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds() < BMC_COOLDOWN_SECONDS


def mark_bmc_click(store: dict[str, Any], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    iso = now.isoformat()
    store["mk_nag_bmc_clicked_at"] = iso
    return iso


def _day_bucket(store: dict[str, Any], day: str) -> dict[str, Any]:
    raw = store.get("mk_nag_day")
    if not isinstance(raw, dict) or raw.get("day") != day:
        bucket = {"day": day, "count": 0, "sources": []}
        store["mk_nag_day"] = bucket
        return bucket
    return raw


def nags_today(store: dict[str, Any], now: datetime | None = None) -> int:
    day = calendar_day(now)
    bucket = _day_bucket(store, day)
    try:
        return max(0, int(bucket.get("count") or 0))
    except (TypeError, ValueError):
        return 0


def record_nag_shown(
    store: dict[str, Any],
    *,
    variant: str,
    source: str,
    now: datetime | None = None,
) -> None:
    day = calendar_day(now)
    bucket = _day_bucket(store, day)
    bucket["count"] = int(bucket.get("count") or 0) + 1
    sources = bucket.get("sources")
    if not isinstance(sources, list):
        sources = []
    sources.append(source)
    bucket["sources"] = sources
    store["mk_nag_day"] = bucket
    store["mk_nag_last_variant"] = variant
    try:
        store["mk_nag_shown_count"] = int(store.get("mk_nag_shown_count") or 0) + 1
    except (TypeError, ValueError):
        store["mk_nag_shown_count"] = 1


def can_show_overlay(store: dict[str, Any], now: datetime | None = None) -> bool:
    if in_honeymoon(store, now):
        return False
    if honor_snoozed(store, now):
        return False
    if bmc_cooldown_active(store, now):
        return False
    if nags_today(store, now) >= MAX_NAGS_PER_DAY:
        return False
    return True


def is_rich_mr_session(stats: dict[str, Any]) -> bool:
    """Overlay MR seulement si session vraiment premium (CTA inline toujours OK)."""
    done = int(stats.get("done") or 0)
    edits = int(stats.get("edits") or 0)
    fusions = int(stats.get("fusions") or 0)
    researches = int(stats.get("researches") or 0)
    weak = int(stats.get("weak_picks") or 0)
    craft = edits + fusions + researches
    if done >= 8:
        return True
    if done >= 5 and craft >= 2:
        return True
    if done >= 3 and (fusions >= 1 or researches >= 2 or weak >= 2):
        return True
    ach = str(stats.get("achievement_id") or "")
    if ach and ach not in ("empty_session", "warmup", ""):
        return done >= 4
    return False


def eligible_variants(context: dict[str, Any]) -> list[str]:
    source = str(context.get("source") or "")
    out: list[str] = []
    series = int(context.get("series_count") or 0)
    done = int(context.get("done") or 0)
    super_on = bool(context.get("super_enabled"))
    ach = str(context.get("achievement_id") or "")
    lifetime_series = int(context.get("lifetime_series") or 0)
    lifetime_reviews = int(context.get("lifetime_reviews") or 0)
    milestone_hit = bool(context.get("milestone_hit"))

    if source == "batch":
        out.append("batch_hero")
        if series > 0:
            out.append("time_saved")
        if super_on:
            out.append("super_glow")
    elif source == "mr_recap":
        out.append("mr_craft")
        if done > 0:
            out.append("time_saved")
        if super_on:
            out.append("super_glow")
        if ach and ach not in ("empty_session", ""):
            out.append("achievement_echo")

    if milestone_hit or lifetime_series >= MILESTONE_SERIES or lifetime_reviews >= MILESTONE_REVIEWS:
        if "achievement_echo" not in out:
            out.append("achievement_echo")

    if not out:
        out = ["time_saved", "batch_hero"]
    return out


def pick_variant(context: dict[str, Any], store: dict[str, Any]) -> str:
    eligible = eligible_variants(context)
    last = store.get("mk_nag_last_variant")
    if last in eligible and len(eligible) > 1:
        eligible = [v for v in eligible if v != last]
    # Préférer l'angle le plus ancré au contexte
    preferred_order = {
        "batch": ["batch_hero", "super_glow", "time_saved", "achievement_echo", "mr_craft"],
        "mr_recap": ["mr_craft", "achievement_echo", "super_glow", "time_saved", "batch_hero"],
    }
    order = preferred_order.get(str(context.get("source") or ""), VARIANT_IDS)
    for vid in order:
        if vid in eligible:
            return vid
    return eligible[0]


def should_show_for_event(
    store: dict[str, Any],
    context: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    """Décision complète avant affichage overlay."""
    if not can_show_overlay(store, now):
        return False
    source = str(context.get("source") or "")
    if source == "mr_recap" and not is_rich_mr_session(context):
        return False
    if source == "batch":
        # Batch arrêté / vide : pas de nag
        if context.get("stopped"):
            return False
        if int(context.get("series_count") or 0) <= 0:
            return False
    return True
