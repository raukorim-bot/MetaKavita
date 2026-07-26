// --- HELPERS PARTAGÉS ---
// Chargé en premier : toutes les autres fonctions du frontend (fetch vers l'API,
// Socket.IO) dépendent de getRootPath() pour fonctionner correctement derrière
// un reverse-proxy avec sous-chemin (voir ROOT_PATH côté serveur, app.py).

// Fonction de secours pour garantir que le root_path existe toujours
const getRootPath = () => window.ROOT_PATH || '';

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
