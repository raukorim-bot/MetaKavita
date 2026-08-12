"""
Cadence des appels aux fournisseurs externes, partagée par TOUS les chemins.

Un fournisseur ne connaît pas la fonctionnalité qui l'appelle : son quota vaut
pour l'instance MetaKavita entière. L'enrichissement, le diagnostic scrapers, le
comptage catalogue de l'inventaire et la recherche de couvertures doivent donc
lire et écrire les mêmes horodatages — sinon une recherche de couvertures (une
requête par fournisseur, lancées en parallèle) part en même temps que
l'enrichissement et fait sauter le `rate_limit` qu'on croyait respecter, avec à
la clé des 429 puis un bannissement d'IP côté fournisseur.

Ce module n'a aucune dépendance interne : c'est ce qui permet à
`services/cover_search.py` de l'utiliser sans importer `metadata_fetcher` (dont
il doit rester découplé, cf. l'en-tête de ce fichier).
"""

from __future__ import annotations

import threading
import time

# Horodatage du dernier appel effectif, par identifiant de scraper.
LAST_REQUEST_TIMES: dict = {}

# --- GARDE ANTI-COURSE PAR SCRAPER ---
# `throttle_provider()` fait un cycle lire (last_call) -> éventuellement dormir
# -> écrire (nouvel horodatage), en 3 étapes séparées. Sans verrou, deux appels
# concurrents pour LE MÊME scraper (ex: le bouton "Sync" d'une série pendant que
# la file de fond traite une AUTRE série qui utilise aussi ce fournisseur comme
# provider #1) peuvent tous les deux lire le même `last_call` périmé AVANT que
# l'un des deux n'ait écrit son propre horodatage : les deux jugent alors,
# indépendamment, qu'il n'y a pas besoin d'attendre, et partent quasi
# simultanément vers l'API externe — violant le rate_limit qu'on croyait
# respecter, avec un risque de 429/ban IP chez le fournisseur. Un verrou par
# scraper (pas un verrou global, pour ne pas ralentir des fournisseurs
# indépendants entre eux) rend tout le cycle lire-dormir-écrire atomique.
_THROTTLE_LOCKS_GUARD = threading.Lock()
_THROTTLE_LOCKS: dict = {}


def _get_throttle_lock(scraper_id):
    with _THROTTLE_LOCKS_GUARD:
        lock = _THROTTLE_LOCKS.get(scraper_id)
        if lock is None:
            lock = threading.Lock()
            _THROTTLE_LOCKS[scraper_id] = lock
        return lock


def throttle_provider(scraper):
    """
    Attend uniquement le temps strictement nécessaire pour respecter le rate_limit
    du scraper ciblé. Si l'API était inactive, délai = 0.0s !
    """
    with _get_throttle_lock(scraper.id):
        now = time.time()
        last_call = LAST_REQUEST_TIMES.get(scraper.id, 0.0)
        elapsed = now - last_call
        required_delay = getattr(scraper, 'rate_limit', 1.0)

        if elapsed < required_delay:
            sleep_needed = required_delay - elapsed
            time.sleep(sleep_needed)

        LAST_REQUEST_TIMES[scraper.id] = time.time()


def reset_throttle_state():
    """Remet la cadence à zéro. Réservé aux tests (état global de module)."""
    LAST_REQUEST_TIMES.clear()
    with _THROTTLE_LOCKS_GUARD:
        _THROTTLE_LOCKS.clear()


__all__ = [
    "LAST_REQUEST_TIMES",
    "reset_throttle_state",
    "throttle_provider",
]
