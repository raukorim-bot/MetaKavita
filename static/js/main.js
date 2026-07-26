// --- ORCHESTRATION AU CHARGEMENT DE LA PAGE & MODAL CHANGELOG ---
// Chargé en dernier : appelle des fonctions définies dans config.js (toggleTranslationFields),
// batch.js (loadLibrary, filterSeries) une fois toutes les autres briques prêtes.

document.addEventListener('DOMContentLoaded', () => {
    const savedStatus = localStorage.getItem('filter_status');
    const savedHideIgnored = localStorage.getItem('filter_hide_ignored');
    const savedSearch = localStorage.getItem('filter_search');
    const savedLibrary = localStorage.getItem('filter_library');
    toggleTranslationFields();
    if (savedStatus) {
        const statusSelect = document.getElementById('statusFilter');
        if (statusSelect) statusSelect.value = savedStatus;
    }
    if (savedHideIgnored && savedHideIgnored === 'false') {
        const hideIgnoredCb = document.getElementById('hideIgnoredCb');
        if (hideIgnoredCb) hideIgnoredCb.checked = false;
    }
    if (savedSearch) {
        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.value = savedSearch;
    }
    
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.has('library_id') && savedLibrary) {
        const libSelector = document.getElementById('lib_selector');
        if (libSelector && libSelector.querySelector(`option[value="${savedLibrary}"]`)) {
            libSelector.value = savedLibrary;
            loadLibrary(savedLibrary);
            return; 
        }
    } else if (urlParams.has('library_id')) {
        localStorage.setItem('filter_library', urlParams.get('library_id'));
    } else {
        localStorage.setItem('filter_library', '');
    }

    filterSeries();
    restoreBatchSelection();
    filterSeries();
});

// --- GESTION DYNAMIQUE DE LA MODAL CHANGELOG ---
function checkChangelogPopup() {
    const currentVersion = window.APP_VERSION || "1.5.5";
    const lastSeenVersion = localStorage.getItem('last_seen_version');
    
    if (lastSeenVersion !== currentVersion) {
        openChangelogModal(false);
    }
}

function openChangelogModal(forceOpen = false) {
    const modal = document.getElementById('changelogModal');
    const body = document.getElementById('changelogModalBody');
    if (!modal || !body) return;

    // Affiche un loader temporaire pendant la requête
    body.innerHTML = `<div class="loader-spinner">⏳ Chargement des nouveautés...</div>`;
    modal.style.display = 'flex';

    // Récupération dynamique depuis CHANGELOG.md via l'API
    fetch(getRootPath() + '/api/changelog')
        .then(res => res.json())
        .then(data => {
            if (data.success && data.changelog) {
                body.innerHTML = data.changelog;
                if (!forceOpen) {
                    localStorage.setItem('last_seen_version', data.version);
                }
            } else {
                body.innerHTML = `<p>Version ${window.APP_VERSION} active.</p>`;
            }
        })
        .catch(() => {
            body.innerHTML = `<p>Version ${window.APP_VERSION} active.</p>`;
        });
}

function closeChangelogModal() {
    const modal = document.getElementById('changelogModal');
    if (modal) modal.style.display = 'none';
    if (window.APP_VERSION) {
        localStorage.setItem('last_seen_version', window.APP_VERSION);
    }
}

// --- MENU AIDE (À propos / Documentation) ---
function closeHelpMenu() {
    const dropdown = document.getElementById('helpDropdown');
    const btn = document.getElementById('helpMenuBtn');
    if (dropdown) dropdown.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
}

function toggleHelpMenu(event) {
    if (event) event.stopPropagation();
    const dropdown = document.getElementById('helpDropdown');
    const btn = document.getElementById('helpMenuBtn');
    if (!dropdown || !btn) return;
    const willOpen = dropdown.hidden;
    dropdown.hidden = !willOpen;
    btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
}

function openAboutModal() {
    const modal = document.getElementById('aboutModal');
    if (modal) modal.style.display = 'flex';
}

function closeAboutModal() {
    const modal = document.getElementById('aboutModal');
    if (modal) modal.style.display = 'none';
}

document.addEventListener('click', (event) => {
    const help = document.querySelector('.topbar-help');
    if (help && !help.contains(event.target)) {
        closeHelpMenu();
    }
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeHelpMenu();
        closeAboutModal();
        closeChangelogModal();
    }
});

// Déclencheur au chargement de la page
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(checkChangelogPopup, 600);
});
