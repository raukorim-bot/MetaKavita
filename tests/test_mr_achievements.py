"""Hauts-faits Manual Review — moteur lifetime + branchement /stats."""

from services.mr_achievements import evaluate, lifetime_bag_from_stats
from services.stats_service import compute_playful_stats
from translations import translations


def test_lifetime_bag_from_stats_defaults():
    bag = lifetime_bag_from_stats({})
    assert bag["done"] == 0
    assert bag["skipped"] == 0
    assert bag["fusions"] == 0
    assert bag["super_used"] is False


def test_evaluate_unlocks_oracle_sculptor_alchemist():
    bag = {
        "done": 5,
        "skipped": 0,
        "top1": 5,
        "edits": 6,
        "purged": 0,
        "researches": 0,
        "fusions": 2,
        "weak_picks": 0,
        "score_sum": 4.5,
        "score_n": 5,
        "super_used": False,
    }
    t = translations["fr"]
    result = evaluate(bag, t)
    unlocked_ids = {c["id"] for c in result["unlocked"]}
    assert "oracle" in unlocked_ids
    assert "sculptor" in unlocked_ids
    assert "alchemist" in unlocked_ids
    assert "curator" in unlocked_ids
    assert "empty_session" not in unlocked_ids
    assert result["unlocked_count"] == len(result["unlocked"])
    assert result["total"] == result["unlocked_count"] + len(result["locked"])
    assert result["hero"]["id"] == "alchemist"  # priority 85 > oracle 75
    assert "fusion" in result["hero"]["flavor"].lower() or "mélangé" in result["hero"]["flavor"].lower()


def test_evaluate_excludes_session_only_empty():
    result = evaluate(
        {
            "done": 0,
            "skipped": 0,
            "top1": 0,
            "edits": 0,
            "purged": 0,
            "researches": 0,
            "fusions": 0,
            "weak_picks": 0,
            "score_sum": 0,
            "score_n": 0,
            "super_used": False,
        },
        translations["fr"],
    )
    ids = {c["id"] for c in result["unlocked"]} | {c["id"] for c in result["locked"]}
    assert "empty_session" not in ids
    assert result["unlocked_count"] == 0


def test_compute_playful_stats_includes_mr_achievements():
    lifetime = {
        "series_enriched": 0,
        "matches_won": 0,
        "series_missed": 0,
        "manual_reviews": 3,
        "manual_skips": 0,
        "manual_top1_accepts": 3,
        "manual_score_sum": 2.7,
        "manual_field_edits": 0,
        "manual_fusions": 1,
        "manual_weak_picks": 0,
        "manual_researches": 0,
        "manual_purges": 0,
        "manual_super_confirms": 0,
    }
    playful = compute_playful_stats({}, {}, lifetime, translations_dict=translations["fr"])
    assert "mr_achievements" in playful
    assert playful["mr_achievements"]["unlocked_count"] >= 1
    unlocked_ids = {c["id"] for c in playful["mr_achievements"]["unlocked"]}
    assert "oracle" in unlocked_ids
    assert "alchemist" in unlocked_ids
    assert "lightning" in unlocked_ids
