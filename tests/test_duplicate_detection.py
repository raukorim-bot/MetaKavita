"""Duplicate scoring matrix — hygiene V1 (threshold 0.92 medium)."""

from __future__ import annotations

from scrapers.utils import (
    DUP_ACCEPT_THRESHOLD,
    find_title_relation_markers,
    get_dup_accept_threshold,
    normalize_str,
    relation_title_penalty,
)
from services.library_audit.duplicates import (
    cluster_duplicate_series,
    dup_group_key,
    score_duplicate_pair,
)


def test_dup_threshold_defaults():
    assert get_dup_accept_threshold({"DUP_THRESHOLD_CUSTOM": False}) == DUP_ACCEPT_THRESHOLD
    assert get_dup_accept_threshold(
        {"DUP_THRESHOLD_CUSTOM": True, "DUP_ACCEPT_THRESHOLD": 0.97}
    ) == 0.97
    assert get_dup_accept_threshold(
        {"DUP_THRESHOLD_CUSTOM": True, "DUP_ACCEPT_THRESHOLD": 0.85}
    ) == 0.85
    assert get_dup_accept_threshold(
        {"DUP_THRESHOLD_CUSTOM": True, "DUP_ACCEPT_THRESHOLD": 0.50}
    ) == 0.70


def test_markers_perfect_and_gaiden():
    m = find_title_relation_markers(normalize_str("Berserk Perfect Edition"))
    assert "perfect edition" in m["edition"]
    m2 = find_title_relation_markers(normalize_str("One Piece Gaiden"))
    assert "gaiden" in m2["spinoff"]
    m3 = find_title_relation_markers(normalize_str("foo spin off bar"))
    assert "spin off" in m3["spinoff"]


def test_relation_penalty_edition_and_shared():
    a = find_title_relation_markers(normalize_str("Berserk"))
    b = find_title_relation_markers(normalize_str("Berserk Perfect Edition"))
    pen, reasons = relation_title_penalty(a, b)
    assert pen >= 0.35
    assert "edition_marker" in reasons

    p1 = find_title_relation_markers(normalize_str("X Perfect Edition"))
    p2 = find_title_relation_markers(normalize_str("X Perfect Edition Vol 2"))
    pen2, reasons2 = relation_title_penalty(p1, p2)
    assert "different_edition" not in reasons2
    assert "edition_marker" not in reasons2

    d1 = find_title_relation_markers(normalize_str("X Perfect Edition"))
    d2 = find_title_relation_markers(normalize_str("X Deluxe Edition"))
    pen3, reasons3 = relation_title_penalty(d1, d2)
    assert "different_edition" in reasons3


def test_same_anilist_hard_dup():
    r = score_duplicate_pair(
        {"id": 1, "name": "A", "aniListId": 10, "libraryType": "Manga"},
        {"id": 2, "name": "B", "aniListId": 10, "libraryType": "Manga"},
    )
    assert r["score"] == 1.0


def test_different_anilist_not_dup():
    r = score_duplicate_pair(
        {"id": 1, "name": "Same Title", "aniListId": 10, "libraryType": "Manga"},
        {"id": 2, "name": "Same Title", "aniListId": 99, "libraryType": "Manga"},
    )
    assert r["score"] == 0.0


def test_gaiden_not_clustered():
    r = score_duplicate_pair(
        {"id": 1, "name": "Naruto", "libraryType": "Manga"},
        {"id": 2, "name": "Naruto Gaiden", "libraryType": "Manga"},
    )
    assert r["score"] < 0.92


def test_perfect_edition_not_clustered():
    r = score_duplicate_pair(
        {"id": 1, "name": "Berserk", "libraryType": "Manga"},
        {"id": 2, "name": "Berserk Perfect Edition", "libraryType": "Manga"},
    )
    assert r["score"] < 0.92


def test_novel_spinoff_not_clustered():
    r = score_duplicate_pair(
        {"id": 1, "name": "Overlord", "libraryType": "Manga"},
        {"id": 2, "name": "Overlord Novel", "libraryType": "Manga"},
    )
    assert r["score"] < 0.92


def test_comic_years_different():
    r = score_duplicate_pair(
        {"id": 1, "name": "Batman (2016)", "libraryType": "Comic"},
        {"id": 2, "name": "Batman (2025)", "libraryType": "Comic"},
    )
    assert r["score"] == 0.0
    assert "different_comic_year" in r["reasons"]


def test_artbook_noise():
    r = score_duplicate_pair(
        {"id": 1, "name": "One Piece", "libraryType": "Manga"},
        {"id": 2, "name": "One Piece Artbook", "libraryType": "Manga"},
    )
    assert r["score"] < 0.92


def test_true_duplicate_titles():
    r = score_duplicate_pair(
        {"id": 1, "name": "Attack on Titan", "libraryType": "Manga"},
        {"id": 2, "name": "Attack on Titan", "libraryType": "Manga"},
    )
    assert r["score"] >= 0.92


def test_cluster_excludes_whitelist():
    series = [
        {"id": 1, "name": "Clone Series", "libraryId": 5, "libraryType": "Manga"},
        {"id": 2, "name": "Clone Series", "libraryId": 5, "libraryType": "Manga"},
        {"id": 3, "name": "Other", "libraryId": 5, "libraryType": "Manga"},
    ]
    groups = cluster_duplicate_series(series, library_id=5, threshold=0.92)
    assert len(groups) == 1
    key = dup_group_key([1, 2])
    groups2 = cluster_duplicate_series(
        series, library_id=5, threshold=0.92, exclude_keys={key}
    )
    assert groups2 == []
