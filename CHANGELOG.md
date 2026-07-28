## [1.6.2] - Unreleased (Security Hardening)

EN
### ðŸ”’ Security
* **BF46. Dependency CVE bumps** â€” `gunicorn` `21.2.0` â†’ `23.0.0` and `requests` `2.31.0` â†’ `2.33.1`. Clears five known advisories: two request-smuggling issues in Gunicorn (`PYSEC-2026-1433`, `PYSEC-2026-1434`, both fixed in 22.0.0) and three in Requests (`PYSEC-2026-1873`, `PYSEC-2026-1872`, `PYSEC-2026-2275`, the last only fixed in 2.33.0). No public API change in either package for the way MetaKavita uses them. `googletrans` is deliberately left at `4.0.0-rc1`.
* **BF47. `/api/proxy-image` size cap** â€” The proxy now streams the remote response and refuses anything over **5 MB** with a `413`, instead of buffering the whole body into memory with `res.content`. An allowlisted host serving a very large file could previously exhaust the container's memory, which under `gunicorn -w 1` takes down the whole application. `Content-Length` is checked first as a cheap early reject; the running byte total is what actually enforces the limit, since that header can be absent or untrue. Redirect hops are now closed as they are followed (`url_allowlist.fetch_with_safe_redirects`), which matters once responses are streamed.
* **BF48. Webhook token as a header** â€” `/webhook` accepts `X-Webhook-Token` in addition to the existing `?token=` query parameter, which keeps working unchanged. The header is preferred because a query string ends up in reverse-proxy access logs, browser history and `Referer` headers. Token comparison now runs on UTF-8 bytes, so a non-ASCII token returns a clean `401` instead of raising inside `secrets.compare_digest`.
* **BF49. `config.json` written 0600** â€” `save_config()` restricts the file to its owner after every write. It holds `SECRET_KEY`, `WEBHOOK_TOKEN` and every API key, and was previously created with the process umask (0644 â€” world-readable â€” on a default Docker image). Applied on every save so a file restored from a backup or written by an older version is repaired too. Best-effort: `chmod` is skipped silently on Windows and on filesystems that refuse it, and can never fail a save.

---

FR
### ðŸ”’ SÃ©curitÃ©
* **BF46. MontÃ©e de versions (CVE)** â€” `gunicorn` `21.2.0` â†’ `23.0.0` et `requests` `2.31.0` â†’ `2.33.1`. Corrige cinq vulnÃ©rabilitÃ©s connues : deux failles de *request smuggling* dans Gunicorn (`PYSEC-2026-1433`, `PYSEC-2026-1434`, corrigÃ©es en 22.0.0) et trois dans Requests (`PYSEC-2026-1873`, `PYSEC-2026-1872`, `PYSEC-2026-2275`, cette derniÃ¨re uniquement corrigÃ©e en 2.33.0). Aucun changement d'API publique pour l'usage qu'en fait MetaKavita. `googletrans` reste volontairement en `4.0.0-rc1`.
* **BF47. Plafond de taille sur `/api/proxy-image`** â€” Le proxy lit dÃ©sormais la rÃ©ponse distante en flux et refuse au-delÃ  de **5 Mo** avec un `413`, au lieu de charger tout le corps en mÃ©moire via `res.content`. Un hÃ´te autorisÃ© servant un trÃ¨s gros fichier pouvait Ã©puiser la mÃ©moire du conteneur â€” ce qui, sous `gunicorn -w 1`, emporte toute l'application. Le `Content-Length` sert de refus prÃ©coce peu coÃ»teux ; c'est le total courant des octets lus qui applique rÃ©ellement la limite, cet en-tÃªte pouvant Ãªtre absent ou mensonger. Les hops de redirection sont maintenant fermÃ©s au fil de leur suivi (`url_allowlist.fetch_with_safe_redirects`), ce qui compte dÃ¨s lors que les rÃ©ponses sont streamÃ©es.
* **BF48. Jeton du webhook en en-tÃªte** â€” `/webhook` accepte `X-Webhook-Token` en plus du paramÃ¨tre `?token=` existant, qui continue de fonctionner Ã  l'identique. L'en-tÃªte est recommandÃ© car une chaÃ®ne de requÃªte se retrouve dans les logs d'accÃ¨s des reverse proxies, l'historique du navigateur et les en-tÃªtes `Referer`. La comparaison se fait dÃ©sormais sur les octets UTF-8 : un jeton non-ASCII renvoie un `401` propre au lieu de faire lever `secrets.compare_digest`.
* **BF49. `config.json` Ã©crit en 0600** â€” `save_config()` restreint le fichier Ã  son propriÃ©taire aprÃ¨s chaque Ã©criture. Il contient `SECRET_KEY`, `WEBHOOK_TOKEN` et toutes les clÃ©s d'API, et Ã©tait crÃ©Ã© avec l'umask du processus (0644 â€” lisible par tous â€” sur une image Docker par dÃ©faut). RÃ©appliquÃ© Ã  chaque sauvegarde, afin de corriger aussi un fichier restaurÃ© d'une sauvegarde ou Ã©crit par une version antÃ©rieure. Best-effort : le `chmod` est ignorÃ© silencieusement sous Windows et sur les systÃ¨mes de fichiers qui le refusent, et ne peut jamais faire Ã©chouer une sauvegarde.

---

## [1.6.1] - 2026-07-26 (Comic Flexible + Playful Stats + Batch QoS + Wikidata + Reliability)

