# MetaKavita

MetaKavita is an automated metadata enricher and manager for [Kavita](https://kavitareader.com/). It detects library types (Manga, Comic, Comic Flexible, Book), scrapes summaries, years, publication status, genres, tags, staff, publishers, age ratings and covers from public sources, optionally translates summaries, and writes the result into Kavita through the API.

It also ships a **Plug & Play Community Scraper** architecture: extra Python scrapers load without rebuilding the Docker image.

> **⭐ If MetaKavita saves you time, please give this repo a star!**  
> It helps other Kavita users discover the tool (and who knows — maybe one day it'll buy the dev a coffee or a beer 🍻).  
> *Si MetaKavita te fait gagner du temps, ajoute une étoile à ce dépôt !*  
> *Ça aide d'autres utilisateurs de Kavita à découvrir l'outil (et qui sait — peut-être qu'un jour ça paiera un café ou une bière au dev 🍻).*

---

## Documentation

User guides are split by language — English and French are no longer mixed in this file:

| | |
| :--- | :--- |
| 🇺🇸 **English** | [`docs/en/README.md`](docs/en/README.md) |
| 🇫🇷 **Français** | [`docs/fr/README.md`](docs/fr/README.md) |

Install, dashboard, Manual Review, Inventory, volumes, scrapers, translation, reverse proxy, Companion, and security each have their own page.

Developer notes stay here at the root: [`DEVELOPER.md`](./DEVELOPER.md) · [`CUSTOM_SCRAPERS.md`](./CUSTOM_SCRAPERS.md) · [`CHANGELOG.md`](./CHANGELOG.md) · [`ROADMAP.md`](./ROADMAP.md)

---

## Quick start (Docker)

Designed as a LAN / VPN tool. Read [Security (EN)](docs/en/security.md) / [Sécurité (FR)](docs/fr/security.md) before any public exposure.

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest   # or pin :1.7.4
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TRUSTED_PROXY_COUNT=0   # 0 if NOT behind a reverse proxy
      # - KAVITA_URL=http://host.docker.internal:5001
      # - ROOT_PATH=/metakavita
    volumes:
      - ./data:/app/data
```

```bash
docker compose up -d
```

Open `http://localhost:5010`. First run is a setup wizard. Do not set `KAVITA_URL` to `localhost` inside the container — that is MetaKavita itself.

Full compose, wizard notes, and build-from-source: [EN install](docs/en/install.md) · [FR installation](docs/fr/install.md)

---

## 🙌 Contributors / Contributeurs

Community feedback that shaped MetaKavita — thank you!  
*(Retours communautaires qui ont fait évoluer MetaKavita — merci !)*

| Contributor | Contributions |
| :--- | :--- |
| [**angusmaul**](https://github.com/angusmaul) | Security hardening PRs #16–#19 (issue #15): gunicorn/requests CVE bumps (BF46), `/api/proxy-image` 5 MB stream cap (BF47), webhook `X-Webhook-Token` (BF48), `config.json` 0600 (BF49), non-root Docker PUID/PGID + HEALTHCHECK (C54), `.dockerignore` (C55), custom scraper RCE docs (C56) — plus matching unit tests. Deep re-tests & reports through 1.6.2–1.6.4: age-rating enum / Kitsu `R→mature` (#29), Auto prefer-safe + hentai/futanari tags (#25), duplicate-tag write & preview (#24), auth/CSRF Live Log INFO (BF82/BF83), dashboard series-search freeze (#30 / BF93). |
| [**LazyGeniusMan**](https://github.com/LazyGeniusMan) | MangaBaka API hardening (`schema=full`, `type=novel` filter, tag/genre & MAL parsing), official Book/LN provider feedback, `KAVITA_EXTERNAL_URL` (Docker internal API vs public UI URL), Traefik / Socket.IO CORS origin reports, configurable `MAX_TAGS` feedback. |
| [**SqueezedByte**](https://github.com/SqueezedByte) | KOReader / Kamare crash report (`localizedName` nulling), Kavita force-update read-timeout reports → `KAVITA_HTTP_TIMEOUT` + 2-pass soft-success, MangaBaka cover CDN allowlist (`images`/`cdn` `.mangabaka.dev` / `.org`, #31 / BF91–BF92). |
| [**ThoughtzThruKeyz**](https://github.com/ThoughtzThruKeyz) | Publisher metadata feature request, ComicVine scraping feedback, disable-translation option (`NONE`), series / localized title configuration ideas. |
| [**randrini**](https://github.com/randrini) | Free Google Translate (`googletrans`) integration request. |

---

## Notes

* **Tech stack:** Python 3.11, Flask, Gunicorn (Eventlet WSGI), Flask-SocketIO, Curl-Cffi, BeautifulSoup4, Regex.
* **Kavita API quirks:** [`kavita_api.md`](./kavita_api.md)
* **Community scrapers:** [community-scraper-metakavita](https://github.com/raukorim-bot/community-scraper-metakavita)
