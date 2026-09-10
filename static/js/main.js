// --- ORCHESTRATION AU CHARGEMENT DE LA PAGE & MODAL CHANGELOG ---
// Chargé en dernier : appelle des fonctions définies dans config.js (toggleTranslationFields),
// batch.js (loadLibrary, filterSeries) une fois toutes les autres briques prêtes.

const SCRAPING_OPTIONS_OPEN_KEY = 'mk_scraping_options_open';
const SCRAPING_CAT_OPEN_KEY = 'mk_scraping_cat_open';
const SIDEBAR_SCROLL_KEY = 'mk_sidebar_scroll';

function sidebarEl() {
    return document.querySelector('aside.sidebar');
}

function applySidebarUiMemory() {
    const details = document.getElementById('scrapingOptionsDetails');
    if (details) {
        const saved = localStorage.getItem(SCRAPING_OPTIONS_OPEN_KEY);
        details.open = saved === null ? true : saved === 'true';
    }
    let catState = {};
    try {
        catState = JSON.parse(localStorage.getItem(SCRAPING_CAT_OPEN_KEY) || '{}') || {};
    } catch (_) {
        catState = {};
    }
    document.querySelectorAll('.so-cat[data-so-cat]').forEach((cat) => {
        const key = cat.getAttribute('data-so-cat');
        if (key && Object.prototype.hasOwnProperty.call(catState, key)) {
            cat.open = !!catState[key];
        }
    });
    const sidebar = sidebarEl();
    if (sidebar) {
        const y = parseInt(localStorage.getItem(SIDEBAR_SCROLL_KEY) || '0', 10);
        if (!isNaN(y) && y > 0) sidebar.scrollTop = y;
    }
}

function snapshotSidebarUi() {
    try {
        const details = document.getElementById('scrapingOptionsDetails');
        if (details) {
            localStorage.setItem(SCRAPING_OPTIONS_OPEN_KEY, details.open ? 'true' : 'false');
        }
        const cats = {};
        document.querySelectorAll('.so-cat[data-so-cat]').forEach((cat) => {
            const key = cat.getAttribute('data-so-cat');
            if (key) cats[key] = !!cat.open;
        });
        localStorage.setItem(SCRAPING_CAT_OPEN_KEY, JSON.stringify(cats));
        const sidebar = sidebarEl();
        if (sidebar) localStorage.setItem(SIDEBAR_SCROLL_KEY, String(sidebar.scrollTop || 0));
    } catch (_) { /* stockage refusé */ }
}

