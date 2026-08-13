"""
Politique de comblement, et aperçu qui n'écrit rien.

La règle est simple et volontairement timide : **on ne comble que les vides**.
Un champ déjà renseigné dans Kavita reste tel quel, un champ verrouillé aussi —
le verrou est la manière dont l'utilisateur, ou une écriture MetaKavita
précédente, a dit « ne touche plus à ça ». `VOLUME_FORCE_OVERWRITE` lève la
règle pour un run, sur le modèle de `COVER_FORCE_OVERWRITE`.

Rien ici n'appelle Kavita ni un fournisseur : ce module décide, il n'agit pas.
C'est ce qui permet à l'aperçu d'être exact sans rien modifier.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.kavita_chapter_payload import is_valid_isbn, normalize_release_date
from services.volume_enrichment.matching import (
    ISBN_KEY_PREFIX,
    match_units,
    unit_key,
    unit_number,
)

#: Champs proposés par l'aperçu, dans l'ordre d'affichage.
FIELDS = ("title", "summary", "release_date", "isbn", "cover_url")

#: Champ -> (clé de lecture dans le ChapterDto, verrou correspondant).
#: `cover_url` n'a **pas** de clé de lecture, et ce n'est pas un oubli : Kavita
#: pose toujours une `coverImage` sur un chapitre scanné, une vignette découpée
#: dans la première page. La lire reviendrait à classer toutes les couvertures
#: en « déjà rempli » et à n'en écrire aucune. Ici, seul le verrou compte — et
#: comme MetaKavita verrouille ce qu'il envoie, une couverture posée par la
#: passe précédente est épargnée par la suivante.
FIELD_SOURCES = {
    "title": ("titleName", "titleNameLocked"),
    "summary": ("summary", "summaryLocked"),
    "release_date": ("releaseDate", "releaseDateLocked"),
    "isbn": ("isbn", "isbnLocked"),
    "cover_url": (None, "coverImageLocked"),
}

# Motifs de non-écriture, rendus tels quels à l'interface qui les traduit.
SKIP_LOCKED = "locked"
SKIP_FILLED = "filled"
SKIP_INVALID = "invalid"


def unit_label(entry: Dict[str, Any]) -> str:
    """Comment un tome se nomme dans le journal : « tome 3 », « chapitre 12 ».

    Un identifiant de chapitre Kavita ne dit rien à personne : c'est le numéro de
    tome que l'utilisateur voit sur sa tranche, et celui que l'aperçu affiche.
    """
    for key, mot in (("matched_on", "tome"), ("volume_number", "tome"),
                     ("chapter_number", "chapitre")):
        value = entry.get(key)
        if value not in (None, "", 0):
            return f"{mot} {value}"
    chapter_id = entry.get("chapter_id")
    return f"chapitre {chapter_id}" if chapter_id else "tome inconnu"


def _current_value(chapter: Dict[str, Any], field: str) -> str:
    key, _lock = FIELD_SOURCES[field]
    if key is None:
        return ""
    raw = chapter.get(key)
    if field == "release_date":
        return normalize_release_date(raw) or ""
    return str(raw or "").strip()


def _is_locked(chapter: Dict[str, Any], field: str) -> bool:
    _key, lock = FIELD_SOURCES[field]
    return bool(chapter.get(lock, False))


def plan_unit(
    unit: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    force: bool = False,
    chapter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ce qui serait écrit sur une unité, et pourquoi le reste ne le serait pas."""
    current_state = chapter if chapter is not None else (unit.get("chapter") or {})
    changes: Dict[str, Dict[str, Any]] = {}

    for field in FIELDS:
        proposed = payload.get(field)
        if isinstance(proposed, str):
            proposed = proposed.strip()
        if not proposed:
            continue

        if field == "isbn" and not is_valid_isbn(proposed):
            # Kavita refuse silencieusement un ISBN à clé fausse : le proposer
            # afficherait une écriture qui n'aurait pas lieu.
            changes[field] = {
                "proposed": proposed,
                "current": _current_value(current_state, field),
                "write": False,
                "reason": SKIP_INVALID,
            }
            continue
        if field == "release_date":
            normalized = normalize_release_date(proposed)
            if not normalized:
                continue
            proposed = normalized

        current = _current_value(current_state, field)
        locked = _is_locked(current_state, field)

        if locked and not force:
            reason = SKIP_LOCKED
        elif current and not force:
            reason = SKIP_FILLED
        elif current == proposed:
            # Rien à faire : écrire la même valeur coûterait un appel pour rien.
            reason = SKIP_FILLED
        else:
            reason = ""

        changes[field] = {
            "proposed": proposed,
            "current": current,
            "write": not reason,
            "reason": reason,
        }

    return {
        "chapter_id": unit.get("chapter_id"),
        "volume_id": unit.get("volume_id"),
        "volume_number": unit.get("volume_number"),
        "chapter_number": unit.get("chapter_number"),
        # Le numéro sur lequel l'appariement s'est fait. Il n'est pas toujours
        # celui du tome : un tome à plusieurs chapitres s'apparie au chapitre.
        # L'aperçu doit montrer celui-là, sinon un run de comics rangé sous le
        # volume 1 afficherait cinquante lignes intitulées « 1 ».
        "matched_on": unit_number(unit),
        # La clé réelle de l'appariement, qui n'est pas toujours un numéro : un
        # one-shot s'apparie sur son ISBN. Elle sert au marquage des doublons, pas
        # à l'affichage — « isbn:9782800… » ne se lit pas dans une colonne « Tome ».
        "matched_key": unit_key(unit),
        "name": unit.get("name") or "",
        "provider_ref": payload.get("provider_ref") or "",
        "changes": changes,
        "write_count": sum(1 for c in changes.values() if c["write"]),
    }


