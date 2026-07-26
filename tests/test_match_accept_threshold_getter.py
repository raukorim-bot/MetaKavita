"""Baromètre de fiabilité : get_match_accept_threshold() respecte custom off/on + clamp."""
from scrapers.utils import MATCH_ACCEPT_THRESHOLD, get_match_accept_threshold


def test_custom_off_always_returns_default():
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": False, "MATCH_ACCEPT_THRESHOLD": 0.45}) == 0.60
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": False, "MATCH_ACCEPT_THRESHOLD": 0.99}) == MATCH_ACCEPT_THRESHOLD


def test_custom_on_returns_configured_value():
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": 0.45}) == 0.45
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": 0.85}) == 0.85


def test_custom_on_clamps_out_of_bounds():
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": 0.10}) == 0.30
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": 1.50}) == 1.00


def test_custom_on_invalid_falls_back_to_default():
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": "nope"}) == 0.60
    assert get_match_accept_threshold({"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": float("nan")}) == 0.60
