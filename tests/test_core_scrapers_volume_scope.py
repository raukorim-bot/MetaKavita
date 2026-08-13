"""Le registre réellement chargé doit porter des fournisseurs de tomes (BF143).

Le registre ne charge QUE `data/scrapers/`, jamais le package `scrapers/` de
l'image : ce dossier est alimenté au boot par deux sources concurrentes (le
catalogue communautaire, puis l'image). Tant que la comparaison se faisait par
égalité de sha256, une copie posée par un catalogue en retard était déclarée
« à jour » pour toujours — les scrapers de l'image capables de lister les tomes
n'arrivaient jamais jusqu'au registre, et `get_by_scope("volume")` rendait une
liste vide. Toute la passe d'enrichissement par tome était donc inopérante,
quelle que soit la configuration, sans qu'aucun test ne s'en aperçoive : ceux
qui existaient chargeaient les scrapers depuis `scrapers/` par chemin, en
contournant le registre.

Ces tests interrogent le registre tel qu'il est chargé à l'exécution — même
objet que celui dont se sert `services/volume_enrichment/providers.py`.
"""
from __future__ import annotations

import ast
import os

from scrapers import ScraperRegistry
from scrapers.base import BaseScraper
from services.scraper_manager import is_core_filename, package_scrapers_dir


def _declares_volume_scope(path: str) -> bool:
    """True si une classe du fichier assigne un `scopes` contenant `volume` (AST)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            targets = []
            value = None
            if isinstance(item, ast.Assign):
                targets = [t.id for t in item.targets if isinstance(t, ast.Name)]
                value = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                targets = [item.target.id]
                value = item.value
            if "scopes" not in targets or value is None:
                continue
            try:
                literal = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                continue
            if isinstance(literal, (set, list, tuple)) and "volume" in literal:
                return True
    return False


def _image_volume_core_files() -> list:
    """Fichiers core de l'image qui annoncent le scope `volume`."""
    src_dir = package_scrapers_dir()
    out = []
    for filename in sorted(os.listdir(src_dir)):
        if not filename.endswith(".py") or not is_core_filename(filename):
            continue
        if _declares_volume_scope(os.path.join(src_dir, filename)):
            out.append(filename)
    return out


def _loaded_volume_core_scrapers() -> list:
    """Fournisseurs de tomes core, tels que le registre les a réellement chargés."""
    return [
        s
        for s in ScraperRegistry.get_by_scope("volume", include_disabled=True)
        if is_core_filename(ScraperRegistry.get_source_file(s.id))
    ]


def test_le_registre_charge_au_moins_un_fournisseur_core_de_tomes():
    """Sans ça, `volume_providers()` rend une liste vide et la passe ne fait rien."""
    core_volume = _loaded_volume_core_scrapers()
    assert core_volume, (
        "Aucun scraper core chargé ne déclare le scope 'volume'. "
        "L'enrichissement par tome n'a donc AUCUN fournisseur : "
        "data/scrapers/ a divergé de l'image (sync core)."
    )


def test_un_fournisseur_de_tomes_implemente_vraiment_l_index():
    """Déclarer le scope ne suffit pas : `BaseScraper.fetch_volume_index` rend None.

    Un fichier qui garderait le scope en perdant la méthode passerait le test
    précédent tout en ne produisant aucun index.
    """
    implemented = [
        s
        for s in _loaded_volume_core_scrapers()
        if callable(getattr(s, "fetch_volume_index", None))
        and type(s).fetch_volume_index is not BaseScraper.fetch_volume_index
    ]
    assert implemented, (
        "Aucun fournisseur core de tomes n'implémente fetch_volume_index — "
        "la méthode héritée de BaseScraper rend None pour toute série."
    )


def test_tout_scraper_de_tomes_livre_par_l_image_arrive_jusqu_au_registre():
    """La divergence image ↔ data/scrapers, prise à la racine.

    C'est le test qui échoue si le mécanisme de sync core laisse à nouveau une
    copie plus ancienne masquer un scraper corrigé livré par l'image.
    """
    expected = {os.path.splitext(f)[0] for f in _image_volume_core_files()}
    loaded = {
        os.path.splitext(ScraperRegistry.get_source_file(s.id))[0]
        for s in _loaded_volume_core_scrapers()
    }
    missing = sorted(expected - loaded)
    assert not missing, (
        f"L'image livre {sorted(expected)} avec le scope 'volume', mais le "
        f"registre ne les a pas chargés ainsi : {missing} manquent. "
        "La copie sous data/scrapers/ est plus ancienne que celle de l'image."
    )
