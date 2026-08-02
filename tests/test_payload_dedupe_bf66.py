"""BF66 — Dedupe tags/genres (case-insensitive) before MAX_* caps."""

from services.kavita_payload import _dedupe_titles, build_kavita_payload, build_preview_fields


def test_nr_g1_unique_tags_genres_noop(monkeypatch):
    """NR-G1: already-unique lists are unchanged (order + titles)."""
    monkeypatch.setattr("services.kavita_payload.get_max_genres", lambda config=None: 5)
    monkeypatch.setattr("services.kavita_payload.get_max_tags", lambda config=None: 15)

    genres = ["Action", "Comedy", "Drama"]
    tags = ["School", "Friendship", "Sports"]
    result = build_kavita_payload(
        {"genres": list(genres), "tags": list(tags), "summary": "x"},
        {},
        ["genres", "tags"],
        {},
        {},
        True,
        1,
    )
    assert [g["title"] for g in result["metadata"]["genres"]] == genres
    assert [t["title"] for t in result["metadata"]["tags"]] == tags
    assert len(result["metadata"]["genres"]) == min(len(genres), 5)
    assert len(result["metadata"]["tags"]) == min(len(tags), 15)


def test_nr_p1_france_france_dedupe(monkeypatch):
    """NR-P1: France/france collapses; first casing kept."""
    monkeypatch.setattr("services.kavita_payload.get_max_genres", lambda config=None: 10)
    monkeypatch.setattr("services.kavita_payload.get_max_tags", lambda config=None: 10)

    result = build_kavita_payload(
        {
            "tags": ["France", "Foreign", "france"],
            "genres": ["Action", "action", "Comedy"],
            "summary": "x",
        },
        {},
        ["tags", "genres"],
        {},
        {},
        True,
        1,
    )
    assert [t["title"] for t in result["metadata"]["tags"]] == ["France", "Foreign"]
    assert [g["title"] for g in result["metadata"]["genres"]] == ["Action", "Comedy"]


def test_nr_p1_cap_after_dedupe(monkeypatch):
    """NR-P1: MAX_TAGS applies after dedupe (6 unique + 2 dupes → 5)."""
    monkeypatch.setattr("services.kavita_payload.get_max_tags", lambda config=None: 5)
    monkeypatch.setattr("services.kavita_payload.get_max_genres", lambda config=None: 5)

    tags = [f"Tag{i}" for i in range(6)] + ["Tag0", "Tag1"]
    result = build_kavita_payload(
        {"tags": tags, "summary": "x"},
        {},
        ["tags"],
        {},
        {},
        True,
        1,
    )
    assert [t["title"] for t in result["metadata"]["tags"]] == [f"Tag{i}" for i in range(5)]


def test_dedupe_titles_helper_order_and_empty():
    assert _dedupe_titles(["A", "a", "", "  ", "B", "b "]) == ["A", "B"]
    assert _dedupe_titles(None) == []
    assert _dedupe_titles([]) == []


def test_preview_fields_dedupe_tags_genres():
    """Confirm/MR preview must match payload dedupe (no duplicate France in UI)."""
    preview = build_preview_fields(
        {
            "tags": ["Europe", "France", "Foreign", "France", "Art"],
            "genres": ["Action", "action", "Comedy"],
            "summary": "x",
        }
    )
    assert preview["tags"] == "Europe, France, Foreign, Art"
    assert preview["genres"] == "Action, Comedy"
