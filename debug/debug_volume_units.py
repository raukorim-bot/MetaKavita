"""Ce que Kavita rend vraiment pour une série, et ce que l'appariement en fait.

Écrit pour une question précise : dans le rapport de tomes de Blacksad, deux
lignes portent le même numéro d'album — le même album ComicVine part donc sur
deux chapitres Kavita, couverture téléchargée et téléversée deux fois. Le code
d'appariement ne déduplique que par `chapter_id`, jamais par numéro apparié, et
`unit_number()` a deux façons de choisir un numéro selon le nombre de chapitres
du tome. Reste à savoir laquelle des deux produit la collision, et pourquoi.

Ce script **n'écrit rien**. Il ne fait que des `GET` vers Kavita, qui est local.
L'index du fournisseur, lui, sort sur Internet : il est derrière `--index` et
derrière la porte de `_live_network_guard`.

Usage, depuis la racine du projet :

    python debug/debug_volume_units.py 42
    python debug/debug_volume_units.py "Blacksad"
    python debug/debug_volume_units.py 42 --index

À lancer là où MetaKavita tourne : le script lit `data/config.json` pour
l'adresse de Kavita et sa clé.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import json
from collections import defaultdict

from config_manager import load_config
from kavita_api import KavitaAPI
from services.volume_enrichment.matching import (
    LOOSE_VOL,
    SPECIAL_VOL,
    number_key,
    unit_number,
    units_from_volumes,
)

#: Champs de `ChapterDto` qui pèsent dans l'appariement ou dans la décision
#: d'écrire. Le DTO en porte une soixantaine : tout afficher noierait le signal.
CHAPTER_FIELDS = (
    "id", "minNumber", "maxNumber", "number", "range", "title", "titleName",
    "isSpecial", "pages", "summary", "releaseDate", "isbn", "coverImage",
    "coverImageLocked", "summaryLocked", "titleNameLocked", "releaseDateLocked",
)


def _sentinel_label(value) -> str:
    """Nomme les deux valeurs que Kavita utilise comme marqueurs."""
    key = number_key(value)
    if key is not None:
        return ""
    as_text = str(value)
    if str(SPECIAL_VOL) in as_text:
        return "  ← sentinelle HORS-SÉRIE (SpecialVolumeNumber)"
    if str(LOOSE_VOL) in as_text:
        return "  ← sentinelle FEUILLES VOLANTES (LooseLeafVolumeNumber)"
    return "  ← numéro inexploitable"


def _resolve_series(api, wanted: str):
    """Rend (series_id, nom) depuis un identifiant ou un nom approchant."""
    try:
        return int(wanted), ""
    except (TypeError, ValueError):
        pass

    needle = wanted.strip().lower()
    for series in api.get_all_series() or []:
        name = str(series.get("name") or "")
        if needle in name.lower():
            return int(series.get("id")), name
    return None, ""


def dump_raw_volumes(volumes) -> None:
    print("\n" + "=" * 78)
    print("  CE QUE KAVITA REND — GET /api/Series/volumes")
    print("=" * 78)
    for volume in volumes or []:
        if not isinstance(volume, dict):
            print(f"\n  (entrée non-dict : {type(volume).__name__})")
            continue
        vol_number = volume.get("minNumber", volume.get("number"))
        chapters = volume.get("chapters") or []
        print(
            f"\n  TOME id={volume.get('id')}  minNumber={vol_number!r}  "
            f"name={volume.get('name')!r}  chapitres={len(chapters)}"
            f"{_sentinel_label(vol_number)}"
        )
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            shown = {k: chapter.get(k) for k in CHAPTER_FIELDS if k in chapter}
            # Le résumé et la couverture comptent par leur présence, pas par leur
            # contenu : un résumé entier rendrait la sortie illisible.
            if shown.get("summary"):
                shown["summary"] = f"<{len(str(shown['summary']))} caractères>"
            if shown.get("coverImage"):
                shown["coverImage"] = f"<{shown['coverImage']}>"
            print(f"      CHAPITRE {json.dumps(shown, ensure_ascii=False)}")


def dump_units(units) -> dict:
    """Affiche chaque unité avec le numéro retenu, et rend les collisions."""
    print("\n" + "=" * 78)
    print("  CE QUE L'APPARIEMENT EN FAIT — units_from_volumes + unit_number")
    print("=" * 78)
    print(
        "\n  Rappel de la règle : un tome d'un seul chapitre est apparié sur son\n"
        "  numéro de TOME ; un tome de plusieurs chapitres est un conteneur, et\n"
        "  chaque chapitre est apparié sur son numéro de CHAPITRE.\n"
    )
    by_key = defaultdict(list)
    for unit in units:
        key = unit_number(unit)
        sibling = int(unit.get("sibling_count") or 1)
        source = "tome" if sibling <= 1 else "chapitre"
        print(
            f"  chapitre_id={unit.get('chapter_id'):>6}  "
            f"tome={unit.get('volume_number')!r:>8}  "
            f"chap={unit.get('chapter_number')!r:>8}  "
            f"fratrie={sibling}  "
            f"spécial={bool(unit.get('is_special'))}  "
            f"nom={str(unit.get('name'))[:28]!r:<30} "
            f"→ apparié sur {key!r} (via le numéro de {source})"
        )
        if key is not None and not unit.get("is_special"):
            by_key[key].append(unit)

    collisions = {k: v for k, v in by_key.items() if len(v) > 1}
    print("\n" + "-" * 78)
    if not collisions:
        print("  Aucune collision : chaque album ne visait qu'un seul chapitre.")
    else:
        print(f"  {len(collisions)} COLLISION(S) — un même album visait plusieurs chapitres :")
        for key, group in sorted(collisions.items()):
            print(f"\n    album n°{key} → {len(group)} chapitres :")
            for unit in group:
                sibling = int(unit.get("sibling_count") or 1)
                print(
                    f"       chapitre_id={unit.get('chapter_id')}  "
                    f"tome_id={unit.get('volume_id')}  "
                    f"tome={unit.get('volume_number')!r}  "
                    f"chap={unit.get('chapter_number')!r}  "
                    f"fratrie={sibling}  nom={str(unit.get('name'))[:40]!r}"
                )
        print(
            "\n  Lecture : si les chapitres d'une collision appartiennent à des tomes\n"
            "  DIFFÉRENTS, c'est que deux tomes Kavita portent le même numéro. S'ils\n"
            "  appartiennent au MÊME tome, c'est que leur numéro de chapitre est le\n"
            "  même — un scan qui a rangé deux fichiers sous le même numéro."
        )
    return collisions


def dump_index(series_name: str, units, library_type: str, config: dict) -> None:
    from _live_network_guard import confirm_live_network

    confirm_live_network(
        "debug_volume_units.py --index",
        "le fournisseur de tomes retenu par la cascade (ComicVine, Bédéthèque, "
        "Planète BD ou MangaDex selon le type de bibliothèque)",
        details="Une seule série, mais un fournisseur HTML peut demander un album par requête.",
    )

    from services.volume_enrichment.matching import match_units
    from services.volume_enrichment.providers import resolve_index

    provider, index = resolve_index(
        series_name,
        units,
        library_type=library_type,
        experimental=bool(config.get("VOLUME_ENRICH_EXPERIMENTAL", False)),
        config=config,
    )
    print("\n" + "=" * 78)
    print(f"  INDEX DU FOURNISSEUR — {provider or '(aucun)'}")
    print("=" * 78)
    for raw_number, payload in sorted((index or {}).items(), key=lambda kv: str(kv[0])):
        fields = sorted((payload or {}).keys()) if isinstance(payload, dict) else payload
        print(f"  album {raw_number!r} → champs {fields}")

    matched, unmatched = match_units(units, index)
    print(f"\n  {len(matched)} unité(s) appariée(s), {len(unmatched)} non appariée(s).")
    for unit in unmatched:
        print(
            f"    non appariée : chapitre_id={unit.get('chapter_id')} "
            f"tome={unit.get('volume_number')!r} chap={unit.get('chapter_number')!r} "
            f"nom={str(unit.get('name'))[:40]!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspecte la structure Kavita d'une série et son appariement par tome."
    )
    parser.add_argument("series", help="Identifiant Kavita, ou fragment du nom de la série.")
    parser.add_argument(
        "--index",
        action="store_true",
        help="Interroge aussi le fournisseur (sort sur Internet, demande confirmation).",
    )
    args = parser.parse_args()

    config = load_config()
    url, key = config.get("KAVITA_URL"), config.get("KAVITA_API_KEY")
    if not url or not key:
        print("❌ KAVITA_URL ou KAVITA_API_KEY absente de data/config.json.")
        return 1

    api = KavitaAPI(url, key)
    series_id, matched_name = _resolve_series(api, args.series)
    if not series_id:
        print(f"❌ Aucune série ne correspond à « {args.series} ».")
        return 1

    series = api.get_series(series_id) or {}
    name = series.get("name") or matched_name or str(series_id)
    library_type = (
        series.get("libraryType") or api.get_library_type_for_series(series_id) or "Manga"
    )
    print(f"\nSérie « {name} » (id={series_id}), bibliothèque de type {library_type}.")

    volumes = api.get_series_volumes(series_id)
    if not volumes:
        print("❌ Kavita n'a rendu aucun tome — série vide, ou lecture en échec.")
        return 1

    dump_raw_volumes(volumes)
    units = units_from_volumes(volumes)
    print(f"\n  → {len(units)} unité(s) écrivable(s) pour {len(volumes)} tome(s).")
    dump_units(units)

    if args.index:
        dump_index(name, units, library_type, config)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
