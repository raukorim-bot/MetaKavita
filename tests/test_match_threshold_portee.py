"""
Portée du seuil d'acceptation pendant une collecte de review manuelle (BF121/BF123).

Le mode `return_candidates=True` (Manual Review / Super Review) abaisse le seuil
d'acceptation des scrapers à 0.0 pour que l'utilisateur voie AUSSI les
correspondances faibles au lieu de les perdre. Historiquement cet abaissement
était fait en remplaçant l'attribut de module `get_match_accept_threshold` dans
`scrapers.utils`, dans `metadata_fetcher` et dans tous les modules `scrapers*`
chargés : un état global de PROCESS, donc partagé par tous les threads.

Conséquences reproduites ici :

1. un enrichissement automatique (worker batch) tournant EN PARALLÈLE sur une
   autre série voyait lui aussi 0.0 et acceptait n'importe quel candidat ;
2. deux collectes manuelles qui se chevauchent : la seconde capturait comme
   « original » la fonction déjà patchée, et le seuil restait à 0.0 pour tout
   le process jusqu'au redémarrage ;
3. les workers de la vague 2 (`ThreadPoolExecutor`) doivent au contraire, eux,
   hériter du seuil abaissé — sinon la review manuelle ne collecte plus les
   candidats faibles (le piège de la correction) ;
4. les cartes envoyées en streaming étaient étiquetées « au-dessus du seuil »
   parce que la bande était calculée avec le seuil abaissé au lieu du vrai
   seuil UI.
"""
from __future__ import annotations

import threading

import pytest

import metadata_fetcher
import scrapers.utils as scraper_utils
from test_manual_review import _install_fake_registry, _make_scraper

# Config explicite : les assertions ne doivent pas dépendre du data/config.json réel.
_REAL_CONFIG = {"MATCH_THRESHOLD_CUSTOM": True, "MATCH_ACCEPT_THRESHOLD": 0.60}


@pytest.fixture(autouse=True)
def _fetch_config(monkeypatch):
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {
            "UI_LANG": "fr",
            "SMART_SCORING": True,
            "SMART_COMPLETION": False,
            "MATCH_THRESHOLD_CUSTOM": True,
            "MATCH_ACCEPT_THRESHOLD": 0.60,
        },
    )


def _seen_threshold():
    """Seuil tel que le voit un scraper (config réelle passée explicitement)."""
    return scraper_utils.get_match_accept_threshold(dict(_REAL_CONFIG))


