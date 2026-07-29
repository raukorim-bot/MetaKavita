"""
C7 — Statistiques ludiques pour la page /stats.

- Compteurs lifetime (`series_enriched`, `matches_won`) : télémétrie pure.
- Estimations fun (temps, cafés…) : volume organique = max(lifetime, cache / podium),
  pour rester crédible même si la télémétrie a démarré après coup.
- Cache SQLite : état actuel (file, placard, overrides…).
- Podium : `provider_stats` (un win par match utile).
"""

from typing import Optional

from scrapers import ScraperRegistry

# Constantes d'estimation (pas exposées en UI)
# Recherche + remplissage manuel d'une fiche ≈ 6 min ; comparer un hit provider ≈ 90 s.
STATS_MINUTES_PER_SERIES = 6
STATS_MINUTES_PER_MATCH = 1.5
STATS_MINUTES_PER_COFFEE = 5
STATS_CHARS_PER_SUMMARY = 420
STATS_DEEPL_EUR_PER_1K = 0.02
STATS_MINUTES_PER_NETFLIX = 45
STATS_PAGES_PER_SERIES = 160
STATS_BMC_COFFEE_EUR = 3.0


def _format_duration(total_minutes: int) -> dict:
    total_minutes = max(0, int(total_minutes))
    days = total_minutes // (60 * 24)
    rem = total_minutes % (60 * 24)
    hours = rem // 60
    minutes = rem % 60

    if days:
        display = f"{days}j {hours}h {minutes:02d}m"
    elif hours:
        display = f"{hours}h {minutes:02d}m"
    else:
        display = f"{minutes} min"

    return {
        "total_minutes": total_minutes,
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "display": display,
    }


def _estimate_minutes(series_count: int, match_count: int) -> int:
    """Temps manuel évité : fiche série + comparaison des matchs utiles."""
    raw = (
        max(0, series_count) * STATS_MINUTES_PER_SERIES
        + max(0, match_count) * STATS_MINUTES_PER_MATCH
    )
    return int(round(raw))


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
    translations_dict: Optional[dict] = None,
) -> dict:
    """
    Métriques ludiques + données pour Chart.js.

    `lifetime` : {series_enriched, matches_won, series_missed} — compteurs purs.
    `cached_data` : état actuel (file, placard, overrides, donut).
    Estimations fun : plancher sur le cache / podium si lifetime est en retard.
    `translations_dict` : titres/flavors des hauts-faits MR (optionnel).
    """
    from services.mr_achievements import evaluate_from_lifetime

    cached_data = cached_data or {}
    provider_wins = provider_wins or {}
    lifetime = lifetime or {}

    series_enriched = int(lifetime.get("series_enriched") or 0)
    matches_won = int(lifetime.get("matches_won") or 0)
    series_missed = int(lifetime.get("series_missed") or 0)
    lifetime_attempts = series_enriched + series_missed
    lifetime_hit_rate = round(100.0 * series_enriched / lifetime_attempts, 1) if lifetime_attempts else 0.0

    manual_reviews = int(lifetime.get("manual_reviews") or 0)
    manual_skips = int(lifetime.get("manual_skips") or 0)
    manual_top1_accepts = int(lifetime.get("manual_top1_accepts") or 0)
    manual_score_sum = float(lifetime.get("manual_score_sum") or 0)
    manual_field_edits = int(lifetime.get("manual_field_edits") or 0)
    manual_avg_score = (manual_score_sum / manual_reviews) if manual_reviews else 0.0
    manual_top1_rate = (manual_top1_accepts / manual_reviews) if manual_reviews else 0.0

    # --- État actuel (cache) ---
    completed = sum(1 for v in cached_data.values() if v.get("status") == "COMPLETED")
    pending = sum(1 for v in cached_data.values() if v.get("status") == "PENDING")
    pending_review = sum(1 for v in cached_data.values() if v.get("status") == "PENDING_REVIEW")
    not_found = sum(1 for v in cached_data.values() if v.get("status") == "NOT_FOUND")
    ignored = sum(1 for v in cached_data.values() if v.get("status") == "IGNORED")
    total = len(cached_data)

    decided = completed + not_found
    success_rate = round(100.0 * completed / decided, 1) if decided else 0.0
    completion_pct = round(100.0 * completed / total, 1) if total else 0.0

    provider_wins_total = sum(int(w) for w in provider_wins.values() if w)

    # Volume organique pour les estimations : jamais sous le réel visible
    estimate_series = max(series_enriched, completed)
    estimate_matches = max(matches_won, provider_wins_total)
    estimates_use_cache_floor = (
        estimate_series > series_enriched or estimate_matches > matches_won
    )
    if series_enriched:
        avg_matches = round(matches_won / series_enriched, 2)
    elif estimate_series:
        avg_matches = round(estimate_matches / estimate_series, 2)
    else:
        avg_matches = 0.0

    # --- Estimations fun ---
    time_minutes = _estimate_minutes(estimate_series, estimate_matches)
    duration = _format_duration(time_minutes)
    coffees = round(time_minutes / STATS_MINUTES_PER_COFFEE, 1) if time_minutes else 0.0
    deepl_eur = (estimate_series * STATS_CHARS_PER_SUMMARY * STATS_DEEPL_EUR_PER_1K) / 1000.0
    netflix_eps = round(time_minutes / STATS_MINUTES_PER_NETFLIX, 1) if time_minutes else 0.0
    manga_pages = estimate_series * STATS_PAGES_PER_SERIES
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

    # Hit rate organique : lifetime si dispo, sinon cache decided
    organic_hit_rate = lifetime_hit_rate
    if lifetime_attempts == 0 and decided:
        organic_hit_rate = success_rate

    charts = {
        "status": {
            "labels": ["COMPLETED", "PENDING", "PENDING_REVIEW", "NOT_FOUND", "IGNORED"],
            "values": [completed, pending, pending_review, not_found, ignored],
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
            "values": (
                [series_enriched, series_missed]
                if lifetime_attempts
                else [completed, not_found]
            ),
        },
    }

    return {
        "series_enriched": series_enriched,
        "matches_won": matches_won,
        "series_missed": series_missed,
        "avg_matches": avg_matches,
        "lifetime_hit_rate": organic_hit_rate,
        "manual_reviews": manual_reviews,
        "manual_skips": manual_skips,
        "manual_top1_accepts": manual_top1_accepts,
        "manual_score_sum": manual_score_sum,
        "manual_field_edits": manual_field_edits,
        "manual_avg_score": round(manual_avg_score, 4),
        "manual_top1_rate": round(manual_top1_rate, 4),
        "estimate_series": estimate_series,
        "estimate_matches": estimate_matches,
        "estimates_use_cache_floor": estimates_use_cache_floor,
        "completed": completed,
        "pending": pending,
        "pending_review": pending_review,
        "not_found": not_found,
        "ignored": ignored,
        "total": total,
        "time_saved": duration,
        "coffees_avoided": coffees,
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
        "mr_achievements": evaluate_from_lifetime(lifetime, translations_dict),
    }
