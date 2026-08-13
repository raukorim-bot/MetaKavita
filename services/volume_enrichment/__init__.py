"""
Enrichissement des métadonnées au niveau du tome et de l'album (issue #27).

Découpage :

* `matching`    : appariement numéro de tome ↔ chapitre Kavita, sentinelles comprises,
* `plan`        : politique de comblement, aperçu sans aucune écriture,
* `apply`       : exécution du plan, cadencée, chronométrée et journalisée,
* `index_cache` : mémoïsation courte de l'index fournisseur, entre l'aperçu et
                  l'écriture qui suit,
* `job`         : les deux passes en thread dédié — une bibliothèque, ou une seule
                  série — annulables et diffusant leur progression.
"""
