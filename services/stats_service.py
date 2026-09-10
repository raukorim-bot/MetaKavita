"""
C7 — Statistiques ludiques pour la page /stats.

- Compteurs lifetime (`series_enriched`, `matches_won`, origines, couvertures posées, 🔒, vagues Auto-sync) : télémétrie pure.
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
STATS_PAGES_PER_VOLUME = 180  # pile des tomes écrits, pas « une série = un tankobon »
STATS_BMC_COFFEE_EUR = 3.0
STATS_MINUTES_PER_TRAIN = 120  # TGV Paris–Lyon, ordre de grandeur
STATS_MINUTES_PER_NIGHT = 480  # une nuit de 8 h
STATS_CM_PER_VOLUME = 1.6
STATS_MINUTES_TYPE_PER_VOLUME = 1  # coller titre + résumé + ISBN, pas lire le tome


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


def _library_score(
    completed, pending, not_found, ignored, total,
    needs_relock=0, pending_review=0,
) -> int:
    if total <= 0:
        return 0
    score = 100.0 * completed / total
    score -= 15.0 * pending / total
    score -= 10.0 * ignored / total
    score -= 20.0 * not_found / total
    score -= 8.0 * needs_relock / total
    score -= 5.0 * pending_review / total
    return max(0, min(100, int(round(score))))


def _is_manual_override(entry: dict) -> bool:
    forced_id = (entry.get("forced_id") or "").strip()
    forced_provider = (entry.get("forced_provider") or "AUTO").strip()
    alt_langs = (entry.get("alt_title_langs") or "").strip()
    return bool(forced_id) or (forced_provider and forced_provider != "AUTO") or bool(alt_langs)


def _is_cover_protected(entry: dict) -> bool:
    """Couverture encore protégée : le marqueur C65, pas un masque chirurgical sans cover."""
    return bool(entry.get("cover_manual"))


def _is_surgical(entry: dict) -> bool:
    from services.enrichment_engine import targeted_fields_is_granular

    return targeted_fields_is_granular(entry.get("targeted_fields"))


def _provider_display_name(provider_id: str) -> str:
    scraper = ScraperRegistry.get(provider_id)
    if scraper:
        return scraper.display_name
    return provider_id


def pick_hygiene_counts(all_meta: Optional[dict], others: Optional[list] = None) -> dict:
    """Préfère le scan « toutes les bibliothèques », sinon le plus récent."""
    if all_meta and int((all_meta.get("counts") or {}).get("series") or 0):
        return dict(all_meta.get("counts") or {})
    dated = sorted(
        others or [],
        key=lambda row: str(row.get("scanned_at") or ""),
        reverse=True,
    )
    for row in dated:
        if str(row.get("library_id") or "").lower() == "all":
            continue
        counts = row.get("counts") or {}
        if int(counts.get("series") or 0):
            return dict(counts)
    return {}


def _hygiene_snapshot(counts: Optional[dict]) -> dict:
    h = counts or {}
    series = int(h.get("series") or 0)
    return {
        "has_data": series > 0,
        "series": series,
        "healthy": int(h.get("healthy") or 0),
        "incomplete": int(h.get("incomplete") or 0),
        "unknown_expected": int(h.get("unknown_expected") or 0),
        "missing": int(h.get("missing") or 0),
        "duplicates": int(h.get("duplicates") or 0),
        "no_external_id": int(h.get("no_external_id") or 0),
        "failed": int(h.get("failed") or 0),
        "excluded": int(h.get("excluded") or 0),
    }


def _lang_palette(cached_data: dict) -> list:
    codes = set()
    for entry in (cached_data or {}).values():
        raw = entry.get("alt_title_langs") or ""
        for part in str(raw).replace(";", ",").split(","):
            code = part.strip().lower()
            if code:
                codes.add(code)
    return sorted(codes)


def _volume_snapshot(
    status_counts: Optional[dict],
    series_done: int = 0,
    writes: Optional[dict] = None,
    lifetime: Optional[dict] = None,
) -> dict:
    raw = status_counts or {}
    done = int(raw.get("DONE") or 0)
    failed = int(raw.get("FAILED") or 0)
    nothing = int(raw.get("NOTHING_FOUND") or 0)
    skipped = int(raw.get("SKIPPED") or 0)
    writes = writes or {}
    providers = writes.get("providers") or {}
    fields = writes.get("fields") or {}
    ranked = sorted(
        ((pid, int(n)) for pid, n in providers.items() if n and pid),
        key=lambda x: (-x[1], x[0]),
    )
    champion = None
    if ranked:
        pid, wins = ranked[0]
        champion = {
            "id": pid,
            "name": _provider_display_name(pid),
            "wins": wins,
        }
    known = ("title", "summary", "isbn", "release_date")
    credits = sum(int(n) for key, n in fields.items() if key not in known)
    life = lifetime or {}
    workshop = sum(
        int(life.get(k) or 0)
        for k in (
            "runs_workshop",
            "workshop_units",
            "workshop_reviews",
            "workshop_magic",
            "workshop_edits",
            "workshop_resets",
        )
    )
    return {
        "has_data": bool(done or failed or nothing or skipped or series_done or workshop),
        "done": done,
        "failed": failed,
        "nothing_found": nothing,
        "skipped": skipped,
        "series_done": int(series_done or 0),
        "units": done + failed + nothing + skipped,
        "champion": champion,
        "titles": int(fields.get("title") or 0),
        "summaries": int(fields.get("summary") or 0),
        "isbns": int(fields.get("isbn") or 0),
        "dates": int(fields.get("release_date") or 0),
        "credits": credits,
        "shelf_cm": round(done * STATS_CM_PER_VOLUME, 1) if done else 0.0,
        "typing": _format_duration(int(round(done * STATS_MINUTES_TYPE_PER_VOLUME))),
        "workshop_runs": int(life.get("runs_workshop") or 0),
        "workshop_units": int(life.get("workshop_units") or 0),
        "workshop_reviews": int(life.get("workshop_reviews") or 0),
        "workshop_magic": int(life.get("workshop_magic") or 0),
        "workshop_edits": int(life.get("workshop_edits") or 0),
        "workshop_resets": int(life.get("workshop_resets") or 0),
    }


def _mapping_override_count(config: Optional[dict]) -> int:
    from services.field_mapping import PLAN_SPECS

    n = 0
    cfg = config or {}
    for _plan_id, _lib, _wave, _default_key, map_key in PLAN_SPECS:
        raw = cfg.get(map_key)
        if not isinstance(raw, dict):
            continue
        for provider in raw.values():
            val = str(provider or "").strip().upper()
            if val and val not in ("CASCADE", "AUTO", "NONE", "-", "—"):
                n += 1
    return n


def _auto_sync_snapshot(lifetime: Optional[dict]) -> dict:
    """Compteurs de vagues Auto-sync (C98) — distincts de runs_auto (écritures Kavita)."""
    life = lifetime or {}
    waves = int(life.get("auto_sync_waves") or 0)
    series = int(life.get("auto_sync_series") or 0)
    ok = int(life.get("auto_sync_ok") or 0)
    return {
        "waves": waves,
        "waves_stopped": int(life.get("auto_sync_waves_stopped") or 0),
        "waves_scan": int(life.get("auto_sync_waves_scan") or 0),
        "waves_interval": int(life.get("auto_sync_waves_interval") or 0),
        "series": series,
        "ok": ok,
        "errors": int(life.get("auto_sync_errors") or 0),
        "review": int(life.get("auto_sync_review") or 0),
        "relock": int(life.get("auto_sync_relock") or 0),
        "stopped": int(life.get("auto_sync_stopped") or 0),
        "writes": int(life.get("runs_auto") or 0),
        "ok_rate": round(100.0 * ok / series, 1) if series else 0.0,
        "time_saved": _format_duration(int(round(ok * STATS_MINUTES_PER_SERIES))),
    }


def compute_playful_stats(
    cached_data: dict,
    provider_wins: Optional[dict] = None,
    lifetime: Optional[dict] = None,
    translations_dict: Optional[dict] = None,
    config: Optional[dict] = None,
    hygiene_counts: Optional[dict] = None,
    volume_status_counts: Optional[dict] = None,
    volume_series_done: int = 0,
    expected_overrides: int = 0,
    dup_dismissals: int = 0,
    volume_writes: Optional[dict] = None,
) -> dict:
    """
    Métriques ludiques + données pour Chart.js.

    `lifetime` : {series_enriched, matches_won, series_missed, covers_applied,
    locks_sealed, runs_*, auto_sync_*} — compteurs purs (0 si la clé n'existe pas encore).
    `cached_data` : état actuel (file, placard, overrides, donut).
    Estimations fun : plancher sur le cache / podium si lifetime est en retard.
    `translations_dict` : titres/flavors des hauts-faits MR (optionnel).
    """
    from services.mr_achievements import evaluate_from_lifetime, scored_average

    cached_data = cached_data or {}
    provider_wins = provider_wins or {}
    lifetime = lifetime or {}

    series_enriched = int(lifetime.get("series_enriched") or 0)
    matches_won = int(lifetime.get("matches_won") or 0)
    series_missed = int(lifetime.get("series_missed") or 0)
    covers_applied = int(lifetime.get("covers_applied") or 0)
    locks_sealed = int(lifetime.get("locks_sealed") or 0)
    runs_batch = int(lifetime.get("runs_batch") or 0)
    runs_webhook = int(lifetime.get("runs_webhook") or 0)
    runs_auto = int(lifetime.get("runs_auto") or 0)
    runs_row = int(lifetime.get("runs_row") or 0)
    runs_workshop = int(lifetime.get("runs_workshop") or 0)
    lifetime_attempts = series_enriched + series_missed
    lifetime_hit_rate = round(100.0 * series_enriched / lifetime_attempts, 1) if lifetime_attempts else 0.0

    manual_reviews = int(lifetime.get("manual_reviews") or 0)
    manual_skips = int(lifetime.get("manual_skips") or 0)
    manual_top1_accepts = int(lifetime.get("manual_top1_accepts") or 0)
    manual_score_sum = float(lifetime.get("manual_score_sum") or 0)
    manual_field_edits = int(lifetime.get("manual_field_edits") or 0)
    manual_fusions = int(lifetime.get("manual_fusions") or 0)
    manual_weak_picks = int(lifetime.get("manual_weak_picks") or 0)
    manual_researches = int(lifetime.get("manual_researches") or 0)
    manual_purges = int(lifetime.get("manual_purges") or 0)
    manual_super_confirms = int(lifetime.get("manual_super_confirms") or 0)
    # Dénominateur : confirms scorées, pas toutes les reviews (un candidat
    # sans score ne doit pas diluer). Si le compteur a démarré après la somme
    # lifetime, la moyenne explose au-delà de 1 — scored_average retombe alors
    # sur le nombre de reviews (BF177).
    manual_score_n = int(lifetime.get("manual_score_n") or 0)
    manual_avg_score = scored_average(manual_score_sum, manual_score_n, manual_reviews)
    manual_top1_rate = (manual_top1_accepts / manual_reviews) if manual_reviews else 0.0

    # --- État actuel (cache) ---
    completed = sum(1 for v in cached_data.values() if v.get("status") == "COMPLETED")
    needs_relock = sum(1 for v in cached_data.values() if v.get("status") == "NEEDS_RELOCK")
    pending = sum(1 for v in cached_data.values() if v.get("status") == "PENDING")
    pending_review = sum(1 for v in cached_data.values() if v.get("status") == "PENDING_REVIEW")
    not_found = sum(1 for v in cached_data.values() if v.get("status") == "NOT_FOUND")
    ignored = sum(1 for v in cached_data.values() if v.get("status") == "IGNORED")
    total = len(cached_data)

    decided = completed + not_found
    success_rate = round(100.0 * completed / decided, 1) if decided else 0.0
    completion_pct = round(100.0 * completed / total, 1) if total else 0.0

    provider_wins_total = sum(int(w) for w in provider_wins.values() if w)

    volumes = _volume_snapshot(
        volume_status_counts, volume_series_done, volume_writes, lifetime,
    )

    # Volume organique pour les estimations : jamais sous le réel visible
    estimate_series = max(series_enriched, completed)
    estimate_matches = max(matches_won, provider_wins_total)
    estimates_use_cache_floor = (
        estimate_series > series_enriched or estimate_matches > matches_won
    )
    # Tuile lifetime : 0 tant que la télémétrie n'a pas de séries.
    # Le plancher cache/podium ne sert que les estimations de temps.
    avg_matches = round(matches_won / series_enriched, 2) if series_enriched else 0.0

    # --- Estimations fun ---
    typing_minutes = int((volumes.get("typing") or {}).get("total_minutes") or 0)
    time_minutes = _estimate_minutes(estimate_series, estimate_matches) + typing_minutes
    duration = _format_duration(time_minutes)
    coffees = round(time_minutes / STATS_MINUTES_PER_COFFEE, 1) if time_minutes else 0.0
    deepl_eur = (estimate_series * STATS_CHARS_PER_SUMMARY * STATS_DEEPL_EUR_PER_1K) / 1000.0
    netflix_eps = round(time_minutes / STATS_MINUTES_PER_NETFLIX, 1) if time_minutes else 0.0
    manga_pages = int(volumes.get("done") or 0) * STATS_PAGES_PER_VOLUME
    bmc_coffees = round(deepl_eur / STATS_BMC_COFFEE_EUR, 1) if deepl_eur else 0.0
    train_rides = round(time_minutes / STATS_MINUTES_PER_TRAIN, 1) if time_minutes else 0.0
    sleep_nights = round(time_minutes / STATS_MINUTES_PER_NIGHT, 1) if time_minutes else 0.0

    alt_titles = sum(
        1 for v in cached_data.values() if (v.get("alternative_title") or "").strip()
    )
    lang_codes = _lang_palette(cached_data)

    manual_overrides = sum(1 for v in cached_data.values() if _is_manual_override(v))
    protected_covers = sum(1 for v in cached_data.values() if _is_cover_protected(v))
    forced_ids = sum(1 for v in cached_data.values() if (v.get("forced_id") or "").strip())
    forced_providers = sum(
        1 for v in cached_data.values()
        if (v.get("forced_provider") or "AUTO").strip() not in ("", "AUTO")
    )
    alt_lang_crafts = sum(1 for v in cached_data.values() if (v.get("alt_title_langs") or "").strip())
    surgical = sum(1 for v in cached_data.values() if _is_surgical(v))
    inventory_excluded = sum(1 for v in cached_data.values() if v.get("inventory_excluded"))

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

    charts = {
        "status": {
            "labels": ["COMPLETED", "NEEDS_RELOCK", "PENDING", "PENDING_REVIEW", "NOT_FOUND", "IGNORED"],
            "values": [completed, needs_relock, pending, pending_review, not_found, ignored],
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
            "values": [completed, not_found],
        },
    }

    return {
        "series_enriched": series_enriched,
        "matches_won": matches_won,
        "series_missed": series_missed,
        "covers_applied": covers_applied,
        "locks_sealed": locks_sealed,
        "runs_batch": runs_batch,
        "runs_webhook": runs_webhook,
        "runs_auto": runs_auto,
        "runs_row": runs_row,
        "runs_workshop": runs_workshop,
        "auto_sync": _auto_sync_snapshot(lifetime),
        "avg_matches": avg_matches,
        "lifetime_hit_rate": lifetime_hit_rate,
        "manual_reviews": manual_reviews,
        "manual_skips": manual_skips,
        "manual_top1_accepts": manual_top1_accepts,
        "manual_score_sum": manual_score_sum,
        "manual_field_edits": manual_field_edits,
        "manual_fusions": manual_fusions,
        "manual_weak_picks": manual_weak_picks,
        "manual_researches": manual_researches,
        "manual_purges": manual_purges,
        "manual_super_confirms": manual_super_confirms,
        "manual_avg_score": round(manual_avg_score, 4),
        "manual_top1_rate": round(manual_top1_rate, 4),
        "estimate_series": estimate_series,
        "estimate_matches": estimate_matches,
        "estimates_use_cache_floor": estimates_use_cache_floor,
        "completed": completed,
        "needs_relock": needs_relock,
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
        "library_score": _library_score(
            completed, pending, not_found, ignored, total,
            needs_relock=needs_relock, pending_review=pending_review,
        ),
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
        "train_rides": train_rides,
        "sleep_nights": sleep_nights,
        "alt_titles": alt_titles,
        "lang_palette": len(lang_codes),
        "lang_codes": ", ".join(lang_codes[:8]),
        "expected_overrides": max(0, int(expected_overrides or 0)),
        "dup_dismissals": max(0, int(dup_dismissals or 0)),
        "total_wins": total_provider_wins,
        "provider_diversity": provider_diversity,
        "champion": champion,
        "underdog": underdog,
        "podium": podium,
        "has_provider_data": bool(podium),
        "charts": charts,
        "mr_achievements": evaluate_from_lifetime(lifetime, translations_dict),
        "inventory": _hygiene_snapshot(hygiene_counts),
        "inventory_excluded": inventory_excluded,
        "volumes": volumes,
        "mapping_enabled": bool((config or {}).get("FIELD_MAPPING_ENABLED")),
        "mapping_overrides": _mapping_override_count(config),
    }
