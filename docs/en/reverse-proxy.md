# Reverse proxy & subpath

[English](README.md) · [Français](../fr/reverse-proxy.md)

← [Documentation](README.md)

MetaKavita supports subpath hosting (e.g. `https://your-domain.com/metakavita`).

1. Set `ROOT_PATH=/metakavita` in the container environment. Env wins over the value saved in setup / `config.json`. Restart after changing.
2. In the reverse proxy (Nginx Proxy Manager, Traefik, Caddy, …), route `/metakavita` to container port `5010`.
3. Pass WebSocket upgrade headers (`Upgrade $http_upgrade` and `Connection "upgrade"`).

AJAX routes and Socket.IO adapt to the subpath and stay Same-Origin.

Enabling `ROOT_PATH` does not break direct access: the instance remains reachable at `https://your-domain.com/metakavita` **and** at `http://192.168.x.x:5010/`.

Set `TRUSTED_PROXY_COUNT=1` (default) behind one reverse proxy. Set it to **`0` when MetaKavita is reachable directly**, otherwise `X-Forwarded-*` is attacker-controlled and the per-IP lockout can be evaded. See [Security](security.md) and [Configuration](configuration.md).

`CORS_ALLOWED_ORIGINS` lists explicit origins for HTTP + Socket.IO. Empty = Same-Origin only. `*` is rejected. It does not replace a correct WebSocket upgrade on the proxy.
