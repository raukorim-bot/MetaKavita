# Auto-sync, webhooks et santé

[English](../en/automation.md) · [Français](README.md)

← [Documentation](README.md)

## Auto-sync (Config → Planification)

Kavita n'émet pas de webhooks HTTP sortants pour les mises à jour de bibliothèque. L'auto-sync est le chemin de fond qui prend les séries nouvelles ou en attente.

Un **interrupteur maître** éteint toute la carte (pas de minuterie, pas de hub de scan). Allumé, choisis **un** déclencheur :

* **Toutes les X minutes** — comme avant : séries absentes du cache ou encore `PENDING`. Les minutes ne sont plus l'interrupteur (`0` voulait dire off).
* **À la fin d'un scan de bibliothèque Kavita** — Meta écoute le hub de messages de Kavita (le même canal que l'UI Kavita). Après un court silence, il compare le catalogue à un instantané et n'enfile que les séries **nouvelles**. Un **filet** en heures (défaut 24, `0` = off) rattrape un scan fini pendant que Meta ou le socket était coupé.

Le **mode** ne s'applique qu'aux jobs Auto-sync (pas le lot du tableau de bord, un clic ligne, ni Companion) :

* **Auto** — écrit, et peut combler les champs ciblés vides. Force update optionnel.
* **Review** / **Super** — parque en Review manuelle (masqués si cette catégorie de barre latérale est off).

`DISABLED_LIBRARIES` reste une dénylist d'IDs de bibliothèques Kavita pour **l'auto-sync seulement**. Dashboard, lot manuel et webhook voient toutes les biblios.

**Stop** sur le tableau de bord vide aussi l'Auto-sync en attente. Un scrape déjà lancé continue. Les jobs webhook et clic ligne restent dans la file.

Quand une vague Auto-sync se termine, un bouton sarcelle apparaît à côté des Reviews (nombre de séries, terminées, erreurs, liste). Fermer la modale marque le rapport lu. Ce n'est pas le lot du tableau de bord. Les vagues closes alimentent aussi un chapitre sur `/stats` (lifetime, à partir de cette version — pas de rattrapage). Le filtre **Dernière vague** du tableau de bord ne garde que les séries de ce rapport.

Anciennes configs avec seulement `AUTO_SYNC_INTERVAL` : `0` reste éteint ; une valeur positive reste allumée, déclencheur minutes. Le scan ne s'allume jamais tout seul.

## Webhook

`POST http://<ton-ip-metakavita>:5010/webhook`

Privilégie l'en-tête — un jeton dans la query se retrouve dans les logs du reverse proxy, l'historique et `Referer` :

```
X-Webhook-Token: <TON_WEBHOOK_TOKEN>
```

La forme historique reste fonctionnelle (**legacy / dépréciée**) :

`POST http://<ton-ip-metakavita>:5010/webhook?token=<TON_WEBHOOK_TOKEN>`

Si les deux sont fournis, l'en-tête gagne.

Dans **Config → Planification** : URL de base `/webhook` (sans jeton), champ jeton copiable, bouton de régénération.

```json
{
  "seriesId": 6827,
  "force": true
}
```

`seriesId` suffit. `"name"` legacy optionnel. `"force": true` force un re-scrape.

Flags Companion :

```json
{ "seriesId": 6827, "force": true, "auto": true }
{ "seriesId": 6827, "force": true, "super_review": true }
```

* `auto: true` — écriture même si Review manuelle est on (bouton **Auto**).
* `super_review: true` — Super Review one-shot (prioritaire sur `auto`).

Voir [Companion](companion.md).

## Endpoint de santé

`GET /healthz` → `{"status": "ok", "version": "<courante>"}`

Sonde de liveness non authentifiée (`HEALTHCHECK` Docker, Kubernetes, Portainer, Uptime Kuma). Elle ne lit pas la config, n'ouvre pas la base et ne contacte pas Kavita — une panne Kavita ne doit pas redémarrer un MetaKavita sain.