function restoreScrapingOptionsOpenState() {
    const details = document.getElementById('scrapingOptionsDetails');
    if (!details) return;
    let restoring = true;
    applySidebarUiMemory();
    details.addEventListener('toggle', function () {
        if (!restoring) snapshotSidebarUi();
    });
    document.querySelectorAll('.so-cat[data-so-cat]').forEach((cat) => {
        cat.addEventListener('toggle', function () {
            if (!restoring) snapshotSidebarUi();
        });
    });
    const sidebar = sidebarEl();
    let scrollTimer = null;
    if (sidebar) {
        sidebar.addEventListener('scroll', function () {
            if (restoring) return;
            clearTimeout(scrollTimer);
            scrollTimer = setTimeout(snapshotSidebarUi, 120);
        }, { passive: true });
    }
    window.addEventListener('pagehide', snapshotSidebarUi);
    requestAnimationFrame(function () {
        applySidebarUiMemory();
        requestAnimationFrame(function () {
            applySidebarUiMemory();
            restoring = false;
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const savedStatus = localStorage.getItem('filter_status');
    const savedHideIgnored = localStorage.getItem('filter_hide_ignored');
    const savedSearch = localStorage.getItem('filter_search');
    const savedSearchInside = localStorage.getItem('filter_search_inside');
    const savedLibrary = localStorage.getItem('filter_library');
    toggleTranslationFields();
    restoreScrapingOptionsOpenState();
    if (typeof syncManualReviewCoverSwitch === 'function') syncManualReviewCoverSwitch();
    if (savedStatus) {
        const statusSelect = document.getElementById('statusFilter');
        // Legacy: duplicates used to live in the status filter — ignore it.
        if (statusSelect && savedStatus !== 'DUPLICATES') {
            statusSelect.value = savedStatus;
        } else if (savedStatus === 'DUPLICATES') {
            localStorage.setItem('filter_status', 'ALL');
        }
    }
    if (savedHideIgnored && savedHideIgnored === 'false') {
        const hideIgnoredCb = document.getElementById('hideIgnoredCb');
        if (hideIgnoredCb) hideIgnoredCb.checked = false;
    }
    if (savedSearchInside === 'true') {
        const searchInsideCb = document.getElementById('searchInsideCb');
        if (searchInsideCb) searchInsideCb.checked = true;
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
    const loadingMsg = (window.AppTranslations && window.AppTranslations.changelog_loading) ||
        '⏳ Chargement des nouveautés...';
    body.innerHTML = `<div class="loader-spinner">${loadingMsg}</div>`;
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

// --- MENUS DE LA BARRE DU HAUT (Scrapers / Aide) ---
// Deux menus voisins : ouvrir l'un ferme l'autre, sinon les deux panneaux se
// superposent. L'état ouvert vit sur aria-expanded du bouton, que le CSS lit
// pour le surligner et retourner le chevron.
function closeTopbarMenus() {
    document.querySelectorAll('.topbar-menu .help-dropdown').forEach((dropdown) => {
        dropdown.hidden = true;
    });
    document.querySelectorAll('.topbar-menu-btn').forEach((btn) => {
        btn.setAttribute('aria-expanded', 'false');
    });
}

function toggleTopbarMenu(event, dropdownId) {
    if (event) event.stopPropagation();
    const dropdown = document.getElementById(dropdownId);
    if (!dropdown) return;
    const willOpen = dropdown.hidden;
    closeTopbarMenus();
    if (!willOpen) return;
    dropdown.hidden = false;
    const btn = dropdown.parentElement
        ? dropdown.parentElement.querySelector('.topbar-menu-btn')
        : null;
    if (btn) btn.setAttribute('aria-expanded', 'true');
}

// --- ENCART COMPANION ---
// L'oubli est volontairement local au navigateur : le serveur ne sait pas si
// l'extension est installée, et une clé de config de plus pour une carte
// promotionnelle n'apporterait rien.
const COMPANION_CARD_KEY = 'mk_companion_card_dismissed';

function dismissCompanionCard() {
    const card = document.getElementById('companionCard');
    if (card) card.hidden = true;
    try { localStorage.setItem(COMPANION_CARD_KEY, '1'); } catch (e) { /* ignore */ }
}

function showCompanionCard() {
    try { localStorage.removeItem(COMPANION_CARD_KEY); } catch (e) { /* ignore */ }
    const card = document.getElementById('companionCard');
    if (!card) return;
    card.hidden = false;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    // Une carte qui réapparaît en haut de page pendant qu'on lit ailleurs passe
    // inaperçue : un pulse bref la désigne, puis la classe s'efface.
    card.classList.remove('is-recalled');
    void card.offsetWidth;
    card.classList.add('is-recalled');
    setTimeout(() => card.classList.remove('is-recalled'), 1600);
}

function openAboutModal() {
    const modal = document.getElementById('aboutModal');
    if (modal) modal.style.display = 'flex';
}

function closeAboutModal() {
    const modal = document.getElementById('aboutModal');
    if (modal) modal.style.display = 'none';
}

function openScrapingOptionsHelpModal() {
    const modal = document.getElementById('scrapingOptionsHelpModal');
    if (modal) modal.style.display = 'flex';
}

function closeScrapingOptionsHelpModal() {
    const modal = document.getElementById('scrapingOptionsHelpModal');
    if (modal) modal.style.display = 'none';
}

document.addEventListener('click', (event) => {
    const inside = event.target.closest ? event.target.closest('.topbar-menu') : null;
    if (!inside) closeTopbarMenus();
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeTopbarMenus();
        closeAboutModal();
        closeScrapingOptionsHelpModal();
        closeChangelogModal();
        if (typeof closeCoverModal === 'function') closeCoverModal();
        if (typeof closeProvidersModal === 'function') closeProvidersModal();
        if (typeof closeConfigModal === 'function') closeConfigModal();
        if (typeof closeAutoSyncReportModal === 'function') closeAutoSyncReportModal();
    }
});

// Déclencheur au chargement de la page
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(checkChangelogPopup, 600);
});
