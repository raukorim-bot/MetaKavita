"""
Index des albums ComicVine (issue #27).

C'est ce qui rend l'enrichissement par tome viable : `/api/issues/` ramène cent
albums par requête, résumés et couvertures compris. Un appel par album mettrait
une bibliothèque de mille unités à plus d'une heure de réseau, cadence comprise.
Le test de pagination est donc un test de coût autant que de justesse.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.comicvine`, qui renvoie la copie installée dans
`data/scrapers/` — même précaution que `test_scraper_comicvine_issue_pass.py`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_repo_scraper_module():
    path = Path(__file__).resolve().parents[1] / "scrapers" / "comicvine.py"
    spec = importlib.util.spec_from_file_location("scrapers.comicvine_volume_index_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cv = _load_repo_scraper_module()
ComicVineScraper = cv.ComicVineScraper


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("pas du json")
        return self._payload


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(cv, "load_config", lambda: {"COMICVINE_API_KEY": "clef"})


def _issue(n, **extra):
    issue = {
        "id": 1000 + n,
        "name": f"Album {n}",
        "issue_number": str(n),
        "cover_date": f"20{10 + n:02d}-05-07",
        "description": f"<p>Résumé {n}</p>",
        "image": {"original_url": f"https://static.comicvine.com/{n}.jpg"},
    }
    issue.update(extra)
    return issue


def test_the_index_is_keyed_by_album_number(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        assert "issues" in url
        assert params["filter"] == "volume:4242"
        return FakeResponse({"results": [_issue(1), _issue(2)], "number_of_total_results": 2})

    monkeypatch.setattr(cv.requests, "get", fake_get)

    index = ComicVineScraper().fetch_volume_index("Saga", series_id="4050-4242")

    assert set(index) == {"1", "2"}
    assert index["1"]["title"] == "Album 1"
    assert index["1"]["release_date"] == "2011-05-07"
    assert index["1"]["cover_url"] == "https://static.comicvine.com/1.jpg"
    assert index["1"]["provider_ref"] == "4000-1001"


def test_the_html_summary_is_flattened(monkeypatch):
    """Kavita affiche le résumé en texte : y laisser du HTML donnerait des
    balises à l'écran."""
    monkeypatch.setattr(
        cv.requests,
        "get",
        lambda *a, **kw: FakeResponse(
            {"results": [_issue(1, description="<p>Un <b>récit</b>.</p>")], "number_of_total_results": 1}
        ),
    )

    index = ComicVineScraper().fetch_volume_index("Saga", series_id="4242")

    assert "<" not in index["1"]["summary"]
    assert "récit" in index["1"]["summary"]


def test_a_run_of_150_albums_costs_two_calls(monkeypatch):
    """Cent par page : au-delà, il faut suivre l'offset, sinon les cinquante
    derniers albums n'existent pas."""
    calls = []

    def fake_get(url, params=None, **kwargs):
        offset = params["offset"]
        calls.append(offset)
        page = [_issue(n) for n in range(offset + 1, min(offset + 100, 150) + 1)]
        return FakeResponse({"results": page, "number_of_total_results": 150})

    monkeypatch.setattr(cv.requests, "get", fake_get)

    index = ComicVineScraper().fetch_volume_index("Saga", series_id="4242")

    assert calls == [0, 100], "un run de 150 albums doit tenir en deux appels"
    assert len(index) == 150
    assert "150" in index


def test_pagination_stops_on_a_short_page_even_without_a_total(monkeypatch):
    """Une réponse sans `number_of_total_results` ne doit pas faire boucler."""
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["offset"])
        return FakeResponse({"results": [_issue(n) for n in range(1, 4)]})

    monkeypatch.setattr(cv.requests, "get", fake_get)

    index = ComicVineScraper().fetch_volume_index("Saga", series_id="4242")

    assert calls == [0]
    assert len(index) == 3


def test_pagination_is_bounded_even_if_the_server_never_stops(monkeypatch):
    """Un volume ComicVine mal choisi (recueil de strips) peut compter des
    milliers d'issues : la boucle doit avoir un plafond."""
    calls = []

    def fake_get(url, params=None, **kwargs):
        offset = params["offset"]
        calls.append(offset)
        page = [_issue(n) for n in range(offset + 1, offset + 101)]
        return FakeResponse({"results": page, "number_of_total_results": 10**6})

    monkeypatch.setattr(cv.requests, "get", fake_get)

    ComicVineScraper().fetch_volume_index("Saga", series_id="4242")

    assert len(calls) == ComicVineScraper.ISSUES_MAX_PAGES