EN
### âœ¨ Highlights
* **Reliability barometer** â€” Sidebar checkbox unlocks a match-accept threshold slider (`0.30`â€“`1.00`, default `0.60`). Off = fixed tested default. Config: `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD`; scrapers use `get_match_accept_threshold()`.
* **BDTheque.com (comics)** â€” New `BDTHEQUE` scraper for https://www.bdtheque.com/ (not BÃ©dÃ©thÃ¨que / bedetheque.com): AJAX series search, series page parse (staff, publisher, genres, status, cover), Magic Input `/series/{id}/{slug}`, unified scoring, cover search. Distinct from existing `BEDETHEQUE`. Cover URLs: always `/repupload/T/{couv}` (site typeahead); series page reads `data-echo` (echo.js lazy-load) instead of `placeholder.png`.
* **Kavita library sync filter** â€” Config â†’ Planning: checkboxes to enable/disable Kavita libraries (`DISABLED_LIBRARIES` denylist). Empty = all enabled; new libraries stay on by default. Applies to UI list/toolbar, batch, auto-sync, and webhook.
* **MyAnimeList official API** â€” New `MAL` scraper (replaces dead Jikan path): `X-MAL-CLIENT-ID` auth via `MAL_API_KEY` (Client ID from https://myanimelist.net/apiconfig). Manga + Book (light novels), Magic Input `myanimelist.net/manga/{id}`, unified scoring, covers CDN. No user OAuth required for search/details.
* **Wikidata provider (live)** â€” New `WIKIDATA` scraper for Manga / Comic / Book: SPARQL + Entity API, Magic Input `Qâ€¦` / wikidata.org URLs, unified scoring, Commons covers. Shared claimâ†’MetaKavita mapping in `scrapers/wikidata_map.py`. Best as fallback / ISBN / cross-IDs (AniList, MAL), not a replacement for AniList. Offline SQLite subset deferred (ops complexity). Optional dump helpers under `debug/download_wikidata_dump.sh` + `debug/extract_wikidata_dump.py` (not wired into the live scraper).
* **Comic (Flexible) / ID 5 (C35)** â€” Kavita's mixed Comic Flexible libraries are no longer treated as strict Comic. MetaKavita runs `COMIC_PROVIDER_*` first, then falls back to Manga `PROVIDER_*` when no useful metadata is found. Manual cover search queries Comic + Manga scrapers.
* **Playful Statistics (C7)** â€” Restyled `/stats` with Chart.js (donut + bars), lifetime counters (`series_enriched` / `matches_won` / `series_missed`), hit-rate KPI, ~24 fun cards. `ENABLE_PLAYFUL_STATS` on by default (disable in config modal). Live topbar KPIs on the dashboard (3 lifetime counters + session counter reset on tab close via `sessionStorage`). Socket.IO `enrichment_stats` keeps counters live during batch.
* **`/stats` scroll story** â€” Premium chapter-per-viewport layout (Leetify / GPU-landing vibe): hero score, lifetime, time saved, cache health, manual craft, providers + podium, then a full summary table. Intersection Observer reveals + count-up; color accents per chapter.
* **Dashboard visual polish** â€” Same design language as `/stats` (DM Sans + Fraunces, teal/sky accents, glass topbar, softer series rows) without changing workflow density.
* **Organic playful estimates** â€” Time saved no longer stuck at `0 min` when lifetime telemetry lags behind the cache: fun metrics use `max(lifetime, completed / provider wins)`. Time model = ~6 min/series + ~1.5 min/useful match; duration can show days.

### ðŸ§° Batch QoS & Granularity
* **Resume-friendly selection** â€” Successful series (âœ… / already up to date) auto-uncheck. Checked series IDs persist in `localStorage` per library (`mk_batch_selection:*`) so a refresh or network drop does not wipe the selection; filters no longer clear hidden checkboxes.
* **Stop vs chunked enqueue** â€” Stop aborts the UI Ã—50 `/batch-sync` loop (`AbortController`) and disables server enqueue until the next batchâ€™s first packet (`resume_enqueue=true`), so late in-flight chunks cannot refill the queue after a drain.
* **Batch progress bar** â€” Above the batch action buttons: `done / total` fill driven by Socket.IO `batch_progress` (`remaining` + active title from the worker `qsize()`). Total is set at launch from the UI selection; bar hides on completion (~1.5s) or Stop/drain.
* **Batch targeted-fields mask** â€” Collapsible sidebar panel â€œTargeted fields (batch)â€: ephemeral write filter for the next batch only (does not persist overrides). Leave all 12 checked = respect each seriesâ€™ saved mask. Uncheck any field â†’ CSV sent to `/batch-sync` as a 4-tuple queue item (`targeted_fields_override`).
* **Check all / Uncheck all** â€” Same controls on the sidebar batch mask and on each seriesâ€™ targeted-fields override panel.

### ðŸ› UI polish
* **Collapsible Scraping Options** â€” Click the sidebar â€œScraping Optionsâ€ title to show/hide the whole strategy card (open by default; open/closed state persisted in `localStorage` as `mk_scraping_options_open`).
* **`/stats` page scroll** â€” Dashboard `100vh` + `overflow: hidden` overrides so the playful stats page scrolls on desktop again.

---

FR
### âœ¨ Points forts
* **BaromÃ¨tre de fiabilitÃ©** â€” Case sidebar + curseur de seuil dâ€™acceptation (`0.30`â€“`1.00`, dÃ©faut `0.60`). Off = dÃ©faut testÃ© fixe. Config : `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` ; scrapers via `get_match_accept_threshold()`.
* **BDTheque.com (comics)** â€” Nouveau scraper `BDTHEQUE` pour https://www.bdtheque.com/ (pas BÃ©dÃ©thÃ¨que / bedetheque.com) : recherche AJAX sÃ©ries, parse fiche (staff, Ã©diteur, genres, statut, couverture), Magic Input `/series/{id}/{slug}`, scoring unifiÃ©, recherche de covers. Distinct de `BEDETHEQUE`. Couvertures : toujours `/repupload/T/{couv}` (typeahead site) ; fiche sÃ©rie lit `data-echo` (lazy-load echo.js) au lieu de `placeholder.png`.
* **Filtre de bibliothÃ¨ques Kavita** â€” Config â†’ Planification : cases Ã  cocher pour activer/dÃ©sactiver les bibliothÃ¨ques (`DISABLED_LIBRARIES`, dÃ©nylist). Vide = tout actif ; les nouvelles biblios restent actives. Sâ€™applique Ã  la liste UI / toolbar, batch, auto-sync et webhook.
* **MyAnimeList API officielle** â€” Nouveau scraper `MAL` (remplace Jikan mort) : auth `X-MAL-CLIENT-ID` via `MAL_API_KEY` (Client ID sur https://myanimelist.net/apiconfig). Manga + Book (light novels), Magic Input `myanimelist.net/manga/{id}`, scoring unifiÃ©, couvertures CDN. Pas dâ€™OAuth utilisateur pour search/details.
* **Provider Wikidata (live)** â€” Nouveau scraper `WIKIDATA` pour Manga / Comic / Book : SPARQL + Entity API, Magic Input `Qâ€¦` / URLs wikidata.org, scoring unifiÃ©, couvertures Commons. Mapping claimsâ†’MetaKavita partagÃ© (`scrapers/wikidata_map.py`). Utile en fallback / ISBN / IDs croisÃ©s â€” pas un remplacement dâ€™AniList. Sous-ensemble SQLite hors-ligne reportÃ© (complexitÃ© ops). Helpers dump optionnels : `debug/download_wikidata_dump.sh` + `debug/extract_wikidata_dump.py` (non branchÃ©s au scraper live).
* **Comic (Flexible) / ID 5 (C35)** â€” Les bibliothÃ¨ques mixtes Kavita Â« Comic Flexible Â» ne sont plus traitÃ©es comme du Comic strict. MetaKavita interroge dâ€™abord `COMIC_PROVIDER_*`, puis bascule sur les providers Manga (`PROVIDER_*`) si aucun hit utile. La recherche manuelle de couvertures interroge Comic + Manga.
* **Statistiques ludiques (C7)** â€” `/stats` restylÃ©e avec Chart.js (donut + barres), compteurs lifetime (`series_enriched` / `matches_won` / `series_missed`), KPI taux de hit, ~24 cartes fun. `ENABLE_PLAYFUL_STATS` ON par dÃ©faut. Compteurs live dans la topbar (3 KPI lifetime + session remise Ã  0 Ã  la fermeture dâ€™onglet via `sessionStorage`). Ã‰vÃ©nement Socket.IO `enrichment_stats` pendant les batchs.
* **`/stats` en rÃ©cit scroll** â€” Parcours premium chapitre par viewport (esprit Leetify / landing GPU) : score hero, lifetime, temps gagnÃ©, santÃ© du cache, craft manuel, providers + podium, puis tableau rÃ©capitulatif. Reveals + count-up ; accents couleur par chapitre.
* **Polish dashboard** â€” MÃªme langage visuel que `/stats` (DM Sans + Fraunces, accents teal/sky, topbar glass, lignes de sÃ©ries plus nettes) sans alourdir le workflow.
* **Estimations organiques** â€” Le temps gagnÃ© ne reste plus Ã  `0 min` si la tÃ©lÃ©mÃ©trie lifetime est en retard sur le cache : les mÃ©triques fun utilisent `max(lifetime, completed / wins providers)`. ModÃ¨le = ~6 min/sÃ©rie + ~1,5 min/match utile ; affichage possible en jours.

### ðŸ§° QoS & granularitÃ© batch
* **SÃ©lection reprise-friendly** â€” Une sÃ©rie OK (âœ… / dÃ©jÃ  Ã  jour) se dÃ©coche automatiquement. Les IDs cochÃ©s sont persistÃ©s en `localStorage` par bibliothÃ¨que (`mk_batch_selection:*`) : refresh / coupure rÃ©seau ne vident plus la sÃ©lection ; les filtres ne dÃ©cochent plus les lignes masquÃ©es.
* **Stop vs envoi par paquets** â€” Stop coupe la boucle UI Ã—50 `/batch-sync` (`AbortController`) et dÃ©sarme lâ€™enqueue serveur jusquâ€™au premier paquet du prochain batch (`resume_enqueue=true`), pour quâ€™un chunk encore en vol ne remplisse plus la file aprÃ¨s le drain.
* **Barre de progression batch** â€” Au-dessus des boutons dâ€™actions : jauge `fait / total` pilotÃ©e par Socket.IO `batch_progress` (`remaining` + titre actif depuis le `qsize()` du worker). Le total est fixÃ© au lancement (sÃ©lection UI) ; la barre disparaÃ®t en fin de lot (~1,5 s) ou au Stop/drain.
* **Masque de champs ciblÃ©s (batch)** â€” Sous-menu sidebar pliable : filtre dâ€™Ã©criture Ã©phÃ©mÃ¨re pour le prochain batch uniquement (ne modifie pas les overrides sÃ©rie). Tout laisser cochÃ© = respecter le masque de chaque sÃ©rie. DÃ©cocher un champ â†’ CSV envoyÃ© Ã  `/batch-sync` (4-tuple file, `targeted_fields_override`).
* **Tout cocher / Tout dÃ©cocher** â€” Sidebar (masque batch) et panneau override de chaque sÃ©rie.

### ðŸ› Polish UI
* **Options de Scraping pliables** â€” Clic sur le titre sidebar pour afficher/masquer toute la carte stratÃ©gie (ouverte par dÃ©faut ; Ã©tat ouvert/fermÃ© persistÃ© en `localStorage` sous `mk_scraping_options_open`).
* **Scroll `/stats`** â€” Contournement du layout dashboard `100vh` + `overflow: hidden` pour que la page stats scrolle Ã  nouveau sur desktop.

---

## [1.6.0] - 2026-07-26 (Smart Scoring, Localized Titles, Help Menu, Self-Host Polish & Hardening)

EN
### âœ¨ Highlights
* **Smart Scoring (C45)** â€” Providers compete by match score; the best match wins (sidebar toggle). Provider #1 seeds ISBN/author context, then the others run in parallel. Smart Completion fills gaps from highest score to lowest. Off = classic list-order fallback.
* **Localized Titles Policy (C53, issue #12)** â€” Control Kavita `localizedName` only (never rewrite Series `name`). Modes: `all` (default, titles joined with `" / "`), `prefer` (language tags), `none`. Global config + per-series `alt_title_langs`. AniList / MangaDex / Kitsu emit structured `titles[]`.
* **Help / About / Docs (C52)** â€” Topbar Help menu: About modal, GitHub documentation links, in-app release notes. Kavita+ support next to Buy me a coffee (opens this instanceâ€™s `settings#admin-kavitaplus`).
* **MangaBaka Book / LN (C47, thanks LazyGeniusMan)** â€” Official Book support (`schema=full`, `type=novel`), stronger tag/genre/MAL parsing.
* **Self-host & Docker** â€” `CORS_ALLOWED_ORIGINS` (C46), `KAVITA_EXTERNAL_URL` (C48), configurable `KAVITA_HTTP_TIMEOUT` + soft-success on RE-LOCK timeout (BF19), `MAX_TAGS` / `MAX_GENRES` caps (C49 / C51).

### ðŸ§  Matching & Scrapers
* **Unified scoring matrix** â€” MangaDex, MangaUpdates, Manga-News, Shikimori, Kitsu, ComicVine, and BÃ©dÃ©thÃ¨que now use `score_candidate()` + author cross-check (fewer false positives). Centralized `MATCH_ACCEPT_THRESHOLD = 0.60`.
* **Community scrapers** â€” Opt-in `uses_unified_scoring`; `_safe_match_score()` never crashes enrichment on a bad score. Sideload example kept under `data/scrapers/`.
* **Registry hardening** â€” No re-registration of imported classes; explicit warning on duplicate scraper IDs.
* **Forced-ID fallback (BF22)** â€” After a failed direct ID/URL lookup, MetaKavita automatically retries a title search.

### ðŸ  Self-Hosting & Power-User Settings
* **`CORS_ALLOWED_ORIGINS`** â€” CSV of explicit origins for Flask + Socket.IO (HTTPS self-hosts / Traefik). Empty = Same-Origin; `*` rejected.
* **`KAVITA_EXTERNAL_URL`** â€” Public UI link to Kavita vs internal `KAVITA_URL` for Docker API calls.
* **`KAVITA_HTTP_TIMEOUT` (default 60s)** â€” If the write succeeds but RE-LOCK times out, count as success with a warning; one capped RE-LOCK-only retry.
* **`MAX_TAGS` / `MAX_GENRES`** â€” Caps via env / `config.json` (defaults 15 / 5). No UI â€” power-user only (`get_max_tags()` / `get_max_genres()`).
* **`debug/benchmark_batch.py`** â€” Wall-clock batch benchmark (dry-run by default; `--live --i-know` for real writes).

### ðŸ—ï¸ Architecture & Reliability
* **Modular backend** â€” Blueprints (`routes/`), `services/`, `models.py` (`SeriesOverride`), thin `app.py` composition root (C32).
* **Modular frontend** â€” Seven plain `<script>` files + Jinja partials (no bundler). Legacy `script.js` removed.
* **pytest + CI** â€” Full non-regression suite with GitHub Actions on every push/PR.
* **Concurrency** â€” Per-series enrich lock; `CONFIG_LOCK` on config RMW; atomic scraper rate-limiter.

### ðŸ› Bug Fixes
* **Publisher preference never saved (BF18)** â€” Per-series `publisher_pref` is now persisted and respected.
* **Manual cover vs auto-cover** â€” Cover checkbox unchecks after manual apply; cover-only saves no longer reset status to `PENDING` / un-ignore series; targeted-fields membership uses a real list split.
* **Partial Kavita payloads (BF20)** â€” External-ID updates GET-merge like `localizedName` (no alt-title wipe / lock reset).
* **Silent general-update failure (BF26)** â€” Metadata OK + general fail is reported, not a fake `COMPLETED`.
* **Wrong DTO for `localizedName` (BF30)** â€” Deep metadata reads it from `GET /api/Series/{id}`.
* **Comic/Book env ignored (BF23)** â€” `COMIC_PROVIDER_*` / `BOOK_PROVIDER_*` / `RESET_CONTEXT_ON_FORCE` load from Docker env again.
* **Characters / frontend / queue / config** â€” Defensive character parsing (BF27); fetch `res.ok` handling (BF31); sync `task_done()` (BF32); corrupt `config.json` no longer overwritten (BF34); `TARGET_LANG` not forced every enrich (BF35); changelog modal HTML-escaped (BF28).

### ðŸ”’ Security & Hardening
Full application audit (BF20â€“BF45 + C50). Empty `ADMIN_PASSWORD` for open LAN backoffice remains intentional.
* **CSRF + session cookies (C50)** â€” Token on mutating POSTs; `SameSite=Lax` + `HttpOnly` (`SESSION_COOKIE_SECURE` optional).
* **SSRF / covers / proxy** â€” Shared URL allowlist; private IPs blocked; up to 3 redirects with hop re-validation; safe `image/*` only (BF21/BF25 â†’ BF43/BF44).
* **XSS** â€” Cover modal built with DOM APIs / `textContent` (BF24).
* **Secrets** â€” No hardcoded `SECRET_KEY` fallback (BF37); API key prefix not logged (BF38); credential-safe exception logs (BF42); revoked hardcoded Hardcover debug token.
* **Cleanup** â€” Dead MAL / Nautiljon modules removed (BF36); ComicVine `proxy_domains` narrowed (BF40).

---

FR
### âœ¨ Points forts
* **Smart Scoring (C45)** â€” Les fournisseurs sont dÃ©partagÃ©s par score ; le meilleur match gagne (interrupteur sidebar). Le provider #1 amorce le contexte ISBN/auteurs, puis les autres tournent en parallÃ¨le. La ComplÃ©tion intelligente comble les trous du score le plus haut au plus bas. DÃ©sactivÃ© = fallback classique par ordre de liste.
* **Politique des titres localisÃ©s (C53, issue #12)** â€” ContrÃ´le de Kavita `localizedName` uniquement (jamais de rÃ©Ã©criture de Series `name`). Modes : `all` (dÃ©faut, titres joints par `" / "`), `prefer` (tags de langue), `none`. Config globale + `alt_title_langs` par sÃ©rie. AniList / MangaDex / Kitsu Ã©mettent des `titles[]` structurÃ©s.
* **Aide / Ã€ propos / Docs (C52)** â€” Menu Aide du topbar : modal Ã€ propos, liens documentation GitHub, nouveautÃ©s in-app. Soutien Kavita+ Ã  cÃ´tÃ© de Buy me a coffee (ouvre `settings#admin-kavitaplus` de *cette* instance).
* **MangaBaka Book / LN (C47, merci LazyGeniusMan)** â€” Support Book officiel (`schema=full`, `type=novel`), parsing tags/genres/MAL renforcÃ©.
* **Self-host & Docker** â€” `CORS_ALLOWED_ORIGINS` (C46), `KAVITA_EXTERNAL_URL` (C48), `KAVITA_HTTP_TIMEOUT` configurable + soft-success si RE-LOCK timeout (BF19), plafonds `MAX_TAGS` / `MAX_GENRES` (C49 / C51).

### ðŸ§  Matching & Scrapers
* **Matrice de scoring unifiÃ©e** â€” MangaDex, MangaUpdates, Manga-News, Shikimori, Kitsu, ComicVine et BÃ©dÃ©thÃ¨que passent par `score_candidate()` + contrÃ´le dâ€™auteur (moins de faux positifs). Seuil centralisÃ© `MATCH_ACCEPT_THRESHOLD = 0.60`.
* **Scrapers communautaires** â€” Opt-in `uses_unified_scoring` ; `_safe_match_score()` empÃªche tout plantage sur un score mal formÃ©. Exemple sideload conservÃ© dans `data/scrapers/`.
* **Registre** â€” Plus de rÃ©-enregistrement des classes importÃ©es ; avertissement explicite en cas dâ€™ID en double.
* **Repli aprÃ¨s ID forcÃ© (BF22)** â€” Ã‰chec dâ€™un lookup ID/URL â†’ nouvelle tentative automatique en recherche titre.

### ðŸ  Self-hosting & rÃ©glages avancÃ©s
* **`CORS_ALLOWED_ORIGINS`** â€” Origins CSV pour Flask + Socket.IO (self-host HTTPS / Traefik). Vide = Same-Origin ; `*` rejetÃ©.
* **`KAVITA_EXTERNAL_URL`** â€” Lien UI public vers Kavita vs `KAVITA_URL` interne pour lâ€™API Docker.
* **`KAVITA_HTTP_TIMEOUT` (dÃ©faut 60s)** â€” Ã‰criture OK mais RE-LOCK en timeout â†’ succÃ¨s avec warning ; un retry plafonnÃ© du seul RE-LOCK.
* **`MAX_TAGS` / `MAX_GENRES`** â€” Plafonds via env / `config.json` (dÃ©fauts 15 / 5). Pas dâ€™UI â€” power-user (`get_max_tags()` / `get_max_genres()`).
* **`debug/benchmark_batch.py`** â€” Benchmark wall-clock de batch (dry-run par dÃ©faut ; `--live --i-know` pour Ã©critures rÃ©elles).

### ðŸ—ï¸ Architecture & fiabilitÃ©
* **Backend modulaire** â€” Blueprints (`routes/`), `services/`, `models.py` (`SeriesOverride`), `app.py` mince (C32).
* **Frontend modulaire** â€” Sept fichiers `<script>` + partials Jinja (sans bundler). Ancien `script.js` retirÃ©.
* **pytest + CI** â€” Suite de non-rÃ©gression + GitHub Actions Ã  chaque push/PR.
* **Concurrence** â€” Verrou dâ€™enrichissement par sÃ©rie ; `CONFIG_LOCK` sur la config ; rate-limiter scrapers atomique.

### ðŸ› Correctifs
* **PrÃ©fÃ©rence dâ€™Ã©diteur jamais sauvÃ©e (BF18)** â€” `publisher_pref` par sÃ©rie dÃ©sormais persistÃ© et respectÃ©.
* **Couverture manuelle vs auto-cover** â€” Case Â« Couverture Â» dÃ©cochÃ©e aprÃ¨s choix manuel ; une appli couverture seule ne remet plus le statut en `PENDING` / ne dÃ©signore plus ; appartenance des champs ciblÃ©s via dÃ©coupage en liste.
* **Payloads Kavita partiels (BF20)** â€” Mise Ã  jour des IDs externes en GET-merge (plus de wipe de titres alt / verrous).
* **Ã‰chec silencieux de lâ€™update gÃ©nÃ©ral (BF26)** â€” Metadata OK + gÃ©nÃ©ral KO â†’ erreur signalÃ©e, pas de faux `COMPLETED`.
* **Mauvais DTO pour `localizedName` (BF30)** â€” Lecture via `GET /api/Series/{id}`.
* **Env Comic/Book ignorÃ©e (BF23)** â€” `COMIC_PROVIDER_*` / `BOOK_PROVIDER_*` / `RESET_CONTEXT_ON_FORCE` rechargÃ©s depuis Docker.
* **Personnages / frontend / file / config** â€” Parsing personnages dÃ©fensif (BF27) ; gestion `res.ok` (BF31) ; `task_done()` sync (BF32) ; `config.json` corrompu non Ã©crasÃ© (BF34) ; `TARGET_LANG` non forcÃ© Ã  chaque enrich (BF35) ; changelog Ã©chappÃ© HTML (BF28).

### ðŸ”’ SÃ©curitÃ© & durcissement
Audit applicatif complet (BF20â€“BF45 + C50). `ADMIN_PASSWORD` vide (backoffice LAN ouvert) reste un choix volontaire.
* **CSRF + cookies de session (C50)** â€” Jeton sur les POST mutatifs ; `SameSite=Lax` + `HttpOnly` (`SESSION_COOKIE_SECURE` optionnel).
* **SSRF / couvertures / proxy** â€” Allowlist dâ€™URL partagÃ©e ; IPs privÃ©es bloquÃ©es ; jusquâ€™Ã  3 redirects re-validÃ©s ; MIME `image/*` uniquement (BF21/BF25 â†’ BF43/BF44).
* **XSS** â€” Modal couvertures via APIs DOM / `textContent` (BF24).
* **Secrets** â€” Plus de fallback `SECRET_KEY` hardcodÃ© (BF37) ; prÃ©fixe de clÃ© API non loguÃ© (BF38) ; logs dâ€™exceptions sans fuite (BF42) ; jeton Hardcover debug rÃ©voquÃ©.
* **Nettoyage** â€” Modules morts MAL / Nautiljon retirÃ©s (BF36) ; `proxy_domains` ComicVine restreint (BF40).

## [1.5.8] - 2026-07-25 (The Kavita API Deep Compliance & KOReader Stability Update)

EN
### ðŸ› Critical Bug Fixes
* **LocalizedName Corruption & KOReader/Kamare Crash Fix (`kavita_api.py`)**: `update_series_general()` now always fetches a series' full current state before writing (GET-merge-POST), preventing Kavita from silently nulling `LocalizedName` and force-unlocking `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` on partial updates (e.g. format-only). Root cause of a reported KOReader "Kamare" plugin crash.
* **GET-Only System Fields Sanitization (`kavita_api.py`)**: Centralized sanitization in `update_series_metadata()` to strip computed/read-only properties (`totalCount`, `maxCount`, `pages`, `wordCount`) and prevent Entity Framework Core state-concurrency exceptions.
* **MangaBaka "Completed" Status Mapping (`scrapers/mangabaka.py`)**: Normalized MangaBaka's raw `completed` status to `FINISHED` so completed series no longer stay marked as "Ongoing".
* **`BaseScraper` Attribute Typo (`scrapers/base.py`)**: Fixed a typo (`eeds_api_key` instead of `needs_api_key`) on the base class' default attribute.

FR
### ðŸ› Correctifs Critiques
* **Corruption LocalizedName & Crash KOReader/Kamare (`kavita_api.py`)** : `update_series_general()` rÃ©cupÃ¨re dÃ©sormais systÃ©matiquement l'Ã©tat complet de la sÃ©rie avant d'Ã©crire (GET-fusion-POST), empÃªchant Kavita d'effacer silencieusement `LocalizedName` et de dÃ©verrouiller de force les locks de nom lors de mises Ã  jour partielles. Cause racine d'un crash signalÃ© sur l'extension KOReader "Kamare".
* **Purge des ClÃ©s SystÃ¨me Kavita (`kavita_api.py`)** : Suppression systÃ©matique des propriÃ©tÃ©s calculÃ©es (`totalCount`, `maxCount`, `pages`, `wordCount`) avant l'envoi des mÃ©tadonnÃ©es pour Ã©viter les exceptions Entity Framework Core.
* **Mappage du Statut "TerminÃ©" MangaBaka (`scrapers/mangabaka.py`)** : Normalisation du statut brut `completed` de MangaBaka vers le statut interne `FINISHED` (les sÃ©ries terminÃ©es ne restent plus bloquÃ©es en "En cours").
* **Typo d'Attribut `BaseScraper` (`scrapers/base.py`)** : Correction de `eeds_api_key` en `needs_api_key`.

## [1.5.7] - 2026-07-25 (The Community Scrapers, Publisher QoS & Kavita OpenAPI Compliance Update)

EN
### âœ¨ New Features & QoS
* **Community Scrapers Sideloading (`data/scrapers/`)**: MetaKavita now dynamically loads and integrates external Python scrapers dropped directly into the user-mapped `data/scrapers/` folder without rebuilding the Docker image. Custom scrapers automatically benefit from UI API Key generation and SSRF protection.
* **Publisher Localization Preference**: Added a global setting and an elegant per-series segmented toggle (`Auto` | `VF/VA` | `VO`) to let users prioritize Localized/Translated publishers (e.g., *Viz Media*, *GlÃ©nat*) or Original publishers (e.g., *Shueisha*, *Kodansha*).
* **Title Translation Fallback (Experimental)**: Added an optional safety net that automatically translates unfound localized titles to English to perform a second search pass.

### ðŸ¦¸ Scraper Enhancements
* **MangaUpdates & MangaBaka Overhaul**: Upgraded parsers to actively categorize and extract both original and licensed publishers. Replaced standard `requests` in MangaUpdates with `curl_cffi` (`impersonate="chrome110"`) to seamlessly bypass Cloudflare anti-bot blocks.

### ðŸ› Critical Bug Fixes & Kavita OpenAPI Deep Compliance
* **Kavita `publishers` Schema Mismatch Fix (`app.py`, `kavita_api.py`)**: Corrected the publisher payload key to plural `publishers` expecting an array of `PersonDto` objects (`[{"id": 0, "name": "Publisher"}]`), resolving an issue where Kavita silently discarded incoming publishers.
* **C# Lock Guard 2-Pass Transaction Protocol (`kavita_api.py`)**: Implemented an automated 2-pass sequence (`*Locked: False` âž” write âž” `*Locked: True`) across all metadata updates. This forces Kavita's C# backend to overwrite fields previously locked in its SQLite database without returning silent false-positives.
* **Plural Staff Lock Keys Standardized (`app.py`)**: Corrected all staff lock property names to match Kavita's C# singular OpenAPI spec (`writerLocked`, `characterLocked`, `publisherLocked`, etc.), ensuring authors and characters remain permanently locked after sync.
* **Permanent Cover Upload & C# Filename Binding (`kavita_api.py`)**: Fixed an HTTP 500 (`Invalid Filename`) exception on `POST /api/Upload/series` by passing `fileName` with dynamic extension detection (`.jpg`, `.png`, `.webp`) and `lockCover: True` alongside pure Base64 payloads.
* **Endpoint & Payload Separation (`app.py`, `kavita_api.py`)**: Strictly routed `summary` to `POST /api/Series/metadata` and `localizedName`/`format` to `POST /api/Series/update`.

### ðŸ› ï¸ System, Code Health & Documentation
* **Bulletproof SQLite Schema Migrations (`db_manager.py`)**: Rewrote database initialization (`_ensure_schema`) to gracefully handle column additions one by one, preventing `sqlite3.OperationalError` crashes on container updates.
* **Custom Scraper Guide**: Added `CUSTOM_SCRAPERS.md` containing strict architecture rules and ready-to-use AI prompts ("Vibecoding") to build custom providers easily.

FR
### âœ¨ Nouvelles FonctionnalitÃ©s & QoS
* **Scrapers Communautaires PersonnalisÃ©s (`data/scrapers/`)** : MetaKavita charge dÃ©sormais dynamiquement les scripts Python dÃ©posÃ©s dans le volume utilisateur `data/scrapers/`. Permet d'ajouter des sites Ã  la volÃ©e sans recompiler l'image Docker.
* **PrÃ©fÃ©rence d'Ã‰diteur (VF/VA vs VO)** : Ajout d'une option globale et d'un interrupteur par sÃ©rie (`Auto` | `VF/VA` | `VO`) permettant de prioriser l'Ã©diteur localisÃ© (ex: *GlÃ©nat*, *Kurokawa*) ou l'Ã©diteur d'origine (ex: *Shueisha*, *Kodansha*).
* **Titre de Secours (Traduction Fallback ExpÃ©rimentale)** : Ajout d'un filet de sÃ©curitÃ© dÃ©sactivable traduisant automatiquement un titre non-trouvÃ© vers l'anglais pour relancer une seconde recherche sur les API internationales.

### ðŸ¦¸ AmÃ©liorations Scrapers
* **MangaUpdates & MangaBaka** : Mise Ã  jour des parseurs pour extraire, catÃ©goriser et trier les Ã©diteurs traduits et originaux. IntÃ©gration de `curl_cffi` (`impersonate="chrome110"`) sur MangaUpdates pour contourner les blocages anti-bot Cloudflare.

### ðŸ› Correctifs Critiques & ConformitÃ© OpenAPI Kavita
* **Correction du SchÃ©ma `publishers` (`app.py`, `kavita_api.py`)** : Correction du nom de variable pour utiliser `publishers` au pluriel avec un tableau de `PersonDto` (`[{"id": 0, "name": "Ã‰diteur"}]`), rÃ©solvant le problÃ¨me oÃ¹ Kavita rejetait silencieusement la maison d'Ã©dition.
* **Protocole C# Lock Guard Ã  2 Passages (`kavita_api.py`)** : ImplÃ©mentation d'une sÃ©quence automatique en 2 temps (`*Locked: False` âž” Ã©criture âž” `*Locked: True`) sur toutes les mises Ã  jour. Force le serveur C# de Kavita Ã  Ã©craser les champs dÃ©jÃ  verrouillÃ©s en base de donnÃ©es sans faire de faux-positifs.
* **Normalisation des Verrous au Singulier (`app.py`)** : Alignement de tous les verrous du staff sur le schÃ©ma OpenAPI de Kavita (`writerLocked`, `characterLocked`, `publisherLocked`, etc.), garantissant que les auteurs restent dÃ©finitivement verrouillÃ©s aprÃ¨s synchronisation.
* **Upload de Couverture Permanent & Fix Erreur 500 (`kavita_api.py`)** : RÃ©solution de l'exception HTTP 500 (`Invalid Filename`) sur `POST /api/Upload/series` grÃ¢ce Ã  l'envoi conjoint de `fileName` (avec extension dynamique `.jpg`, `.png`, `.webp`) et `lockCover: True` en Base64 pur.
* **SÃ©paration Stricte des Endpoints (`app.py`, `kavita_api.py`)** : Routage du rÃ©sumÃ© vers `POST /api/Series/metadata` et des gÃ©nÃ©ralitÃ©s (`localizedName`, `format`) vers `POST /api/Series/update`.

### ðŸ› ï¸ SystÃ¨me, QualitÃ© du Code & Documentation
* **Migrations SQLite SÃ©curisÃ©es (`db_manager.py`)** : Initialisation robuste (`_ensure_schema`) ajoutant les colonnes manquantes une par une pour empÃªcher les crashs HTTP 500 lors des mises Ã  jour du conteneur.
* **Guide Scrapers Communautaires** : Ajout du fichier `CUSTOM_SCRAPERS.md` contenant les rÃ¨gles d'architecture et les prompts IA (Vibecoding) pour crÃ©er facilement de nouveaux scrapers.

## [1.5.6] - 2026-07-24 (The Permanent Cover Upload Hotfix)

EN
### ðŸ› Bug Fixes
* **Pure Base64 Cover Payload (`kavita_api.py`)**: Fixed a critical bug (the "Phantom Cover" syndrome) where Kavita silently rejected image payloads, resulting in deleted covers upon hard browser refreshes. Removed the `Data URI` prefix (`data:image/jpeg;base64,...`) and reverted to pure Base64 strings, which allows Kavita's C# engine to correctly write and save the images permanently to the disk.

FR
### ðŸ› Correctifs
* **Payload Base64 Pur (`kavita_api.py`)** : RÃ©solution du bug critique des "couvertures fantÃ´mes" oÃ¹ Kavita rejetait silencieusement les images et finissait par les effacer du disque dur. Le payload a Ã©tÃ© corrigÃ© pour envoyer une chaÃ®ne Base64 pure (sans prÃ©fixe *Data URI*), ce qui permet au moteur C# de Kavita de lire les octets et d'enregistrer l'image de maniÃ¨re permanente.

## [1.5.5] - 2026-07-23 (The Deep Extraction, High-Speed Engine & Scoring Precision Update)

EN
### âš¡ High-Speed Engine & Throttling Overhaul
* **Smart Per-Provider Rate Limiter (`metadata_fetcher.py`)**: Replaced hardcoded worker sleep delays (`1.5s`/`2.5s`) with a timestamp-based dynamic throttler (`LAST_REQUEST_TIMES`). Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s.
* **Unrestricted Provider Forcing (`templates/index.html`, `metadata_fetcher.py`)**: Unlocked all registered scrapers in the Magic Input dropdown, allowing users to force any metadata source regardless of library type or search string.

### âœ¨ Deep Metadata Extraction & Unified Scoring Matrix
* **Deep Kavita Metadata Extraction (`kavita_api.py`, `app.py`)**: Pre-fetches existing metadata from Kavita's database (sanitized ISBNs, authors, publisher, release year, genres) before querying external APIs to anchor searches and prevent false positives.
* **Unified Weighted Scoring Matrix (`scrapers/utils.py`)**:
  * *ISBN Golden Rule*: Instant 100% confidence match on exact ISBN.
  * *Anti-Homonym Author Mismatch Rule*: Implemented a strict `-50%` penalty if a candidate's author differs from Kavita's context (e.g., preventing manga adaptations from matching classical novels).
  * *Roman Numeral Volume Converter*: Automatically converts Roman volume numbers (e.g. `Tome II` -> `Tome 2`) before evaluating similarity.
  * *Anti-Spin-Off & Guidebook Filters*: Added `-35%` penalty for missing distinctive query words (*Lanfeust des Ã‰toiles* vs *Troy*) and `-50%` penalty for noise keywords (`Guidebook`, `Fanbook`, `Artbook`).
  * *Volume 1 Anchoring*: Grants `+0.10` bonus to Volume 1/unnumbered editions while applying `-0.45` penalty to intermediate volumes.

### ðŸ¦¸ New Scrapers & Core Enhancements
* **ComicVine Refactor (`scrapers/comicvine.py`)**:
  * Switched volume queries to structured `/volumes/?filter=name:` endpoint with explicit `field_list`.
  * Weighted candidate selection favoring primary US/European publishers (`DC Comics`, `Marvel`, `Image`, `Dargaud`) and issue count while heavily penalizing foreign translation houses.
  * **Issue #1 Creator & Summary Fallback**: Automatically queries Issue #1 when a Volume lacks staff or description, boosting summary length from 39 chars to 3,500+ chars.
* **New Scraper Integrations**:
  * **Hardcover (Experimental)**: Hasura GraphQL & Typesense search engine for books and graphic novels (`curl_cffi` Chrome impersonation).
  * **MangaDex**: Official REST API v5 integration with content rating filters, native AniList/MAL ID extraction, and oneshot scoring.
  * **MangaUpdates**: Official REST API v1 scraper with `hit_title` matching and BBCode text cleaning.
  * **Manga-News**: Franco-Belgian & French catalog scraper (`curl_cffi`) for VF publishers and HD artwork.
  * **Shikimori**: Fast REST JSON scraper with multilingual title matching and dedicated `/roles` staff parsing.
  * **Open Library**: Literature and novel provider powered by Internet Archive.
* **Resiliency & Bug Fixes**:
  * **BÃ©dÃ©thÃ¨que**: Fixed duplicate method signature causing fatal `.get()` crashes on lists.
  * **MangaBaka**: Added `(data.get('authors') or [])` guards against null JSON keys causing `TypeError`.
  * **Kavita Cache Invalidation**: Dynamically clears `_series_lib_type_cache` on batch runs, recognizing updated library types (including ID 5 `Comic Flexible`) without container restarts.

FR
### âš¡ Moteur Haute Performance & Throttling Dynamique
* **Rate-Limiter Intelligente par Horodatage (`metadata_fetcher.py`)** : Remplacement des pauses fixes dans `app.py` par un rÃ©gulateur dynamique basÃ© sur `time.time()`. Les API inactives rÃ©pondent instantanÃ©ment sans attente artificielle, exÃ©cutant les Smart Fusions de 3 sources en ~1,6s.
* **ForÃ§age Libre des Fournisseurs (`templates/index.html`, `metadata_fetcher.py`)** : DÃ©blocage de l'ensemble des scrapers dans le menu dÃ©roulant du Champ Magique pour permettre le forÃ§age manuel de n'importe quelle source.

### âœ¨ Extraction Profonde & Matrice de Scoring
* **Extraction Profonde Kavita (`kavita_api.py`, `app.py`)** : RÃ©cupÃ©ration en amont des donnÃ©es existantes (ISBN, auteurs, Ã©diteur, annÃ©e) avant le scraping pour ancrer les recherches.
* **Matrice de Scoring UnifiÃ©e (`scrapers/utils.py`)** :
  * *RÃ¨gle d'or ISBN* : Match instantanÃ© Ã  100% sur ISBN exact.
  * *RÃ¨gle Anti-Homonyme Auteur* : PÃ©nalitÃ© de `-50%` si l'auteur du candidat diffÃ¨re de l'auteur dans Kavita.
  * *Convertisseur de Chiffres Romains* : Conversion automatique des tomes (`Tome II` -> `Tome 2`).
  * *Filtres Anti-Spin-Off & Anti-Guidebook* : PÃ©nalitÃ©s ciblÃ©es sur les mots-clÃ©s manquants (`-35%`) ou parasites (`-50%` pour `Guidebook`/`Fanbook`).
  * *Ancrage Tome 1* : Bonus de `+0.10` pour les Tomes 1 et pÃ©nalitÃ© de `-0.45` sur les tomes intermÃ©diaires.

### ðŸ¦¸ Nouveaux Scrapers & AmÃ©liorations Core
* **Refonte StructurÃ©e ComicVine (`scrapers/comicvine.py`)** :
  * Bascule sur l'endpoint structurÃ© `/volumes/?filter=name:` avec `field_list` explicite.
  * Priorisation des Ã©diteurs originaux majeurs (`DC Comics`, `Marvel`, `Image`, `Dargaud`) et pÃ©nalisation des traducteurs Ã©trangers.
  * RÃ©cupÃ©ration automatique du rÃ©sumÃ© et des auteurs sur l'Issue #1 si la fiche sÃ©rie est pauvre (rÃ©sumÃ©s propulsÃ©s de 39 Ã  3 500+ caractÃ¨res).
* **Nouveaux Scrapers IntÃ©grÃ©s** :
  * **Hardcover (ExpÃ©rimental)** : Moteur GraphQL Hasura & Typesense pour livres et BDs.
  * **MangaDex** : API v5 avec filtres adulte, IDs externes et scoring.
  * **MangaUpdates** : API v1 avec nettoyage BBCode et matching `hit_title`.
  * **Manga-News** : Catalogue VF (`curl_cffi`) pour Ã©diteurs franÃ§ais et couvertures HD.
  * **Shikimori** : API REST JSON multilingue avec extraction du staff via `/roles`.
  * **Open Library** : API LittÃ©rature d'Internet Archive.
* **Correctifs & StabilitÃ©** :
  * **BÃ©dÃ©thÃ¨que** : Correction de la mÃ©thode `fetch()` Ã©crasÃ©e par erreur.
  * **MangaBaka** : SÃ©curisation contre les clÃ©s `null` dans l'API JSON.
  * **Cache Kavita** : Purge automatique du cache au lancement des batchs pour reconnaÃ®tre les changements de types de bibliothÃ¨ques (ID 5 `Comic Flexible`) sans redÃ©marrer Docker.

## [1.5.4] - 2026-07-22 (The "Smart Override" & Network Flexibility Update)

EN
### âœ¨ New Features & Core Architecture
* **Enhanced Webhook Endpoint (`force` & Token Rotation)**: The `/webhook` endpoint now supports a `"force": true` (or `"force_update": true`) parameter in its JSON/Form payload, as well as via URL query string (`?force=true`), allowing external scripts to trigger forced metadata overwrites. Added a read-only Webhook URL input in the Config Modal with a one-click token regeneration button.
* **Reverse Proxy & Subpath Support (C17)**: Full native support for hosting MetaKavita under custom URL subpaths (e.g., `https://domain.com/metakavita`). Configurable via the `ROOT_PATH` environment variable or proxy headers (`X-Forwarded-Prefix`). Dynamically prefixes client AJAX calls and WebSocket (`Socket.IO`) connections while maintaining strict Same-Origin CORS security.
* **Disable Translation Option (BF6)**: Added a "Disabled (Keep original)" option to the Translation Provider dropdown, allowing users to preserve scraped descriptions in their original language without querying external translation APIs.
* **The "Magic Input" (Smart URL Routing)**: The old "AniList ID" override field has been completely replaced by a universal Magic Input. You can now paste a direct URL from *any* supported provider (e.g., `https://mangabaka.org/1234` or a ComicVine link) directly into the field. MetaKavita will automatically detect the domain, extract the ID, and bypass the default cascade to scrape that exact page!
* **Context-Aware Magic Dropdown**: The provider dropdown next to the Magic Input now dynamically filters its options based on the Kavita library type (e.g., hiding ComicVine for Mangas), preventing invalid manual forcing.
* **Smart ID Match Engine**: If you paste a raw numerical ID or slug and leave the dropdown on "AUTO", the system will query compatible providers and intelligently validate the match by comparing the fetched title with your Kavita title (>50% similarity required). False positives are automatically rejected and the cascade continues safely!
* **Granular Scraping (Targeted Fields)**: Worried about overwriting a summary you manually edited in Kavita? Each series now features a hidden "âš™ï¸ Targeted Fields" dropdown. You can granularly select exactly which data MetaKavita is allowed to update (Summary, Cover, Staff, Genres, Tags, Year, Status, Publisher, Age, Format, WebLinks, Alt Titles).
* **Self-Healing Configuration Engine**: MetaKavita now dynamically validates your search cascade. If you select a default provider that has been physically deleted from the `scrapers/` folder, the engine will automatically self-heal, warn you in the logs, and safely fallback to the next available scraper to prevent your batch queues from crashing.
* **Extended Kavita API Coverage**: The staff mapping engine has been expanded. MetaKavita now natively pushes `Editors`, `Letterers`, `Inkers`, and the localized `Language` directly into Kavita's database.

### ðŸ› Bug Fixes & UI Improvements
* **Google Books Stability & Anchor Match**: Refactored `googlebooks.py` to evaluate up to 10 search results using title similarity scoring (`calculate_similarity`). Implemented a Volume 1 / Band 1 priority anchor for novel series (such as *Perry Rhodan Neo*) to prevent random description shifts during batch re-syncs. Rejects candidates below 50% similarity to allow clean cascade fallback.
* **Re-integrated English Target Language**: Fixed an oversight where English (`EN`) was missing from the target translation language selection dropdown (`TARGET_LANG`).
* **Strict ID Routing**: Fixed a major bug where searching by ID would accidentally trigger title searches on fallback providers, causing chaotic metadata fusion. IDs and URLs are now strictly routed as pure ID queries exclusively to supported scrapers.
* **Alternative Titles Crash**: Fixed a fatal `TypeError` (`expected str instance, NoneType found`) that crashed the server when fusing alternative titles containing `None` values from incomplete APIs (like Kitsu).
* **Visual Feedback on Mass Actions**: The "Save All Overrides" button now features an active loading state (`â³ Saving in progress...`) and dynamically disables itself during processing to prevent UI freezing and server saturation.

FR
### âœ¨ Nouvelles FonctionnalitÃ©s & Architecture
* **Endpoint Webhook Enrichi (Option `force` & RÃ©gÃ©nÃ©ration de jeton)** : L'endpoint `/webhook` accepte dÃ©sormais un paramÃ¨tre `"force": true` (ou `"force_update": true`) dans son payload JSON/Form, ainsi que par paramÃ¨tre d'URL (`?force=true`), permettant aux scripts externes d'imposer un rÃ©-enrichissement forcÃ©. Ajout de l'affichage de l'URL Webhook dans la modal de configuration avec un bouton de rÃ©gÃ©nÃ©ration du jeton.
* **Support Reverse Proxy & Sous-dossiers / Subpath (C17)** : Support natif complet pour le dÃ©ploiement derriÃ¨re un sous-chemin d'URL (ex: `https://domaine.com/metakavita`). Configurable via la variable d'environnement `ROOT_PATH` ou les en-tÃªtes proxy (`X-Forwarded-Prefix`). Adapte dynamiquement les requÃªtes AJAX et le tunnel WebSocket (`Socket.IO`) tout en conservant la sÃ©curitÃ© CORS Same-Origin.
* **Option de DÃ©sactivation de la Traduction (BF6)** : Ajout d'une option "DÃ©sactivÃ© (Conserver l'original)" dans le sÃ©lecteur de traduction pour sauvegarder les rÃ©sumÃ©s dans leur langue d'origine sans faire appel aux API externes.
* **Le "Champ Magique" (Routage URL Intelligent)** : L'ancien champ d'ID AniList a Ã©tÃ© remplacÃ© par un champ universel. Vous pouvez dÃ©sormais coller l'URL directe d'une Å“uvre provenant de *n'importe quel* fournisseur supportÃ© (ex: une URL BÃ©dÃ©thÃ¨que ou MangaBaka). MetaKavita dÃ©tectera automatiquement le domaine, extraira l'ID et contournera la cascade pour scraper cette page prÃ©cise !
* **Menu DÃ©roulant Contextuel** : Le menu de forÃ§age de fournisseur Ã  cÃ´tÃ© du champ magique s'adapte dÃ©sormais dynamiquement au type de bibliothÃ¨que Kavita (ex: masquage de ComicVine pour les Mangas), Ã©vitant les erreurs de forÃ§age.
* **Moteur "Smart ID Match"** : Si vous saisissez un ID brut (ou slug) en laissant le fournisseur sur "AUTO", le systÃ¨me interrogera les sites compatibles et validera les rÃ©sultats en comparant le nom de la sÃ©rie Kavita avec le nom trouvÃ© par l'API (nÃ©cessite >50% de ressemblance). Les faux positifs sont rejetÃ©s et la cascade continue !
* **Scraping Granulaire (Champs CiblÃ©s)** : Peur d'Ã©craser un rÃ©sumÃ© que vous avez tapÃ© Ã  la main dans Kavita ? Chaque sÃ©rie dispose dÃ©sormais d'un menu "âš™ï¸ Champs CiblÃ©s". Vous pouvez cocher/dÃ©cocher individuellement les 12 mÃ©tadonnÃ©es que MetaKavita est autorisÃ© Ã  modifier.
* **Auto-RÃ©paration de la Configuration (Self-Healing)** : MetaKavita valide dynamiquement votre cascade de recherche. Si un fournisseur par dÃ©faut a Ã©tÃ© supprimÃ© physiquement du dossier `scrapers/`, le moteur s'auto-rÃ©pare, le signale dans les logs, et bascule sur le premier scraper disponible pour empÃªcher le crash de vos files d'attente.
* **Couverture API Kavita Ã‰tendue** : Le moteur de mapping du staff a Ã©tÃ© complÃ©tÃ©. MetaKavita reconnait et envoie dÃ©sormais les `Ã‰diteurs` (Staff), `Lettreurs`, `Encreurs`, ainsi que la `Langue` de localisation Ã  Kavita.

### ðŸ› Corrections de Bugs & AmÃ©liorations UI
* **Stabilisation & Ancrage Google Books** : Refonte de `googlebooks.py` pour Ã©valuer jusqu'Ã  10 rÃ©sultats via un score de similaritÃ© (`calculate_similarity`). Ajout d'un ancrage prioritaire sur le Tome 1 / Band 1 pour les sÃ©ries de romans (ex: *Perry Rhodan Neo*) afin d'Ã©viter le changement alÃ©atoire de rÃ©sumÃ© lors des re-synchronisations. Rejet des rÃ©sultats <50% de similaritÃ© pour basculer proprement sur la suite de la cascade.
* **RÃ©intÃ©gration de l'Anglais en Langue Cible** : Correction d'un oubli oÃ¹ l'anglais (`EN`) manquait dans la liste dÃ©roulante des langues de traduction (`TARGET_LANG`).
* **Routage Strict des IDs** : RÃ©solution d'un bug critique oÃ¹ la recherche par ID dÃ©clenchait accidentellement une recherche par titre sur les fournisseurs de secours, crÃ©ant des fusions de mÃ©tadonnÃ©es chaotiques. Les URLs et IDs sont dÃ©sormais strictement routÃ©s.
* **Crash des Titres Alternatifs** : Correction d'une erreur fatale `TypeError` (`expected str instance, NoneType found`) qui faisait crasher le serveur lors de la fusion de titres alternatifs contenant des valeurs `None` (souvent renvoyÃ©es par Kitsu).
* **Feedback Visuel de Masse** : Le bouton "Tout sauvegarder d'un coup" affiche dÃ©sormais un Ã©tat de chargement dynamique (`â³ Sauvegarde en cours...`) et se verrouille le temps du traitement pour Ã©viter de saturer le serveur ou de freezer l'interface.

## [1.5.2] - 2026-07-21 (The Plug & Play Architecture Update)

EN
### ðŸ› Bug Fixes & Refinements
* **Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly. The system now dynamically filters active scrapers based on the Kavita `library_type` (e.g., Manga, Comic) and passes this context to adapt the title cleaning rules (fixing the `unexpected keyword argument` crash).
* **BÃ©dÃ©thÃ¨que Spin-off Override Bug**: Fixed an issue where searching for a main series (e.g., "La QuÃªte d'Ewilan") would return covers from its spin-offs (e.g., "Ellana") due to BÃ©dÃ©thÃ¨que's alphabetical sorting. Implemented an exact-match logic that delays the loop-break, evaluating all title variations (with and without articles) to guarantee the parent series is pushed to the top of the results.

### ðŸ§± Plug & Play Scraper Architecture
* **Auto-Discovery Registry**: Refactored the core engine to use a Registry pattern (`ScraperRegistry`). Scrapers are now dynamically loaded from the `scrapers/` folder on startup. Adding a new provider is now as simple as dropping a `.py` file.
* **Standardized Base Interface**: Introduced the `BaseScraper` abstract class, enforcing a strict contract (ID, display name, supported library types, rate limits, and proxy domains) for all metadata providers.
* **Dynamic UI Generation**: The global configuration modal (`index.html`) and the provider cascading logic now dynamically generate dropdowns and fallback rules based on currently active scrapers. No more hardcoding!
* **Decoupled Utilities**: Extracted `clean_title` logic into a dedicated `scrapers/utils.py` module to ensure adherence to the Single Responsibility Principle and prevent circular dependencies.

### New Provider: BÃ©dÃ©thÃ¨que Scraper
* **Full Integration**: Added a dedicated scraper for BÃ©dÃ©thÃ¨que, heavily optimized for Franco-Belgian Comics.
* **Anti-Bot & CSRF Bypass**: Leveraged `curl_cffi` and dynamic CSRF token extraction (`csrf_token_bel`) to seamlessly bypass BÃ©dÃ©thÃ¨que's aggressive anti-scraping firewalls.
* **Smart Summary Recovery**: BÃ©dÃ©thÃ¨que often leaves Series descriptions empty. The scraper intelligently falls back to the Tome 1 (Album) summary, and utilizes SEO `og:description` meta tags as a bulletproof extraction method if HTML structures change.
* **Surgical Staff Parsing**: Automatically identifies roles (ScÃ©nario, Dessin, Couleurs) and reformats author names from "Lastname, Firstname" to "Firstname Lastname" for a pristine display in Kavita.

ðŸ‡«ðŸ‡·
### ðŸ› Corrections de Bugs & AmÃ©liorations
* **Recherche de Couvertures Contextuelle** : Correction d'une rÃ©gression oÃ¹ la recherche manuelle d'images interrogeait tous les fournisseurs Ã  l'aveugle. Le systÃ¨me filtre dÃ©sormais dynamiquement les scrapers selon le type de bibliothÃ¨que (`Manga`, `Comic`, `Book`) et transmet ce contexte pour adapter le nettoyage du titre (ce qui corrige au passage l'erreur fatale `unexpected keyword argument`).
* **Bug d'Ã‰crasement par les Spin-offs (BÃ©dÃ©thÃ¨que)** : RÃ©solution d'un problÃ¨me oÃ¹ la recherche d'une sÃ©rie principale (ex: "La QuÃªte d'Ewilan") renvoyait les couvertures de son spin-off (ex: "Ellana") Ã  cause du tri alphabÃ©tique natif de BÃ©dÃ©thÃ¨que. Ajout d'une logique de "match exact" qui Ã©value toutes les variations de titres (gestion des articles "Le", "La") pour garantir que la sÃ©rie mÃ¨re remonte en premiÃ¨re position.

### ðŸ§± Architecture Scraper "Plug & Play"
* **DÃ©couverte Automatique (Registry)** : Refonte totale du cÅ“ur de l'application avec un pattern Registre (`ScraperRegistry`). Les scrapers sont dÃ©sormais chargÃ©s dynamiquement au dÃ©marrage depuis le dossier `scrapers/`. Ajouter un nouveau site se rÃ©sume Ã  glisser un fichier python. Fin du hardcoding !
* **Interface StandardisÃ©e** : CrÃ©ation de la classe abstraite `BaseScraper` qui impose un contrat strict (ID, nom public, types de bibliothÃ¨ques supportÃ©s, dÃ©lais entre requÃªtes, domaines proxy anti-SSRF) Ã  tous les fournisseurs.
* **GÃ©nÃ©ration Dynamique de l'UI** : Les menus dÃ©roulants de la modale de configuration et le routage interne s'adaptent dÃ©sormais dynamiquement aux scrapers dÃ©tectÃ©s par le systÃ¨me.
* **Utilitaires DÃ©couplÃ©s** : DÃ©placement de la fonction de nettoyage `clean_title` vers un module autonome `scrapers/utils.py` pour un code plus propre et sans dÃ©pendances circulaires.

### ðŸ‡«ðŸ‡· Nouveau Fournisseur : BÃ©dÃ©thÃ¨que
* **IntÃ©gration BÃ©dÃ©thÃ¨que** : Ajout d'un scraper ultra-spÃ©cialisÃ© pour la base de donnÃ©es de rÃ©fÃ©rence de la bande dessinÃ©e franco-belge.
* **Contournement Anti-Bot (CSRF)** : Utilisation de `curl_cffi` et rÃ©cupÃ©ration Ã  la volÃ©e des jetons de sÃ©curitÃ© HTTP (`csrf_token_bel`) pour esquiver les pare-feux et blocages IP restrictifs de BÃ©dÃ©thÃ¨que.
* **RÃ©cupÃ©ration Intelligente des RÃ©sumÃ©s** : La page "SÃ©rie" est souvent vide sur BÃ©dÃ©thÃ¨que. Le scraper est conÃ§u pour piocher intelligemment le rÃ©sumÃ© sur l'Album (Tome 1) en cas d'Ã©chec. Il utilise Ã©galement la balise SEO `og:description` comme mÃ©thode de secours absolue pour garantir un rÃ©sultat.
* **Parsing Chirurgical du Staff** : Extraction prÃ©cise des rÃ´les (ScÃ©nario, Dessin, Couleurs) et reformatage automatique des noms d'auteurs ("Nom, PrÃ©nom" devient "PrÃ©nom Nom") pour un affichage esthÃ©tique dans Kavita.

## [1.5.0] - 2026-07-20 (The Multi-Media & Resiliency Update)

EN
### ðŸš€ Kitsu Integration & Provider Purge
* **Kitsu JSON:API Integration**: Added `scrapers/kitsu.py` using the free, open, and blazing-fast Kitsu API (no API key required). It fetches incredibly rich metadata and completely replaces our initial tests with MyAnimeList/Jikan (which suffered from heavy 504 Gateway Timeouts).
* **Nautiljon Purge**: Due to highly aggressive Cloudflare IP banning policies and an archaic anti-scraping stance, Nautiljon has been completely removed from the default provider cascades and routing maps.

### ðŸŒ Zero-Config Translation & Resilient Pipeline
* **Zero-Config Google Translate**: Integrated `py-googletrans` (v4.0.0-rc1) to provide 100% free, unlimited translations out of the box without requiring any API keys. Azure and DeepL remain available for enterprise-grade stability, but Google Translate acts as the ultimate magic fallback.
* **Azure & DeepL Integration**: Integrated Microsoft Azure Translator as the primary translation engine (2M characters/month F0 free tier) with DeepL as an automatic fail-safe fallback in case of HTTP 403, 429, or 456 quota exceptions.
* **Azure Translator Hardening**: Added explicit payload and HTTP response debug logging to easily diagnose Microsoft Azure API rejections.

### ðŸŽ¨ Translation UI & Settings Reorganization
* **Dynamic Translation Provider UI**: Added a clean dropdown in the settings modal to select the active translation engine (Google, Azure, DeepL). Irrelevant API key fields are now dynamically hidden to reduce UI clutter.
* **Settings Modal Reorganization**: Improved the Global Configuration layout using semantic CSS columns to neatly group Provider API Keys under Kavita's connection settings.

### ðŸ§© Dynamic Routing & Scraper Factory
* **Scraper Factory Pattern**: Refactored `PROVIDERS_MAP` in `metadata_fetcher.py` into a nested map structure indexed by Kavita's exact library types (`Manga`, `Comic`, `Book`). Implemented a resilient fallback system in `get_scraper_engine` to handle mismatched requests.
* **Kavita Library Type Extraction**: Updated `kavita_api.py` to extract the `type` property of libraries and map them to standard string representations (`Manga`, `Comic`, `Book`). Added an in-memory cache to prevent redundant API calls during batch syncing.
* **Global Server Batch Support**: Enhanced `/batch-sync` execution to allow full server syncing. If no specific library is selected, the system dynamically iterates through all libraries and routes them according to their individual library types.

### ðŸ¦¸ Hybrid ComicVine Scraper (Ultimate)
* **Two-Step Resolution Flow**: Implemented `scrapers/comicvine.py` using a dual-request approach (Volume Search âž¡ï¸ Fallback to Issue Search âž¡ï¸ Resolve Parent Volume âž¡ï¸ Fetch detailed metadata) to resolve French/European BD albums.
* **String Similarity Validator**: Integrated a hybrid scoring engine (`difflib.SequenceMatcher` + Token intersection) to strictly validate search results and drastically reduce false-positive matches on vaguely similar titles.
* **In-Memory Homonym Recovery**: Designed an automatic fallback search that sorts homonym volumes by issue count and pulls metadata from highly populated entries (e.g. Gaston 2009) if the resolved entry is an empty reissue stub.
* **Noisy HTML Pruning**: Added a custom HTML stripper to automatically delete structural wiki sections ("Publishers", "Collected Editions") that cluttered the final summary.
* **Komf-Aligned Credits Mapping**: Standardized artist and author role matching (`person_credits`) to align with Komf's mapping rules, populating Kavita's extended staff fields.

### ðŸ“– Production Google Books Scraper
* **Full Implementation**: Replaced the testing stub with a production-ready Google Books API scraper to fetch rich metadata for Novels and Western/European Comics (ISBN-compatible).
* **Dynamic Internationalization**: Google Books searches (`langRestrict`) are now dynamically bound to the user's `TARGET_LANG` configuration, ensuring native language summaries whenever possible.
* **API Key Support**: Added `GOOGLEBOOKS_API_KEY` to the global configuration to prevent HTTP 429 (Too Many Requests) limits on self-hosted instances.

### ðŸ§¹ Contextual Title Cleaning
* **Clean Title Contexts**: Adapted `clean_title` to clean queries based on library types. Comics/BDs safely strip noise leading zeros (e.g., `04 ` or `04 - `) while preserving issue/tome numbering. Books isolate `"Title - Author"` splits cleanly.

### ðŸ› Bug Fixes
* **Metadata Corruption Lock (Age & Format)**: Fixed a logic bug in `app.py` where `ageRatingLocked` and `formatLocked` were forcefully applied to Kavita even when scrapers returned unmapped/unknown values, which silently erased existing database values.
* **MangaBaka Silent Crash**: Fixed a `NoneType` iteration bug that silently killed the Smart Completion fusion when MangaBaka returned null tags.
* **Auto-Reading Direction Deduction**: MangaBaka now safely and intelligently deduces the Reading Format (Manga vs Webtoon) by inspecting its own tags/genres if the API doesn't explicitly provide it.
* **Env Var Override Lock**: Fixed an issue where Docker environment variables (like `ADMIN_PASSWORD`) would override the user's manual UI changes upon container restart. `config.json` now acts as the absolute source of truth.
* **Hard Logout Cleansing**: Secured the `/logout` route to physically destroy the session cookie (`expires=0`) on the client side, ensuring a clean re-authentication state.

FR
### ðŸš€ IntÃ©gration de Kitsu & Purge de Nautiljon
* **IntÃ©gration Kitsu JSON:API** : Ajout de `scrapers/kitsu.py` exploitant l'API publique de Kitsu (sans clÃ© requise et ultra-rapide). RÃ©cupÃ¨re des mÃ©tadonnÃ©es riches et remplace nos essais avortÃ©s avec MyAnimeList/Jikan (qui souffrait d'erreurs 504 en boucle).
* **Retraite de Nautiljon** : Face aux bannissements IP abusifs et imprÃ©visibles de leur pare-feu Cloudflare, Nautiljon a Ã©tÃ© totalement Ã©radiquÃ© du routage et des cascades par dÃ©faut.

### ðŸŒ Google Translate "Zero-Config" & RÃ©silience
* **Google Translate (Gratuit)** : IntÃ©gration de `py-googletrans` (v4.0.0-rc1) offrant des traductions 100% gratuites et illimitÃ©es dÃ¨s l'installation, sans aucune clÃ© d'API requise. Azure et DeepL restent disponibles pour une stabilitÃ© maximale, mais Google prendra le relais de maniÃ¨re transparente !
* **IntÃ©gration d'Azure & DeepL** : Ajout de Microsoft Azure Translator comme moteur principal (F0, 2M de caractÃ¨res gratuits par mois) avec bascule automatique vers DeepL en cas d'erreur de quota.
* **Fiabilisation Azure Translator** : Ajout de logs de diagnostic explicites (taille du payload, rÃ©gion, requÃªtes brutes) pour tracer et comprendre instantanÃ©ment les rejets de l'API Microsoft.

### ðŸŽ¨ UI du Traducteur & RÃ©organisation
* **SÃ©lecteur Dynamique de Traduction** : Ajout d'un menu dÃ©roulant intuitif dans la configuration pour choisir son moteur de traduction (Google, Azure, DeepL). Les champs de clÃ©s API inutiles sont masquÃ©s dynamiquement pour Ã©purer l'interface.
* **RÃ©organisation de la Modal** : AmÃ©lioration de la grille CSS pour regrouper proprement les clÃ©s d'API des fournisseurs de mÃ©tadonnÃ©es juste sous les identifiants Kavita.

### ðŸ§© Routage Dynamique & Scraper Factory
* **Architecture Scraper Factory** : Restructuration de `PROVIDERS_MAP` en dictionnaire imbriquÃ© indexÃ© par type exact de bibliothÃ¨que Kavita (`Manga`, `Comic`, `Book`). ImplÃ©mentation d'un systÃ¨me de repli rÃ©silient vers les mangas en cas d'erreur.
* **DÃ©tection du Type de BibliothÃ¨que** : Extraction de la propriÃ©tÃ© `type` des bibliothÃ¨ques Kavita avec mise en cache mÃ©moire pour optimiser les appels d'API.
* **Support du Batch Global** : AmÃ©lioration de la file d'attente `/batch-sync` pour lancer une synchronisation Ã  l'Ã©chelle du serveur entier. En l'absence de sÃ©lection, le systÃ¨me traite l'intÃ©gralitÃ© du serveur en appliquant le routage dynamique Ã  la volÃ©e.

### ðŸ¦¸ Scraper ComicVine Hybride (Ultime)
* **Recherche en Deux Ã‰tapes** : Interrogation des volumes, puis des issues (albums) en cas d'Ã©chec pour remonter vers la sÃ©rie parente. RÃ©sout les albums franco-belges orphelins.
* **Validateur de SimilaritÃ©** : ImplÃ©mentation d'un algorithme de score hybride (`difflib` + intersection de mots-clÃ©s) pour Ã©carter rigoureusement les faux-positifs lors des recherches floues de l'API.
* **RÃ©solution d'Homonymes Vides** : Tri des homonymes par nombre de tomes dÃ©croissant pour extraire la description d'une Ã©dition majeure rÃ©digÃ©e si l'Ã©dition active est vide.
* **Nettoyage HTML Anti-Bruit** : Suppression automatique des sections wiki structurelles (Ã‰diteurs, Ã‰ditions compilÃ©es, etc.) qui polluaient le rÃ©sumÃ© final.
* **Mappage de Staff** : Normalisation de la rÃ©cupÃ©ration du staff crÃ©ateur pour alimenter proprement les rÃ´les dans Kavita (ScÃ©nario, Dessin, Couleur, etc.).

### ðŸ“– Scraper Google Books de Production
* **ImplÃ©mentation ComplÃ¨te** : Remplacement du bouchon de test par un scraper Google Books officiel, capable d'enrichir les Romans et les BD europÃ©ennes (via la catÃ©gorie Comic).
* **Internationalisation Dynamique** : Les recherches Google Books (`langRestrict`) s'adaptent dÃ©sormais automatiquement Ã  la `Langue de traduction` choisie par l'utilisateur pour trouver la bonne Ã©dition.
* **Support de ClÃ© API** : Ajout du champ `GOOGLEBOOKS_API_KEY` pour Ã©viter l'erreur HTTP 429 (Trop de requÃªtes) inhÃ©rente aux serveurs auto-hÃ©bergÃ©s.

### ðŸ§¹ Nettoyage Contextuel de Titres
* **Nettoyage Adaptatif** : Ajustement de `clean_title` selon le format du mÃ©dia. La catÃ©gorie Comics nettoie proprement les prÃ©fixes de tri sans casser les Å“uvres aux noms chiffrÃ©s. Les romans isolent les structures `"Titre - Auteur"`.

### ðŸ› Corrections de Bugs
* **Corruption de MÃ©tadonnÃ©es Kavita** : Correction d'un bug critique dans `app.py` oÃ¹ les champs `ageRatingLocked` et `formatLocked` Ã©taient verrouillÃ©s Ã  vide si un scraper renvoyait une valeur inconnue, Ã©crasant ainsi les donnÃ©es prÃ©existantes de Kavita.
* **Crash Silencieux MangaBaka** : RÃ©solution d'une erreur `NoneType` qui annulait silencieusement la fusion intelligente (Smart Completion) lorsque l'API renvoyait des tags vides.
* **Sens de Lecture Automatique** : Le scraper MangaBaka dÃ©duit dÃ©sormais intelligemment le format de lecture (Webtoon vs Manga) en analysant ses propres mots-clÃ©s.
* **Verrouillage des Variables d'Environnement** : Correction d'un bug oÃ¹ les variables Docker (ex: `ADMIN_PASSWORD`) Ã©crasaient la configuration de l'utilisateur au redÃ©marrage. Le fichier `config.json` a dÃ©sormais la prioritÃ© absolue.
* **Nettoyage de Session** : SÃ©curisation de la route `/logout` qui force dÃ©sormais l'expiration physique du cookie de session cÃ´tÃ© navigateur.

---

## [1.4.0] - 2026-07-19 (Ergonomic Revolution & Total UI Overhaul)

EN
### ðŸŽ¨ Major UI & Ergonomics Overhaul
* **Settings Modal**: Moved all infrastructure and technical configuration inputs (Kavita URL/API, DeepL API, languages, auto-sync, fallback providers) into a clean, dedicated overlay Modal, completely uncluttering the left sidebar.
* **Scraping Strategy Sidebar**: Kept runtime scraping options (Smart Completion, Auto-Cover, Auto-Reading Direction, Force Update) directly visible in the left sidebar for instant workflow changes before batch sync.
* **Unified Central Toolbar**: Merged the library selector (`#lib_selector`) into the central toolbar alongside search and status filters. Searching, status filtering, and library switching are now in one unified horizontal line.
* **Consolidated Mass Execution Block**: Aligned the "Reset Errors / Amnistie" button inside the bottom batch action block, grouping all mass-level executions in a single clean row.
* **Search Input Specificity**: Constrained the search input's width using high-specificity CSS selectors, preventing overlap with the global save button on large screens.

### ðŸ“ Added Ergonomic Features
* **Manual Cover Search**: Added a manual search bar inside the cover selection modal, allowing users to type and search alternate titles without closing the modal or modifying overrides.
* **Live Processing Highlight**: WebSocket logs now trigger an active glowing border/background animation (`.is-processing`) and automatically scroll the series currently being processed into view. Statut badges are updated live without page reload.
* **Workspace Persistence**: Filter selections (Library, Status, Search string, Hide Ignored state) are now saved automatically inside `localStorage` and restored upon loading the dashboard.
* **Quick ID Lookup**: Added a lookup magnifying button next to the AniList ID input field, opening a pre-filled AniList search in a new tab.

### ðŸ› Bug Fixes
* Fixed an issue where completed or skipped series during batch runs displayed an `undefined` status badge inside the interface.

FR
### ðŸŽ¨ Refonte Majeure de l'UI & Ergonomie
* **Modal de Configuration**: DÃ©placement de toute la configuration technique et d'infrastructure (URL/API Kavita, API DeepL, langues, auto-sync, cascade de fournisseurs) dans une modal d'administration dÃ©diÃ©e, aÃ©rant complÃ¨tement la barre latÃ©rale.
* **Options StratÃ©giques Visibles**: Conservation des cases d'exÃ©cution de scraping (fusion, sens de lecture, covers, mise Ã  jour forcÃ©e) directement accessibles dans la barre latÃ©rale gauche pour un ajustement Ã  la volÃ©e.
* **Toolbar Centrale UnifiÃ©e**: IntÃ©gration du sÃ©lecteur de bibliothÃ¨que directement dans la barre d'outils centrale. Le ciblage, le filtrage et la recherche s'effectuent dÃ©sormais sur une seule et mÃªme ligne horizontale.
* **Grille d'Actions de Masse**: Alignement du bouton Â« Amnistie des erreurs Â» au bas de l'Ã©cran avec les autres boutons d'actions par lots (Lancer, Ignorer, ArrÃªter) pour une meilleure cohÃ©rence.
* **Taille de la barre de recherche**: Limitation Ã©tanche de la largeur de l'input de recherche pour Ã©viter tout chevauchement ou Ã©tirement inesthÃ©tique contre le bouton de sauvegarde.

### ðŸ“ FonctionnalitÃ©s d'Ergonomie IntÃ©grÃ©es
* **Recherche Manuelle de Couvertures**: Ajout d'une barre de recherche interne dans la modal des couvertures pour interroger les bases de donnÃ©es avec d'autres titres Ã  la volÃ©e.
* **Suivi de Traitement Live**: Les logs WebSocket dÃ©clenchent une animation de pulsation lumineuse violette (`.is-processing`) sur la ligne de la sÃ©rie active et la font dÃ©filer automatiquement Ã  l'Ã©cran. Les badges de statut se mettent Ã  jour en direct.
* **Persistance de l'Espace de Travail**: Sauvegarde automatique de tes filtres (BibliothÃ¨que, Recherche, Statut, IgnorÃ©s) dans le `localStorage` pour retrouver ton tableau de bord identique aprÃ¨s fermeture.
* **Recherche d'ID Rapide (Quick Lookup)**: Ajout d'un bouton loupe Ã  cÃ´tÃ© du champ de saisie d'ID AniList pour ouvrir directement une recherche prÃ©-remplie dans un nouvel onglet.

### ðŸ› Corrections de Bugs
* Correction d'un bug d'affichage oÃ¹ le badge de statut affichait la valeur textuelle `undefined` lors des sauts de sÃ©ries dÃ©jÃ  enrichies durant un batch.

---

## [1.3.2] - 2026-07-19 (Security & Metadata Overhaul)

EN
### ðŸ›¡ï¸ Major Security Audit
* **WSGI Production Server:** Dropped Werkzeug in favor of a robust Gunicorn + Eventlet architecture for production readiness.
* **Global Authentication:** The dashboard can now be locked using the `ADMIN_PASSWORD` Docker variable. Features strict immunity against Timing Attacks (`secrets.compare_digest`) and Brute-Force delays.
* **SSRF Proxy Protection:** The image proxy is now locked behind a strict domain Whitelist (`ALLOWED_PROXY_DOMAINS`), ignoring port bypasses.
* **Webhook Hardening:** Webhook calls are now secured via a cryptographically generated `WEBHOOK_TOKEN`, making it safe to use behind Reverse Proxies.
* **Hidden API Keys:** API keys are physically hidden from the DOM / HTML source code and preserved safely upon saving other settings.

### ðŸ§© Ultimate Regex Cleaner
* **Centralized Logic:** Title cleaning logic is now decoupled in `scrapers/__init__.py`.
* **Advanced Stripping:** The engine strips stray dots, `[Team]` prefixes, edition keywords (`Omnibus`, `Perfect Edition`), and volume numbers (`01 - Title`), improving the API match rate.

### ðŸ“š Extended Kavita Metadata
* **Rich Staff & Lore:** MetaKavita now pushes Publishers, Age Ratings, Colorists, Translators, and Cover Artists to Kavita.
* **External IDs & WebLinks:** Automatically populates Kavita's native `AniListId`, `MalId`, and `MangaBakaId`. Auto-generates clickable UI WebLinks to display official provider icons right under the manga title!
* **Reading Direction:** New toggle to automatically adapt the reading direction (Manga, Webtoon, Comic) based on the country of origin.

### ðŸŽ¨ UI Improvements
* **AJAX Search Bar:** Find any series instantly without scrolling.

FR
### ðŸ›¡ï¸ Audit de SÃ©curitÃ© Majeur
* **Serveur de Production WSGI :** Abandon de Werkzeug au profit d'une architecture Gunicorn + Eventlet robuste.
* **Authentification Globale :** L'interface peut Ãªtre verrouillÃ©e via la variable `ADMIN_PASSWORD`. Inclut une immunitÃ© contre les attaques temporelles et un dÃ©lai anti-force-brute.
* **Protection Proxy SSRF :** Le proxy d'images est verrouillÃ© par une liste blanche dynamique, insensible aux contournements par port.
* **Webhook SÃ©curisÃ© :** Les appels Webhook exigent dÃ©sormais un `WEBHOOK_TOKEN` cryptographique, sÃ©curisant l'usage derriÃ¨re un Reverse Proxy.
* **ClÃ©s API Invisibles :** Les clÃ©s API n'apparaissent plus dans le code source HTML (DOM).

### ðŸ§© Nettoyeur Regex Ultime
* **Logique CentralisÃ©e :** Le nettoyage des titres est dÃ©sormais un module indÃ©pendant (`scrapers/__init__.py`).
* **Filtrage AvancÃ© :** Le moteur supprime les points, les prÃ©fixes de scantrad, les mots-clÃ©s (`IntÃ©grale`, `Deluxe Edition`) et les numÃ©ros de dossiers complexes, propulsant le taux de rÃ©ussite des API.

### ðŸ“š MÃ©tadonnÃ©es Kavita Ã‰tendues
* **Staff et DÃ©tails :** MetaKavita gÃ¨re dÃ©sormais les Ã‰diteurs, la classification d'Ã‚ge, les Coloristes, Traducteurs, et Artistes de Couverture.
* **IDs et Liens Externes :** Remplissage automatique des champs `AniListId`, `MalId`, et `MangaBakaId`. GÃ©nÃ©ration de WebLinks cliquables pour afficher les icÃ´nes officielles dans Kavita !
* **Sens de Lecture :** Nouvelle option permettant d'adapter automatiquement le sens de lecture (Manga, Webtoon) selon l'origine de l'Å“uvre.

### ðŸŽ¨ AmÃ©liorations UI
* **Barre de recherche AJAX :** Filtrez vos centaines de sÃ©ries instantanÃ©ment en temps rÃ©el.