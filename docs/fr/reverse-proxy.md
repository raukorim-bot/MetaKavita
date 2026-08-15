# Reverse proxy et sous-dossier

[English](../en/reverse-proxy.md) · [Français](README.md)

← [Documentation](README.md)

MetaKavita gère un sous-chemin (ex. `https://ton-domaine.com/metakavita`).

1. Renseigne `ROOT_PATH=/metakavita` dans l'environnement du conteneur. L'env prime sur le setup / `config.json`. Redémarrage après changement.
2. Dans le reverse proxy (Nginx Proxy Manager, Traefik, Caddy, …), redirige `/metakavita` vers le port `5010`.
3. Transmets les en-têtes WebSocket (`Upgrade $http_upgrade` et `Connection "upgrade"`).

Les routes AJAX et Socket.IO s'adaptent au sous-chemin, en Same-Origin.

Activer `ROOT_PATH` ne coupe pas l'accès direct : l'instance reste joignable via le sous-chemin **et** via `http://192.168.x.x:5010/`.

`TRUSTED_PROXY_COUNT=1` (défaut) derrière un reverse proxy. Mets **`0` si MetaKavita est joignable directement**, sinon `X-Forwarded-*` est contrôlé par le client et le verrouillage par IP peut être esquivé. Voir [Sécurité](security.md) et [Configuration](configuration.md).

`CORS_ALLOWED_ORIGINS` liste les origins explicites (HTTP + Socket.IO). Vide = Same-Origin uniquement. `*` est rejeté. Ça ne remplace pas une config WebSocket correcte sur le proxy.
