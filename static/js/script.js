// Variables globales pour mémoriser l'état de la modal et de la brique de déploiement
let currentCoverModalSeriesId = null;
let currentCoverModalSeriesName = null;
let allPanelsExpanded = false; // Mémorise l'état global du déploiement des options

// --- AFFICHAGE CONDITIONNEL DU FOURNISSEUR DE TRADUCTION ---
function toggleTranslationFields() {
    const provider = document.getElementById('translationProvider');
    if (!provider) return;
    
    const deeplFields = document.getElementById('deepl_fields');
    const azureFields = document.getElementById('azure_fields');
    
    if (provider.value === 'DEEPL') {
        deeplFields.style.display = 'block';
        azureFields.style.display = 'none';
    } else if (provider.value === 'AZURE') {
        deeplFields.style.display = 'none';
        azureFields.style.display = 'block';
    } else {
        // Mode Google (Gratuit) : On masque toutes les clés API !
        deeplFields.style.display = 'none';
        azureFields.style.display = 'none';
    }
}

// --- GESTION DU THÈME ---
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// --- GESTION DES MODALS (CONFIGURATION GLOBALE & COUVERTURES) ---
function openConfigModal() {
    document.getElementById('configModal').style.display = 'flex';
}

function closeConfigModal() {
    document.getElementById('configModal').style.display = 'none';
}

function togglePanel(id) {
    var panel = document.getElementById(id);
    panel.style.display = (panel.style.display === 'block') ? 'none' : 'block';
}

// NOUVEAU : Fonction de déploiement/repli global de tous les panneaux d'options (Solution Ergonomie)
function toggleAllOverridePanels() {
    allPanelsExpanded = !allPanelsExpanded;
    const targetDisplay = allPanelsExpanded ? 'block' : 'none';
    
    document.querySelectorAll('.override-panel').forEach(panel => {
        panel.style.display = targetDisplay;
    });
}

// Écouteur pour la touche "Entrée" sur la recherche de couverture de la modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        const modalSearchInput = document.getElementById('modalCoverSearchInput');
        if (document.activeElement === modalSearchInput) {
            e.preventDefault();
            triggerManualCoverSearch();
        }
    }
});

document.addEventListener('DOMContentLoaded', () => {
    // Restauration des filtres mémorisés dans le localStorage
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
    
    // Si aucune bibliothèque n'est présente dans l'URL mais qu'une était mémorisée, on la charge
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
});

// --- ACTIONS SUR LES SÉRIES ---
function saveOverride(seriesId, btn) {
    const forcedId = document.getElementById('id-' + seriesId).value;
    const altTitle = document.getElementById('title-' + seriesId).value;
    btn.innerText = "⏳...";
    
    fetch('/save-override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${seriesId}&forced_id=${forcedId}&alternative_title=${encodeURIComponent(altTitle)}`
    }).then(r => {
        if(r.ok) {
            btn.innerText = "✅"; 
            setTimeout(() => { btn.innerText = window.AppTranslations.save; }, 1500);
        }
    });
}

// Recherche rapide d'ID (AniList Direct Lookup)
function lookupAniListId(seriesName) {
    const url = `https://anilist.co/search/manga?search=${encodeURIComponent(seriesName)}`;
    window.open(url, '_blank');
}

async function saveAllOverrides() {
    const panels = document.querySelectorAll('.override-panel');
    for (let panel of panels) {
        if (panel.style.display === 'block') {
            panel.querySelector('button.btn-success').click();
            await new Promise(r => setTimeout(r, 200));
        }
    }
}

function filterSeries() {
    const filter = document.getElementById('statusFilter').value;
    const hideIgnoredCb = document.getElementById('hideIgnoredCb');
    const hideIgnored = hideIgnoredCb ? hideIgnoredCb.checked : false;
    
    const searchInput = document.getElementById('searchInput');
    const searchQuery = searchInput ? searchInput.value.toLowerCase().trim() : '';
    
    // Sauvegarde automatique de l'état des filtres
    localStorage.setItem('filter_status', filter);
    if (hideIgnoredCb) localStorage.setItem('filter_hide_ignored', hideIgnored ? 'true' : 'false');
    if (searchInput) localStorage.setItem('filter_search', searchQuery);
    
    let count = 0;
    
    document.querySelectorAll('.series-item').forEach(item => {
        const status = item.dataset.status;
        const titleElem = item.querySelector('.series-name');
        const title = titleElem ? titleElem.innerText.toLowerCase() : '';
        
        let show = false;
        
        if (filter === 'ALL') {
            show = true;
            if (hideIgnored && status === 'IGNORED') {
                show = false;
            }
        } else if (status === filter) {
            show = true;
        }
        
        if (show && searchQuery !== '') {
            if (!title.includes(searchQuery)) {
                show = false;
            }
        }
        
        if (show) {
            item.style.display = 'flex';
            count++;
        } else {
            item.style.display = 'none';
            const cb = item.querySelector('.series-cb');
            if(cb) cb.checked = false;
        }
    });
    
    document.getElementById('selectAll').checked = false;
    
    const countElem = document.getElementById('visibleCount');
    if(countElem) {
        countElem.innerText = count + (count > 1 ? window.AppTranslations.elements : window.AppTranslations.element);
    }
}

