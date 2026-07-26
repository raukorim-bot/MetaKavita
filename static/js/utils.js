// --- HELPERS PARTAGÉS ---
// Chargé en premier : toutes les autres fonctions du frontend (fetch vers l'API,
// Socket.IO) dépendent de getRootPath() pour fonctionner correctement derrière
// un reverse-proxy avec sous-chemin (voir ROOT_PATH côté serveur, app.py).

// Fonction de secours pour garantir que le root_path existe toujours
const getRootPath = () => window.ROOT_PATH || '';

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
