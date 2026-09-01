"""
Passe d'enrichissement par tome, en thread dédié.

**Pas dans `sync_queue`.** Cette file n'a qu'un worker, partagé par le webhook
Kavita, l'auto-sync et le bouton de chaque ligne : y verser une passe de mille
tomes gèlerait l'enrichissement série pendant des heures. Le patron suivi ici
est celui de `library_audit/hygiene_scan.py` — un thread, un état sous verrou,
une annulation coopérative entre deux unités.

La reprise s'appuie sur `volume_unit_cache`, aux deux mailles : une série déjà
parcourue en entier n'est pas réinterrogée, et dans une série reprise en cours
de route, les unités qui portent déjà leur verdict ne sont pas replanifiées. La
passe est ainsi redémarrable après un arrêt du conteneur sans repayer le
fournisseur ni relire chez Kavita ce qui est fait.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from config_manager import load_config
from db_manager import (
    get_all_cached_data,
    get_volume_unit_overrides,
    get_volume_unit_states,
    list_enriched_series_ids,
    mark_series_pass_done,
)
from kavita_api import KavitaAPI
from secure_logging import safe_exc_str, series_label
from services.cooperative import yield_to_worker
from services.volume_enrichment.apply import apply_plan
from services.volume_enrichment.index_cache import resolve_index_cached
from services.volume_enrichment.matching import unmatchable_reason, units_from_volumes
from services.volume_enrichment.plan import build_plan
from services.volume_enrichment.providers import (
    credits_fetcher,
    resolve_index,
)
from services.volume_enrichment.translate import translate_plan_summaries

#: Identifiants de correspondance externe d'un `SeriesDto`, et le nom sous lequel
#: un scraper les attend dans `existing_metadata`.
#:
#: La série a déjà été appariée une fois, par l'enrichissement par série, et
#: Kavita en garde la trace. Ne pas la lui transmettre faisait *redeviner* la
#: série à chaque passe par tome, par recherche de titre : sur « Gaston
#: Lagaffe », la recherche peut tomber sur une autre édition du même titre, dont
#: les numéros d'albums ne recoupent pas ceux de Kavita — l'index revient alors
#: exact mais inutilisable, et l'aperçu conclut « aucun fournisseur ne connaît
#: cette série » alors que le fournisseur la connaissait très bien.
#:
#: Les clés sont nommées par fournisseur, jamais génériques : un `provider_id`
#: passe-partout serait accepté par n'importe quel scraper, et un identifiant
#: AniList lu comme un numéro de run ComicVine rendrait l'index complet d'une
#: œuvre sans rapport — c'est le risque que `forced_id_for` écarte déjà pour le
#: Champ Magique.
_EXTERNAL_ID_HINTS = {
    "aniListId": "anilist_id",
    "malId": "mal_id",
    "hardcoverId": "hardcover_id",
    "metronId": "metron_id",
    "comicVineId": "comicvine_id",
    "mangaBakaId": "mangabaka_id",
    "cbrId": "cbr_id",
}


def provider_hints(series: Optional[dict]) -> Dict[str, Any]:
    """Ce que la série sait déjà d'elle-même, à l'usage des fournisseurs.

    Kavita rend `0` pour « pas d'identifiant » : c'est une absence, pas un
    numéro, et l'envoyer ferait chercher le run 0.
    """
    series = series or {}
    hints: Dict[str, Any] = {"year": series.get("year")}
    for kavita_key, hint_key in _EXTERNAL_ID_HINTS.items():
        try:
            value = int(series.get(kavita_key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            hints[hint_key] = str(value)
    loc = str(series.get("localizedName") or "").strip()
    if loc:
        hints["localizedName"] = loc
    alts: List[str] = []
    original = str(series.get("originalName") or "").strip()
    if original:
        alts.append(original)
    raw_alts = series.get("alternativeNames") or series.get("alternative_titles") or []
    if isinstance(raw_alts, str):
        raw_alts = [raw_alts]
    for title in raw_alts:
        text = str(title or "").strip()
        if text:
            alts.append(text)
    seen = {loc.casefold()} if loc else set()
    unique = []
    for title in alts:
        key = title.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(title)
    if unique:
        hints["alternative_titles"] = unique
    return hints


_lock = threading.Lock()
_state: Dict[str, Any] = {
    "running": False,
    "library_id": None,
    # Renseigné pour une passe sur une seule série, lancée depuis l'aperçu :
    # l'état est global, mais l'interface doit savoir de qui elle parle pour
    # remettre le bon bouton en progression.
    "series_id": None,
    "done": 0,
    "total": 0,
    "current_name": "",
    "phase": "",
    "provider": "",
    "error": None,
    # Une unité peut réussir son texte et se faire refuser sa couverture : sans
    # ce report, l'avertissement restait dans les journaux et l'utilisateur
    # repartait convaincu que la couverture était posée.
    "errors": [],
    "cancelled": False,
    # `cancelled` dit « une annulation est en cours », pas « la dernière passe a
    # été annulée » : le laisser à vrai après coup faisait rendre
    # `running=false, cancelled=true` à `/api/volume-enrich/status` jusqu'au
    # démarrage suivant. Le verdict de la passe terminée est ici.
    "was_cancelled": False,
    "counts": {},
    "skipped": 0,
}


def _begin_state(**fields) -> None:
    """Remet l'état à neuf pour une passe qui démarre. À appeler sous `_lock`.

    Les deux démarrages (bibliothèque, série) doivent laisser exactement le même
    état derrière eux : un champ oublié par l'un des deux, c'est le verdict de la
    passe précédente qui s'affiche au début de la suivante.
    """
    _state.update(
        {
            "running": True,
            "library_id": None,
            "series_id": None,
            "done": 0,
            "total": 0,
            "current_name": "",
            "phase": "starting",
            "provider": "",
            "error": None,
            "errors": [],
            "cancelled": False,
            "was_cancelled": False,
            "counts": {},
            "skipped": 0,
        }
    )
    _state.update(fields)


def _emit(event: str, payload: dict) -> None:
    # `extensions` et non `app` : importer le module applicatif depuis un thread
    # de fond réexécuterait son chargement partout où il n'est pas l'entrée du
    # process (même raison que dans hygiene_scan).
    try:
        from extensions import socketio

        socketio.emit(event, payload)
    except Exception as exc:
        logging.debug("[Tomes] emit %s ignoré : %s", event, exc)


def get_volume_enrich_state() -> dict:
    with _lock:
        return dict(_state)


def cancel_volume_enrich() -> Dict[str, Any]:
    """Demande l'arrêt : pris en compte entre deux unités, jamais au milieu."""
    with _lock:
        if not _state["running"]:
            return {"success": False, "running": False}
        _state["cancelled"] = True
    return {"success": True, "cancelled": True}


