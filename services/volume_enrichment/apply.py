"""
Exécution d'un plan d'enrichissement, unité par unité.

Deux règles gouvernent ce module.

**On relit avant d'écrire.** Le plan a pu être construit il y a dix minutes,
l'utilisateur a pu éditer le tome dans Kavita entre-temps, et surtout
`UpdateChapterDto` remplace tout : partir d'un état périmé effacerait ce qui a
été ajouté depuis. La politique de comblement est donc réappliquée sur l'état
frais, pas sur celui de l'aperçu.

**On cadence.** Les appels Kavita sont locaux, mais la passe de crédits
interroge le fournisseur une fois par album : `throttle_provider` la borne comme
le reste de MetaKavita.

Les crédits sont le cas particulier de ces deux règles : `ChapterController`
n'inspecte aucun verrou avant d'assigner les treize collections de personnes, si
bien que rien côté Kavita ne rattrape un payload trop généreux. La politique
leur est donc appliquée ici, par `credits_to_write`, et non déléguée au serveur.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

from db_manager import (
    purge_series_hygiene_cache,
    record_lifetime_event,
    record_workshop_history,
    save_volume_unit_state,
)
from secure_logging import safe_exc_str, series_label
from services.cooperative import yield_to_worker
from services.kavita_chapter_payload import (
    build_update_chapter_dto,
    credits_to_write,
    split_written_fields,
)
from services.volume_enrichment.plan import changes_to_write, plan_unit, unit_label

#: Étapes chronométrées d'une unité, dans l'ordre où elles surviennent. « Une
#: éternité » était le seul diagnostic disponible : les journaux ne disaient ni
#: combien de temps prenait la lecture du chapitre, ni l'écriture, ni le
#: téléchargement de la couverture, ni son envoi à Kavita — donc le coupable se
#: devinait. `time.monotonic` et non `time.time` : c'est une durée, et l'horloge
#: murale d'un conteneur peut sauter (NTP, veille de l'hôte).
_STEPS = ("read", "credits", "write", "cover")


@contextmanager
def _timed(marks: Dict[str, float], step: str):
    start = time.monotonic()
    try:
        yield
    finally:
        marks[step] = marks.get(step, 0.0) + (time.monotonic() - start)


def _format_marks(marks: Dict[str, float]) -> str:
    """« read=0.04s write=0.31s cover=2.80s ». Les étapes nulles sont muettes."""
    return " ".join(
        f"{step}={marks[step]:.2f}s" for step in _STEPS if marks.get(step)
    )


def apply_entry(
    api,
    series_id: int,
    entry: Dict[str, Any],
    *,
    force: bool = False,
    fields: Optional[List[str]] = None,
    provider: str = "",
    credits_fetcher: Optional[Callable[[str], Optional[Dict[str, List[str]]]]] = None,
    label: str = "",
    origin: str = "",
) -> Dict[str, Any]:
    """Écrit une unité. Rend `{status, written, error, timings}`.

    `label` est le nom de la série tel qu'il apparaît dans le journal. Il n'entre
    dans aucune décision : il sert à ce qu'un refus de couverture nomme l'œuvre
    concernée plutôt qu'un identifiant de chapitre.

    `status` vaut `DONE`, `NOTHING_FOUND`, `SKIPPED` ou `FAILED` — les quatre
    états du cache d'unités, pour que la reprise sache quoi refaire.

    `timings` porte le temps passé par étape, en secondes : c'est ce que
    `apply_plan` additionne pour son récapitulatif de fin de série.
    """
    chapter_id = entry.get("chapter_id")
    marks: Dict[str, float] = {}
    result = {"chapter_id": chapter_id, "status": "SKIPPED", "written": [],
              "error": "", "timings": marks}
    if not chapter_id:
        return result

    proposed = changes_to_write(entry, fields)
    want_credits = bool(credits_fetcher and entry.get("provider_ref"))
    want_workshop = origin == "workshop"
    if not proposed and not want_credits and not want_workshop:
        result["status"] = "NOTHING_FOUND" if not entry.get("changes") else "SKIPPED"
        return result

    with _timed(marks, "read"):
        current = api.get_chapter(chapter_id)
    if not current:
        # Un dict vide passerait pour un chapitre sans métadonnées, et
        # l'écriture qui suit effacerait tout ce que Kavita avait.
        result["status"] = "FAILED"
        result["error"] = "chapter-read-failed"
        return result

    # Politique réappliquée sur l'état frais : ce qui a été rempli ou verrouillé
    # depuis l'aperçu n'est plus à écrire.
    fresh = plan_unit(entry, {**proposed, "provider_ref": entry.get("provider_ref")},
                      force=force, chapter=current)
    changes = changes_to_write(fresh, fields)

    if origin == "workshop":
        from services.workshop_form import form_chapter_changes

        extra = form_chapter_changes(entry.get("edits") or {}, current, force=force)
        extra_people = extra.pop("people", None)
        changes.update(extra)
        if extra_people:
            merged = dict(changes.get("people") or {})
            merged.update(extra_people)
            changes["people"] = merged

    if credits_fetcher and entry.get("provider_ref"):
        try:
            # La cadence est portée par le fetcher lui-même (voir
            # providers.credits_fetcher) : c'est lui qui connaît le scraper.
            with _timed(marks, "credits"):
                people = credits_fetcher(entry["provider_ref"])
        except Exception as exc:
            people = None
            logging.debug("[Tomes] crédits indisponibles : %s", safe_exc_str(exc))
        # `ChapterController` n'inspecte aucun verrou : une collection envoyée est
        # une collection écrite. La politique de comblement doit donc être
        # appliquée ici, sur l'état frais, sans quoi les crédits seraient la seule
        # écriture du module à passer outre les verrous de l'utilisateur.
        allowed = credits_to_write(current, people, force=force)
        if allowed:
            changes["people"] = allowed
        elif people:
            logging.debug(
                "[Tomes] crédits écartés (verrou ou collection déjà remplie) pour le chapitre %s",
                chapter_id,
            )

    cover_url = changes.pop("cover_url", "")

    if not changes and not cover_url:
        result["status"] = "SKIPPED"
        return result

    written: List[str] = []
    if changes:
        dto = build_update_chapter_dto(current, changes)
        written = split_written_fields(dto)
        if written:
            with _timed(marks, "write"):
                ok, message = api.update_chapter_metadata(dto)
            if not ok:
                result["status"] = "FAILED"
                result["error"] = message
                return result

    if cover_url:
        # Le détail (téléchargement chez le fournisseur puis envoi en base64 à
        # Kavita, qui génère sa vignette) est chronométré dans
        # `KavitaAPI.upload_chapter_cover` : d'ici, les deux sont indissociables.
        with _timed(marks, "cover"):
            ok, message = api.upload_chapter_cover(chapter_id, cover_url, lock=True)
        if ok:
            written.append("cover")
        else:
            # La couverture est un extra : son échec ne condamne pas le texte
            # déjà écrit, mais il doit se voir.
            logging.info(
                "[Tomes] %s %s : couverture refusée — %s",
                label or series_label(None, series_id),
                unit_label(entry),
                message,
            )
            result["error"] = message

    result["written"] = written
    result["status"] = "DONE" if written else "SKIPPED"
    if origin == "workshop" and result["status"] == "DONE":
        record_lifetime_event("workshop_units")
        record_workshop_history(
            series_id,
            "send",
            chapter_id=chapter_id,
            detail={
                "fields": list(written),
                "volume_number": entry.get("volume_number"),
                "chapter_number": entry.get("chapter_number"),
            },
        )
    logging.debug(
        "[Tomes] %s %s écrit : %s",
        label or series_label(None, series_id),
        unit_label(entry),
        _format_marks(marks),
    )
    return result


def apply_plan(
    api,
    series_id: int,
    plan: Dict[str, Any],
    *,
    selection: Optional[Dict[Any, List[str]]] = None,
    force: bool = False,
    credits_fetcher: Optional[Callable[[str], Optional[Dict[str, List[str]]]]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Exécute le plan et tient le cache d'unités à jour.

    `selection` restreint aux unités et champs cochés dans l'aperçu :
    `{chapter_id: ["summary", "cover_url"]}`. Sans elle, tout le plan part.
    """
    provider = plan.get("provider") or ""
    entries = plan.get("units") or []
    counts = {"done": 0, "skipped": 0, "failed": 0, "nothing": 0}
    total = len(entries)
    errors: List[str] = []
    started = time.monotonic()
    processed = 0
    spent: Dict[str, float] = {}
    # Le nom vient du plan, seul endroit où les deux chemins l'ont déjà : la passe
    # le lit chez Kavita, l'aperçu le renvoie à l'interface.
    label = series_label(plan.get("series_name"), series_id)

    # Une ligne à l'entrée, pas seulement au bilan. Sans elle, une passe bloquée
    # sur sa première unité est indiscernable d'une passe jamais démarrée : le
    # journal ne portait rien entre la traduction de l'index et le récapitulatif
    # de fin, et le seul indice restait un « 0 / N » figé à l'écran.
    logging.info(
        "[Tomes] %s : écriture de %s tome(s) via %s%s…",
        label,
        len(entries) if selection is None else sum(
            1 for e in entries if e.get("chapter_id") in selection
        ),
        provider or "—",
        " (écrasement forcé)" if force else "",
    )

    for position, entry in enumerate(entries, start=1):
        if should_cancel and should_cancel():
            break
        chapter_id = entry.get("chapter_id")
        if selection is not None and chapter_id not in selection:
            continue
        fields = selection.get(chapter_id) if selection is not None else None

        try:
            outcome = apply_entry(
                api,
                series_id,
                entry,
                force=force,
                fields=fields,
                provider=provider,
                credits_fetcher=credits_fetcher,
                label=label,
            )
        except Exception as exc:
            logging.error("[Tomes] %s %s : écriture impossible — %s",
                          label, unit_label(entry), safe_exc_str(exc))
            outcome = {
                "chapter_id": chapter_id,
                "status": "FAILED",
                "written": [],
                "error": safe_exc_str(exc),
            }

        processed += 1
        for step, seconds in (outcome.get("timings") or {}).items():
            spent[step] = spent.get(step, 0.0) + seconds

        # Une erreur remonte quel que soit l'état : une unité peut réussir son
        # texte et se faire refuser sa couverture, et cet échec-là reste `DONE`.
        # Ne collecter que sur `FAILED` le laissait dans les seuls journaux —
        # l'utilisateur repartait convaincu que la couverture était posée.
        if outcome.get("error"):
            errors.append(str(outcome["error"]))

        if outcome["status"] == "DONE":
            counts["done"] += 1
        elif outcome["status"] == "FAILED":
            counts["failed"] += 1
        elif outcome["status"] == "NOTHING_FOUND":
            counts["nothing"] += 1
        else:
            counts["skipped"] += 1

        if chapter_id:
            try:
                save_volume_unit_state(
                    series_id,
                    chapter_id,
                    outcome["status"],
                    volume_id=entry.get("volume_id"),
                    volume_number=entry.get("volume_number"),
                    chapter_number=entry.get("chapter_number"),
                    provider=provider,
                    written_fields=outcome.get("written"),
                )
            except Exception as exc:
                # Perdre la trace ne doit pas perdre l'écriture : la passe
                # suivante refera l'unité, ce qui est sans danger.
                logging.debug("[Tomes] état d'unité non enregistré : %s", safe_exc_str(exc))

        if on_progress:
            on_progress(position, total, outcome)

        # La passe ne rendait la main qu'aux entrées-sorties Kavita : plus
        # Kavita répond vite, moins elle basculait. Mesuré sous eventlet avec un
        # vrai serveur WSGI et un Kavita instantané, 4 500 unités : pas une
        # seule requête HTTP servie de toute la passe.
        yield_to_worker()

    if counts["done"]:
        # Le rapport de tomes de l'Inventaire sert son analyse depuis un cache.
        # Sans cette purge, il continuait d'annoncer « sans résumé : 11 / 11 »
        # après une écriture réussie, et l'utilisateur jugeait le résultat sur une
        # photo d'avant — la ligne du tableau montrait la nouvelle valeur, l'encart
        # de tête l'ancienne, et les deux se contredisaient à l'écran.
        #
        # `keep_overrides=True` : l'attendu forcé et l'exclusion de l'inventaire
        # sont des décisions de l'utilisateur, pas de l'analyse. Une écriture de
        # métadonnées n'a aucune raison de les effacer.
        try:
            purge_series_hygiene_cache(series_id, keep_overrides=True)
        except Exception as exc:
            # Un rapport périmé se rafraîchit d'un clic ; perdre l'écriture, non.
            logging.debug(
                "[Tomes] %s : cache d'hygiène non purgé — %s",
                label,
                safe_exc_str(exc),
            )

    if processed:
        # Au niveau `info` : c'est le récapitulatif qu'on veut trouver dans le
        # journal d'un utilisateur qui écrit « l'écriture prend une éternité »,
        # sans lui demander de passer en debug pour le reproduire.
        logging.info(
            "[Tomes] ✅ %s : %s tome(s) traité(s) en %.1f s — %s écrit(s), "
            "%s sans rien à changer, %s en échec — %s",
            label,
            processed,
            time.monotonic() - started,
            counts["done"],
            counts["skipped"] + counts["nothing"],
            counts["failed"],
            _format_marks(spent) or "aucun appel",
        )
    return {"counts": counts, "errors": errors[:5], "timings": spent}
