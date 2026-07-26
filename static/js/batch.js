// --- LISTE DE SÉRIES : FILTRAGE, SÉLECTION, SYNCHRONISATION UNITAIRE/LOT, IGNORER ---
// Dépend de utils.js (getRootPath).

const BATCH_SELECTION_PREFIX = 'mk_batch_selection:';

/** Stop pendant l'envoi des paquets ×50 : coupe la boucle + AbortController. */
var batchEnqueueAbort = false;
var batchEnqueueController = null;

/** Total du batch courant (fixé au lancement UI ; barre via événement batch_progress). */
var batchProgressTotal = 0;
var batchProgressHideTimer = null;

function showBatchProgress(total) {
    batchProgressTotal = Math.max(0, parseInt(total, 10) || 0);
    if (batchProgressHideTimer) {
        clearTimeout(batchProgressHideTimer);
        batchProgressHideTimer = null;
    }
    const wrap = document.getElementById('batchProgressWrap');
    if (!wrap) return;
    wrap.style.display = '';
    wrap.setAttribute('aria-hidden', 'false');
    updateBatchProgressUI(0, batchProgressTotal);
}

function hideBatchProgress() {
    batchProgressTotal = 0;
    if (batchProgressHideTimer) {
        clearTimeout(batchProgressHideTimer);
        batchProgressHideTimer = null;
    }
    const wrap = document.getElementById('batchProgressWrap');
    const fill = document.getElementById('batchProgressFill');
    if (wrap) {
        wrap.style.display = 'none';
        wrap.setAttribute('aria-hidden', 'true');
    }
    if (fill) fill.style.width = '0%';
}

function updateBatchProgressUI(done, total) {
    const label = document.getElementById('batchProgressLabel');
    const fill = document.getElementById('batchProgressFill');
    const track = document.querySelector('#batchProgressWrap .batch-progress-track');
    const safeTotal = Math.max(0, total || 0);
    const safeDone = Math.max(0, Math.min(safeTotal, done || 0));
    const tpl = (window.AppTranslations && window.AppTranslations.batch_progress) || '{0} / {1}';
    if (label) label.textContent = tpl.replace('{0}', String(safeDone)).replace('{1}', String(safeTotal));
    const pct = safeTotal > 0 ? Math.round((safeDone / safeTotal) * 100) : 0;
    if (fill) fill.style.width = pct + '%';
    if (track) track.setAttribute('aria-valuenow', String(pct));
}

function applyBatchProgressPayload(payload) {
    if (!payload) return;
    if (payload.stopped) {
        hideBatchProgress();
        return;
    }
    if (batchProgressTotal <= 0) return;

    const remaining = parseInt(payload.remaining, 10);
    const rem = isNaN(remaining) ? 0 : Math.max(0, remaining);
    const hasActive = !!(payload.active);
    let done;
    if (rem === 0 && !hasActive) {
        done = batchProgressTotal;
    } else {
        done = Math.max(0, batchProgressTotal - rem - (hasActive ? 1 : 0));
    }
    updateBatchProgressUI(done, batchProgressTotal);

    if (rem === 0 && !hasActive) {
        if (batchProgressHideTimer) clearTimeout(batchProgressHideTimer);
        batchProgressHideTimer = setTimeout(hideBatchProgress, 1500);
    }
}

function getBatchSelectionKey() {
    const lib = localStorage.getItem('filter_library') || '';
    return BATCH_SELECTION_PREFIX + (lib || 'all');
}

/** Persiste les IDs cochés (reprise batch après refresh / coupure). */
function saveBatchSelection() {
    const ids = Array.from(document.querySelectorAll('.series-cb:checked')).map(cb => String(cb.value));
    localStorage.setItem(getBatchSelectionKey(), JSON.stringify(ids));
}

function restoreBatchSelection() {
    let saved;
    try {
        saved = JSON.parse(localStorage.getItem(getBatchSelectionKey()) || '[]');
    } catch (e) {
        saved = [];
    }
    if (!Array.isArray(saved) || saved.length === 0) return;

    const want = new Set(saved.map(String));
    document.querySelectorAll('.series-cb').forEach(cb => {
        cb.checked = want.has(String(cb.value));
    });

    // Nettoie les IDs disparus de la bibliothèque
    saveBatchSelection();
}

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
    let visibleChecked = 0;
    let visibleTotal = 0;
    
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
            visibleTotal++;
            const cb = item.querySelector('.series-cb');
            if (cb && cb.checked) visibleChecked++;
        } else {
            // Ne pas décocher : la sélection batch doit survivre aux filtres / rechargements.
            item.style.display = 'none';
        }
    });
    
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.checked = visibleTotal > 0 && visibleChecked === visibleTotal;
    }
    
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
    saveBatchSelection();
}

