// --- HELPERS PARTAGÉS ---
// Chargé en premier : toutes les autres fonctions du frontend (fetch vers l'API,
// Socket.IO) dépendent de getRootPath() pour fonctionner correctement derrière
// un reverse-proxy avec sous-chemin (voir ROOT_PATH côté serveur, app.py).

// Fonction de secours pour garantir que le root_path existe toujours
const getRootPath = () => window.ROOT_PATH || '';

/**
 * Échappement HTML unique du frontend.
 *
 * L'apostrophe compte autant que le guillemet double : plusieurs gabarits
 * construisent des attributs en quotes simples (`onclick='...'`, `title='...'`),
 * qu'un titre de série contenant une apostrophe suffirait à refermer. Les
 * modules gardent un alias local (`esc`, `escapeHtml`, `_escHtml`) mais tous
 * délèguent ici : quatre implémentations divergentes, dont deux incomplètes,
 * avaient déjà laissé passer ce cas.
 */
function escapeHtmlText(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
window.escapeHtmlText = escapeHtmlText;

var _appToastTimer = null;
function showAppToast(msg) {
    var el = document.getElementById('appToast')
        || document.getElementById('batchQueueToast');
    if (!el || !msg) return;
    el.textContent = String(msg);
    el.hidden = false;
    clearTimeout(_appToastTimer);
    _appToastTimer = setTimeout(function () { el.hidden = true; }, 3200);
}
window.showAppToast = showAppToast;

/**
 * URL d'affichage navigateur pour une couverture externe.
 * Les scrapers avec `requires_proxy=True` bloquent le hotlink : l'<img> doit
 * passer par `/api/proxy-image` (Referer serveur). L'URL stockée / envoyée à
 * Kavita reste la vraie URL CDN — ne pas persister le résultat.
 *
 * Hôtes : `window.PROXY_COVER_HOSTS` (injecté depuis le registre scrapers) +
 * fallback hardcodé pour pages sans injection.
 */
function toDisplayCoverUrl(url) {
    if (!url || typeof url !== 'string') return '';
    const trimmed = url.trim();
    if (!trimmed) return '';
    // Déjà un chemin proxy (absolu ou relatif)
    if (trimmed.indexOf('/api/proxy-image?') !== -1) return trimmed;
    if (!/^https?:\/\//i.test(trimmed)) return '';
    let host;
    try {
        host = new URL(trimmed).hostname.toLowerCase();
    } catch (e) {
        return '';
    }
    const fallbackHosts = [
        'uploads.mangadex.org', 'mangadex.org',
        'static.comicvine.com', 'comicvine.gamespot.com',
        'cdn.anime-planet.com', 'anime-planet.com', 'www.anime-planet.com',
    ];
    // Union: registry hosts + fallback. Never drop anime-planet / mangadex when
    // PROXY_COVER_HOSTS is a non-empty partial list (community scraper not loaded yet).
    const configured = Array.isArray(window.PROXY_COVER_HOSTS) ? window.PROXY_COVER_HOSTS : [];
    const hosts = Array.from(new Set(configured.concat(fallbackHosts)));
    const needsProxy = hosts.some((d) => {
        const dom = String(d || '').toLowerCase();
        return !!dom && (host === dom || host.endsWith('.' + dom));
    });
    if (!needsProxy) return trimmed;
    let proxied = getRootPath() + '/api/proxy-image?url=' + encodeURIComponent(trimmed);
    // Companion embed : un <img> ne peut pas porter le header X-Companion-Embed-Token
    // que le shell injecte sur les fetch, donc le jeton voyage en query (l'allowlist
    // de domaines et le plafond de taille du proxy s'appliquent de la même façon).
    const embed = window.COMPANION_EMBED;
    if (embed && embed.embedToken) {
        proxied += '&embed_token=' + encodeURIComponent(embed.embedToken);
    }
    return proxied;
}

// --- CSRF : injecte X-CSRF-Token sur tous les fetch mutatifs ---
// …et traite la session expirée au même endroit : c'est le seul point de passage
// commun à tous les appels du frontend.
(function patchFetchWithCsrf() {
    const originalFetch = window.fetch.bind(window);
    let authReloadStarted = false;

    /**
     * Session expirée : le gate répond 401 + X-MetaKavita-Auth, jamais une
     * redirection vers /login — `fetch()` la suivrait en silence et le JS
     * recevrait 200 + du HTML, donc une SyntaxError sur `r.json()` affichée
     * comme « Erreur réseau ». Recharger fait apparaître le vrai formulaire de
     * connexion, et l'utilisateur comprend qu'il doit se reconnecter.
     *
     * L'en-tête est testé plutôt que le corps : lire le corps ici le
     * consommerait pour l'appelant.
     */
    function handleAuthExpired(res) {
        if (!res || res.status !== 401 || authReloadStarted) return;
        if (res.headers.get('X-MetaKavita-Auth') !== 'required') return;
        // Shell Companion : il s'authentifie par jeton d'embed, pas par session.
        // Recharger n'y afficherait aucun formulaire (l'iframe est cross-origin)
        // et bouclerait dès que le jeton est révoqué en fin de revue.
        if (window.COMPANION_EMBED) return;
        authReloadStarted = true;
        window.location.reload();
    }

    window.fetch = function(input, init) {
        init = init || {};
        const method = String(init.method || 'GET').toUpperCase();
        if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
            const meta = document.querySelector('meta[name="csrf-token"]');
            const token = meta ? meta.getAttribute('content') : '';
            if (token) {
                const headers = new Headers(init.headers || {});
                if (!headers.has('X-CSRF-Token')) {
                    headers.set('X-CSRF-Token', token);
                }
                init = Object.assign({}, init, { headers: headers });
            }
        }
        return originalFetch(input, init).then(function(res) {
            handleAuthExpired(res);
            return res;
        });
    };
})();

// --- GESTION DU THÈME ---
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// --- ENTRÉES DE TYPE MOT DE PASSE / SECRETS (ŒIL) ---
function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.classList.contains('secret-masked')) {
        const revealed = input.classList.toggle('is-revealed');
        btn.innerText = revealed ? '🙈' : '👁️';
        return;
    }
    if (input.type === 'password') {
        input.type = 'text';
        btn.innerText = '🙈';
    } else {
        input.type = 'password';
        btn.innerText = '👁️';
    }
}
