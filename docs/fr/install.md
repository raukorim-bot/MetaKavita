# Installation

[English](../en/install.md) · [Français](README.md)

← [Documentation](README.md)

MetaKavita est conçu en priorité comme un outil de gestion interne (LAN / VPN). Avant toute exposition publique, lire [Sécurité](security.md).

## Option A : image pré-compilée (recommandé)

Aucun clonage n'est requis. Crée un fichier `docker-compose.yml` sur ton serveur :

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest   # ou pin :1.7.4
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    # Atteindre Kavita sur l'hôte (Portainer / stack séparée). Jamais localhost
    # depuis le conteneur — c'est MetaKavita lui-même.
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      # Au premier démarrage, un wizard guidé (compte, Kavita, langues, options, cascades).
      # Pour l'ignorer (déploiements pré-provisionnés), générez un hachage avec
      # `python debug/hash_password.py` puis renseignez :
      # - ADMIN_USERNAME=admin
      # - ADMIN_PASSWORD_HASH=pbkdf2:sha256:...
      - TRUSTED_PROXY_COUNT=0   # 0 si vous n'êtes PAS derrière un reverse proxy
      # - KAVITA_URL=http://host.docker.internal:5001  # Kavita publié sur l'hôte
      # - KAVITA_URL=http://kavita:5000                # même réseau Docker
      # - KAVITA_API_KEY=ta_cle_api_kavita
      # - PUID=1000    # UID hôte qui doit posséder ./data (`id -u`)
      # - PGID=1000    # GID hôte qui doit posséder ./data (`id -g`)
      # - ROOT_PATH=/metakavita # Optionnel : pour hébergement en sous-dossier
      # - CORS_ALLOWED_ORIGINS=https://metakavita.home.local.ltd
      # - SESSION_COOKIE_SECURE=1  # Optionnel : derrière un reverse proxy HTTPS
    volumes:
      - ./data:/app/data
```

```bash
docker compose up -d
```

Ouvre `http://localhost:5010`. Le premier démarrage est un wizard (compte, URL et clé API Kavita, langues, options).

Ne mets pas `KAVITA_URL` à `localhost` dans le conteneur — c'est MetaKavita lui-même. Utilise `host.docker.internal` quand Kavita est publié sur l'hôte, ou le nom de service Docker quand les deux conteneurs partagent un réseau.

`ADMIN_PASSWORD` a été retiré. Le wizard crée le compte. Pour pré-provisionner, renseigne `ADMIN_PASSWORD_HASH` (voir [Configuration](configuration.md)).

## Option B : compiler depuis les sources

```bash
git clone https://github.com/raukorim-bot/MetaKavita.git
cd MetaKavita
docker compose up -d --build
```

Suite : [Variables de configuration](configuration.md) · [Reverse proxy](reverse-proxy.md)
