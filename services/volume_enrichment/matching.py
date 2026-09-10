"""
Appariement entre les unités Kavita et l'index d'un fournisseur.

Le piège est dans les sentinelles. Kavita 0.8 range les chapitres sans tome
dans un volume numéroté **-100000** (`Parser.LooseLeafVolumeNumber`) et les
hors-série dans le volume **100000** (`Parser.SpecialVolumeNumber`). Les prendre
pour des numéros de tome donnerait « album 100000 » à un fournisseur, et pire :
un hors-série recevrait les métadonnées du tome 1.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# Mêmes valeurs que services/library_audit/volume_report.py, redéclarées ici
# pour que ce module reste utilisable sans dépendre de l'Inventaire.
SPECIAL_VOL = 100_000
LOOSE_VOL = -100_000

#: Préfixe des clés d'appariement par ISBN. Un one-shot n'a pas de numéro de tome
#: — Kavita le range en feuille volante ou en hors-série — mais il porte souvent
#: son ISBN, qui désigne l'album avec certitude là où un numéro ne fait que le
#: situer. Le préfixe n'est pas un nombre : une clé ISBN et une clé de tome ne
#: peuvent donc pas se confondre dans le même index.
ISBN_KEY_PREFIX = "isbn:"
#: Clé d'un override d'atelier (Champ Magique) quand le tome n'a ni numéro ni ISBN.
CHAPTER_KEY_PREFIX = "ch:"

# Champs qu'un fournisseur peut proposer pour une unité.
INDEX_FIELDS = ("title", "summary", "release_date", "isbn", "cover_url")

# `provider_ref` n'est pas une métadonnée : c'est l'adresse de l'album chez le
# fournisseur, dont la passe crédits a besoin pour le réinterroger. Le nettoyage
# de l'index doit donc le laisser passer, sans le compter comme un champ écrit.
INDEX_KEYS = INDEX_FIELDS + ("provider_ref",)


def is_sentinel(number: Any) -> bool:
    """Vrai pour les numéros que Kavita utilise comme marqueurs, pas comme tomes."""
    value = as_number(number)
    if value is None:
        return False
    return abs(value - SPECIAL_VOL) < 0.01 or abs(value - LOOSE_VOL) < 0.01


def is_special_number(number: Any) -> bool:
    """Vrai pour la sentinelle des hors-série, et pour elle seule.

    Côté Kavita, `Parser.SpecialVolumeNumber` **est** la définition du hors-série :
    le scanner y range tout fichier reconnu comme spécial, et le drapeau
    `isSpecial` du DTO n'en est qu'un reflet — que la réponse peut omettre selon
    la version et le chemin d'appel. La sentinelle suffit donc à conclure, faute
    de quoi l'unité retomberait sur son numéro de chapitre, un simple compteur,
    et le hors-série recevrait le titre, le résumé et la couverture d'un vrai
    tome, verrous compris. C'est la règle qu'applique déjà `_is_special_vol` de
    l'Inventaire ; le côté qui écrit ne peut pas être le plus permissif des deux.

    La sentinelle des feuilles volantes (-100000) n'entre pas dans le lot : elle
    marque des chapitres sans tome, qui portent de vrais numéros de chapitre et
    s'apparient normalement.
    """
    value = as_number(number)
    if value is None:
        return False
    return abs(value - SPECIAL_VOL) < 0.01


def as_number(raw: Any) -> Optional[float]:
    """« 03 », « 3.0 », 3 → 3.0 ; le reste → None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip().replace(",", ".")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    if value != value:  # NaN
        return None
    return value


def number_key(raw: Any) -> Optional[str]:
    """Clé stable pour comparer des numéros venus de deux mondes.

    Kavita rend `3.0`, ComicVine rend `"3"`, Bédéthèque rend `"03"` : sans
    normalisation, aucun des trois ne s'apparie aux autres.
    """
    value = as_number(raw)
    if value is None or is_sentinel(value):
        return None
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:g}"


