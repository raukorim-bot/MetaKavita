"""C86 — la modale expose les deux options et le JS porte le payload field_picks."""
from __future__ import annotations

import os
import re

from translations import translations

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_modal_has_manual_completion_and_merge_toggles():
    modal = _read("templates/partials/_manual_review_modal.html")
    assert 'id="mrManualCompletion"' in modal
    assert 'id="mrMergeFields"' in modal
    assert "disabled" in modal


def test_js_sends_field_picks_and_hides_sources():
    js = _read("static/js/manual_review.js")
    assert "field_picks" in js
    assert "manual_completion" in js
    assert "function pickRequestExtras" in js
    assert "function onFieldPickChange" in js
    assert "data-mr-field-hit" in js
    assert "function renderCover" in js
    assert "manual_completion: false" in js
    assert "showMerge = all.length > 1 && !manualCompletion" in js
    assert "mr-master-badge" in js
    assert "renderFieldPickAside" not in js


def test_manual_completion_strings_exist_in_both_languages():
    for key in (
        "mr_manual_completion",
        "mr_manual_completion_title",
        "mr_merge_fields",
        "mr_merge_fields_title",
        "mr_merge_fields_needs_manual",
        "mr_pick_field",
    ):
        assert translations["fr"].get(key), key
        assert translations["en"].get(key), key


def test_dashboard_injects_manual_completion_keys():
    index = _read("templates/index.html")
    for key in (
        "mr_manual_completion",
        "mr_merge_fields",
        "mr_merge_fields_needs_manual",
        "mr_pick_field",
    ):
        assert re.search(rf"^\s*{key}:", index, re.M), key
