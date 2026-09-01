# Installation

[English](README.md) · [Français](../fr/install.md)

← [Documentation](README.md)

MetaKavita is designed primarily as an internal management tool (LAN / VPN). Before exposing it publicly, read [Security](security.md).

## Option A: Pull the pre-built image (recommended)

No cloning required. Create a `docker-compose.yml` anywhere on your server:

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest   # or pin :1.7.2
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    # Reach Kavita on the host (Portainer / separate stack). Never use localhost
    # inside the container — that is MetaKavita itself.
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      # First run opens a guided setup wizard (account, Kavita, languages, options, cascades).
      # To skip it (pre-provisioned deploys), generate a hash with
      # `python debug/hash_password.py` and set:
      # - ADMIN_USERNAME=admin
      # - ADMIN_PASSWORD_HASH=pbkdf2:sha256:...
      - TRUSTED_PROXY_COUNT=0   # set to 0 if NOT behind a reverse proxy
      # - KAVITA_URL=http://host.docker.internal:5001  # host-published Kavita
      # - KAVITA_URL=http://kavita:5000                # same Docker network
      # - KAVITA_API_KEY=your_kavita_api_key
      # - PUID=1000    # Host user id that should own ./data (run `id -u`)
      # - PGID=1000    # Host group id that should own ./data (run `id -g`)
      # - ROOT_PATH=/metakavita # Optional subpath for reverse proxies
      # - CORS_ALLOWED_ORIGINS=https://metakavita.home.local.ltd
      # - SESSION_COOKIE_SECURE=1  # Optional: set behind HTTPS reverse proxy
    volumes:
      - ./data:/app/data
```

```bash
docker compose up -d
```

Open `http://localhost:5010`. The first run is a setup wizard (account, Kavita URL and API key, languages, options).

Do not set `KAVITA_URL` to `localhost` inside the container — that is MetaKavita itself. Use `host.docker.internal` when Kavita is published on the host, or the Docker service name when both containers share a network.

`ADMIN_PASSWORD` was removed. The wizard creates the account. To pre-provision, set `ADMIN_PASSWORD_HASH` (see [Configuration](configuration.md)).

## Option B: Build from source

```bash
git clone https://github.com/raukorim-bot/MetaKavita.git
cd MetaKavita
docker compose up -d --build
```

Next: [Configuration variables](configuration.md) · [Reverse proxy](reverse-proxy.md)