def _cancel_requested() -> bool:
    with _lock:
        return bool(_state.get("cancelled"))


def start_volume_enrich(
    library_id,
    series_ids: Optional[List[int]] = None,
    *,
    force: bool = False,
    with_credits: bool = False,
    resume: bool = True,
) -> Dict[str, Any]:
    """Lance la passe. Refuse d'en démarrer une seconde en parallèle."""
    with _lock:
        if _state["running"]:
            return {"success": False, "busy": True, **dict(_state)}
        _begin_state(library_id=str(library_id) if library_id is not None else "")

    thread = threading.Thread(
        target=_run,
        args=(library_id, list(series_ids or []), force, with_credits, resume),
        daemon=True,
        name="volume-enrich",
    )
    try:
        thread.start()
    except Exception as exc:
        # Un thread qui ne démarre pas laisserait `running` à vrai pour
        # toujours : plus aucune passe ne serait acceptée avant un redémarrage
        # du conteneur, et rien à l'écran ne dirait pourquoi.
        with _lock:
            _state["running"] = False
            _state["error"] = safe_exc_str(exc)
        logging.error("[Tomes] passe non démarrée : %s", safe_exc_str(exc))
        return {"success": False, "error": safe_exc_str(exc)}
    return {"success": True, "started": True}


#: Bilan d'une série qu'on n'a pas touchée du tout.
_EMPTY_COUNTS = {"done": 0, "skipped": 0, "failed": 0, "nothing": 0}

#: Ce que le journal dit d'une série écartée avant toute recherche. Le motif vient
#: de `matching.unmatchable_reason`, qui décide sans rien appeler.
_SKIP_REASONS = {
    "oneshot": "one-shot sans numéro de tome ni ISBN, rien à apparier "
               "— aucun fournisseur interrogé",
    "specials": "aucune unité n'a de numéro de tome ni d'ISBN, rien à apparier "
                "— aucun fournisseur interrogé",
}


def _unmatchable_without_override(series_id: int, units, name: str) -> str:
    """Écarte un one-shot sans ISBN, sauf si l'atelier a déjà posé un lien magique."""
    reason = unmatchable_reason(units, name)
    if not reason:
        return ""
    if get_volume_unit_overrides(series_id):
        return ""
    return reason


def _overlay_index(series_id: int, index, units):
    from services.workshop import overlay_overrides

    return overlay_overrides(series_id, index, units)

#: États d'unité sur lesquels une reprise n'a plus rien à faire. `FAILED` en est
#: absent exprès : c'est précisément ce qu'une reprise doit retenter (Kavita qui
#: hoquette le temps d'un tome), et `list_enriched_series_ids` rouvre déjà la
#: série pour cette raison.
_SETTLED_UNIT_STATES = frozenset({"DONE", "NOTHING_FOUND", "SKIPPED"})


