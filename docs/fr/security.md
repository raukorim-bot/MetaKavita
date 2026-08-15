# Sécurité

[English](../en/security.md) · [Français](README.md)

← [Documentation](README.md)

## Usage prévu

MetaKavita est un **outil de gestion interne (backoffice)** pour un LAN ou un réseau privé (WireGuard, Tailscale).

## Contrôles intégrés

* **Authentification :** verrouillage par mot de passe, protection timing (`secrets.compare_digest`), délais anti-force brute. Aucune config ne sert l'interface sans connexion.
* **CSRF (v1.6+) :** jeton de session sur les POST mutatifs (`X-CSRF-Token` / champ form). Le webhook reste exempt (auth par jeton).
* **Sessions :** `HttpOnly` + `SameSite=Lax` (`SESSION_COOKIE_SECURE=1` optionnel derrière HTTPS). `SECRET_KEY` générée au premier boot — jamais de fallback public hardcodé.
* **SSRF (v1.6+) :** allowlist partagée pour couvertures et `/api/proxy-image` (http(s) uniquement, pas de credentials / localhost / IPs privées ; jusqu'à 3 redirects re-validés ; MIME `image/*`).
* **XSS modal couvertures (v1.6+) :** construction via APIs DOM (`textContent`).
* **Webhooks :** `WEBHOOK_TOKEN` cryptographique, régénérable depuis l'UI.
* **Masquage :** clés API censurées dans le DOM ; les logs d'auth Kavita n'affichent plus de préfixe de clé.

`SECRET_KEY` et `WEBHOOK_TOKEN` sont générés au premier lancement. Garde-les secrets.

### Les scrapers personnalisés exécutent du code arbitraire

Un `.py` dans `data/scrapers/` **n'est pas de la configuration** : il est importé et exécuté au démarrage avec tous les droits de l'application. Pas de bac à sable. Un scraper malveillant peut lire `config.json` (`SECRET_KEY`, `WEBHOOK_TOKEN`, toutes les clés), tout fichier visible du conteneur, et ouvrir des connexions sortantes. Préfère [community-scraper-metakavita](https://github.com/raukorim-bot/community-scraper-metakavita), et lis le fichier avant — y compris ceux générés par IA.

Avertissement complet : [`CUSTOM_SCRAPERS.md`](../../CUSTOM_SCRAPERS.md).

## Exposition publique

Ces protections **ne garantissent pas une sécurité absolue**. Exposer MetaKavita sur Internet se fait à tes risques.

1. Reverse proxy & HTTPS (Nginx, Traefik, Caddy).
2. Une seconde couche d'auth (Authelia, Authentik, Cloudflare Access, ou HTTP Basic).
3. Restriction d'IP ou VPN dès que possible.
4. Mot de passe long et complexe sur l'écran de setup.
5. **`TRUSTED_PROXY_COUNT=0` si tu n'es pas derrière un reverse proxy**, pour que le verrouillage compte la vraie adresse. Un plafond global (20 échecs / 15 min) borne encore la force brute, mais verrouille l'écran pour tout le monde.

MetaKavita est fourni « en l'état », sans garantie. Les mainteneurs déclinent toute responsabilité en cas de perte de données, d'intrusion ou d'incident lié à une exposition publique ou une erreur de configuration.
