# Security

[English](README.md) · [Français](../fr/security.md)

← [Documentation](README.md)

## Intended use

MetaKavita is an **internal management tool (backoffice)** for a LAN or a private network (WireGuard, Tailscale).

## Built-in controls

* **Authentication:** password lock with timing-attack prevention (`secrets.compare_digest`) and anti-brute-force delays. There is no configuration in which the dashboard is served without a login.
* **CSRF (v1.6+):** session token on mutating POSTs (`X-CSRF-Token` / form field). Webhook stays token-auth exempt.
* **Sessions:** `HttpOnly` + `SameSite=Lax` (optional `SESSION_COOKIE_SECURE=1` behind HTTPS). `SECRET_KEY` is generated on first boot — never a public hardcoded fallback.
* **SSRF (v1.6+):** shared URL allowlist for covers and `/api/proxy-image` (http(s) only, no credentials / localhost / private IPs; up to 3 redirects, each hop re-validated; safe `image/*` MIME).
* **Cover UI XSS (v1.6+):** results built with DOM APIs (`textContent`).
* **Webhooks:** cryptographically generated `WEBHOOK_TOKEN`, rotatable from the UI.
* **Credential masking:** API keys censored in the DOM; Kavita auth logs never print key prefixes.

`SECRET_KEY` and `WEBHOOK_TOKEN` are generated on first launch. Keep them private.

### Custom scrapers execute arbitrary code

A `.py` in `data/scrapers/` is **not configuration** — it is imported and run at startup with the application's full privileges. There is no sandbox. A malicious scraper can read `config.json` (`SECRET_KEY`, `WEBHOOK_TOKEN`, every API key), reach any file the container can, and open outbound connections. Prefer [community-scraper-metakavita](https://github.com/raukorim-bot/community-scraper-metakavita), and still read the file before install — including AI-generated ones.

Full warning: [`CUSTOM_SCRAPERS.md`](../../CUSTOM_SCRAPERS.md).

## Public exposure

Built-in controls **do not guarantee immunity**. Exposing MetaKavita to the open internet is at your own risk.

1. Reverse proxy & HTTPS (Nginx, Traefik, Caddy).
2. A second auth layer (Authelia, Authentik, Cloudflare Access, or HTTP Basic Auth).
3. IP restrictions or a VPN whenever possible.
4. A long, complex password on the first-run setup screen.
5. **`TRUSTED_PROXY_COUNT=0` if you are not behind a reverse proxy**, so lockout counts the real client address. A global cap (20 failed logins / 15 minutes) still bounds brute-force, but it locks the login screen for everyone.

MetaKavita is provided "as-is" without warranty. The maintainers assume no liability for data loss, unauthorized access, or incidents from public exposure or misconfiguration.