def test_an_album_without_a_number_is_dropped(monkeypatch):
    """Sans numéro, impossible de savoir sur quel tome écrire."""
    monkeypatch.setattr(
        cv.requests,
        "get",
        lambda *a, **kw: FakeResponse(
            {"results": [_issue(1), _issue(2, issue_number=None)], "number_of_total_results": 2}
        ),
    )

    index = ComicVineScraper().fetch_volume_index("Saga", series_id="4242")

    assert set(index) == {"1"}


def test_an_http_error_returns_none_rather_than_a_truncated_index(monkeypatch):
    monkeypatch.setattr(cv.requests, "get", lambda *a, **kw: FakeResponse({}, status_code=420))

    assert ComicVineScraper().fetch_volume_index("Saga", series_id="4242") is None


def test_a_partial_index_survives_a_failure_on_the_second_page(monkeypatch):
    """Cent albums lus valent mieux que rien ; le reste sera retenté."""
    state = {"calls": 0}

    def fake_get(url, params=None, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            return FakeResponse(
                {
                    "results": [_issue(n) for n in range(1, 101)],
                    "number_of_total_results": 150,
                }
            )
        return FakeResponse({}, status_code=500)

    monkeypatch.setattr(cv.requests, "get", fake_get)

    index = ComicVineScraper().fetch_volume_index("Saga", series_id="4242")

    assert len(index) == 100


def test_a_missing_api_key_short_circuits(monkeypatch):
    monkeypatch.setattr(cv, "load_config", lambda: {"COMICVINE_API_KEY": ""})

    def fake_get(*a, **kw):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("aucun appel sans clé")

    monkeypatch.setattr(cv.requests, "get", fake_get)

    assert ComicVineScraper().fetch_volume_index("Saga", series_id="4242") is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("4050-4242", "4242"),
        ("4242", "4242"),
        ("https://comicvine.gamespot.com/saga/4050-4242/", "4242"),
        ("4000-999", None),
        ("", None),
        (None, None),
        ("pas-un-id", None),
    ],
)
def test_the_volume_id_is_read_from_whatever_the_user_pasted(raw, expected):
    assert ComicVineScraper._volume_id_from_any(raw) == expected


def test_without_a_forced_id_the_run_is_searched(monkeypatch):
    """Le Champ Magique n'est pas toujours rempli : il faut retrouver le run
    par son nom, et réutiliser le scoring déjà en place."""
    seen = []

    def fake_get(url, params=None, **kwargs):
        seen.append(url)
        if "volumes" in url:
            return FakeResponse(
                {
                    "results": [
                        {"id": 4242, "name": "Saga", "count_of_issues": 60,
                         "publisher": {"name": "Image"}, "start_year": 2012},
                    ]
                }
            )
        assert params["filter"] == "volume:4242"
        return FakeResponse({"results": [_issue(1)], "number_of_total_results": 1})

    monkeypatch.setattr(cv.requests, "get", fake_get)

    index = ComicVineScraper().fetch_volume_index("Saga")

    assert set(index) == {"1"}
    assert any("volumes" in u for u in seen)


def test_a_run_that_cannot_be_found_yields_nothing(monkeypatch):
    monkeypatch.setattr(cv.requests, "get", lambda *a, **kw: FakeResponse({"results": []}))

    assert ComicVineScraper().fetch_volume_index("Série inconnue") is None


def test_credits_are_bucketed_by_kavita_collection(monkeypatch):
    monkeypatch.setattr(
        cv.requests,
        "get",
        lambda *a, **kw: FakeResponse(
            {
                "results": {
                    "person_credits": [
                        {"name": "Brian K. Vaughan", "role": "writer"},
                        {"name": "Fiona Staples", "role": "artist, cover"},
                        {"name": "Fonografiks", "role": "letterer"},
                        {"name": "Personne", "role": "assistant"},
                    ]
                }
            }
        ),
    )

    credits = ComicVineScraper().fetch_volume_credits("4000-1001")

    assert credits["writers"] == ["Brian K. Vaughan"]
    assert credits["pencillers"] == ["Fiona Staples"]
    assert credits["coverArtists"] == ["Fiona Staples"]
    assert credits["letterers"] == ["Fonografiks"]
    assert "assistant" not in credits


def test_credits_refuse_a_reference_that_is_not_an_album(monkeypatch):
    def fake_get(*a, **kw):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("aucun appel sur une référence vide")

    monkeypatch.setattr(cv.requests, "get", fake_get)

    assert ComicVineScraper().fetch_volume_credits("") is None
    assert ComicVineScraper().fetch_volume_credits("pas-un-ref") is None


def test_comicvine_declares_the_volume_scope():
    """Sans cette déclaration, `get_by_scope('volume')` ne le verrait pas."""
    assert "volume" in ComicVineScraper().normalized_scopes()
