"""WebLinks replace when force_update + RESET_CONTEXT_ON_FORCE."""
from services.kavita_payload import build_kavita_payload


def _build(force_update, reset_context, existing_links, provider_extra=None):
    pd = {
        "anilist_id": 30002,
        "mal_id": 2,
        "url": "https://anilist.co/manga/30002/Berserk",
    }
    if provider_extra:
        pd.update(provider_extra)
    return build_kavita_payload(
        provider_data=pd,
        metadata={"seriesId": 1, "webLinks": existing_links},
        active_fields=["weblinks"],
        config={"RESET_CONTEXT_ON_FORCE": reset_context, "TARGET_LANG": ""},
        cache_data={},
        force_update=force_update,
        series_id=1,
    )


def test_weblinks_merge_without_reset_keeps_existing():
    built = _build(
        force_update=True,
        reset_context=False,
        existing_links="https://wrong.example/old,https://anilist.co/manga/999",
    )
    links = (built["metadata"].get("webLinks") or "").split(",")
    assert "https://wrong.example/old" in links
    assert "https://anilist.co/manga/999" in links
    assert "https://anilist.co/manga/30002" in links
    assert "https://myanimelist.net/manga/2" in links


def test_weblinks_replace_on_force_and_reset_context():
    built = _build(
        force_update=True,
        reset_context=True,
        existing_links="https://wrong.example/old,https://anilist.co/manga/999",
    )
    links = (built["metadata"].get("webLinks") or "").split(",")
    assert "https://wrong.example/old" not in links
    assert "https://anilist.co/manga/999" not in links
    assert "https://anilist.co/manga/30002" in links
    assert "https://myanimelist.net/manga/2" in links


def test_weblinks_no_replace_when_reset_without_force():
    """RESET_CONTEXT alone (no force) must keep merge behaviour."""
    built = _build(
        force_update=False,
        reset_context=True,
        existing_links="https://wrong.example/old",
    )
    links = (built["metadata"].get("webLinks") or "").split(",")
    assert "https://wrong.example/old" in links


def test_weblinks_replace_clears_when_scrape_has_no_links():
    built = build_kavita_payload(
        provider_data={"title": "X"},
        metadata={"seriesId": 1, "webLinks": "https://wrong.example/old"},
        active_fields=["weblinks"],
        config={"RESET_CONTEXT_ON_FORCE": True, "TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert built["metadata"].get("webLinks") == ""