// Délégation : toute case série → persistance
document.addEventListener('change', function(e) {
    if (e.target && e.target.classList && e.target.classList.contains('series-cb')) {
        saveBatchSelection();
    }
});

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
        const altLangsInput = document.getElementById('alt-langs-' + id);
        const altTitleLangs = altLangsInput ? altLangsInput.value.trim() : '';
        
        const fields = ['summary', 'cover', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles'];
        const activeFields = fields.filter(f => {
            const cb = document.getElementById(`field-${f}-${id}`);
            return cb && cb.checked;
        }).join(',');
        
        btn.style.display = 'none';
        btn.previousElementSibling.style.display = 'none'; 
        let loading = btn.nextElementSibling;
        loading.style.display = 'inline-block';
        
        // Envoi au serveur incluant publisher_pref + alt_title_langs
        fetch(getRootPath() + '/save-override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `series_id=${id}&forced_id=${encodeURIComponent(forcedId)}&alternative_title=${encodeURIComponent(altTitle)}&forced_provider=${encodeURIComponent(forcedProvider)}&targeted_fields=${encodeURIComponent(activeFields)}&publisher_pref=${encodeURIComponent(publisherPref)}&alt_title_langs=${encodeURIComponent(altTitleLangs)}`
        })
        .then(res => {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json().catch(() => ({}));
        })
        .then(() => proceedSyncSingle(id, name, btn, loading))
        .catch(() => {
            loading.style.display = 'none';
            btn.style.display = 'inline-block';
            btn.previousElementSibling.style.display = 'inline-block';
            btn.innerText = "❌ Fail";
            setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
        });
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

    const restoreBtn = () => {
        loading.style.display = 'none';
        btn.style.display = 'inline-block';
        btn.previousElementSibling.style.display = 'inline-block';
    };

    fetch(getRootPath() + '/force-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${id}&series_name=${encodeURIComponent(name)}`
    })
    .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
    })
    .then(data => {
        restoreBtn();
        if(data.success) {
            btn.innerText = "✅ OK";
        } else {
            btn.innerText = "❌ Fail";
        }
        setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
    })
    .catch(() => {
        restoreBtn();
        btn.innerText = "❌ Fail";
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

    showBatchProgress(ids.length);

    batchEnqueueAbort = false;
    if (batchEnqueueController) {
        try { batchEnqueueController.abort(); } catch (e) { /* ignore */ }
    }
    batchEnqueueController = typeof AbortController !== 'undefined' ? new AbortController() : null;

    btn.innerText = window.AppTranslations.batch_sending;
    
    const batchFieldsMask = getBatchTargetedFieldsMask();
    let stopped = false;

    for (let i = 0; i < ids.length; i += 50) {
        if (batchEnqueueAbort) {
            stopped = true;
            break;
        }

        const batch = ids.slice(i, i + 50);
        const formData = new FormData();
        
        const libInput = form.querySelector('[name="library_id"]');
        if(libInput) formData.append('library_id', libInput.value);
        
        const forceUpdateCb = document.getElementById('sidebar_force_update');
        if (forceUpdateCb && forceUpdateCb.checked) {
            formData.append('force_update', 'true');
        }

        if (batchFieldsMask !== null) {
            formData.append('targeted_fields', batchFieldsMask);
        }

        // Premier paquet : réarme l'acceptation serveur après un Stop précédent.
        if (i === 0) {
            formData.append('resume_enqueue', 'true');
        }
        
        batch.forEach(id => formData.append('selected_series', id));

        try {
            const fetchOpts = { method: 'POST', body: formData };
            if (batchEnqueueController) fetchOpts.signal = batchEnqueueController.signal;
            const res = await fetch(getRootPath() + '/batch-sync', fetchOpts);
            if (batchEnqueueAbort) {
                stopped = true;
                break;
            }
            if (res.status === 409) {
                stopped = true;
                break;
            }
        } catch (err) {
            if (batchEnqueueAbort || (err && err.name === 'AbortError')) {
                stopped = true;
                break;
            }
            throw err;
        }
    }

    batchEnqueueController = null;
    if (stopped || batchEnqueueAbort) {
        btn.innerText = window.AppTranslations.batch_stopped || '🛑 Batch stopped!';
    } else {
        btn.innerText = window.AppTranslations.batch_ok;
    }
    setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 4000);
}

/** Coupe l'envoi des paquets UI (×50) ET vide la file serveur. */
function stopBatch() {
    batchEnqueueAbort = true;
    if (batchEnqueueController) {
        try { batchEnqueueController.abort(); } catch (e) { /* ignore */ }
    }
    hideBatchProgress();
    fetch(getRootPath() + '/stop-batch', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        const btn = document.getElementById('mainBatchBtn');
        if (btn) btn.innerText = window.AppTranslations.batch_stopped || window.AppTranslations.launchBatch;
        setTimeout(() => {
            if (btn) btn.innerText = window.AppTranslations.launchBatch;
        }, 3000);
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
            restoreBatchSelection();
            filterSeries(); // recalcule selectAll / compteur après restauration
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