def test_le_seuil_manuel_ne_fuit_pas_vers_un_enrichissement_parallele(monkeypatch):
    """Pendant une collecte manuelle, un autre thread garde le vrai seuil."""
    inside_scrape = threading.Event()
    other_thread_may_finish = threading.Event()
    seen_elsewhere = []

    def blocking_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        inside_scrape.set()
        other_thread_may_finish.wait(timeout=5)
        return {"title": "Manual", "summary": "M", "_match_score": 0.95}

    _install_fake_registry(monkeypatch, {"MANUAL": _make_scraper("MANUAL", blocking_fetch)})

    def run_manual_collect():
        metadata_fetcher.fetch_metadata(
            query="Q",
            providers_list=["MANUAL"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
            return_candidates=True,
        )

    collector = threading.Thread(target=run_manual_collect)
    collector.start()
    try:
        assert inside_scrape.wait(timeout=5), "le scraper manuel n'a jamais démarré"
        # Le worker batch d'une AUTRE série lit le seuil pendant la collecte.
        seen_elsewhere.append(_seen_threshold())
    finally:
        other_thread_may_finish.set()
        collector.join(timeout=5)

    assert seen_elsewhere == [0.60], (
        "un enrichissement automatique parallèle a vu le seuil de la review "
        f"manuelle ({seen_elsewhere}) et accepterait n'importe quel candidat"
    )
    # Et le process retrouve bien son seuil après la collecte.
    assert _seen_threshold() == 0.60


def test_les_workers_paralleles_heritent_du_seuil_manuel(monkeypatch):
    """Vague 2 (`ThreadPoolExecutor`) : les workers doivent voir 0.0."""
    seen_in_workers = {}

    def make_fetch(name, score):
        def fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
            seen_in_workers[name] = _seen_threshold()
            return {"title": name, "summary": name, "_match_score": score}

        return fetch

    scrapers = {
        "P1": _make_scraper("P1", make_fetch("P1", 0.95)),
        "P2": _make_scraper("P2", make_fetch("P2", 0.20)),
        "P3": _make_scraper("P3", make_fetch("P3", 0.10)),
    }
    _install_fake_registry(monkeypatch, scrapers)

    payload, used = metadata_fetcher.fetch_metadata(
        query="Q",
        providers_list=["P1", "P2", "P3"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
    )

    assert seen_in_workers == {"P1": 0.0, "P2": 0.0, "P3": 0.0}, (
        "les workers de la vague 2 n'héritent pas du seuil de collecte : "
        f"{seen_in_workers}"
    )
    assert [c["provider"] for c in payload["above"]] == ["P1"]
    assert sorted(c["provider"] for c in payload["below"]) == ["P2", "P3"]
    assert set(used) == {"P1", "P2", "P3"}


def test_deux_collectes_imbriquees_ne_corrompent_pas_le_seuil(monkeypatch):
    """Deux collectes qui se chevauchent : le seuil revient à sa valeur réelle.

    Reproduit l'imbrication qui laissait le seuil à 0.0 DÉFINITIVEMENT : la
    seconde collecte démarre pendant la première, et la première se termine
    avant la seconde.
    """
    first_started = threading.Event()
    second_started = threading.Event()
    first_finished = threading.Event()
    second_may_finish = threading.Event()

    def first_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        first_started.set()
        second_started.wait(timeout=5)
        return {"title": "A", "summary": "A", "_match_score": 0.9}

    def second_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        second_started.set()
        second_may_finish.wait(timeout=5)
        return {"title": "B", "summary": "B", "_match_score": 0.9}

    scrapers = {
        "A": _make_scraper("A", first_fetch),
        "B": _make_scraper("B", second_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    def collect(provider):
        metadata_fetcher.fetch_metadata(
            query="Q",
            providers_list=[provider],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
            return_candidates=True,
        )

    def run_first():
        collect("A")
        first_finished.set()

    t_first = threading.Thread(target=run_first)
    t_second = threading.Thread(target=lambda: collect("B"))
    t_first.start()
    try:
        assert first_started.wait(timeout=5)
        t_second.start()
        assert second_started.wait(timeout=5)
        # La 1re collecte se termine (et restaure) AVANT la 2de.
        assert first_finished.wait(timeout=5)
        assert _seen_threshold() == 0.60
    finally:
        second_may_finish.set()
        t_first.join(timeout=5)
        t_second.join(timeout=5)

    assert _seen_threshold() == 0.60, (
        "le seuil est resté abaissé après l'imbrication de deux collectes"
    )


def test_carte_streamee_sous_le_seuil_est_marquee_faible(monkeypatch):
    """La bande envoyée en streaming utilise le vrai seuil UI, pas 0.0."""
    streamed = []

    def weak(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Weak", "summary": "W", "_match_score": 0.20}

    def strong(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Strong", "summary": "S", "_match_score": 0.88}

    scrapers = {
        "WEAK": _make_scraper("WEAK", weak),
        "STRONG": _make_scraper("STRONG", strong),
    }
    _install_fake_registry(monkeypatch, scrapers)

    payload, _used = metadata_fetcher.fetch_metadata(
        query="Q",
        providers_list=["WEAK", "STRONG"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
        on_candidate=lambda card, band: streamed.append((card, band)),
    )

    bands = {card["provider"]: band for card, band in streamed}
    flags = {card["provider"]: card.get("below_threshold") for card, band in streamed}
    assert bands == {"WEAK": "below", "STRONG": "above"}, (
        f"bande streamée incohérente avec le seuil UI : {bands}"
    )
    assert flags == {"WEAK": True, "STRONG": False}, (
        "below_threshold persisté en base est faux pour la carte faible : "
        f"{flags}"
    )
    # Le payload final (recalculé après la collecte) dit la même chose.
    assert [c["provider"] for c in payload["above"]] == ["STRONG"]
    assert [c["provider"] for c in payload["below"]] == ["WEAK"]
