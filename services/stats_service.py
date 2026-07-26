"""
C7 — Statistiques ludiques pour la page /stats.

- Compteurs lifetime (`series_enriched`, `matches_won`) : estimations fun (temps, cafés…).
- Cache SQLite : état actuel de la bibliothèque (file, placard, overrides…).
- Podium : `provider_stats` (un win par match utile).
"""

from typing import Optional

from scrapers import ScraperRegistry

# Constantes d'estimation (pas exposées en UI)
STATS_MINUTES_PER_SERIES = 4
STATS_MINUTES_PER_COFFEE = 5
STATS_CHARS_PER_SUMMARY = 400
STATS_DEEPL_EUR_PER_1K = 0.02
STATS_MINUTES_PER_NETFLIX = 45
STATS_PAGES_PER_SERIES = 180
STATS_BMC_COFFEE_EUR = 3.0


def _format_duration(total_minutes: int) -> dict:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return {
        "total_minutes": total_minutes,
        "hours": hours,
        "minutes": minutes,
        "display": f"{hours}h {minutes:02d}m" if hours else f"{minutes} min",
    }


def _library_score(completed, pending, not_found, ignored, total) -> int:
    if total <= 0:
        return 0
    score = 100.0 * completed / total
    score -= 15.0 * pending / total
    score -= 10.0 * ignored / total
    score -= 20.0 * not_found / total
    return max(0, min(100, int(round(score))))


def _is_manual_override(entry: dict) -> bool:
    forced_id = (entry.get("forced_id") or "").strip()
    forced_provider = (entry.get("forced_provider") or "AUTO").strip()
    alt_langs = (entry.get("alt_title_langs") or "").strip()
    return bool(forced_id) or (forced_provider and forced_provider != "AUTO") or bool(alt_langs)


def _is_cover_protected(entry: dict) -> bool:
    raw = entry.get("targeted_fields") or "ALL"
    if raw == "ALL" or raw == "NONE":
        return False
    fields = [f.strip() for f in str(raw).split(",") if f.strip()]
    return bool(fields) and "cover" not in fields


def _is_surgical(entry: dict) -> bool:
    raw = (entry.get("targeted_fields") or "ALL").strip()
    return raw not in ("ALL", "NONE", "")


def _provider_display_name(provider_id: str) -> str:
    scraper = ScraperRegistry.get(provider_id)
    if scraper:
        return scraper.display_name
    return provider_id


