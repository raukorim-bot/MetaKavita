"""
Mémoïsation courte de l'index fournisseur, entre l'aperçu et l'écriture.

L'écriture d'une série reconstruisait le plan entier alors que l'aperçu venait
de le bâtir quelques secondes plus tôt : même série, mêmes réglages, même
fournisseur, même index. Le coût n'était pas symbolique. Depuis que la cadence
s'applique à chaque requête, un index ComicVine paie son `rate_limit` (1,2 s) et
un index Bédéthèque ou Planète BD coûte une requête par album, à 2,5 s l'une —
sur sept albums, l'utilisateur payait deux fois le même prix pour obtenir deux
fois le même index, et le bouton restait muet pendant ce temps.

Ce qui est retenu, et ce qui ne l'est pas :

**On retient l'index du fournisseur**, c'est-à-dire le couple `(provider, index)`
rendu par `resolve_index`. C'est la seule partie du chemin qui sorte sur
Internet, donc la seule qui coûte des secondes.

**On ne retient rien de Kavita.** Les tomes sont relus à chaque fois, et
`apply_entry` relit le chapitre juste avant d'écrire pour réappliquer la
politique de comblement sur cet état frais (`plan_unit(..., chapter=current)`).
Mémoïser l'index ne déplace pas cette frontière : un tome rempli ou verrouillé à
la main entre l'aperçu et le clic est toujours vu comme tel, et
`UpdateChapterDto` continue de partir d'un état lu à l'instant.

La durée de vie est courte et la table bornée : c'est un pont entre un aperçu et
le clic qui suit, pas un cache de métadonnées. Le précédent suivi ici est celui
de `translate.py`, verrou compris — la passe de bibliothèque tourne dans un vrai
thread, pas dans un greenlet, et deux écrivains sur un `OrderedDict` ne
pardonnent pas.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.volume_enrichment.providers import (
    CASCADE_SLOTS,
    forced_volume_provider,
    resolve_index,
)

#: Index résolus, par clé de contexte. Valeur : `(expiration, provider, index)`.
_CACHE: "OrderedDict[tuple, Tuple[float, str, Dict[str, Any]]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()

#: Dix minutes : le temps qu'un utilisateur relise un aperçu de quarante albums
#: avant de cliquer, et pas plus. Au-delà, un fournisseur a pu corriger sa fiche
#: et l'aperçu affiché n'est de toute façon plus sous les yeux de personne.
_TTL_SECONDS = 600.0

#: Un index de série pèse quelques dizaines de kilo-octets (résumés compris) :
#: on borne à ce qu'un utilisateur peut ouvrir d'aperçus en dix minutes, pas à ce
#: qu'une bibliothèque contient de séries.
_MAX_ENTRIES = 32


def _cascade_signature(library_type: str, config: Optional[dict]) -> Tuple[str, ...]:
    """Les fournisseurs réglés pour ce type, dans leur ordre.

    L'ordre décide de tout — `fetch_index` garde le premier index qui couvre la
    série — donc deux cascades différentes ne doivent jamais se partager une
    entrée : changer ComicVine pour Bédéthèque dans la modale Fournisseurs et
    retrouver l'index de ComicVine serait un réglage sans effet visible.

    Le fournisseur imposé et le repli manga entrent dans la signature pour la
    même raison : ils changent la liste consultée, donc l'index. Sans eux, cocher
    « ne pas retomber sur les fournisseurs manga » et rouvrir l'aperçu resservait
    l'index de MangaDex pendant dix minutes, ce qui se lit comme un réglage qui ne
    marche pas.
    """
    if config is None:
        from config_manager import load_config

        config = load_config()
    slots = CASCADE_SLOTS.get(library_type) or CASCADE_SLOTS["Manga"]
    return (
        tuple(str(config.get(slot) or "").strip().upper() for slot in slots)
        + (forced_volume_provider(config),)
        + (str(bool(config.get("VOLUME_NO_MANGA_FALLBACK", False))),)
    )


def _wanted_signature(units: Optional[List[Dict[str, Any]]]) -> Tuple[str, ...]:
    """Les numéros de tome demandés, triés : un remplacement à effectif constant
    ne doit pas resservir l'index du set précédent."""
    from services.volume_enrichment.matching import matchable_numbers

    return tuple(sorted(matchable_numbers(units or [])))


