"""
Non-régression : `throttle_provider()` (metadata_fetcher.py) fait un cycle
lire (dernier appel) -> éventuellement dormir -> écrire (nouvel horodatage) en
3 étapes distinctes sur le dict global `LAST_REQUEST_TIMES`. Sans verrou, deux
appels concurrents pour LE MÊME scraper (ex: le bouton "Sync" d'une série
pendant que la file de fond traite une autre série utilisant le même
fournisseur en provider #1) peuvent tous les deux lire le même `last_call`
périmé avant que l'un des deux n'écrive le sien, et partent alors quasi
simultanément vers l'API externe — violant le rate_limit qu'on croyait
respecter, avec un risque de 429/ban IP chez le fournisseur.

Ce test lance plusieurs appels réellement concurrents pour le même scraper et
vérifie que chaque appel effectif est bien espacé du précédent d'au moins
`rate_limit` secondes (preuve d'une sérialisation réelle, pas d'un simple
horodatage qui donnerait l'illusion du respect du délai).
"""
import threading
import time
from types import SimpleNamespace

import metadata_fetcher


def test_throttle_provider_serializes_concurrent_calls_for_the_same_scraper(monkeypatch):
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})

    scraper = SimpleNamespace(id="FAKE_SCRAPER_FOR_TEST", rate_limit=0.2)

    call_times = []
    call_times_guard = threading.Lock()

    def call_once():
        metadata_fetcher.throttle_provider(scraper)
        with call_times_guard:
            call_times.append(time.time())

    threads = [threading.Thread(target=call_once) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(call_times) == 4
    call_times.sort()

    for earlier, later in zip(call_times, call_times[1:]):
        # Petite marge (20ms) pour absorber la résolution de l'horloge/ordonnancement,
        # sans quoi le test serait flaky sur une machine chargée.
        assert later - earlier >= scraper.rate_limit - 0.02, (
            f"Deux appels pour le même scraper se sont exécutés à {later - earlier:.3f}s "
            f"d'écart, alors que rate_limit={scraper.rate_limit}s : le verrou anti-course "
            "ne sérialise plus correctement les appels concurrents."
        )


def test_throttle_provider_does_not_serialize_unrelated_scrapers(monkeypatch):
    """Le verrou est PAR scraper : deux fournisseurs différents ne doivent pas
    se ralentir mutuellement (sinon un fournisseur lent pénaliserait tous les
    autres à chaque appel simultané)."""
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})

    scraper_a = SimpleNamespace(id="FAKE_SCRAPER_A", rate_limit=1.0)
    scraper_b = SimpleNamespace(id="FAKE_SCRAPER_B", rate_limit=1.0)

    start = time.time()

    threads = [
        threading.Thread(target=metadata_fetcher.throttle_provider, args=(scraper_a,)),
        threading.Thread(target=metadata_fetcher.throttle_provider, args=(scraper_b,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    elapsed = time.time() - start
    assert elapsed < scraper_a.rate_limit, (
        "Deux scrapers indépendants se sont bloqués mutuellement : le verrou "
        "anti-course devrait être scindé par scraper.id, pas global."
    )