function toggleSelectAll() {
    const isChecked = document.getElementById('selectAll').checked;
    document.querySelectorAll('.series-item').forEach(item => {
        if (item.style.display !== 'none') {
            const cb = item.querySelector('.series-cb');
            if(cb) cb.checked = isChecked;
        }
    });
}

// --- SYNCHRONISATION ---
function syncSingle(id, name, btn) {
    const forcedIdInput = document.getElementById('id-' + id);
    const altTitleInput = document.getElementById('title-' + id);
    
    if(forcedIdInput && altTitleInput) {
        const forcedId = forcedIdInput.value;
        const altTitle = altTitleInput.value;
        
        btn.style.display = 'none';
        btn.previousElementSibling.style.display = 'none'; 
        let loading = btn.nextElementSibling;
        loading.style.display = 'inline-block';
        
        fetch('/save-override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `series_id=${id}&forced_id=${forcedId}&alternative_title=${encodeURIComponent(altTitle)}`
        }).then(() => proceedSyncSingle(id, name, btn, loading));
    } else {
        proceedSyncSingle(id, name, btn, null);
    }
}

function proceedSyncSingle(id, name, btn, loadingElem) {
    let loading = loadingElem;
    if(!loading) {
        btn.style.display = 'none';
        btn.previousElementSibling.style.display = 'none'; 
        loading = btn.nextElementSibling;
        loading.style.display = 'inline-block';
    }

    fetch('/force-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${id}&series_name=${encodeURIComponent(name)}`
    })
    .then(res => res.json())
    .then(data => {
        loading.style.display = 'none';
        btn.style.display = 'inline-block';
        btn.previousElementSibling.style.display = 'inline-block';
        if(data.success) {
            btn.innerText = "✅ OK";
        } else {
            btn.innerText = "❌ Fail";
        }
        setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
    });
}

async function launchBatch(event) {
    event.preventDefault();
    const form = event.target;
    const btn = document.getElementById('mainBatchBtn');
    const checkboxes = form.querySelectorAll('.series-cb:checked');
    const ids = Array.from(checkboxes).map(cb => cb.value);
    
    if (ids.length === 0) {
        btn.innerText = window.AppTranslations.batch_empty;
        setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 2000);
        return;
    }

    btn.innerText = window.AppTranslations.batch_sending;
    
    for (let i = 0; i < ids.length; i += 50) {
        const batch = ids.slice(i, i + 50);
        const formData = new FormData();
        
        const libInput = form.querySelector('[name="library_id"]');
        if(libInput) formData.append('library_id', libInput.value);
        
        const forceUpdateCb = document.getElementById('sidebar_force_update');
        if (forceUpdateCb && forceUpdateCb.checked) {
            formData.append('force_update', 'true');
        }
        
        batch.forEach(id => formData.append('selected_series', id));
        await fetch('/batch-sync', { method: 'POST', body: formData });
    }

    btn.innerText = window.AppTranslations.batch_ok;
    setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 4000);
}

function stopBatch() {
    fetch('/stop-batch', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        const btn = document.getElementById('mainBatchBtn');
        if (btn) btn.innerText = window.AppTranslations.launchBatch;
    });
}

