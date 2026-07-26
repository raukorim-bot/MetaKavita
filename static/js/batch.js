// --- LISTE DE SÉRIES : FILTRAGE, SÉLECTION, SYNCHRONISATION UNITAIRE/LOT, IGNORER ---
// Dépend de utils.js (getRootPath).

function filterSeries() {
    const filter = document.getElementById('statusFilter').value;
    const hideIgnoredCb = document.getElementById('hideIgnoredCb');
    const hideIgnored = hideIgnoredCb ? hideIgnoredCb.checked : false;
    
    const searchInput = document.getElementById('searchInput');
    const searchQuery = searchInput ? searchInput.value.toLowerCase().trim() : '';
    
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
        const providerSelect = document.getElementById('provider-' + id);
        const forcedProvider = providerSelect ? providerSelect.value : 'AUTO';
        
        const pubPrefInput = document.querySelector(`input[name="pubpref-${id}"]:checked`);
        const publisherPref = pubPrefInput ? pubPrefInput.value : 'GLOBAL';
        
        const fields = ['summary', 'cover', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles'];
        const activeFields = fields.filter(f => {
            const cb = document.getElementById(`field-${f}-${id}`);
            return cb && cb.checked;
        }).join(',');
        
        btn.style.display = 'none';
        btn.previousElementSibling.style.display = 'none'; 
        let loading = btn.nextElementSibling;
        loading.style.display = 'inline-block';
        
        // Envoi au serveur incluant le publisher_pref
        fetch(getRootPath() + '/save-override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `series_id=${id}&forced_id=${encodeURIComponent(forcedId)}&alternative_title=${encodeURIComponent(altTitle)}&forced_provider=${encodeURIComponent(forcedProvider)}&targeted_fields=${encodeURIComponent(activeFields)}&publisher_pref=${encodeURIComponent(publisherPref)}`
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

    fetch(getRootPath() + '/force-sync', {
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
        await fetch(getRootPath() + '/batch-sync', { method: 'POST', body: formData });
    }

    btn.innerText = window.AppTranslations.batch_ok;
    setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 4000);
}

function stopBatch() {
    fetch(getRootPath() + '/stop-batch', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        const btn = document.getElementById('mainBatchBtn');
        if (btn) btn.innerText = window.AppTranslations.launchBatch;
    });
}

// --- AMNISTIE DES ERREURS ET DES IGNORÉS (AJAX) ---
function resetErrors(btn) {
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    
    fetch(getRootPath() + '/reset-errors', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            btn.innerText = "✅ OK";
            setTimeout(() => { btn.innerText = originalText; }, 2000);
            
            // Remise à jour visuelle des éléments NOT_FOUND et IGNORED en PENDING
            document.querySelectorAll('.series-item[data-status="NOT_FOUND"], .series-item[data-status="IGNORED"]').forEach(item => {
                item.dataset.status = 'PENDING';
                
                const badge = item.querySelector('.badge');
                if (badge) {
                    badge.className = 'badge badge-pending';
                    badge.innerText = window.AppTranslations.filter_pending;
                }
                
                const ignoreBtn = item.querySelector('.series-actions .btn-icon');
                if (ignoreBtn) {
                    ignoreBtn.innerText = '🚫';
                    ignoreBtn.title = window.AppTranslations.ignore_btn;
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
    
    fetch(getRootPath() + '/?library_id=' + libraryId)
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
            
            const newUrl = libraryId ? getRootPath() + '/?library_id=' + libraryId : getRootPath() + '/';
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

    fetch(getRootPath() + '/toggle-ignore', {
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
                const res = await fetch(getRootPath() + '/toggle-ignore', {
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
