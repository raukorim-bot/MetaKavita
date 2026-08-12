"""
Non-régression : la recherche de couvertures doit respecter la même cadence que
l'enrichissement.

Une recherche de couvertures interroge TOUS les fournisseurs de la bibliothèque
en parallèle (un greenlet par job côté Socket.IO, jusqu'à 8 threads côté HTTP).
Le fournisseur, lui, ne distingue pas ces appels de ceux de l'enrichissement :
tant que les deux chemins n'écrivaient pas dans les mêmes horodatages, ouvrir le
sélecteur de couvertures pendant un batch doublait le débit vers chaque API — donc
429 puis bannissement d'IP.
"""
import threading
import time
from types import SimpleNamespace

from services import provider_throttle
from services.cover_search import CoverJob, run_cover_job


class _Scraper:
    requires_proxy = False

    def __init__(self, sid, rate_limit=0.2):
        self.id = sid
        self.display_name = sid
        self.rate_limit = rate_limit
        self.calls = []

    def fetch_covers(self, query, library_type=None):
        self.calls.append(time.time())
        return [{"url": f"http://img.test/{self.id}.jpg", "title": query}]


def _job(scraper, mode="by_title", query="ma serie"):
    return CoverJob(
        scraper=scraper, mode=mode, query=query, library_type="Manga", priority=10
    )


def test_cover_jobs_for_one_provider_are_spaced_by_its_rate_limit():
    scraper = _Scraper("FAKE_COVER_PROVIDER", rate_limit=0.2)

    threads = [
        threading.Thread(target=run_cover_job, args=(_job(scraper),)) for _ in range(3)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=5)

    assert len(scraper.calls) == 3
    scraper.calls.sort()
    for earlier, later in zip(scraper.calls, scraper.calls[1:]):
        # 20 ms de marge : résolution d'horloge et ordonnancement sur machine chargée.
        assert later - earlier >= scraper.rate_limit - 0.02, (
            f"deux appels de couvertures espacés de {later - earlier:.3f}s pour un "
            f"rate_limit de {scraper.rate_limit}s"
        )


def test_a_cover_job_waits_for_an_enrichment_call_on_the_same_provider():
    """Les deux chemins partagent les horodatages : un enrichissement qui vient
    d'appeler le fournisseur retarde la recherche de couvertures, et l'inverse."""
    scraper = _Scraper("FAKE_SHARED_PROVIDER", rate_limit=0.3)

    provider_throttle.throttle_provider(SimpleNamespace(id=scraper.id, rate_limit=0.3))
    start = time.time()
    run_cover_job(_job(scraper))
    waited = time.time() - start

    assert waited >= 0.3 - 0.02, (
        "la recherche de couvertures est partie sans attendre l'appel "
        "d'enrichissement précédent sur le même fournisseur"
    )


def test_two_providers_do_not_slow_each_other_down():
    a, b = _Scraper("FAKE_A", rate_limit=1.0), _Scraper("FAKE_B", rate_limit=1.0)

    start = time.time()
    threads = [
        threading.Thread(target=run_cover_job, args=(_job(a),)),
        threading.Thread(target=run_cover_job, args=(_job(b),)),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=5)
    elapsed = time.time() - start

    assert len(a.calls) == 1 and len(b.calls) == 1
    assert elapsed < 1.0, "la cadence doit rester par fournisseur, pas globale"


def test_a_failing_provider_still_records_its_call():
    """Un appel parti compte, même s'il échoue : sinon un fournisseur en erreur
    serait retenté en boucle sans délai."""

    class _Boom(_Scraper):
        def fetch_covers(self, query, library_type=None):
            self.calls.append(time.time())
            raise RuntimeError("boom")

    scraper = _Boom("FAKE_BOOM", rate_limit=0.2)

    assert run_cover_job(_job(scraper)) == []
    assert provider_throttle.LAST_REQUEST_TIMES.get(scraper.id, 0) > 0