def compute_playful_stats(
    cached_data: dict,
    provider_wins: Optional[dict] = None,
    lifetime: Optional[dict] = None,
) -> dict:
    """
    Métriques ludiques + données pour Chart.js.

    `lifetime` : {series_enriched, matches_won} — source des estimations fun.
    `cached_data` : état actuel (file, placard, overrides, donut).
    """
    cached_data = cached_data or {}
    provider_wins = provider_wins or {}
    lifetime = lifetime or {}

    series_enriched = int(lifetime.get("series_enriched") or 0)
    matches_won = int(lifetime.get("matches_won") or 0)
    series_missed = int(lifetime.get("series_missed") or 0)
    avg_matches = round(matches_won / series_enriched, 2) if series_enriched else 0.0
    lifetime_attempts = series_enriched + series_missed
    lifetime_hit_rate = round(100.0 * series_enriched / lifetime_attempts, 1) if lifetime_attempts else 0.0

    # --- État actuel (cache) ---
    completed = sum(1 for v in cached_data.values() if v.get("status") == "COMPLETED")
    pending = sum(1 for v in cached_data.values() if v.get("status") == "PENDING")
    not_found = sum(1 for v in cached_data.values() if v.get("status") == "NOT_FOUND")
    ignored = sum(1 for v in cached_data.values() if v.get("status") == "IGNORED")
    total = len(cached_data)

    decided = completed + not_found
    success_rate = round(100.0 * completed / decided, 1) if decided else 0.0
    completion_pct = round(100.0 * completed / total, 1) if total else 0.0

    # --- Estimations fun basées sur lifetime ---
    time_minutes = series_enriched * STATS_MINUTES_PER_SERIES
    duration = _format_duration(time_minutes)
    coffees = time_minutes / STATS_MINUTES_PER_COFFEE if time_minutes else 0.0
    deepl_eur = (series_enriched * STATS_CHARS_PER_SUMMARY * STATS_DEEPL_EUR_PER_1K) / 1000.0
    netflix_eps = round(time_minutes / STATS_MINUTES_PER_NETFLIX, 1) if time_minutes else 0.0
    manga_pages = series_enriched * STATS_PAGES_PER_SERIES
    bmc_coffees = round(deepl_eur / STATS_BMC_COFFEE_EUR, 1) if deepl_eur else 0.0

    manual_overrides = sum(1 for v in cached_data.values() if _is_manual_override(v))
    protected_covers = sum(1 for v in cached_data.values() if _is_cover_protected(v))
    forced_ids = sum(1 for v in cached_data.values() if (v.get("forced_id") or "").strip())
    forced_providers = sum(
        1 for v in cached_data.values()
        if (v.get("forced_provider") or "AUTO").strip() not in ("", "AUTO")
    )
    alt_lang_crafts = sum(1 for v in cached_data.values() if (v.get("alt_title_langs") or "").strip())
    surgical = sum(1 for v in cached_data.values() if _is_surgical(v))

    pub_localized = sum(
        1 for v in cached_data.values()
        if (v.get("publisher_pref") or "GLOBAL").strip().upper() in ("LOCALIZED", "VF", "VA", "VF/VA")
    )
    pub_original = sum(
        1 for v in cached_data.values()
        if (v.get("publisher_pref") or "GLOBAL").strip().upper() in ("ORIGINAL", "VO")
    )

    auto_completed = sum(
        1 for v in cached_data.values()
        if v.get("status") == "COMPLETED" and not _is_manual_override(v)
    )
    automation_rate = round(100.0 * auto_completed / completed, 1) if completed else 0.0

    ranked = sorted(
        ((pid, int(wins)) for pid, wins in provider_wins.items() if wins and pid),
        key=lambda x: (-x[1], x[0]),
    )
    total_provider_wins = sum(w for _, w in ranked) or 0
    provider_diversity = len(ranked)
    podium = []
    for pid, wins in ranked[:5]:
        podium.append({
            "id": pid,
            "name": _provider_display_name(pid),
            "wins": wins,
            "pct": round(100.0 * wins / total_provider_wins, 1) if total_provider_wins else 0.0,
        })

    champion = podium[0] if podium else None
    underdog = None
    if len(ranked) >= 2:
        pid, wins = ranked[-1]
        underdog = {"id": pid, "name": _provider_display_name(pid), "wins": wins}

    # Données Chart.js (JSON-friendly)
    charts = {
        "status": {
            "labels": ["COMPLETED", "PENDING", "NOT_FOUND", "IGNORED"],
            "values": [completed, pending, not_found, ignored],
        },
        "providers": {
            "labels": [p["name"] for p in podium],
            "values": [p["wins"] for p in podium],
        },
        "lifetime": {
            "labels": ["series", "matches", "missed"],
            "values": [series_enriched, matches_won, series_missed],
        },
        "hit_miss": {
            "labels": ["hit", "miss"],
            "values": [series_enriched, series_missed],
        },
    }

    return {
        "series_enriched": series_enriched,
        "matches_won": matches_won,
        "series_missed": series_missed,
        "avg_matches": avg_matches,
        "lifetime_hit_rate": lifetime_hit_rate,
        "completed": completed,
        "pending": pending,
        "not_found": not_found,
        "ignored": ignored,
        "total": total,
        "time_saved": duration,
        "coffees_avoided": round(coffees, 1),
        "deepl_eur_saved": round(deepl_eur, 2),
        "success_rate": success_rate,
        "completion_pct": completion_pct,
        "library_score": _library_score(completed, pending, not_found, ignored, total),
        "mysteries": not_found,
        "queue": pending,
        "closet": ignored,
        "manual_overrides": manual_overrides,
        "protected_covers": protected_covers,
        "forced_ids": forced_ids,
        "forced_providers": forced_providers,
        "alt_lang_crafts": alt_lang_crafts,
        "surgical": surgical,
        "pub_localized": pub_localized,
        "pub_original": pub_original,
        "automation_rate": automation_rate,
        "netflix_episodes": netflix_eps,
        "manga_pages": manga_pages,
        "bmc_coffees": bmc_coffees,
        "total_wins": total_provider_wins,
        "provider_diversity": provider_diversity,
        "champion": champion,
        "underdog": underdog,
        "podium": podium,
        "has_provider_data": bool(podium),
        "charts": charts,
    }
