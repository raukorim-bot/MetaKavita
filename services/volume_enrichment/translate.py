"""Traduction des résumés d'album, avant qu'ils n'entrent dans le plan.

L'enrichissement par tome écrivait les résumés dans la langue du fournisseur.
Pour une bibliothèque de comics, cela voulait dire du texte anglais posé sur
chaque album — **et verrouillé au passage**, donc hors de portée d'une correction
ultérieure, puisque la politique de comblement épargne ce qui est verrouillé.

**Le plan est le bon grain, et l'index ne l'était pas.** La traduction portait
d'abord sur l'index entier, en amont de l'appariement : elle payait un appel
réseau pour chaque album que le fournisseur connaît. Or l'index d'un run ComicVine
compte cent numéros là où Kavita en détient dix, et sur une série déjà enrichie
tous les résumés sont remplis et verrouillés — donc traduits pour rien, à chaque
passe, à raison d'un appel par seconde pendant plusieurs minutes. Le plan, lui,
sait exactement quels résumés seront écrits : ce sont ceux-là, et eux seuls, qui
partent chez le traducteur. Une série déjà traduite ne coûte plus un seul appel.

Ce que le grain de l'index protégeait — un album qui couvre deux chapitres,
traduit deux fois — est de toute façon couvert par la mémoïsation, dont la clé est
le texte source.

**Le plan ne fait aucune entrée-sortie.** C'est ce qui rend l'aperçu exact sans
rien modifier, et c'est un invariant du module. La traduction est un appel
réseau : elle n'a pas sa place dans `plan.py`, d'où cette étape séparée, appliquée
au plan une fois qu'il est bâti.

**L'aperçu doit montrer ce qui sera écrit.** Un texte anglais à l'écran suivi
d'un texte français dans Kavita, ce n'est pas un aperçu. Comme l'écriture
reconstruit le plan de son côté, le résultat est mémoïsé : le second passage
retrouve les mêmes phrases sans repayer un appel, et l'utilisateur écrit bien le
texte qu'il a validé.

Le titre n'est pas traduit, volontairement : c'est un nom d'œuvre. Le chemin
série ne le traduit pas non plus.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

from secure_logging import safe_exc_str, series_label
from services.volume_enrichment.plan import SKIP_FILLED

#: Résumés déjà traduits, partagés entre l'aperçu et l'écriture. La clé porte le
#: moteur et la langue : changer l'un ou l'autre dans les réglages doit changer
#: le texte, pas resservir l'ancien.
_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_CACHE_LOCK = threading.Lock()

#: De quoi tenir une passe de bibliothèque entière sans grossir sans fin. Un
#: résumé pèse quelques centaines d'octets ; mille entrées restent négligeables
#: devant le reste, et la passe de bibliothèque n'a de toute façon pas besoin de
#: se souvenir des séries déjà terminées.
_CACHE_MAX = 1000


def _cached(key: tuple) -> Optional[str]:
    with _CACHE_LOCK:
        value = _CACHE.get(key)
        if value is not None:
            _CACHE.move_to_end(key)
        return value


def _remember(key: tuple, value: str) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def reset_cache() -> None:
    """Vide la mémoïsation. Pour les tests, et pour un changement de réglages."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _engine(config: Optional[Dict[str, Any]]) -> tuple:
    from config_manager import load_config

    cfg = config if config is not None else load_config()
    return (
        str(cfg.get("TRANSLATION_PROVIDER", "GOOGLE") or "").upper(),
        str(cfg.get("TARGET_LANG", "FR") or "FR"),
    )


