# Auto-sync, webhooks et santé

[English](../en/automation.md) · [Français](README.md)

← [Documentation](README.md)

## Polling d'arrière-plan (recommandé)

Kavita n'émet pas de webhooks sortants. Une valeur `AUTO_SYNC_INTERVAL` supérieure à `0` (ex. `30` minutes) interroge Kavita pour les séries nouvelles ou en attente.

`DISABLED_LIBRARIES` est une dénylist d'IDs de bibliothèques Kavita pour le **polling auto-sync uniquement**. Dashboard, batch manuel et webhook voient toutes les biblios.

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

`GET /healthz` → `{"status": "ok", "version": "1.7.0"}`

Sonde de liveness non authentifiée (`HEALTHCHECK` Docker, Kubernetes, Portainer, Uptime Kuma). Elle ne lit pas la config, n'ouvre pas la base et ne contacte pas Kavita — une panne Kavita ne doit pas redémarrer un MetaKavita sain.
