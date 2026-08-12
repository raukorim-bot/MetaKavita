"""
Scrapers : un champ présent mais nul ne doit pas écarter le fournisseur.

`data.get('coverImage', {}).get('extraLarge')` lève `AttributeError` dès que la
clé existe et vaut `null` — le défaut `{}` ne joue que pour une clé absente. Or
AniList déclare `coverImage`, `startDate`, `staff` et `characters` nullables, et
les renvoie effectivement à `null` sur des fiches pauvres : la série était
silencieusement écartée d'AniList, sans autre trace qu'un « Erreur Anilist ». Le
reste du fichier utilisait déjà `or {}`, ce qui dit l'intention.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.anilist`, qui renvoie la copie installée dans `data/scrapers/` —
même précaution que `test_bugfix_p0_163.py`.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_SCRAPERS_DIR = Path(__file__).resolve().parents[1] / "scrapers"

# `x.get("k", {}).get(...)` : le défaut ne protège pas d'un `null`. Les lignes qui
# valident le type avec `isinstance` sont déjà à l'abri.
_MOTIF_FAUTIF = re.compile(r"\.get\((?:[^()]*), \{\}\)\.get\(")


def _load(name: str):
    path = _SCRAPERS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scrapers.{name}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def anilist(monkeypatch):
    module = _load("anilist")
    monkeypatch.setattr(module, "get_max_genres", lambda *a, **k: 5)
    monkeypatch.setattr(module, "get_max_tags", lambda *a, **k: 15)
    return module.AnilistScraper()


def test_une_fiche_anilist_aux_champs_nuls_reste_exploitable(anilist):
    """Fiche minimale telle qu'AniList la renvoie : tout ce qui est optionnel est nul."""
    data = {
        "id": 30002,
        "idMal": None,
        "title": {"romaji": "Berserk", "english": None, "native": None},
        "description": None,
        "coverImage": None,
        "genres": None,
        "tags": None,
        "startDate": None,
        "status": "RELEASING",
        "staff": None,
        "characters": None,
        "isAdult": False,
        "countryOfOrigin": "JP",
        "externalLinks": None,
    }

    candidate = anilist._build_candidate(data)

    assert candidate["title"] == "Berserk"
    assert candidate["cover_url"] is None
    assert candidate["year"] is None
    assert candidate["staff"] == []
    assert candidate["characters"] == []
    assert candidate["anilist_id"] == 30002


def test_aucun_scraper_ne_chaine_sur_un_defaut_de_dictionnaire():
    """Le motif est équivalent partout : le corriger sur AniList seul le laisserait
    vivant chez Hardcover, Kitsu, MangaDex et Open Library."""
    coupables = []
    for path in sorted(_SCRAPERS_DIR.glob("*.py")):
        for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "isinstance" in line:
                continue
            if _MOTIF_FAUTIF.search(line):
                coupables.append(f"{path.name}:{num}")

    assert not coupables, (
        "chaînage sur un défaut `{}` : un champ nul lèvera AttributeError et "
        f"écartera le fournisseur — {', '.join(coupables)}"
    )
