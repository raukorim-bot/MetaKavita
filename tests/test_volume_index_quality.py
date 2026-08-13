"""
Qualité de l'index avant qu'il ne gagne la cascade.

Deux rebuts mesurés en charge, tous deux silencieux :

* un fournisseur en tête de cascade dont la page HTML est coupée en cours de
  route mais dont une entrée reste analysable — `{"1": {"summary": '<div
  class="al'}}`. Le fournisseur complet placé derrière n'était jamais appelé, et
  le tome 1 recevait ce fragment de balise **en résumé, verrouillé** : la passe
  suivante épargne un champ verrouillé, donc la correction ne pouvait plus venir
  que d'une réécriture forcée ou d'une reprise à la main, tome par tome ;
* un scraper tiers (`CUSTOM_SCRAPERS.md` documente leur chargement) dont
  `fetch_volume_index` rend une chaîne — page d'erreur rendue telle quelle,
  `return` oublié. `_is_cover_only` faisait `index.values()` sans vérifier le
  type : `AttributeError` sur la série entière, 60 séries sur 60, aucune
  écriture, et aucun repli sur le fournisseur suivant.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.plan import build_plan
from services.volume_enrichment.providers import fetch_index, resolve_index

TRUNCATED = {"1": {"summary": '<div class="al'}}


class _Scraper:
    """Fournisseur de tomes minimal, qui compte ses appels."""

    def __init__(self, scraper_id, index=None):
        self.id = scraper_id
        self.display_name = scraper_id
        self.rate_limit = 0
        self.supported_types = {"Comic", "Manga", "Book"}
        self.calls = 0
        self._index = index

    def fetch_volume_index(self, query, library_type="Comic", series_id=None,
                           existing_metadata=None):
        self.calls += 1
        return self._index


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.providers.throttle_provider", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn", lambda units, **kw: {}
    )


def _units(count=6):
    return [
        {
            "chapter_id": 100 + n,
            "volume_id": 900 + n,
            "volume_number": n,
            "chapter_number": n,
            "sibling_count": 1,
            "chapter": {"id": 100 + n},
        }
        for n in range(1, count + 1)
    ]


def _full(count=6):
    return {str(n): {"summary": f"Résumé du tome {n}", "title": f"Tome {n}"}
            for n in range(1, count + 1)}


# --- L'index tronqué ---------------------------------------------------------


def test_a_truncated_index_does_not_close_the_cascade():
    cut = _Scraper("BEDETHEQUE", TRUNCATED)
    full = _Scraper("COMICVINE", _full())

    provider, index = fetch_index("Saga", providers=[cut, full], units=_units())

    assert full.calls == 1, "le fournisseur complet doit être consulté"
    assert "COMICVINE" in provider
    assert index["1"]["summary"] == "Résumé du tome 1"


def test_a_markup_fragment_is_never_proposed_for_writing():
    """Le champ écrit est verrouillé par MetaKavita : ce qui passe ici ne se
    corrige plus qu'à la main, tome par tome."""
    cut = _Scraper("BEDETHEQUE", TRUNCATED)

    _provider, index = fetch_index("Saga", providers=[cut], units=_units())
    plan = build_plan(_units(), index, provider="BEDETHEQUE")

    proposed = [
        change["proposed"]
        for entry in plan["units"]
        for change in entry["changes"].values()
    ]
    assert not any("<div" in str(value) for value in proposed)


def test_an_index_covering_almost_nothing_is_completed_not_kept_alone():
    """Un tome sur six n'est pas un index : le suivant de la cascade a son mot
    à dire, et le premier reste prioritaire champ par champ."""
    thin = _Scraper("BEDETHEQUE", {"1": {"summary": "Le vrai tome 1"}})
    full = _Scraper("COMICVINE", _full())

    provider, index = fetch_index("Saga", providers=[thin, full], units=_units())

    assert full.calls == 1
    assert provider == "BEDETHEQUE+COMICVINE"
    assert index["1"]["summary"] == "Le vrai tome 1", "le premier reste prioritaire"
    assert len(index) == 6


def test_a_complete_index_stops_the_cascade():
    """La contrepartie : un index qui couvre la série ne doit pas faire payer
    une page HTML de plus au fournisseur suivant."""
    full = _Scraper("COMICVINE", _full())
    following = _Scraper("BEDETHEQUE", _full())

    provider, _index = fetch_index("Saga", providers=[full, following], units=_units())

    assert provider == "COMICVINE"
    assert following.calls == 0


def test_without_known_units_the_first_non_empty_index_still_wins():
    """Les appelants qui ne passent pas d'unités gardent le comportement
    d'avant : sans la série sous les yeux, il n'y a pas de couverture à juger."""
    first = _Scraper("BEDETHEQUE", {"1": {"summary": "Un"}})
    second = _Scraper("COMICVINE", _full())

    provider, _index = fetch_index("Saga", providers=[first, second])

    assert provider == "BEDETHEQUE"
    assert second.calls == 0


# --- Le fournisseur qui ne rend pas un dictionnaire --------------------------


def test_a_provider_returning_a_string_does_not_sink_the_series(monkeypatch):
    third_party = _Scraper("TIERS", "<html>503 Service Unavailable</html>")
    full = _Scraper("COMICVINE", _full())
    monkeypatch.setattr(
        "services.volume_enrichment.providers.volume_providers",
        lambda library_type, config=None: [third_party, full],
    )

    provider, index = resolve_index("Saga", _units(), library_type="Comic", config={})

    assert provider == "COMICVINE"
    assert len(index) == 6


def test_a_provider_returning_a_list_is_discarded_like_the_rest():
    third_party = _Scraper("TIERS", [{"summary": "Un"}])
    full = _Scraper("COMICVINE", _full())

    provider, _index = fetch_index("Saga", providers=[third_party, full], units=_units())

    assert provider == "COMICVINE"


def test_one_bad_entry_does_not_bring_down_the_whole_index():
    """Le reste de l'index d'un scraper tiers approximatif reste exploitable."""
    shaky = dict(_full())
    shaky["7"] = "pas un payload"
    scraper = _Scraper("TIERS", shaky)

    _provider, index = fetch_index("Saga", providers=[scraper], units=_units())

    assert "7" not in index
    assert len(index) == 6
