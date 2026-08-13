# Stress test MetaKavita

Scripts autonomes de mise en charge. Ils ne font partie ni de l'application ni
de la suite pytest : ils l'instrumentent de l'extérieur, à l'échelle et dans la
durée, pour voir ce que des tests unitaires ne voient pas.

## Garanties de sûreté

* **Aucune écriture vers un Kavita réel** : `_harness.FakeKavitaAPI` est un
  double en mémoire ; `kavita_api.KavitaAPI` n'est jamais instancié.
* **Aucun appel réseau** : les fournisseurs sont des doubles ; le seul script
  qui exécute un vrai parseur (`s5`, ComicVine) remplace `requests` par un faux.
* **Aucune écriture dans `data/cache.db`** : `_harness.temp_db()` détourne
  `db_manager.DATA_DIR` / `DB_FILE` vers un dossier temporaire local, supprimé
  à la sortie.
* **Aucun fichier de l'application modifié.**

## Scripts

| Script | Ce qu'il éprouve |
| --- | --- |
| `s1_volume_pass_scale.py` | Passe par tome à grande échelle : milliers de séries, séries à 300 tomes, tomes multi-chapitres, sentinelles (-100000 / 100000), décimaux, séries vides. Réconcilie les compteurs avec les écritures réelles. |
| `s2_cancel_resume.py` | Annulation en cours de passe, latence réelle, reprise : unités perdues, unités refaites, démarrages simultanés. |
| `s3_concurrency.py` | Passe + scan d'hygiène + écritures `series_cache` + trafic HTTP simultanés : verrous SQLite, latence des routes, états globaux. |
| `s4_sqlite_load.py` | Coût unitaire des écritures `db_manager`, écrivains concurrents (1/2/4/8), croissance de la base, requêtes fréquentes à 10 k / 50 k / 200 k unités, croissance du WAL. |
| `s5_providers_degraded.py` | Fournisseurs en panne (timeout, 429, 500, JSON invalide, HTML tronqué, réponse géante, type inattendu), respect du `rate_limit` sous charge, parseur ComicVine réel sur réponses dégradées. |
| `s6_leaks.py` | Passe longue et passes répétées : mémoire, handles, threads, états globaux, coût de `socketio.emit` sans serveur. |
| `s7_eventlet_blocking.py` | Le scénario de production : `eventlet.monkey_patch()`, serveur WSGI local, sonde HTTP dans un vrai thread système. Mesure le gel de la boucle d'événements pendant la passe et pendant le regroupement des doublons. **C'est le seul script qui reproduit la forme réelle du déploiement** ; les six autres tournent en threads système, donc plus indulgents. |

## Relance

Depuis la racine du dépôt :

```powershell
python debug/stress/s1_volume_pass_scale.py
python debug/stress/s2_cancel_resume.py
python debug/stress/s3_concurrency.py
python debug/stress/s4_sqlite_load.py
python debug/stress/s5_providers_degraded.py
python debug/stress/s6_leaks.py
python debug/stress/s7_eventlet_blocking.py
```

Profils plus lourds : `s1 --big` (4 000 séries), `s6 --long` (~45 000 unités).
Scénarios ciblés : `s5 giant`, `s5 comicvine`, `s6 --mem-only`.
Tout enchaîner : `python debug/stress/run_all.py`.

Chaque script écrit ses mesures en JSON dans `debug/stress/results/`.

## Lecture des résultats

`ms_per_unit` et `units_per_s` mesurent le coût **propre à MetaKavita** : les
doubles répondent instantanément, donc ce qui reste est du temps applicatif
(base, appariement, construction des payloads). En production ce coût s'ajoute
au temps fournisseur, qui le domine largement dès qu'un scraper HTML est en
tête de cascade.
