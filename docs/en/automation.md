# Auto-sync, webhooks & health

[English](README.md) · [Français](../fr/automation.md)

← [Documentation](README.md)

## Background polling (recommended)

Kavita does not natively provide outgoing webhooks for library updates. Set `AUTO_SYNC_INTERVAL` above `0` (e.g. `30` minutes) to poll Kavita for new or pending series.

`DISABLED_LIBRARIES` is a comma-separated denylist of Kavita library IDs for **auto-sync polling only**. Dashboard, manual batch, and webhook still see every library.

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

* `auto: true` — write even if Manual Review is on (Companion **Auto**).
* `super_review: true` — one-shot Super Review (wins over `auto`).

See [Companion](companion.md).

## Health endpoint

`GET /healthz` → `{"status": "ok", "version": "1.7.1"}`

Unauthenticated liveness probe (Docker `HEALTHCHECK`, Kubernetes, Portainer, Uptime Kuma). It does not read config, open the database, or contact Kavita — a Kavita outage must not restart a healthy MetaKavita container.
