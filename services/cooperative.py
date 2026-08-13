"""
Point de bascule pour le worker unique.

MetaKavita tourne en `gunicorn -w 1` avec le worker eventlet, et `app.py` appelle
`eventlet.monkey_patch()` avant tout le reste : les `threading.Thread` de la
passe par tome et du scan d'hygiène n'y sont pas des threads système mais des
greenthreads coopératifs. Une boucle qui ne fait que du calcul ne rend donc
jamais la main — et pendant toute sa durée, plus une requête HTTP n'est servie,
plus un événement Socket.IO n'est émis, y compris la progression de la tâche en
cours, qui paraît figée.

`time.sleep` est précisément ce que le monkey-patch remplace par
`eventlet.sleep` : un `sleep(0)` suffit à repasser par l'ordonnanceur. Hors
monkey-patch (pytest, scripts de mesure, interpréteur), c'est un appel sans
effet mesurable — ce qui permet d'en poser dans les boucles sans conditionner le
code au mode de déploiement, et sans importer eventlet là où il n'est pas monté.
"""
from __future__ import annotations

import time


def yield_to_worker() -> None:
    """Rend la main au worker le temps d'un tour d'ordonnanceur."""
    time.sleep(0)