def claim_series_write(series_id) -> bool:
    """Prend la réservation d'écriture d'une série. Faux si elle est déjà prise.

    Séparé du gestionnaire de contexte ci-dessous parce que la passe sur une
    seule série ne peut pas l'utiliser : la réservation doit être prise dans le
    greenlet de la requête — pour répondre 409 sans avoir démarré de thread — et
    relâchée dans le thread qui écrit, plusieurs minutes plus tard.
    """
    from services.enrichment_engine import _processing_lock, _processing_series_ids

    sid = int(series_id)
    with _processing_lock:
        if sid in _processing_series_ids:
            return False
        _processing_series_ids.add(sid)
    return True


def release_series_write(series_id) -> None:
    """Relâche la réservation. Sans effet si elle n'était pas prise."""
    from services.enrichment_engine import _processing_lock, _processing_series_ids

    with _processing_lock:
        _processing_series_ids.discard(int(series_id))


@contextmanager
def series_write_claim(series_id):
    """Réserve l'écriture d'une série, sous le verrou qui existe déjà.

    `services/enrichment_engine.py` tient un verrou par `series_id` parce que
    deux écrivains simultanés sur la même série « s'écraseraient silencieusement
    le travail de l'autre ». La passe tomes (thread dédié) et l'application
    unitaire (greenlet de requête) écrivent dans les mêmes séries : on réutilise
    ce verrou plutôt que d'en poser un second, qui laisserait chaque camp
    aveugle à l'autre.

    Rend True si la réservation est obtenue, False si quelqu'un écrit déjà.
    """
    claimed = claim_series_write(series_id)
    try:
        yield claimed
    finally:
        if claimed:
            release_series_write(series_id)


