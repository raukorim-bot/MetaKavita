# Auto-sync, webhooks & health

[English](README.md) · [Français](../fr/automation.md)

← [Documentation](README.md)

## Auto-sync (Config → Planning)

Kavita has no outgoing HTTP webhooks for library updates. Auto-sync is the background path that fills new or pending series.

A **master switch** turns the whole card off (no timer, no scan hub). When it is on, pick **one** trigger:

* **Every X minutes** — same idea as before: series missing from the cache or still `PENDING`. Minutes are no longer the off switch (`0` used to mean off).
* **When a Kavita library scan finishes** — Meta listens on Kavita’s message hub (the same channel the Kavita UI uses). After a short quiet period it compares the catalogue to a snapshot and enqueues **new** series only. An hours-long **safety net** (default 24, `0` = off) covers a scan that finished while Meta or the socket was down.

**Mode** applies to Auto-sync jobs only (not the dashboard batch, a row click, or Companion):

* **Auto** — writes, and can fill empty targeted fields. Optional force update.
* **Review** / **Super** — park for Manual Review (hidden if that sidebar category is off).

`DISABLED_LIBRARIES` is still a denylist of Kavita library IDs for **auto-sync only**. Dashboard, manual batch, and webhook see every library.

**Stop** on the dashboard also clears waiting Auto-sync jobs. A scrape already running finishes. Webhook and row-click jobs stay in the queue.

When an Auto-sync wave finishes, a teal button appears next to Manual Review (series count, completed, errors, titles). Closing the modal marks the report read. This is not the dashboard batch. Closed waves also feed a chapter on `/stats` (lifetime, from this version on — no backfill). The dashboard filter **Latest wave** keeps only the series from that report.

Older configs with only `AUTO_SYNC_INTERVAL`: `0` stays off; a positive value stays on with the minutes trigger. Scan is never turned on by itself.

## Webhook

`POST http://<your-metakavita-ip>:5010/webhook`

Prefer the header — a token in the query string ends up in reverse-proxy access logs, browser history and `Referer`:

```
X-Webhook-Token: <YOUR_WEBHOOK_TOKEN>
```

The historical query form still works (**legacy / deprecated**):

`POST http://<your-metakavita-ip>:5010/webhook?token=<YOUR_WEBHOOK_TOKEN>`

If both are supplied, the header wins.

In **Config → Planning** you get the base `/webhook` URL (no token in the query), a copyable token field, and a regenerate button.

```json
{
  "seriesId": 6827,
  "force": true
}
```

`seriesId` is enough. Optional legacy `"name"` is still accepted. `"force": true` forces a re-scrape.

Companion flags:

```json
{ "seriesId": 6827, "force": true, "auto": true }
{ "seriesId": 6827, "force": true, "super_review": true }
```

* `auto: true` — write even if Manual Review is on (**Auto** button).
* `super_review: true` — one-shot Super Review (wins over `auto`).

See [Companion](companion.md).

## Health endpoint

`GET /healthz` → `{"status": "ok", "version": "<current>"}`

Unauthenticated liveness probe (Docker `HEALTHCHECK`, Kubernetes, Portainer, Uptime Kuma). It does not read config, open the database, or contact Kavita — a Kavita outage must not restart a healthy MetaKavita container.