def _mark_duplicates(entries: List[Dict[str, Any]]) -> int:
    """Signale les unités qui se partagent un même album. Rend leur nombre.

    Le cas se rencontre pour de vrai : une bibliothèque peut détenir deux
    fichiers du même album, l'un rattaché à son tome, l'autre resté « hors tome »
    faute d'avoir été reconnu par le scanner. Les deux s'apparient alors au même
    album — le premier par son numéro de tome, le second par son numéro de
    chapitre — et l'écriture part deux fois, couverture téléchargée et téléversée
    deux fois.

    Ce n'est pas une erreur d'appariement : les deux fichiers *sont* cet album, et
    les priver de métadonnées serait pire. Mais l'utilisateur est le seul à savoir
    si son doublon est voulu, d'où ce marquage : les lignes restent cochées, et il
    décoche ce qu'il veut. Sans lui, la duplication ne se voyait qu'en comparant
    deux numéros identiques dans une longue liste.
    """
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for entry in entries:
        # La clé d'appariement, pas le numéro affiché : deux fichiers d'un même
        # one-shot n'ont pas de numéro et se partagent pourtant bien un album,
        # celui de leur ISBN commun.
        key = entry.get("matched_key")
        if key is None:
            key = entry.get("matched_on")
        if key is None:
            continue
        groups.setdefault(key, []).append(entry)

    duplicates = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        for rank, entry in enumerate(group, start=1):
            shown = entry.get("matched_on")
            if shown is None:
                key = str(entry.get("matched_key") or "")
                shown = key[len(ISBN_KEY_PREFIX):] if key.startswith(ISBN_KEY_PREFIX) else None
            entry["duplicate_of"] = shown
            entry["duplicate_count"] = len(group)
            # Le rang sert à l'interface : la première ligne d'un groupe est celle
            # qu'on garde par défaut à l'œil, les suivantes sont les redites.
            entry["duplicate_rank"] = rank
            duplicates += 1
    return duplicates


def build_plan(
    units: List[Dict[str, Any]],
    index: Any,
    *,
    force: bool = False,
    provider: str = "",
) -> Dict[str, Any]:
    """Plan complet d'une série : une entrée par unité appariée.

    Les unités sans correspondance sont rendues à part — c'est ce qui permet à
    l'interface de dire « le fournisseur ne connaît pas ce tome » plutôt que de
    les faire disparaître sans explication.
    """
    matched, unmatched = match_units(units, index)
    entries = [plan_unit(unit, payload, force=force) for unit, payload in matched]
    duplicates = _mark_duplicates(entries)
    writable = [e for e in entries if e["write_count"]]

    return {
        "provider": provider,
        "force": bool(force),
        "units": entries,
        "unmatched": [
            {
                "chapter_id": u.get("chapter_id"),
                "volume_number": u.get("volume_number"),
                "chapter_number": u.get("chapter_number"),
                "name": u.get("name") or "",
            }
            for u in unmatched
        ],
        "counts": {
            "matched": len(entries),
            "unmatched": len(unmatched),
            "writable": len(writable),
            "fields": sum(e["write_count"] for e in entries),
            # Unités qui partagent leur album avec au moins une autre. Compte les
            # deux membres d'une paire, pas les paires : c'est le nombre de lignes
            # que l'interface marque.
            "duplicates": duplicates,
        },
    }


def changes_to_write(entry: Dict[str, Any], fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """Réduit une entrée de plan aux seuls champs à écrire.

    `fields` restreint aux champs cochés dans l'aperçu ; sans lui, tout ce que
    la politique a autorisé part.
    """
    allowed = set(fields) if fields is not None else None
    out: Dict[str, Any] = {}
    for field, change in (entry.get("changes") or {}).items():
        if not change.get("write"):
            continue
        if allowed is not None and field not in allowed:
            continue
        out[field] = change["proposed"]
    return out