// --- WEBSOCKETS LOGS & INDICATEUR LIVE DE TRAITEMENT ---
var socket = io();
var logConsole = document.getElementById('log-console');
socket.on('connect', function() { 
    logConsole.innerHTML += '<div class="log-line" style="color: var(--primary);">' + window.AppTranslations.terminal_ready + '</div>'; 
});
socket.on('log_update', function(msg) {
    var newLog = document.createElement('div');
    newLog.className = 'log-line';
    newLog.textContent = msg.data;
    if (msg.data.includes('ERROR') || msg.data.includes('❌') || msg.data.includes('💥')) {
        newLog.className += ' log-error';
    } else if (msg.data.includes('WARNING') || msg.data.includes('⚠️')) {
        newLog.className += ' log-warning';
    }
    logConsole.appendChild(newLog);
    logConsole.scrollTop = logConsole.scrollHeight;

    try {
        const matchStart = msg.data.match(/▶️\s+\[(.*?)\]\s+Début/i) || msg.data.match(/▶️\s+\[(.*?)\]\s+Starting/i);
        if (matchStart && matchStart[1]) {
            const activeTitle = matchStart[1].trim();
            
            document.querySelectorAll('.series-item.is-processing').forEach(item => {
                item.classList.remove('is-processing');
            });
            
            document.querySelectorAll('.series-item').forEach(item => {
                const nameElem = item.querySelector('.series-name');
                if (nameElem && nameElem.textContent.trim().toLowerCase() === activeTitle.toLowerCase()) {
                    item.classList.add('is-processing');
                    item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            });
        }

        const matchEnd = msg.data.match(/\[(.*?)\]\s+✅/i) || 
                         msg.data.match(/\[(.*?)\]\s+⏭️/i) || 
                         msg.data.match(/\[(.*?)\]\s+❌/i) || 
                         msg.data.match(/\[(.*?)\]\s+⚠️/i);
                         
        if (matchEnd && matchEnd[1]) {
            const finishedTitle = matchEnd[1].trim();
            document.querySelectorAll('.series-item').forEach(item => {
                const nameElem = item.querySelector('.series-name');
                if (nameElem && nameElem.textContent.trim().toLowerCase() === finishedTitle.toLowerCase()) {
                    item.classList.remove('is-processing');
                    
                    const badge = item.querySelector('.badge');
                    if (badge) {
                        if (msg.data.includes('✅') || msg.data.includes('réussi') || msg.data.includes('successfully')) {
                            item.dataset.status = 'COMPLETED';
                            badge.className = 'badge badge-completed';
                            badge.innerText = window.AppTranslations.filter_completed;
                        } else if (msg.data.includes('⏭️') || msg.data.includes('déjà à jour') || msg.data.includes('already up to date')) {
                            item.dataset.status = 'COMPLETED';
                            badge.className = 'badge badge-completed';
                            badge.innerText = window.AppTranslations.filter_completed;
                        } else if (msg.data.includes('introuvable') || msg.data.includes('Aucun résultat') || msg.data.includes('No results')) {
                            item.dataset.status = 'NOT_FOUND';
                            badge.className = 'badge badge-notfound';
                            badge.innerText = window.AppTranslations.filter_notfound;
                        }
                    }
                }
            });
        }
    } catch(e) {
        console.error("[WebSockets] Erreur Live Highlight :", e);
    }
});

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

// --- SAUVEGARDE CONFIGURATION (AJAX HYBRIDE) ---
function saveConfig() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    
    const smartCompletion = document.getElementById('sidebar_smart_completion');
    const autoCover = document.getElementById('sidebar_auto_cover');
    const autoReadingDir = document.getElementById('sidebar_auto_reading_dir');
    
    if (smartCompletion) formData.append('SMART_COMPLETION', smartCompletion.checked ? 'true' : 'false');
    if (autoCover) formData.append('AUTO_COVER', autoCover.checked ? 'true' : 'false');
    if (autoReadingDir) formData.append('AUTO_READING_DIR', autoReadingDir.checked ? 'true' : 'false');
    
    const btn = form.querySelector('.btn-primary');
    const originalText = btn ? btn.innerText : "";
    if (btn) btn.innerText = "⏳...";

    fetch('/save-config', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            if (btn) {
                btn.innerText = "✅ OK";
                setTimeout(() => { btn.innerText = originalText; }, 2000);
            }
            
            const currentLang = document.documentElement.lang;
            const newLang = formData.get('UI_LANG');
            if (newLang && currentLang !== newLang) {
                window.location.reload();
            }
        }
    });
}

// --- AMNISTIE DES ERREURS (AJAX) ---
function resetErrors(btn) {
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    
    fetch('/reset-errors', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            btn.innerText = "✅ OK";
            setTimeout(() => { btn.innerText = originalText; }, 2000);
            
            document.querySelectorAll('.series-item[data-status="NOT_FOUND"]').forEach(item => {
                item.dataset.status = 'PENDING';
                const badge = item.querySelector('.badge-notfound');
                if (badge) {
                    badge.className = 'badge badge-pending';
                    badge.innerText = window.AppTranslations.filter_pending;
                }
            });
            filterSeries();
        }
    });
}