def index_key(raw: Any) -> Optional[str]:
    """Clé d'une entrée d'index : un numéro d'album, ou un ISBN.

    Les index par série sont numérotés ; la cascade ISBN, elle, indexe par ISBN
    les unités qui n'ont pas de numéro. Les deux cohabitent dans le même
    dictionnaire sans risque de collision — un ISBN préfixé n'est pas un nombre —
    et un index de fournisseur ne peut apparier une unité par ISBN qu'en rendant
    exactement l'ISBN que Kavita détient, ce qui est une preuve, pas une
    coïncidence.
    """
    if isinstance(raw, str) and raw.startswith(ISBN_KEY_PREFIX):
        text = raw[len(ISBN_KEY_PREFIX):].strip()
        return f"{ISBN_KEY_PREFIX}{text}" if text else None
    if isinstance(raw, str) and raw.startswith(CHAPTER_KEY_PREFIX):
        text = raw[len(CHAPTER_KEY_PREFIX):].strip()
        return f"{CHAPTER_KEY_PREFIX}{text}" if text else None
    return number_key(raw)


def normalize_index(index: Any, keys: Optional[Set[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Index fournisseur → `{clé numérique: payload nettoyé}`.

    Les entrées sans numéro exploitable sont écartées : mieux vaut ne rien
    écrire que d'écrire sur le mauvais tome.

    `keys` restreint le résultat aux numéros que la série possède réellement. Un
    scraper tiers n'a pas la limite des fournisseurs livrés et peut annoncer des
    dizaines de milliers d'albums : sans ce filtre, une série de trois tomes fait
    recopier tout le catalogue.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(index, dict):
        return out
    for raw_number, payload in index.items():
        key = index_key(raw_number)
        if key is None or not isinstance(payload, dict):
            continue
        if keys is not None and key not in keys:
            continue
        clean = {}
        for field in INDEX_KEYS:
            value = payload.get(field)
            if value in (None, ""):
                continue
            clean[field] = value.strip() if isinstance(value, str) else value
        # Une entrée qui ne porte qu'un `provider_ref` ne propose aucune
        # métadonnée : la garder afficherait un tome « à écrire » sans rien à y
        # mettre.
        if any(field in clean for field in INDEX_FIELDS):
            # Deux entrées sur le même numéro : la plus fournie l'emporte.
            if key not in out or len(clean) > len(out[key]):
                out[key] = clean
    return out


def unit_number(unit: Dict[str, Any]) -> Optional[str]:
    """Numéro d'une unité Kavita, celui sur lequel l'apparier.

    Le nombre de chapitres du tome tranche, et c'est ce qui évite d'écrire cinq
    fois le même album. Un tome d'un seul fichier **est** le tome : on l'apparie
    sur son numéro de tome. Un tome qui contient plusieurs chapitres est un
    conteneur — le cas courant en comics, où Kavita range tout un run sous le
    volume 1 et fait de chaque numéro un chapitre : c'est alors le numéro de
    chapitre qui désigne l'album, et l'apparier sur le tome donnerait le même
    numéro #1 à cinquante issues.
    """
    if int(unit.get("sibling_count") or 1) <= 1:
        key = number_key(unit.get("volume_number"))
        if key is not None:
            return key
    return number_key(unit.get("chapter_number"))


def unit_isbn(unit: Dict[str, Any]) -> str:
    """L'ISBN que Kavita porte pour cette unité, ou `""`.

    Le chapitre d'abord : `VolumeDto` n'a pas de propriété `isbn`, c'est le
    chapitre qui la porte (BF160). Le repli sur l'unité ne sert que les
    dictionnaires assemblés autrement — un appelant de test, un tome sans
    chapitre.
    """
    raw = (unit.get("chapter") or {}).get("isbn") or unit.get("isbn") or ""
    return str(raw).strip()


def unit_key(unit: Dict[str, Any]) -> Optional[str]:
    """La clé d'appariement d'une unité : son numéro, sinon son ISBN.

    Le numéro passe d'abord parce qu'il est la clé des index par série, les moins
    chers. L'ISBN est le seul recours d'une unité sans numéro — un one-shot — et
    c'est un recours plus sûr que le numéro, pas moins : il désigne une édition
    précise, quand un numéro suppose qu'on parle bien de la même série.
    """
    key = unit_number(unit)
    if key is not None:
        return key
    isbn = unit_isbn(unit)
    return f"{ISBN_KEY_PREFIX}{isbn}" if isbn else None


def units_from_volumes(volumes: Iterable[Any]) -> List[Dict[str, Any]]:
    """Aplatit la réponse `GET /api/Series/volumes` en unités écrivables.

    Le rapport d'inventaire produit une liste voisine, mais il jette le
    `ChapterDto` brut — dont l'écriture a besoin pour savoir ce qui est déjà
    rempli et ce qui est verrouillé. On repart donc de la réponse Kavita.
    """
    out: List[Dict[str, Any]] = []
    for volume in volumes or []:
        if not isinstance(volume, dict):
            continue
        vol_id = volume.get("id") or volume.get("Id")
        vol_number = volume.get("minNumber")
        if vol_number is None:
            vol_number = volume.get("number") or volume.get("Number")
        # La sentinelle est le seul signal que Kavita fournit vraiment ici :
        # `VolumeDto` ne porte pas de propriété `IsSpecial` — le drapeau appartient
        # à `ChapterDto`, lu plus bas, chapitre par chapitre. La lecture au niveau
        # du tome ne coûte rien et reste une tolérance : elle sert aux réponses
        # assemblées autrement, et au jour où Kavita exposerait le drapeau.
        vol_special = is_special_number(vol_number) or bool(
            volume.get("isSpecial") or volume.get("IsSpecial")
        )
        chapters = volume.get("chapters") or volume.get("Chapters") or []
        if not isinstance(chapters, list):
            continue
        writable = [c for c in chapters if isinstance(c, dict) and (c.get("id") or c.get("Id"))]
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            chapter_id = chapter.get("id") or chapter.get("Id")
            if not chapter_id:
                continue
            chapter_number = chapter.get("minNumber")
            if chapter_number is None:
                chapter_number = chapter.get("number") or chapter.get("Number")
            out.append(
                {
                    "volume_id": vol_id,
                    "chapter_id": chapter_id,
                    "volume_number": None if is_sentinel(vol_number) else vol_number,
                    "chapter_number": None if is_sentinel(chapter_number) else chapter_number,
                    "name": chapter.get("titleName")
                    or chapter.get("title")
                    or chapter.get("range")
                    or "",
                    "is_special": vol_special
                    or bool(chapter.get("isSpecial") or chapter.get("IsSpecial")),
                    "sibling_count": len(writable),
                    "chapter": chapter,
                }
            )
    return out


def _matchable(units: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Les unités qu'un index peut apparier : tout sauf les hors-série.

    Un hors-série ne s'apparie jamais — son numéro ne veut rien dire chez un
    fournisseur — et c'est le seul retrait à faire ici. L'absence de `chapter_id`
    est une autre question, celle de savoir où écrire : elle appartient à
    `match_units` et à `unmatchable_reason`, pas au décompte des clés.
    """
    return [u for u in (units or []) if isinstance(u, dict) and not u.get("is_special")]


def matchable_numbers(units: Iterable[Dict[str, Any]]) -> Set[str]:
    """Les numéros de tome appariables, et eux seuls — sans les ISBN.

    C'est ce qui décide si un index par série valait son appel : un index est
    numéroté, il n'a rien à quoi s'apparier dans une série qui n'a pas de numéro.
    """
    return {key for key in (unit_number(u) for u in _matchable(units)) if key is not None}


def matchable_keys(units: Iterable[Dict[str, Any]]) -> Set[str]:
    """Toutes les clés appariables : les numéros de tome et les ISBN."""
    return {key for key in (unit_key(u) for u in _matchable(units)) if key is not None}


def unmatchable_reason(units: Iterable[Dict[str, Any]], series_name: str = "") -> str:
    """Pourquoi cette série n'a rien à apparier — ou `""` si elle a de quoi.

    Rien de ce que la cascade peut rendre ne s'écrit sans clé : l'index par série,
    la cascade ISBN et la recherche titre + numéro indexent tous leurs résultats,
    et sautent l'unité qui n'a pas de clé. Une série dont aucune unité n'en porte
    payait donc une recherche complète — jusqu'à deux minutes chez un fournisseur
    HTML, et un tour de cadence pour les suivants — pour un aperçu vide garanti
    d'avance.

    Deux motifs, parce que le message n'est pas le même à l'écran :

    * `oneshot` — une seule unité, ni numéro ni ISBN ;
    * `specials` — plusieurs unités, aucune avec de clé.

    La décision est structurelle, jamais un pari sur un titre : c'est l'absence de
    **toute** clé qui écarte une série, jamais le nombre de tomes détenus. Une
    série dont on ne possède que le tome 1 porte la clé « 1 » et reste cherchée —
    c'est précisément le cas où l'écriture par tome a du travail. Un one-shot qui
    porte son ISBN en a une, lui aussi : il part par la cascade ISBN.

    `series_name` n'entre pas dans la décision. Il est gardé dans la signature
    parce que les deux appelants l'ont sous la main et qu'un motif futur pourrait
    en avoir besoin ; un titre n'est pas un identifiant, et un recueil nommé
    « one shots » dont les tomes sont numérotés doit rester servi.
    """
    # Le `chapter_id` compte ici, et pas dans le décompte des clés : une série de
    # tomes vides n'a nulle part où écrire, mais c'est un autre message, déjà
    # rendu par l'appelant. Les hors-série comptent pour le message et pas pour la
    # décision : une série qui n'en contient que trois n'est pas un one-shot.
    present = [u for u in (units or []) if isinstance(u, dict) and u.get("chapter_id")]
    if not present:
        return ""
    if matchable_keys(present):
        return ""
    return "oneshot" if len(present) == 1 else "specials"


def match_units(
    units: Iterable[Dict[str, Any]],
    index: Any,
) -> Tuple[List[Tuple[Dict[str, Any], Dict[str, Any]]], List[Dict[str, Any]]]:
    """Apparie les unités à l'index. Rend (appariées, non appariées).

    Sont écartées d'office : les unités sans `chapter_id` — les métadonnées
    vivent sur le chapitre, un tome vide n'a rien où écrire — et les
    hors-série, dont le numéro ne veut rien dire chez le fournisseur.
    """
    candidates = [u for u in (units or []) if isinstance(u, dict)]
    wanted = matchable_keys(candidates)
    for unit in candidates:
        cid = unit.get("chapter_id")
        if cid:
            wanted = set(wanted)
            wanted.add(f"{CHAPTER_KEY_PREFIX}{int(cid)}")
    normalized = normalize_index(index, keys=wanted)
    matched: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    unmatched: List[Dict[str, Any]] = []
    seen_chapters = set()

    for unit in candidates:
        chapter_id = unit.get("chapter_id")
        if not chapter_id or chapter_id in seen_chapters:
            continue
        seen_chapters.add(chapter_id)
        if unit.get("is_special"):
            continue
        key = unit_key(unit)
        payload = normalized.get(key) if key is not None else None
        if not payload:
            payload = normalized.get(f"{CHAPTER_KEY_PREFIX}{int(chapter_id)}")
        if payload:
            matched.append((unit, payload))
        else:
            unmatched.append(unit)
    return matched, unmatched
