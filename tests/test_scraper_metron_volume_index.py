"""Index des albums Metron : pagination de `issue_list` et filtrage des numéros."""
from __future__ import annotations

import pytest

from scrapers.metron import MetronScraper


@pytest.fixture
def metron(monkeypatch):
    monkeypatch.setattr(
        "scrapers.metron.load_config",
        lambda: {"METRON_API_KEY": "token"},
    )
    scraper = MetronScraper()
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    return scraper


def _issue(n, **extra):
    row = {
        "id": 1000 + n,
        "number": str(n),
        "title": f"Chapter {n}",
        "cover_date": "2012-03-14",
        "image": f"https://static.metron.cloud/{n}.jpg",
    }
    row.update(extra)
    return row


def test_metron_declares_the_volume_scope(metron):
    assert "volume" in metron.scopes
    assert "series" in metron.scopes


def test_metron_indexes_issues_across_pages(metron, monkeypatch):
    pages = {
        "issue_list/": {
            "results": [_issue(1), _issue(2)],
            "next": "https://metron.cloud/api/series/9/issue_list/?page=2",
        },
        "page=2": {
            "results": [_issue(3)],
            "next": None,
        },
    }
    urls = []

    def fake_json(session, headers, url, params=None):
        urls.append(url)
        if "page=2" in url:
            return pages["page=2"]
        if "issue_list/" in url:
            return pages["issue_list/"]
        return {"results": []}

    monkeypatch.setattr(metron, "_get_json", fake_json)
    monkeypatch.setattr(metron, "_resolve_series_id", lambda *a, **k: 9)

    index = metron.fetch_volume_index("Saga", series_id="9")

    assert sorted(index) == ["1", "2", "3"]
    assert index["1"]["title"] == "Chapter 1"
    assert index["1"]["provider_ref"].endswith("/issue/1001/")
    assert any("page=2" in url for url in urls)


def test_metron_filters_to_wanted_numbers(metron, monkeypatch):
    def fake_json(session, headers, url, params=None):
        return {"results": [_issue(n) for n in range(1, 6)], "next": None}

    monkeypatch.setattr(metron, "_get_json", fake_json)
    monkeypatch.setattr(metron, "_resolve_series_id", lambda *a, **k: 9)

    index = metron.fetch_volume_index(
        "Saga", series_id="9", wanted_numbers={"2", "5"}
    )

    assert sorted(index) == ["2", "5"]


def test_metron_cancel_keeps_the_first_page(metron, monkeypatch):
    pages_hit = []

    def fake_json(session, headers, url, params=None):
        pages_hit.append(url)
        if "page=2" in url:
            return {"results": [_issue(3)], "next": None}
        return {
            "results": [_issue(1), _issue(2)],
            "next": "https://metron.cloud/api/series/9/issue_list/?page=2",
        }

    monkeypatch.setattr(metron, "_get_json", fake_json)
    monkeypatch.setattr(metron, "_resolve_series_id", lambda *a, **k: 9)
    n = {"i": 0}

    def should_cancel():
        n["i"] += 1
        return n["i"] > 1

    index = metron.fetch_volume_index(
        "Saga", series_id="9", should_cancel=should_cancel
    )

    assert sorted(index) == ["1", "2"]
    assert not any("page=2" in url for url in pages_hit)


def test_metron_fetch_volume_reads_an_issue_url(metron, monkeypatch):
    def fake_json(session, headers, url, params=None):
        assert "/issue/77/" in url
        return _issue(4, id=77, title="The Walk")

    monkeypatch.setattr(metron, "_get_json", fake_json)

    payload = metron.fetch_volume("https://metron.cloud/issue/77/")

    assert payload["title"] == "The Walk"
    assert payload["provider_ref"].endswith("/issue/77/")


def test_metron_staff_still_only_reads_the_first_page(metron, monkeypatch):
    """Paginer pour les crédits d'une fiche série multiplierait les GET pour rien."""
    urls = []

    def fake_json(session, headers, url, params=None):
        urls.append(url)
        if "/issue/" in url and "issue_list" not in url:
            return {"credits": []}
        return {
            "results": [_issue(1)],
            "next": "https://metron.cloud/api/series/9/issue_list/?page=2",
        }

    monkeypatch.setattr(metron, "_get_json", fake_json)

    metron._staff_from_series(None, {}, 9)

    assert not any("page=2" in url for url in urls)