// --- CHARGEMENT DYNAMIQUE DES BIBLIOTHÈQUES (AJAX) ---
function loadLibrary(libraryId) {
    const contentArea = document.querySelector('.content');
    contentArea.style.opacity = '0.5';
    contentArea.style.pointerEvents = 'none';
    
    localStorage.setItem('filter_library', libraryId || '');
    
    fetch('/?library_id=' + libraryId)
        .then(res => res.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            
            const newContent = doc.querySelector('.content');
            if (newContent) {
                contentArea.innerHTML = newContent.innerHTML;
            }
            
            const currentStats = document.querySelectorAll('.sidebar .card')[0];
            const newStats = doc.querySelectorAll('.sidebar .card')[0];
            if (currentStats && newStats) {
                currentStats.innerHTML = newStats.innerHTML;
            }
            
            const newUrl = libraryId ? '/?library_id=' + libraryId : '/';
            window.history.pushState({ path: newUrl }, '', newUrl);
            
            contentArea.style.opacity = '1';
            contentArea.style.pointerEvents = 'auto';
            
            filterSeries();
        })
        .catch(err => {
            console.error("Erreur lors du chargement de la bibliothèque :", err);
            contentArea.style.opacity = '1';
            contentArea.style.pointerEvents = 'auto';
        });
}

window.addEventListener('popstate', () => {
    window.location.reload();
});

// --- BASCULER LE STATUT "À IGNORER" (AJAX) ---
function toggleIgnore(seriesId, btn) {
    const seriesItem = btn.closest('.series-item');
    const currentStatus = seriesItem.dataset.status;
    
    const originalText = btn.innerText;
    btn.innerText = "⏳";
    btn.disabled = true;

    fetch('/toggle-ignore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${seriesId}&current_status=${currentStatus}`
    })
    .then(res => res.json())
    .then(data => {
        btn.disabled = false;
        if(data.success) {
            seriesItem.dataset.status = data.new_status;
            
            if (data.new_status === 'IGNORED') {
                btn.innerText = '🔄';
                btn.title = window.AppTranslations.unignore_btn;
            } else {
                btn.innerText = '🚫';
                btn.title = window.AppTranslations.ignore_btn;
            }
            
            const badge = seriesItem.querySelector('.badge');
            if (badge) {
                if (data.new_status === 'IGNORED') {
                    badge.className = 'badge badge-ignored';
                    badge.innerText = window.AppTranslations.filter_ignored;
                } else {
                    badge.className = 'badge badge-pending';
                    badge.innerText = window.AppTranslations.filter_pending;
                }
            }
            
            filterSeries();
        } else {
            btn.innerText = originalText;
        }
    })
    .catch(() => {
        btn.disabled = false;
        btn.innerText = originalText;
    });
}

// --- IGNORER TOUTE LA SÉLECTION (AJAX) ---
async function ignoreSelection() {
    const checkboxes = document.querySelectorAll('.series-cb:checked');
    if (checkboxes.length === 0) return;

    const btn = document.getElementById('batchIgnoreBtn');
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    btn.disabled = true;

    for (let cb of checkboxes) {
        const seriesItem = cb.closest('.series-item');
        const seriesId = cb.value;
        const currentStatus = seriesItem.dataset.status;

        if (currentStatus !== 'IGNORED') {
            try {
                const res = await fetch('/toggle-ignore', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `series_id=${seriesId}&current_status=${currentStatus}`
                });
                const data = await res.json();
                
                if (data.success) {
                    seriesItem.dataset.status = 'IGNORED';
                    const badge = seriesItem.querySelector('.badge');
                    if (badge) {
                        badge.className = 'badge badge-ignored';
                        badge.innerText = window.AppTranslations.filter_ignored;
                    }
                    const ignoreBtn = seriesItem.querySelector('.series-actions .btn-icon');
                    if (ignoreBtn) {
                        ignoreBtn.innerText = '🔄';
                        ignoreBtn.title = window.AppTranslations.unignore_btn;
                    }
                }
            } catch(e) {
                console.error("[MetaKavita] Erreur lors de l'ignorance en masse:", e);
            }
        }
    }
    
    btn.innerText = "✅ OK";
    setTimeout(() => { 
        btn.innerText = originalText; 
        btn.disabled = false;
        filterSeries();
    }, 1000);
}