def enrich_one_series(
    api: KavitaAPI,
    series: Dict[str, Any],
    *,
    force: bool = False,
    with_credits: bool = False,
    experimental: bool = False,
    cache: Optional[dict] = None,
    should_cancel=None,
    config: Optional[dict] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    """Index, plan et écriture pour une série, sous la réservation d'écriture."""
    series_id = int(series.get("id"))
    with series_write_claim(series_id) as claimed:
        if not claimed:
            # Série déjà en cours d'écriture (clic « Mettre à jour », webhook,
            # application unitaire depuis l'aperçu). On ne pose PAS la
            # sentinelle : la série doit revenir à la passe suivante.
            logging.info(
                "[Tomes] %s ignorée : une écriture est déjà en cours ailleurs",
                series_label(series.get("name"), series_id),
            )
            return {"counts": dict(_EMPTY_COUNTS), "errors": [], "provider": "",
                    "busy": True}
        return _enrich_one_series_locked(
            api,
            series,
            force=force,
            with_credits=with_credits,
            experimental=experimental,
            cache=cache,
            should_cancel=should_cancel,
            config=config,
            resume=resume,
        )


def _enrich_one_series_locked(
    api: KavitaAPI,
    series: Dict[str, Any],
    *,
    force: bool = False,
    with_credits: bool = False,
    experimental: bool = False,
    cache: Optional[dict] = None,
    should_cancel=None,
    config: Optional[dict] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    """Index, plan et écriture pour une série. Réservation déjà obtenue.

    `cache` est la table `series_cache` déjà lue par l'appelant : la relire à
    chaque série ferait deux mille lectures complètes sur une bibliothèque de
    deux mille séries. `config` suit la même logique — l'ordre des fournisseurs
    s'y lit, et il ne change pas pendant la passe.

    `resume` fait relire l'état par unité, et pas seulement la ligne sentinelle
    de la série. La reprise se faisait jusqu'ici à la maille série : une
    annulation à l'unité 135 d'une série de 300 tomes faisait, au redémarrage,
    réinterroger le fournisseur pour la série entière et replanifier les 300
    unités — donc les relire une par une chez Kavita. Rien n'était réécrit,
    mais seulement parce que la politique « on ne comble que les vides »
    rattrapait le coup ; avec `VOLUME_FORCE_OVERWRITE` et un fournisseur HTML
    dont le texte varie d'une visite à l'autre, tout repartait en écriture. Le
    drapeau suit celui de la passe : `resume=False` (ou une série nommée
    explicitement) reste une demande de tout refaire.
    """
    series_id = int(series.get("id"))
    name = series.get("name") or ""
    label = series_label(name, series_id)
    library_type = (
        series.get("libraryType")
        or api.get_library_type_for_series(series_id)
        or "Manga"
    )

    # `get_series_volumes` rend `[]` aussi bien pour une série sans tome que
    # pour un Kavita muet : la confusion faisait marquer « traitée » une série
    # traversée pendant une coupure, donc écartée de toutes les passes
    # suivantes. `fetch_series_volumes` distingue les deux ; le `getattr` laisse
    # passer les doubles qui n'exposent que l'ancienne méthode.
    fetch_volumes = getattr(api, "fetch_series_volumes", None)
    if callable(fetch_volumes):
        volumes, read_error = fetch_volumes(series_id)
    else:
        volumes, read_error = api.get_series_volumes(series_id), None
    units = units_from_volumes(volumes or [])
    if not units and read_error:
        logging.warning(
            "[Tomes] %s laissée ouverte : tomes illisibles (%s)",
            label,
            read_error,
        )
        return {"counts": {"done": 0, "skipped": 0, "failed": 0, "nothing": 0,
                           "series_failed": 1},
                "errors": [str(read_error)], "provider": ""}
    if not units:
        # Rien à écrire, mais la question est tranchée : la marquer close évite
        # de réinterroger un fournisseur à chaque passe pour une série vide.
        mark_series_pass_done(series_id, provider="")
        return {"counts": {"done": 0, "skipped": 0, "failed": 0, "nothing": 0}, "errors": []}

    # Sans numéro de tome ni ISBN, aucune cascade ne peut rien apparier, quel que
    # soit le fournisseur. On retire la recherche avant de la payer — sauf si
    # l'atelier a déjà collé un lien magique sur un one-shot.
    out_of_scope = _unmatchable_without_override(series_id, units, name)
    if out_of_scope:
        logging.info("[Tomes] %s : %s", label, _SKIP_REASONS.get(out_of_scope, out_of_scope))
        mark_series_pass_done(series_id, provider="")
        return {"counts": {"done": 0, "skipped": 0, "failed": 0, "nothing": len(units)},
                "errors": [], "provider": "", "skipped_reason": out_of_scope}

    resumed = 0
    if resume:
        settled = {
            int(chapter_id)
            for chapter_id, state in (get_volume_unit_states(series_id) or {}).items()
            if (state or {}).get("status") in _SETTLED_UNIT_STATES
        }
        if settled:
            pending = [u for u in units if int(u.get("chapter_id") or 0) not in settled]
            resumed = len(units) - len(pending)
            units = pending
    staged = {
        int(cid)
        for cid, ov in (get_volume_unit_overrides(series_id) or {}).items()
        if (ov.get("payload") or {}).get("_staged")
    }
    if staged:
        units = [u for u in units if int(u.get("chapter_id") or 0) not in staged]
    if not units:
        # Toutes les unités portent déjà leur verdict ou sont en attente d'envoi dans l'atelier :
        # la passe auto ne doit pas écrire par-dessus.
        mark_series_pass_done(series_id, provider="")
        return {"counts": {"done": 0, "skipped": 0, "failed": 0, "nothing": 0,
                           "resumed": resumed}, "errors": [], "provider": ""}

    # Ligne d'ouverture. La recherche chez le fournisseur est la phase la plus
    # longue et la plus muette de la passe — une minute par série, parfois — et
    # rien ne disait ce qui était en cours ni sur quelle œuvre.
    logging.info(
        "[Tomes] ▶ %s : %s tome(s) dans Kavita — recherche des albums…",
        label,
        len(units),
    )

    cached = (cache or {}).get(series_id) or {}
    index_started = time.monotonic()
    if unmatchable_reason(units, name) and get_volume_unit_overrides(series_id):
        provider, index = "", {}
    else:
        provider, index = resolve_index(
            name,
            units,
            library_type=library_type,
            forced_id=str(cached.get("forced_id") or ""),
            forced_provider=str(cached.get("forced_provider") or ""),
            existing_metadata=provider_hints(series),
            should_cancel=should_cancel,
            experimental=experimental,
            config=config,
            kavita_series_id=series_id,
        )
    index = _overlay_index(series_id, index, units)
    if not index:
        # Personne ne connaît cette série. C'est un résultat, et il se retient :
        # ce sont précisément les séries les plus coûteuses (recherche complète
        # puis échec) qui repartiraient en entier à chaque passe.
        # `providers.fetch_index` a déjà nommé la série et les fournisseurs
        # consultés : rien à ajouter ici.
        if not (should_cancel and should_cancel()):
            mark_series_pass_done(series_id, provider="")
        return {"counts": {"done": 0, "skipped": 0, "failed": 0, "nothing": len(units),
                           "resumed": resumed}, "errors": [], "provider": ""}

    logging.info(
        "[Tomes] %s : %s album(s) trouvé(s) via %s en %.1f s",
        label,
        len(index),
        provider or "—",
        time.monotonic() - index_started,
    )

    # La passe de bibliothèque n'a pas d'aperçu à alimenter, mais elle écrit dans
    # les mêmes champs : sans cela, la langue des résumés dépendrait du bouton
    # utilisé pour les écrire. Après le plan, pour ne traduire que ce qui part.
    plan = build_plan(units, index, force=force, provider=provider)
    plan["series_id"] = series_id
    plan["series_name"] = name
    plan = translate_plan_summaries(plan, config)
    fetcher = credits_fetcher(provider) if with_credits else None
    result = apply_plan(
        api,
        series_id,
        plan,
        force=force,
        credits_fetcher=fetcher,
        should_cancel=should_cancel,
    )
    # Close la série pour la reprise, mais seulement si la passe est allée au
    # bout : une annulation au tome 3 sur 40 ne doit pas faire passer les 37
    # autres pour traités.
    #
    # Un tome en échec compte pour une passe inachevée, lui aussi. Kavita qui
    # hoquette (scan en cours, redémarrage, 502 du reverse-proxy) fait rendre
    # `None` à `get_chapter()` : `apply_entry` sort en FAILED sans jamais lever,
    # donc la série traversait l'incident, recevait sa sentinelle et se voyait
    # **définitivement** exclue de la reprise — relancer affichait « déjà
    # traitée » et la sautait.
    failed = int((result.get("counts") or {}).get("failed") or 0)
    if should_cancel and should_cancel():
        pass
    elif failed:
        logging.warning(
            "[Tomes] %s laissée ouverte à la reprise : %s tome(s) en échec",
            label,
            failed,
        )
    else:
        mark_series_pass_done(series_id, provider=provider)
    if resumed:
        result.setdefault("counts", {})["resumed"] = resumed
    result["provider"] = provider
    return result


def _run(library_id, series_ids: List[int], force: bool, with_credits: bool, resume: bool) -> None:
    started = time.monotonic()
    config = load_config()
    api = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    experimental = bool(config.get("VOLUME_ENRICH_EXPERIMENTAL", False))
    # `series_failed` compte des séries, les quatre autres cases comptent des
    # unités : mélanger les deux faisait annoncer « 60 échecs » pour 60 séries
    # représentant 240 tomes, sans qu'on puisse savoir de quoi il s'agissait ni
    # réconcilier le total.
    totals = {"done": 0, "skipped": 0, "failed": 0, "nothing": 0, "series_failed": 0}
    scan_all = not library_id or str(library_id).strip().lower() == "all"

    try:
        if series_ids:
            # Une série que Kavita ne rend pas est écartée, jamais remplacée par
            # une fiche bâtie sur son identifiant : `name` sert de titre à la
            # recherche chez le fournisseur, et chercher « 6429 » ramène soit
            # rien, soit l'album d'une autre œuvre — écrit ensuite tome par tome.
            # Le chemin ne coûtait rien tant que la sélection n'existait pas ;
            # c'est aujourd'hui le seul par lequel la passe démarre.
            targets = []
            for sid in series_ids:
                series = api.get_series(int(sid))
                if not series or not (series.get("name") or "").strip():
                    totals["series_failed"] += 1
                    logging.warning(
                        "[Tomes] %s introuvable dans Kavita — écartée de la passe",
                        series_label(None, sid),
                    )
                    continue
                targets.append(series)
        else:
            targets = api.get_all_series(library_id=None if scan_all else library_id)

        if resume and not series_ids:
            already = list_enriched_series_ids()
            before = len(targets)
            targets = [t for t in targets if int(t.get("id") or 0) not in already]
            skipped = before - len(targets)
            if skipped:
                with _lock:
                    _state["skipped"] = skipped
                logging.info("[Tomes] reprise : %s série(s) déjà traitée(s)", skipped)

        # Une seule lecture de series_cache pour toute la passe : la relire par
        # série ferait deux mille lectures complètes sur une grosse
        # bibliothèque, pour un contenu qui ne bouge pas pendant le parcours.
        cache = get_all_cached_data()

        with _lock:
            _state["total"] = len(targets)
            _state["phase"] = "series"

        _emit(
            "volume_enrich_progress",
            {"running": True, "done": 0, "total": len(targets), "library_id": library_id},
        )

        logging.info(
            "[Tomes] ▶ Passe sur %s série(s)%s%s",
            len(targets),
            " sélectionnée(s)" if series_ids else " de la bibliothèque",
            " — écrasement forcé" if force else "",
        )

        for series in targets:
            if _cancel_requested():
                logging.info("[Tomes] annulation demandée — arrêt de la passe")
                break
            name = series.get("name") or str(series.get("id"))
            with _lock:
                _state["current_name"] = name
                _state["phase"] = "series"

            try:
                result = enrich_one_series(
                    api,
                    series,
                    force=force,
                    with_credits=with_credits,
                    experimental=experimental,
                    cache=cache,
                    should_cancel=_cancel_requested,
                    config=config,
                    resume=resume and not series_ids,
                )
                for key, value in (result.get("counts") or {}).items():
                    totals[key] = totals.get(key, 0) + value
            except Exception as exc:
                totals["series_failed"] += 1
                logging.error(
                    "[Tomes] %s en échec : %s",
                    series_label(series.get("name"), series.get("id")),
                    safe_exc_str(exc),
                )

            with _lock:
                _state["done"] += 1
                _state["counts"] = dict(totals)
                done, total = _state["done"], _state["total"]

            _emit(
                "volume_enrich_progress",
                {
                    "running": True,
                    "done": done,
                    "total": total,
                    "current_name": name,
                    "counts": dict(totals),
                    "library_id": library_id,
                },
            )

            # Une série n'est pas un point de bascule : sous le worker eventlet
            # unique, une bibliothèque dont les séries sont vides ou déjà
            # traitées défile sans jamais toucher au réseau, donc sans jamais
            # rendre la main.
            yield_to_worker()
    except Exception as exc:
        logging.error("[Tomes] passe interrompue : %s", safe_exc_str(exc))
        with _lock:
            _state["error"] = safe_exc_str(exc)
    finally:
        with _lock:
            _state["running"] = False
            _state["phase"] = "done"
            _state["counts"] = dict(totals)
            # L'annulation est une demande, pas un état durable : la garder à
            # vrai après la passe faisait rendre `running=false, cancelled=true`
            # jusqu'au démarrage suivant.
            _state["was_cancelled"] = bool(_state["cancelled"])
            _state["cancelled"] = False
            snapshot = dict(_state)
        logging.info(
            "[Tomes] %s Passe terminée en %.1f s : %s série(s) parcourue(s), "
            "%s tome(s) écrit(s), %s sans rien à changer, %s en échec%s",
            "⛔" if snapshot.get("was_cancelled") else "✅",
            time.monotonic() - started,
            snapshot.get("done", 0),
            totals.get("done", 0),
            totals.get("skipped", 0) + totals.get("nothing", 0),
            totals.get("failed", 0),
            f" — {totals['series_failed']} série(s) en échec"
            if totals.get("series_failed") else "",
        )
        _emit("volume_enrich_progress", {**snapshot, "running": False})
        _emit("volume_enrich_done", snapshot)


# ===== Passe sur une seule série, lancée depuis l'aperçu =====
#
# L'écriture d'une série se faisait dans le greenlet de la requête HTTP, de bout
# en bout : reconstruction du plan (donc réinterrogation du fournisseur), puis
# pour chaque tome une lecture, une écriture et un téléversement de couverture.
# Sur l'unique worker eventlet qui sert toute l'application, cela veut dire une
# requête qui dure des minutes, un bouton bloqué sur « Écriture en cours… » sans
# rien dire de sa progression, et rien pour l'arrêter. La machinerie de la passe
# de bibliothèque répondait déjà à ces trois besoins : on l'emprunte plutôt que
# d'en écrire une seconde.


def build_series_plan(
    api,
    series_id: int,
    *,
    force: bool = False,
    experimental: bool = False,
    config: Optional[dict] = None,
    should_cancel=None,
    cache: Optional[dict] = None,
) -> Dict[str, Any]:
    """Plan complet d'une série : tomes lus chez Kavita, index chez le fournisseur.

    Vit ici et non dans la route parce que les deux chemins doivent bâtir le même
    plan avec les mêmes réglages : l'aperçu, dans le greenlet de la requête, et
    l'écriture, dans son thread. `plan.py` ne pouvait pas l'accueillir — c'est le
    module qui ne fait aucune entrée-sortie, et c'est ce qui rend l'aperçu exact.

    L'index est mémoïsé (`index_cache`) : l'écriture qui suit un aperçu ne
    réinterroge plus le fournisseur. Les tomes, eux, sont relus à chaque appel,
    et `apply_entry` relira encore chaque chapitre avant de l'écrire.
    """
    started = time.monotonic()
    series = api.get_series(series_id) or {}
    name = series.get("name") or ""
    label = series_label(name, series_id)
    library_type = (
        series.get("libraryType")
        or api.get_library_type_for_series(series_id)
        or "Manga"
    )
    units = units_from_volumes(api.get_series_volumes(series_id))
    read_seconds = time.monotonic() - started
    if not units:
        logging.info("[Tomes] %s : aucun tome lisible dans Kavita", label)
        return {
            "provider": "",
            "units": [],
            "unmatched": [],
            "counts": {"matched": 0, "unmatched": 0, "writable": 0, "fields": 0},
            "series_id": series_id,
            "series_name": name,
            "index_cached": False,
        }

    # Même raccourci que dans la passe, et au même endroit : avant le premier
    # appel réseau. L'aperçu d'un one-shot faisait patienter sur une recherche
    # dont le résultat était connu, puis affichait un vide sans le dire. Un
    # Champ Magique d'atelier lève le raccourci.
    out_of_scope = _unmatchable_without_override(series_id, units, name)
    if out_of_scope:
        logging.info("[Tomes] %s : %s", label, _SKIP_REASONS.get(out_of_scope, out_of_scope))
        return {
            "provider": "",
            "units": [],
            "unmatched": [],
            "counts": {"matched": 0, "unmatched": len(units), "writable": 0, "fields": 0},
            "series_id": series_id,
            "series_name": name,
            "index_cached": False,
            "skipped_reason": out_of_scope,
        }

    logging.info(
        "[Tomes] ▶ %s : %s tome(s) dans Kavita — recherche des albums…",
        label,
        len(units),
    )

    cached = (cache if cache is not None else get_all_cached_data()).get(series_id) or {}
    index_started = time.monotonic()
    if unmatchable_reason(units, name) and get_volume_unit_overrides(series_id):
        provider, index, from_cache = "", {}, False
    else:
        provider, index, from_cache = resolve_index_cached(
            series_id,
            name,
            units,
            library_type=library_type,
            force=force,
            forced_id=str(cached.get("forced_id") or ""),
            forced_provider=str(cached.get("forced_provider") or ""),
            existing_metadata=provider_hints(series),
            experimental=experimental,
            config=config,
            should_cancel=should_cancel,
        )
    index = _overlay_index(series_id, index, units)
    index_seconds = time.monotonic() - index_started
    logging.info(
        "[Tomes] %s : %s album(s) trouvé(s) via %s en %.1f s (%s) — tomes lus en %.1f s",
        label,
        len(index or {}),
        provider or "—",
        index_seconds,
        "déjà en mémoire" if from_cache else "fournisseur interrogé",
        read_seconds,
    )

    # Après le plan, et seulement sur les résumés qu'il va écrire : l'aperçu
    # montre le texte qui partira réellement, sans payer un appel pour les albums
    # que Kavita ne détient pas ni pour ceux dont le résumé est déjà là. Mémoïsé
    # de son côté : l'écriture retrouve les mêmes phrases sans repayer.
    plan = build_plan(units, index, force=force, provider=provider)
    plan["series_id"] = series_id
    # Posé avant la traduction : c'est ce qui lui permet de nommer la série dans
    # sa ligne de bilan, comme le reste de la passe.
    plan["series_name"] = name
    plan = translate_plan_summaries(plan, config)
    # Rendu à l'appelant plutôt que déduit des journaux : c'est le seul moyen de
    # vérifier, en test comme en production, que le pont aperçu → écriture tient.
    plan["index_cached"] = bool(from_cache)
    return plan


#: Statut d'unité -> case du décompte. `apply_plan` fait le même tri, mais il ne
#: rend son bilan qu'à la fin : une série de quarante albums doit dire où elle en
#: est avant.
_STATUS_COUNTS = {"DONE": "done", "FAILED": "failed", "NOTHING_FOUND": "nothing"}


def start_series_volume_enrich(
    series_id: int,
    *,
    selection: Optional[Dict[Any, List[str]]] = None,
    force: bool = False,
    with_credits: bool = False,
) -> Dict[str, Any]:
    """Lance l'écriture d'une série en tâche de fond.

    Deux refus, tous deux avant qu'aucun thread ne démarre :

    * une passe tourne déjà — l'état de progression est global, deux passes s'y
      écraseraient l'une l'autre, et l'utilisateur ne saurait plus laquelle il
      regarde ni laquelle il annule ;
    * la série est déjà en cours d'écriture — c'est la réservation que la route
      prenait déjà avant de bloquer sur son écriture synchrone. Sans elle, un
      double-clic récupérait les crédits deux fois, téléversait la couverture
      deux fois et enregistrait deux verdicts pour la même unité.

    La réservation est prise ici et relâchée par le thread : la prendre dans le
    thread laisserait la route répondre « démarré » à un second clic qu'elle
    aurait dû refuser.
    """
    sid = int(series_id)
    with _lock:
        if _state["running"]:
            return {"success": False, "busy": True, **dict(_state)}
        _begin_state(series_id=sid, phase="series")

    if not claim_series_write(sid):
        with _lock:
            _state["running"] = False
            _state["phase"] = "done"
        return {"success": False, "busy": True, "series_busy": True, "series_id": sid}

    thread = threading.Thread(
        target=_run_series,
        args=(sid, selection, force, with_credits),
        daemon=True,
        name=f"volume-enrich-series-{sid}",
    )
    try:
        thread.start()
    except Exception as exc:
        # Même filet que pour la passe de bibliothèque : un thread qui ne
        # démarre pas laisserait `running` à vrai pour toujours, et la série
        # réservée jusqu'au redémarrage du conteneur.
        release_series_write(sid)
        with _lock:
            _state["running"] = False
            _state["error"] = safe_exc_str(exc)
        logging.error(
            "[Tomes] %s : écriture non démarrée — %s",
            series_label(None, sid),
            safe_exc_str(exc),
        )
        return {"success": False, "error": safe_exc_str(exc)}
    return {"success": True, "started": True, "series_id": sid}


def _run_series(
    series_id: int,
    selection: Optional[Dict[Any, List[str]]],
    force: bool,
    with_credits: bool,
) -> None:
    """Écrit une série, en diffusant sa progression à la maille de l'unité.

    La maille compte : à celle de la série, une série unique afficherait
    « 0 / 1 » puis « 1 / 1 » — ce qui ne dit rien à quelqu'un qui attend
    quarante albums. `apply_plan` appelle `on_progress` pour chaque unité qu'il
    traite réellement, et lui seul sait lesquelles la sélection retient.
    """
    started = time.monotonic()
    config = load_config()
    api = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    totals = dict(_EMPTY_COUNTS)
    errors: List[str] = []
    # Vide, pas l'identifiant : `series_label` annonce « série 6429 » quand il
    # n'y a pas de titre, là où un `name = "6429"` se lirait comme un titre.
    name = ""
    provider = ""

    def _on_unit(_position: int, _total: int, outcome: Dict[str, Any]) -> None:
        totals[_STATUS_COUNTS.get(outcome.get("status"), "skipped")] += 1
        with _lock:
            _state["done"] += 1
            _state["counts"] = dict(totals)
            done, total = _state["done"], _state["total"]
        _emit(
            "volume_enrich_progress",
            {
                "running": True,
                "done": done,
                "total": total,
                "current_name": name or str(series_id),
                "series_id": series_id,
                "provider": provider,
                "counts": dict(totals),
            },
        )

    try:
        plan = build_series_plan(
            api,
            series_id,
            force=force,
            experimental=bool(config.get("VOLUME_ENRICH_EXPERIMENTAL", False)),
            config=config,
            should_cancel=_cancel_requested,
        )
        name = plan.get("series_name") or name
        provider = plan.get("provider") or ""
        entries = [
            entry
            for entry in (plan.get("units") or [])
            if selection is None or entry.get("chapter_id") in selection
        ]
        with _lock:
            _state["total"] = len(entries)
            _state["current_name"] = name or str(series_id)
            _state["provider"] = provider
            _state["phase"] = "units"
        _emit(
            "volume_enrich_progress",
            {
                "running": True,
                "done": 0,
                "total": len(entries),
                "current_name": name or str(series_id),
                "series_id": series_id,
                "provider": provider,
                "counts": dict(totals),
            },
        )

        if entries:
            fetcher = credits_fetcher(provider) if with_credits else None
            result = apply_plan(
                api,
                series_id,
                plan,
                selection=selection,
                force=force,
                credits_fetcher=fetcher,
                should_cancel=_cancel_requested,
                on_progress=_on_unit,
            )
            totals.update(result.get("counts") or {})
            errors = list(result.get("errors") or [])
    except Exception as exc:
        logging.error(
            "[Tomes] %s : écriture interrompue — %s",
            series_label(name, series_id),
            safe_exc_str(exc),
        )
        with _lock:
            _state["error"] = safe_exc_str(exc)
    finally:
        # La réservation d'écriture a été prise par la route : elle se relâche
        # ici, quoi qu'il arrive, sinon la série resterait injoignable jusqu'au
        # redémarrage du conteneur.
        release_series_write(series_id)
        with _lock:
            _state["running"] = False
            _state["phase"] = "done"
            _state["counts"] = dict(totals)
            _state["errors"] = errors[:5]
            _state["was_cancelled"] = bool(_state["cancelled"])
            _state["cancelled"] = False
            snapshot = dict(_state)
        logging.info(
            "[Tomes] %s %s via %s : %s tome(s) écrit(s), %s sans rien à changer, "
            "%s en échec en %.1f s",
            "⛔" if snapshot.get("was_cancelled") else "✅",
            series_label(name, series_id),
            provider or "—",
            totals.get("done", 0),
            totals.get("skipped", 0) + totals.get("nothing", 0),
            totals.get("failed", 0),
            time.monotonic() - started,
        )
        _emit("volume_enrich_progress", {**snapshot, "running": False})
        _emit("volume_enrich_done", snapshot)
