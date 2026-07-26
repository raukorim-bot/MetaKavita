"""
Contrats de données (dataclasses) partagés entre la couche persistance
(db_manager.py) et la couche HTTP (routes/).

Objectif (voir DEVELOPER.md section 11.C "Tracer un nouveau reglage sur toute
la chaine") : remplacer les longues signatures positionnelles (ex:
`save_forced_overrides(series_id, forced_id, alt_title, forced_provider,
targeted_fields, publisher_pref)`) par un objet explicite a champs nommes.
Un bug de production reel (le reglage "Preference d'Editeur" par serie qui
n'etait jamais transmis a la fonction de sauvegarde) a ete cause exactement
par ce type de signature a arguments positionnels multiples.
"""

from dataclasses import dataclass


@dataclass
class SeriesOverride:
    """Represente l'ensemble des surcharges manuelles configurables pour une serie
    (forcage de provider/ID, titre alternatif, champs cibles, preference d'editeur)."""

    series_id: int
    forced_id: str = ""
    alternative_title: str = ""
    forced_provider: str = "AUTO"
    targeted_fields: str = "ALL"
    publisher_pref: str = "GLOBAL"

    @classmethod
    def from_cache_dict(cls, series_id: int, cache_data: dict) -> "SeriesOverride":
        """Construit un SeriesOverride a partir d'une entree brute de get_all_cached_data()."""
        cache_data = cache_data or {}
        return cls(
            series_id=int(series_id),
            forced_id=cache_data.get('forced_id') or "",
            alternative_title=cache_data.get('alternative_title') or "",
            forced_provider=cache_data.get('forced_provider') or "AUTO",
            targeted_fields=cache_data.get('targeted_fields') or "ALL",
            publisher_pref=cache_data.get('publisher_pref') or "GLOBAL",
        )