def translate_plan_summaries(
    plan: Any,
    config: Optional[Dict[str, Any]] = None,
) -> Any:
    """Traduit les résumés que le plan va écrire, et ceux-là seulement.

    Le plan est modifié sur place puis rendu : il vient d'être bâti par
    l'appelant, personne d'autre ne le tient.

    Ne lève jamais : un traducteur indisponible laisse le texte d'origine, ce qui
    reste préférable à une passe qui s'arrête. `translate_text` fait déjà le
    repli d'un moteur payant vers Google et rend le texte tel quel en dernier
    recours ; le filet ici couvre le cas où il échouerait plus brutalement.
    """
    if not isinstance(plan, dict):
        return plan
    entries = plan.get("units")
    if not isinstance(entries, list) or not entries:
        return plan

    provider, target = _engine(config)
    # Sortie immédiate quand la traduction est éteinte : `translate_text` le
    # gère aussi, mais il journalise une ligne par appel — soit une ligne par
    # album, pour un travail nul.
    if provider == "NONE":
        return plan

    # Tous les résumés à écrire d'un coup : les moteurs acceptent plusieurs
    # textes par requête, et une série entière tient ainsi en une ou deux
    # requêtes au lieu de quarante. C'est la mesure qui met la passe hors de
    # portée d'un blocage — voir l'en-tête de `translator.py`.
    pending = []
    for entry in entries:
        change = _writable_summary(entry)
        if change is None:
            continue
        source = change["proposed"]
        if _cached((provider, target, source)) is None:
            pending.append(source)

    label = series_label(plan.get("series_name"), plan.get("series_id"))
    if pending:
        logging.info(
            "[Tomes] %s : traduction de %s résumé(s) vers %s via %s…",
            label,
            len(dict.fromkeys(pending)),
            target,
            provider,
        )
        _translate_and_remember(pending, provider, target)

    translated_count = 0
    already_there = 0
    for entry in entries:
        change = _writable_summary(entry)
        if change is None:
            continue
        source = change["proposed"]
        change["proposed"] = _cached((provider, target, source)) or source
        translated_count += 1

        # Le texte traduit peut retomber exactement sur celui que Kavita détient
        # déjà : le cas se présente sur une passe forcée, où la comparaison du
        # plan portait sur le texte du fournisseur, pas sur sa traduction.
        # Annoncer une écriture pour réécrire la même phrase serait un aperçu
        # qui se trompe sur son propre compte.
        if change["proposed"] == (change.get("current") or ""):
            change["write"] = False
            change["reason"] = SKIP_FILLED
            already_there += 1

    if already_there:
        _recount(plan)
    if translated_count:
        logging.info(
            "[Tomes] %s : %s résumé(s) prêt(s) en %s, dont %s traduit(s) à l'instant%s.",
            label,
            translated_count,
            target,
            len(dict.fromkeys(pending)),
            f" — {already_there} déjà identique(s)" if already_there else "",
        )
    return plan


def _writable_summary(entry):
    """Le changement de résumé d'une entrée, s'il va être écrit.

    Un résumé que la politique n'écrit pas — verrouillé, déjà rempli — n'a aucune
    raison d'être traduit : c'est ce qui faisait payer une série entière à chaque
    passe alors qu'elle était déjà faite.
    """
    if not isinstance(entry, dict):
        return None
    change = (entry.get("changes") or {}).get("summary")
    if not isinstance(change, dict) or not change.get("write"):
        return None
    source = change.get("proposed")
    if not isinstance(source, str) or not source.strip():
        return None
    return change


def _translate_and_remember(pending, provider, target):
    """Traduit un lot et le mémoïse. Ne lève pas : la passe doit continuer."""
    from translator import translate_texts

    sources = list(dict.fromkeys(pending))
    try:
        # `quiet` : le traducteur journalise une ligne par requête ; le décompte
        # rendu ci-dessus dit la même chose une seule fois par série.
        results = translate_texts(sources, target_lang=target, quiet=True)
    except Exception as exc:
        logging.warning("[Tomes] résumés non traduits : %s", safe_exc_str(exc))
        return
    if not isinstance(results, list) or len(results) != len(sources):
        # Un décalage écrirait le résumé d'un album sur un autre, et l'écriture
        # verrouille : mieux vaut la langue d'origine.
        logging.warning(
            "[Tomes] traduction ignorée : %s réponse(s) pour %s texte(s)",
            len(results) if isinstance(results, list) else "?",
            len(sources),
        )
        return
    for source, translated in zip(sources, results):
        _remember((provider, target, source), translated or source)


def _recount(plan: Dict[str, Any]) -> None:
    """Remet les compteurs d'accord avec les champs après un abandon.

    Les compteurs sont ce que l'interface affiche et ce sur quoi elle décide
    d'annoncer « rien à écrire » : les laisser en arrière ferait promettre des
    écritures qui n'auront pas lieu.
    """
    entries = [e for e in plan.get("units") or [] if isinstance(e, dict)]
    for entry in entries:
        changes = entry.get("changes") or {}
        entry["write_count"] = sum(
            1 for c in changes.values() if isinstance(c, dict) and c.get("write")
        )
    counts = plan.get("counts")
    if isinstance(counts, dict):
        counts["writable"] = sum(1 for e in entries if e.get("write_count"))
        counts["fields"] = sum(int(e.get("write_count") or 0) for e in entries)
