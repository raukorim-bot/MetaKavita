"""
Construction du payload d'écriture d'un chapitre Kavita (`POST /api/Chapter/update`).

⚠️ `UpdateChapterDto` est un DTO de **remplacement total**. Le contrôleur Kavita
assigne chaque champ sans condition, et tout champ absent du corps JSON arrive
côté C# avec sa valeur par défaut :

* `summary`, `titleName`, `language`, `webLinks` absents → chaînes vides,
* les treize collections de personnes absentes → **tous les crédits effacés**,
* `genres` / `tags` absents → effacés,
* `ageRating` absent → `Unknown`,
* `releaseDate` absent → 1er janvier de l'an 1,
* les vingt verrous absents → **déverrouillés**, ce qui rouvre la porte au scan,
* `sortOrder` absent → **0**, et l'ordre de lecture de toute la série s'effondre,
* les sept identifiants de correspondance externe absents → **remis à zéro**,
  donc la correspondance Kavita+ du chapitre (notes, avis, métadonnées) perdue.

C'est la famille de bugs BF106 / BF122 (verrou de couverture omis → couverture
détruite par Kavita), en plus destructeur. D'où la règle unique de ce module :
on part de l'état lu par `GET /api/Chapter`, on recopie **tout**, et on applique
les changements par-dessus. Aucun appel réseau ici : la fonction est pure pour
qu'un test puisse vérifier champ par champ qu'elle n'efface rien.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

# Collections de personnes portées par un chapitre. La clé est identique dans
# `ChapterDto` (lecture) et `UpdateChapterDto` (écriture).
PEOPLE_KEYS = (
    "writers",
    "coverArtists",
    "publishers",
    "characters",
    "pencillers",
    "inkers",
    "imprints",
    "colorists",
    "letterers",
    "editors",
    "translators",
    "teams",
    "locations",
)

# Verrous acceptés par `UpdateChapterDto`. `teamLocked` et `locationLocked` en
# font partie bien que le contrôleur ne les réapplique pas encore côté Kavita :
# on les renvoie quand même, pour que le jour où il le fera, l'état soit juste.
LOCK_KEYS = (
    "ageRatingLocked",
    "titleNameLocked",
    "genresLocked",
    "tagsLocked",
    "writerLocked",
    "characterLocked",
    "coloristLocked",
    "editorLocked",
    "inkerLocked",
    "imprintLocked",
    "lettererLocked",
    "pencillerLocked",
    "publisherLocked",
    "translatorLocked",
    "teamLocked",
    "locationLocked",
    "coverArtistLocked",
    "languageLocked",
    "summaryLocked",
    "isbnLocked",
    "releaseDateLocked",
    "sortOrderLocked",
)

# `coverImageLocked` n'appartient pas à cette liste : contrairement au chemin
# série (BF106 / BF122, où l'omettre fait effacer la couverture), `UpdateChapterDto`
# ne porte pas ce booléen et `ChapterController` ne touche jamais au verrou de
# couverture d'un chapitre. Il n'y a donc rien à préserver — l'envoyer ne
# protégerait de rien, System.Text.Json l'ignorerait. En lecture, en revanche,
# `ChapterDto.CoverImageLocked` existe bien : l'aperçu a raison de s'y fier pour
# ne pas proposer d'écraser une couverture choisie à la main.

# Identifiants de correspondance externe. La clé est identique dans `ChapterDto`
# (lecture) et `UpdateChapterDto` (écriture) : les deux implémentent la même
# famille d'interfaces côté Kavita.
#
# Le contrôleur appelle `ExternalMetadataIdHelper.SetExternalMetadataIds(chapter,
# dto)` SANS CONDITION, et le helper écrit `entity.X = dto.X ?? 0`. Une clé
# absente du corps JSON arrive donc en `null` côté .NET et remet l'identifiant à
# zéro : Kavita répond 200, et la correspondance externe du chapitre est détruite.
# MetaKavita n'écrit jamais ces identifiants, mais il doit les recopier, sans quoi
# la moindre écriture de résumé ou de titre de tome les efface.
EXTERNAL_ID_KEYS = (
    "aniListId",
    "malId",
    "hardcoverId",
    "metronId",
    "comicVineId",
    "mangaBakaId",
    "cbrId",
)

# Champ écrit -> verrou à poser. Un champ écrit sans son verrou serait repris
# par le prochain scan de fichiers de Kavita.
FIELD_LOCKS = {
    "title": "titleNameLocked",
    "summary": "summaryLocked",
    "release_date": "releaseDateLocked",
    "isbn": "isbnLocked",
}

# Collection de personnes -> son verrou. Le nom du verrou est au singulier là
# où la collection est au pluriel, et `coverArtists` ne suit pas la règle : la
# table évite d'avoir à le deviner.
PEOPLE_LOCKS = {
    "writers": "writerLocked",
    "coverArtists": "coverArtistLocked",
    "publishers": "publisherLocked",
    "characters": "characterLocked",
    "pencillers": "pencillerLocked",
    "inkers": "inkerLocked",
    "imprints": "imprintLocked",
    "colorists": "coloristLocked",
    "letterers": "lettererLocked",
    "editors": "editorLocked",
    "translators": "translatorLocked",
    "teams": "teamLocked",
    "locations": "locationLocked",
}

# Date par défaut de .NET : Kavita l'utilise pour « pas de date ».
EMPTY_DATE = "0001-01-01T00:00:00"


def _people(raw: Any) -> List[Dict[str, str]]:
    """Réduit une collection de personnes à ce que le contrôleur en lit (`Name`)."""
    out: List[Dict[str, str]] = []
    for person in raw or []:
        if isinstance(person, dict):
            name = person.get("name") or person.get("Name")
        else:
            name = person
        name = str(name or "").strip()
        if name:
            out.append({"name": name})
    return out


def _titled(raw: Any) -> List[Dict[str, str]]:
    """Idem pour genres et tags, dont le contrôleur ne lit que `Title`."""
    out: List[Dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, dict):
            title = item.get("title") or item.get("Title")
        else:
            title = item
        title = str(title or "").strip()
        if title:
            out.append({"title": title})
    return out


def credits_to_write(
    current: Dict[str, Any],
    people: Any,
    *,
    force: bool = False,
) -> Dict[str, List[str]]:
    """Filtre des crédits proposés par la politique « on ne comble que les vides ».

    Sur le chemin série, un verrou fermé fait ignorer le champ par Kavita
    lui-même : le pire qui puisse arriver à un payload trop bavard est qu'il soit
    refusé. `ChapterController` ne consulte **aucun** verrou : il assigne les
    treize collections telles qu'elles arrivent. La liste de scénaristes qu'un
    utilisateur a corrigée à la main puis verrouillée est donc remplacée sans
    résistance, et Kavita répond 200. C'est ici, et nulle part ailleurs, que la
    règle affichée par l'aperçu doit être appliquée.

    Une collection est donc écartée si son verrou est fermé, ou si Kavita en a
    déjà une non vide. `force` (`VOLUME_FORCE_OVERWRITE`) lève les deux, comme
    pour les autres champs.
    """
    if not isinstance(people, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for key, names in people.items():
        lock = PEOPLE_LOCKS.get(key)
        if not lock:
            continue
        if not _people(names):
            continue
        if not force:
            if bool(current.get(lock, False)):
                continue
            if _people(current.get(key)):
                continue
        out[key] = names
    return out


def normalize_release_date(value: Any) -> Optional[str]:
    """Ramène une date de parution au format attendu par Kavita, ou None.

    Les fournisseurs renvoient aussi bien « 2019-05-07 » (ComicVine) qu'une
    année seule (Planète BD, Google Books quand l'édition est imprécise).

    La date part dans un `DateTime` non nullable : ce que Kavita ne sait pas
    désérialiser lui fait rendre 400 sur la requête entière, donc le titre et le
    résumé du même DTO sont perdus avec elle. D'où la validation par le
    calendrier réel plutôt que par bornes arithmétiques — « 2019-02-30 » passe
    `1 <= jour <= 31` mais n'existe pas.
    """
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("0001-01-01"):
        return None
    if "T" in text:
        # Horodatage déjà formé (Kavita lui-même, ComicVine) : validé en entier,
        # un « T » dans la chaîne ne prouvant rien.
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if not 1000 <= parsed.year <= 2999:
            return None
        return text
    parts = text.split("-")
    if len(parts) == 3:
        candidate = text
    elif len(parts) == 2:
        candidate = f"{text}-01"
    elif len(parts) == 1 and len(text) == 4:
        candidate = f"{text}-01-01"
    else:
        return None
    try:
        parsed = datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    if not 1000 <= parsed.year <= 2999:
        return None
    return f"{parsed.year:04d}-{parsed.month:02d}-{parsed.day:02d}T00:00:00"


def is_valid_isbn(value: Any) -> bool:
    """ISBN-10 / ISBN-13 avec clé de contrôle valide.

    Kavita refuse silencieusement un ISBN invalide (`ArticleNumberHelper`) : le
    vérifier ici évite d'annoncer une écriture qui n'a pas eu lieu.
    """
    raw = str(value or "").replace("-", "").replace(" ", "").strip().upper()
    if len(raw) == 10:
        total = 0
        for i, char in enumerate(raw):
            if char == "X" and i == 9:
                digit = 10
            elif char.isdigit():
                digit = int(char)
            else:
                return False
            total += digit * (10 - i)
        return total % 11 == 0
    if len(raw) == 13:
        if not raw.isdigit():
            return False
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(raw[:12]))
        return (10 - total % 10) % 10 == int(raw[12])
    return False


def build_update_chapter_dto(current: Dict[str, Any], changes: Dict[str, Any]) -> Dict[str, Any]:
    """Payload complet pour `POST /api/Chapter/update`.

    `current` est le `ChapterDto` rendu par `GET /api/Chapter?chapterId=`.
    `changes` accepte `title`, `summary`, `release_date` et `isbn` ; chaque
    valeur fournie pose aussi son verrou. Tout le reste est recopié tel quel.
    """
    if not isinstance(current, dict) or not current.get("id"):
        raise ValueError("build_update_chapter_dto : ChapterDto sans id")

    # SortOrder hérite de MinNumber côté Kavita : ce repli évite d'envoyer 0 —
    # donc de renvoyer le chapitre en tête de série — si un Kavita plus ancien
    # ne remonte pas le champ.
    sort_order = current.get("sortOrder")
    if sort_order is None:
        sort_order = current.get("minNumber") or 0

    dto: Dict[str, Any] = {
        "id": int(current["id"]),
        "summary": current.get("summary") or "",
        "titleName": current.get("titleName") or "",
        "language": current.get("language") or "",
        "webLinks": current.get("webLinks") or "",
        "isbn": current.get("isbn") or "",
        "releaseDate": current.get("releaseDate") or EMPTY_DATE,
        "ageRating": current.get("ageRating") or 0,
        "sortOrder": sort_order,
        "genres": _titled(current.get("genres")),
        "tags": _titled(current.get("tags")),
    }
    for key in PEOPLE_KEYS:
        dto[key] = _people(current.get(key))
    for key in LOCK_KEYS:
        dto[key] = bool(current.get(key, False))
    # Kavita rend `0` pour « pas d'identifiant », et `0 ?? 0` vaut `0` : la valeur
    # lue se renvoie telle quelle, sans conversion ni repli.
    for key in EXTERNAL_ID_KEYS:
        dto[key] = current.get(key)

    written: List[str] = []

    title = changes.get("title")
    if title:
        dto["titleName"] = str(title).strip()
        written.append("title")

    summary = changes.get("summary")
    if summary:
        dto["summary"] = str(summary).strip()
        written.append("summary")

    release_date = normalize_release_date(changes.get("release_date"))
    if release_date:
        dto["releaseDate"] = release_date
        written.append("release_date")

    isbn = changes.get("isbn")
    if isbn:
        clean = str(isbn).replace("-", "").replace(" ", "").strip()
        if is_valid_isbn(clean):
            dto["isbn"] = clean
            written.append("isbn")
        else:
            # Kavita l'ignorerait sans le dire ; on préfère le tracer.
            logging.info("[Tomes] ISBN ignoré (clé de contrôle invalide) : %s", isbn)

    # Crédits : réservés à l'option `VOLUME_ENRICH_CREDITS`, parce qu'ils
    # coûtent un appel réseau par album là où tout le reste tient en un appel
    # par série. Une collection fournie remplace la sienne ; les douze autres
    # ne bougent pas.
    people = changes.get("people")
    if isinstance(people, dict):
        for key, names in people.items():
            if key not in PEOPLE_LOCKS:
                continue
            merged = _people(names)
            if not merged:
                continue
            dto[key] = merged
            dto[PEOPLE_LOCKS[key]] = True
            written.append(key)

    for field in written:
        lock = FIELD_LOCKS.get(field)
        if lock:
            dto[lock] = True

    dto["_written_fields"] = written
    return dto


def split_written_fields(dto: Dict[str, Any]) -> List[str]:
    """Retire le marqueur interne avant l'envoi réseau et le rend à l'appelant."""
    return list(dto.pop("_written_fields", []))
