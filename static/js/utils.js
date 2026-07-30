// --- HELPERS PARTAGÉS ---
// Chargé en premier : toutes les autres fonctions du frontend (fetch vers l'API,
// Socket.IO) dépendent de getRootPath() pour fonctionner correctement derrière
// un reverse-proxy avec sous-chemin (voir ROOT_PATH côté serveur, app.py).

// Fonction de secours pour garantir que le root_path existe toujours
const getRootPath = () => window.ROOT_PATH || '';

/**
 * URL d'affichage navigateur pour une couverture externe.
 * Les scrapers avec `requires_proxy=True` (MangaDex, ComicVine) bloquent le hotlink :
 * l'<img> doit passer par `/api/proxy-image` (Referer serveur). L'URL stockée /
 * envoyée à Kavita reste la vraie URL CDN — ne pas persister le résultat.
 * Doit rester aligné avec les flags `requires_proxy` des scrapers.
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
    const needsProxy =
        host === 'uploads.mangadex.org' ||
        host === 'mangadex.org' ||
        host.endsWith('.mangadex.org') ||
        host === 'static.comicvine.com' ||
        host === 'comicvine.gamespot.com' ||
        host.endsWith('.comicvine.com');
    if (!needsProxy) return trimmed;
    return getRootPath() + '/api/proxy-image?url=' + encodeURIComponent(trimmed);
}

// --- CSRF : injecte X-CSRF-Token sur tous les fetch mutatifs ---
(function patchFetchWithCsrf() {
    const originalFetch = window.fetch.bind(window);
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
        return originalFetch(input, init);
    };
})();

// --- GESTION DU THÈME ---
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// --- ENTRÉES DE TYPE MOT DE PASSE (ŒIL) ---
function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (input.type === 'password') {
        input.type = 'text';
        btn.innerText = '🙈';
    } else {
        input.type = 'password';
        btn.innerText = '👁️';
    }
}