// --- MODAL COUVERTURES AVEC RECHERCHE MANUELLE ---
function openCoverModal(seriesId, seriesName) {
    currentCoverModalSeriesId = seriesId;
    currentCoverModalSeriesName = seriesName;
    
    document.getElementById('modalSeriesName').innerText = seriesName;
    
    const modalSearchInput = document.getElementById('modalCoverSearchInput');
    if (modalSearchInput) modalSearchInput.value = seriesName;
    
    document.getElementById('coverModal').style.display = 'flex';
    document.getElementById('coversGrid').innerHTML = `<div class="loader-spinner">${window.AppTranslations.modal_cover_loading}</div>`;
    
    fetchCovers(seriesId, seriesName);
}

function fetchCovers(seriesId, query) {
    fetch(`/api/series/${seriesId}/covers?series_name=${encodeURIComponent(query)}`)
    .then(r => r.json())
    .then(data => {
        if(data.success && data.covers.length > 0) {
            let html = '';
            data.covers.forEach(c => {
                // CORRECTION : Faire passer Nautiljon et ComicVine par notre proxy d'images
                let displayUrl = (c.provider === 'Kitsu' || c.provider.startsWith('ComicVine')) ? `/api/proxy-image?url=${encodeURIComponent(c.url)}` : c.url;
                
                html += `
                <div class="cover-item" onclick="applyCover('${seriesId}', '${c.url}')" title="${c.title}">
                    <img src="${displayUrl}" alt="Cover" loading="lazy">
                    <div class="cover-title" style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 8px;" title="${c.title}">${c.title}</div>
                    <div class="cover-provider" style="font-size: 11px; color: var(--primary); margin-top: 2px;">${c.provider}</div>
                </div>`;
            });
            document.getElementById('coversGrid').innerHTML = html;
        } else {
            document.getElementById('coversGrid').innerHTML = `<div class="alert error" style="grid-column: 1 / -1;">❌ Aucune image trouvée.</div>`;
        }
    })
    .catch(err => {
        document.getElementById('coversGrid').innerHTML = `<div class="alert error" style="grid-column: 1 / -1;">❌ Erreur réseau ou de scraping.</div>`;
    });
}

function triggerManualCoverSearch() {
    const modalSearchInput = document.getElementById('modalCoverSearchInput');
    if (modalSearchInput && currentCoverModalSeriesId) {
        const query = modalSearchInput.value.trim();
        if (query) {
            document.getElementById('coversGrid').innerHTML = `<div class="loader-spinner">${window.AppTranslations.modal_cover_loading}</div>`;
            fetchCovers(currentCoverModalSeriesId, query);
        }
    }
}

function closeCoverModal() {
    document.getElementById('coverModal').style.display = 'none';
    document.getElementById('coversGrid').innerHTML = '';
    currentCoverModalSeriesId = null;
    currentCoverModalSeriesName = null;
}

function applyCover(seriesId, coverUrl) {
    document.getElementById('coversGrid').innerHTML = `<div class="loader-spinner">${window.AppTranslations.modal_cover_sending}</div>`;
    
    fetch(`/api/series/${seriesId}/update-cover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cover_url: coverUrl })
    })
    .then(r => r.json())
    .then(data => {
        if(data.success) {
            closeCoverModal();
        } else {
            alert("Erreur lors de l'envoi de la couverture : " + data.msg);
            closeCoverModal();
        }
    });
}

// --- GESTION DES MENUS PROVIDERS ---
function handleProviderChange(changedSelect) {
    const name = changedSelect.name; // ex: "COMIC_PROVIDER_1" ou "PROVIDER_2"
    let prefix = "";
    if (name.startsWith("COMIC_")) {
        prefix = "COMIC_";
    } else if (name.startsWith("BOOK_")) {
        prefix = "BOOK_";
    }
    
    const selects = [
        document.querySelector(`select[name="${prefix}PROVIDER_1"]`),
        document.querySelector(`select[name="${prefix}PROVIDER_2"]`),
        document.querySelector(`select[name="${prefix}PROVIDER_3"]`)
    ];
    
    const newValue = changedSelect.value;

    if (newValue !== 'NONE') {
        selects.forEach(otherSelect => {
            if (otherSelect && otherSelect !== changedSelect && otherSelect.value === newValue) {
                otherSelect.value = 'NONE';
            }
        });
    }

    const p1 = selects[0];
    if (p1 && (!p1.value || p1.value === 'NONE')) {
        const allProviders = Array.from(p1.options).map(opt => opt.value).filter(val => val !== 'NONE');
        const usedByOthers = [selects[1] ? selects[1].value : 'NONE', selects[2] ? selects[2].value : 'NONE'];
        const freeProvider = allProviders.find(p => !usedByOthers.includes(p));
        p1.value = freeProvider || allProviders[0];
    }

    saveConfig();
}