def _cache_key(
    series_id: Any,
    series_name: str,
    *,
    library_type: str,
    force: bool,
    forced_id: str,
    forced_provider: str,
    experimental: bool,
    wanted: Tuple[str, ...],
    config: Optional[dict],
) -> tuple:
    """Tout ce qui peut changer l'index, et rien d'autre.

    `series_name` est le premier argument de `resolve_index` : c'est lui que la
    cascade cherche. Une série renommée dans Kavita garde son identifiant, donc
    sans le nom dans la clé, la correction du titre resterait sans effet jusqu'à
    l'expiration.

    `force` n'agit aujourd'hui que sur la politique de comblement, en aval de
    `resolve_index` : il est dans la clé parce qu'il fait partie du contexte de
    l'aperçu qui a produit l'entrée, et qu'une entrée servie à un run dont les
    réglages diffèrent serait un silence, pas une erreur.

    `wanted` est l'ensemble des numéros Kavita : un tome *remplacé* à nombre
    constant (le 5 part, le 41 arrive) doit faire retourner chez le fournisseur,
    pas resservir un index amputé.
    """
    return (
        int(series_id),
        str(series_name or ""),
        str(library_type or ""),
        bool(force),
        str(forced_id or ""),
        str(forced_provider or ""),
        bool(experimental),
        wanted,
        _cascade_signature(library_type, config),
    )


def _copy_index(index: Any) -> Any:
    """Copie défensive : l'appelant traduit les résumés et bâtit un plan avec.

    `translate_index_summaries` rend bien une copie, mais rien n'oblige le
    prochain appelant à en faire autant, et une entrée mutée resservirait du
    texte déjà traduit à un run qui a changé de langue cible.
    """
    if not isinstance(index, dict):
        return index
    return {
        key: dict(payload) if isinstance(payload, dict) else payload
        for key, payload in index.items()
    }


def _lookup(key: tuple) -> Optional[Tuple[str, Dict[str, Any]]]:
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        expires_at, provider, index = entry
        if expires_at <= now:
            # Purgée à la lecture : sans passe de nettoyage, une entrée périmée
            # jamais relue occuperait une place jusqu'à l'éviction par taille.
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return provider, _copy_index(index)


def _remember(key: tuple, provider: str, index: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + _TTL_SECONDS, provider, _copy_index(index))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)


def forget_series(series_id: Any) -> int:
    """Oublie tout ce qui a été retenu pour une série. Rend le nombre d'entrées.

    Une série peut avoir plusieurs entrées (un aperçu normal, un aperçu forcé,
    un identifiant du Champ Magique saisi entretemps) : on les jette toutes,
    puisque l'appelant demande précisément à repartir du fournisseur.
    """
    sid = int(series_id)
    with _CACHE_LOCK:
        doomed = [key for key in _CACHE if key[0] == sid]
        for key in doomed:
            _CACHE.pop(key, None)
    return len(doomed)


def reset_cache() -> None:
    """Vide la mémoïsation. Pour les tests, et pour un changement de réglages."""
    with _CACHE_LOCK:
        _CACHE.clear()


def resolve_index_cached(
    series_id: Any,
    series_name: str,
    units: List[Dict[str, Any]],
    *,
    library_type: str,
    force: bool = False,
    forced_id: str = "",
    forced_provider: str = "",
    existing_metadata: Optional[Dict[str, Any]] = None,
    experimental: bool = False,
    config: Optional[dict] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[str, Dict[str, Any], bool]:
    """`resolve_index`, mais sans repayer le fournisseur pour la même demande.

    Rend `(provider, index, servi_par_la_mémoïsation)` : le troisième terme sert
    à la journalisation, pour qu'un « c'est lent » désigne le coupable au lieu de
    le faire deviner.

    Un résultat obtenu sous annulation n'est jamais retenu : la cascade s'arrête
    entre deux fournisseurs, donc l'index est partiel par construction, et le
    retenir ferait écrire un index tronqué au clic suivant.
    """
    key = _cache_key(
        series_id,
        series_name,
        library_type=library_type,
        force=force,
        forced_id=forced_id,
        forced_provider=forced_provider,
        experimental=experimental,
        wanted=_wanted_signature(units),
        config=config,
    )
    hit = _lookup(key)
    if hit is not None:
        provider, index = hit
        return provider, index, True

    provider, index = resolve_index(
        series_name,
        units,
        library_type=library_type,
        forced_id=forced_id,
        forced_provider=forced_provider,
        existing_metadata=existing_metadata,
        should_cancel=should_cancel,
        experimental=experimental,
        config=config,
        kavita_series_id=series_id,
    )
    if not (should_cancel and should_cancel()):
        _remember(key, provider, index)
    return provider, index, False
