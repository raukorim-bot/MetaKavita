// --- LISTE DE SÉRIES : FILTRAGE, SÉLECTION, SYNCHRONISATION UNITAIRE/LOT, IGNORER ---
// Dépend de utils.js (getRootPath).

const BATCH_SELECTION_PREFIX = 'mk_batch_selection:';

/** Stop pendant l'envoi des paquets ×50 : coupe la boucle + AbortController. */
var batchEnqueueAbort = false;
var batchEnqueueController = null;

/** Total du batch courant (fixé au lancement UI ; barre via événement batch_progress). */
var batchProgressTotal = 0;
var batchProgressHideTimer = null;
/** Évite un double overlay supporter à la fin du même batch. */
var batchNagFired = false;

function showBatchProgress(total) {
    batchProgressTotal = Math.max(0, parseInt(total, 10) || 0);
    batchNagFired = false;
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
        if (!batchNagFired && batchProgressTotal > 0) {
            batchNagFired = true;
            try {
                if (window.SupporterNag && typeof window.SupporterNag.onBatchComplete === 'function') {
                    // real_sends (services/background_tasks.py) : nombre de séries
                    // RÉELLEMENT écrites vers Kavita. Un batch entièrement composé de
                    // séries déjà à jour (skip silencieux) tombe à 0 — le nagware
                    // supporter ne doit pas se déclencher pour rien.
                    const realSends = parseInt(payload.real_sends, 10);
                    window.SupporterNag.onBatchComplete({
                        remaining: 0,
                        stopped: false,
                        total: batchProgressTotal,
                        real_sends: isNaN(realSends) ? 0 : realSends,
                    });
                }
            } catch (e) { /* pubs supporter : jamais bloquer le batch */ }
        }
    }
}

function getBatchSelectionKey() {
    const lib = localStorage.getItem('filter_library') || '';
    return BATCH_SELECTION_PREFIX + (lib || 'all');
}

/** Persiste tous les IDs cochés (y compris hors filtre) — reprise après refresh. */
function saveBatchSelection() {
    const ids = Array.from(document.querySelectorAll('.series-cb:checked')).map(cb => String(cb.value));
    localStorage.setItem(getBatchSelectionKey(), JSON.stringify(ids));
    updateSelectionCounters();
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

    // Sync compteur / case « tout sélectionner » ; ne touche pas aux coches hors écran.
    if (typeof filterSeries === 'function') filterSeries();
    saveBatchSelection();
}

function isSeriesItemVisible(item) {
    return !!(item && !item.classList.contains('is-filtered-out'));
}

/** Cases cochées parmi les séries actuellement affichées (filtre + recherche). */
function getVisibleCheckedSeriesCbs(root) {
    const scope = root || document;
    return Array.from(scope.querySelectorAll('.series-cb:checked')).filter(cb => {
        return isSeriesItemVisible(cb.closest('.series-item'));
    });
}

function getVisibleCheckedSeriesIds(root) {
    return getVisibleCheckedSeriesCbs(root).map(cb => String(cb.value));
}

/** Badge : cochées *visibles* = ce que le prochain batch emportera. */
function updateSelectionCounters() {
    const el = document.getElementById('selectedCount');
    if (!el) return;
    const T = window.AppTranslations || {};
    const batchCount = getVisibleCheckedSeriesCbs().length;
    if (batchCount === 0) {
        el.hidden = true;
        el.textContent = '';
        return;
    }
    el.hidden = false;
    el.textContent = (T.selected_count || '{0} selected').replace('{0}', String(batchCount));
}

function titleMatchesSearch(title, query, searchInside) {
    if (!query) return true;
    if (searchInside) return title.includes(query);
    return title.startsWith(query);
}

// Issue #30: debounce search keystrokes; filter itself avoids innerText reflows.
var _filterSeriesTimer = null;
function scheduleFilterSeries() {
    if (_filterSeriesTimer) clearTimeout(_filterSeriesTimer);
    _filterSeriesTimer = setTimeout(function () {
        _filterSeriesTimer = null;
        filterSeries();
    }, 150);
}

function filterSeries() {
    const statusFilter = document.getElementById('statusFilter');
    // Pas de toolbar si Kavita n'est pas connecté (carte welcome) — no-op.
    if (!statusFilter) return;

    const filter = statusFilter.value;
    const hideIgnoredCb = document.getElementById('hideIgnoredCb');
    const hideIgnored = hideIgnoredCb ? hideIgnoredCb.checked : false;
    const searchInsideCb = document.getElementById('searchInsideCb');
    const searchInside = searchInsideCb ? !!searchInsideCb.checked : false;
    
    const searchInput = document.getElementById('searchInput');
    const searchQuery = searchInput ? searchInput.value.toLowerCase().trim() : '';
    
    localStorage.setItem('filter_status', filter);
    if (hideIgnoredCb) localStorage.setItem('filter_hide_ignored', hideIgnored ? 'true' : 'false');
    if (searchInsideCb) localStorage.setItem('filter_search_inside', searchInside ? 'true' : 'false');
    if (searchInput) localStorage.setItem('filter_search', searchQuery);
    
    let count = 0;
    let visibleChecked = 0;
    let visibleTotal = 0;
    
    document.querySelectorAll('.series-item').forEach(item => {
        const status = item.dataset.status;
        // Prefer precomputed data-search-title (no layout). Fallback: textContent (still no reflow).
        const title = (item.dataset.searchTitle
            || (item.querySelector('.series-name') || {}).textContent
            || '').toLowerCase();
        
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
            if (!titleMatchesSearch(title, searchQuery, searchInside)) {
                show = false;
            }
        }
        
        // Class toggle batches style work; avoid per-item inline display writes (#30).
        // Ne pas décocher : une faute de frappe / un filtre ne doit pas détruire la sélection.
        // Le batch / ignore de masse ne prennent que les cochées *visibles*.
        item.classList.toggle('is-filtered-out', !show);
        if (show) {
            count++;
            visibleTotal++;
            const cb = item.querySelector('.series-cb');
            if (cb && cb.checked) visibleChecked++;
        }
    });
    
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.checked = visibleTotal > 0 && visibleChecked === visibleTotal;
    }
    
    const countElem = document.getElementById('visibleCount');
    if(countElem) {
        countElem.textContent = count + (count > 1 ? window.AppTranslations.elements : window.AppTranslations.element);
    }
    updateSelectionCounters();
}

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    if (!selectAll) return;
    const isChecked = selectAll.checked;
    document.querySelectorAll('.series-item').forEach(item => {
        const cb = item.querySelector('.series-cb');
        if (!cb) return;
        if (isChecked) {
            // Cocher = sélection devient exactement le visible.
            cb.checked = isSeriesItemVisible(item);
        } else {
            // Décocher = vider toute la sélection (évite une file « fantôme » hors filtre).
            cb.checked = false;
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
function getSeriesActionEls(btn) {
    const actions = btn.closest('.series-actions') || btn.parentElement;
    return {
        actions,
        optionsBtn: actions ? actions.querySelector('[data-action="options"]') : null,
        loading: actions ? actions.querySelector('[data-action="loading"], .loading') : null,
    };
}

function setSeriesSyncBusy(btn, busy) {
    const { optionsBtn, loading } = getSeriesActionEls(btn);
    btn.style.display = busy ? 'none' : 'inline-block';
    if (optionsBtn) optionsBtn.style.display = busy ? 'none' : 'inline-block';
    if (loading) loading.style.display = busy ? 'inline-block' : 'none';
    return loading;
}

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
        
        const fields = ['summary', 'cover', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles', 'language'];
        const activeFields = fields.filter(f => {
            const cb = document.getElementById(`field-${f}-${id}`);
            return cb && cb.checked;
        }).join(',');
        
        const loading = setSeriesSyncBusy(btn, true);
        
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
            setSeriesSyncBusy(btn, false);
            btn.innerText = "❌ Fail";
            setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
        });
    } else {
        proceedSyncSingle(id, name, btn, null);
    }
}

function proceedSyncSingle(id, name, btn, loadingElem) {
    let loading = loadingElem;
    if (!loading) {
        loading = setSeriesSyncBusy(btn, true);
    }

    if (typeof mrPrepareForBatch === "function") {
        mrPrepareForBatch();
    }

    const restoreBtn = () => {
        setSeriesSyncBusy(btn, false);
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
        if (typeof mrOnSyncSettled === "function") mrOnSyncSettled();
        if(data.success) {
            btn.innerText = "✅ OK";
        } else {
            btn.innerText = "❌ Fail";
        }
        setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
    })
    .catch(() => {
        restoreBtn();
        if (typeof mrOnSyncSettled === "function") mrOnSyncSettled();
        btn.innerText = "❌ Fail";
        setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
    });
}

async function launchBatch(event) {
    event.preventDefault();
    const form = event.target;
    const btn = document.getElementById('mainBatchBtn');
    // Uniquement les séries affichées (filtre statut / recherche) — pas l'arrière-plan coché.
    const ids = getVisibleCheckedSeriesIds(form);
    
    if (ids.length === 0) {
        btn.innerText = window.AppTranslations.batch_empty;
        setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 2000);
        return;
    }

    showBatchProgress(ids.length);

    if (typeof mrPrepareForBatch === "function") {
        mrPrepareForBatch();
    }

    batchEnqueueAbort = false;
    if (batchEnqueueController) {
        try { batchEnqueueController.abort(); } catch (e) { /* ignore */ }
    }
    batchEnqueueController = typeof AbortController !== 'undefined' ? new AbortController() : null;

    btn.innerText = window.AppTranslations.batch_sending;
    
    const batchFieldsMask = getBatchTargetedFieldsMask();
    let stopped = false;
    let totalAdded = 0;
    let totalDupes = 0;
    let lastPaused = false;
    let lastCount = null;

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
                hideBatchProgress();
                break;
            }
            const body = await res.json().catch(function () { return {}; });
            if (body && body.success === false) {
                stopped = true;
                break;
            }
            totalAdded += Number(body.added || 0);
            totalDupes += Number(body.skipped_dupes || 0);
            lastPaused = !!body.paused;
            if (body.count != null) lastCount = body.count;
            // Ne pas décocher ici : reprise = cases jusqu'à COMPLETED / NEEDS_RELOCK.
        } catch (err) {
            if (batchEnqueueAbort || (err && err.name === 'AbortError')) {
                stopped = true;
                break;
            }
            if (typeof mrOnSyncSettled === "function") mrOnSyncSettled();
            throw err;
        }
    }

    batchEnqueueController = null;
    if (lastCount != null) updateBatchQueueBadge(lastCount, lastPaused);
    else refreshBatchQueueBadge();
    showBatchQueueToast(totalAdded, totalDupes);
    if (lastPaused || totalAdded === 0) hideBatchProgress();
    if (document.getElementById('batchQueueModal') && !document.getElementById('batchQueueModal').hidden) {
        loadBatchQueueModal();
    }

    if (stopped || batchEnqueueAbort) {
        btn.innerText = window.AppTranslations.batch_stopped || '🛑 Batch stopped!';
    } else {
        btn.innerText = window.AppTranslations.batch_ok;
    }
    setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 4000);
}

function showBatchQueueToast(added, dupes) {
    const el = document.getElementById('batchQueueToast');
    if (!el) return;
    const T = window.AppTranslations || {};
    let msg;
    if (dupes > 0) {
        msg = (T.batch_queue_toast_dupes || '{0} added, {1} already queued')
            .replace('{0}', String(added)).replace('{1}', String(dupes));
    } else {
        msg = (T.batch_queue_toast || '{0} added to queue').replace('{0}', String(added));
    }
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showBatchQueueToast._t);
    showBatchQueueToast._t = setTimeout(function () { el.hidden = true; }, 3200);
}

function updateBatchQueueBadge(count, paused) {
    const badge = document.getElementById('batchQueueBadge');
    if (!badge) return;
    const n = Number(count) || 0;
    if (n <= 0 && !paused) {
        badge.hidden = true;
        badge.textContent = '';
        return;
    }
    const T = window.AppTranslations || {};
    badge.hidden = false;
    badge.textContent = paused
        ? (n + ' · ' + (T.batch_queue_paused_badge || 'pause'))
        : String(n);
}

async function refreshBatchQueueBadge() {
    try {
        const res = await fetch(getRootPath() + '/api/batch-queue');
        const data = await res.json();
        if (data && data.success !== false) {
            updateBatchQueueBadge(data.count, data.paused);
        }
    } catch (e) { /* ignore */ }
}

function openBatchQueueModal() {
    const modal = document.getElementById('batchQueueModal');
    if (!modal) return;
    modal.hidden = false;
    loadBatchQueueModal();
}

function closeBatchQueueModal() {
    const modal = document.getElementById('batchQueueModal');
    if (modal) modal.hidden = true;
}

async function loadBatchQueueModal() {
    const list = document.getElementById('batchQueueList');
    if (!list) return;
    const T = window.AppTranslations || {};
    try {
        const res = await fetch(getRootPath() + '/api/batch-queue');
        const data = await res.json();
        updateBatchQueueBadge(data.count, data.paused);
        const items = data.items || [];
        if (!items.length) {
            list.innerHTML = '<p class="bq-empty">' + (T.batch_queue_empty || 'Empty') + '</p>';
            return;
        }
        list.innerHTML = items.map(function (it) {
            const stateLabel = it.state === 'running'
                ? (T.batch_queue_state_running || 'Running')
                : (T.batch_queue_state_queued || 'Queued');
            const removeBtn = it.state === 'queued'
                ? '<button type="button" class="btn-secondary bq-remove" data-id="' + it.id + '">'
                    + (T.batch_queue_remove || 'Remove') + '</button>'
                : '';
            return '<div class="bq-row" data-state="' + it.state + '">'
                + '<span class="bq-name"></span>'
                + '<span class="bq-state">' + stateLabel + '</span>'
                + removeBtn + '</div>';
        }).join('');
        const rows = list.querySelectorAll('.bq-row');
        items.forEach(function (it, idx) {
            const nameEl = rows[idx] && rows[idx].querySelector('.bq-name');
            if (nameEl) nameEl.textContent = it.series_name || ('#' + it.series_id);
        });
        list.querySelectorAll('.bq-remove').forEach(function (btn) {
            btn.addEventListener('click', function () {
                removeBatchQueueItem(btn.getAttribute('data-id'));
            });
        });
    } catch (e) {
        list.innerHTML = '<p class="bq-empty">Error</p>';
    }
}

async function removeBatchQueueItem(id) {
    if (!id) return;
    await fetch(getRootPath() + '/api/batch-queue/' + encodeURIComponent(id), { method: 'DELETE' });
    loadBatchQueueModal();
}

async function clearBatchQueue() {
    const T = window.AppTranslations || {};
    if (!window.confirm(T.batch_queue_clear_confirm || 'Clear queue?')) return;
    await fetch(getRootPath() + '/api/batch-queue/clear', { method: 'POST' });
    loadBatchQueueModal();
}

async function pauseBatchQueue() {
    await fetch(getRootPath() + '/api/batch-queue/pause', { method: 'POST' });
    loadBatchQueueModal();
    hideBatchProgress();
}

async function resumeBatchQueue() {
    const res = await fetch(getRootPath() + '/api/batch-queue/resume', { method: 'POST' });
    const data = await res.json().catch(function () { return {}; });
    if (data.hydrated > 0) showBatchProgress(data.hydrated);
    loadBatchQueueModal();
}

document.addEventListener('DOMContentLoaded', function () {
    refreshBatchQueueBadge();
});

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
                
                const ignoreBtn = item.querySelector('.series-actions [data-action="ignore"]');
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
            
            const currentStats = document.querySelector('.sidebar .sidebar-stats-card');
            const newStats = doc.querySelector('.sidebar .sidebar-stats-card');
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
    const checkboxes = getVisibleCheckedSeriesCbs();
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
                    const ignoreBtn = seriesItem.querySelector('.series-actions [data-action="ignore"]');
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

/** Met à jour badge (+ bouton seal) pour un statut série. */
function applySeriesStatusBadge(item, status) {
    if (!item) return;
    item.dataset.status = status || item.dataset.status;
    var statusWrap = item.querySelector('.series-status');
    if (!statusWrap) return;
    var badge = statusWrap.querySelector('.badge');
    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'badge';
        statusWrap.prepend(badge);
    }
    var sealBtn = statusWrap.querySelector('.btn-seal-locks');
    var T = window.AppTranslations || {};
    if (status === 'COMPLETED') {
        badge.className = 'badge badge-completed';
        badge.innerText = T.filter_completed || 'Completed';
        badge.removeAttribute('title');
        if (sealBtn) sealBtn.remove();
    } else if (status === 'NEEDS_RELOCK') {
        badge.className = 'badge badge-needs-relock';
        badge.innerText = T.filter_needs_relock || 'Needs seal';
        badge.title = T.filter_needs_relock_hint || '';
        if (!sealBtn) {
            sealBtn = document.createElement('button');
            sealBtn.type = 'button';
            sealBtn.className = 'btn-icon btn-seal-locks';
            sealBtn.textContent = '🔒';
            sealBtn.title = T.seal_locks_btn || 'Seal locks';
            var cb = item.querySelector('.series-cb');
            var sid = cb ? cb.value : '';
            sealBtn.onclick = function () { sealSeriesLocks(sid, sealBtn); };
            statusWrap.appendChild(sealBtn);
        }
    } else if (status === 'PENDING_REVIEW') {
        badge.className = 'badge badge-review';
        badge.innerText = T.filter_pending_review || 'Review';
        if (sealBtn) sealBtn.remove();
    } else if (status === 'NOT_FOUND') {
        badge.className = 'badge badge-notfound';
        badge.innerText = T.filter_notfound || 'Not found';
        if (sealBtn) sealBtn.remove();
    } else if (status === 'IGNORED') {
        badge.className = 'badge badge-ignored';
        badge.innerText = T.filter_ignored || 'Ignored';
        if (sealBtn) sealBtn.remove();
    } else {
        badge.className = 'badge badge-pending';
        badge.innerText = T.filter_pending || 'Pending';
        if (sealBtn) sealBtn.remove();
    }
    if (typeof filterSeries === 'function') filterSeries();
}

async function sealSeriesLocks(seriesId, btn) {
    if (!seriesId) return;
    var T = window.AppTranslations || {};
    if (btn) {
        btn.disabled = true;
        btn.textContent = '…';
    }
    try {
        var res = await fetch(getRootPath() + '/api/series/' + encodeURIComponent(seriesId) + '/seal-locks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin'
        });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok || !data.success) {
            throw new Error((data && data.error) || T.seal_locks_fail || 'Seal failed');
        }
        var item = btn ? btn.closest('.series-item') : null;
        if (!item) {
            document.querySelectorAll('.series-item').forEach(function (el) {
                var cb = el.querySelector('.series-cb');
                if (cb && String(cb.value) === String(seriesId)) item = el;
            });
        }
        if (item) applySeriesStatusBadge(item, 'COMPLETED');
    } catch (e) {
        console.error('[MetaKavita] seal-locks', e);
        alert((e && e.message) || T.seal_locks_fail || 'Seal failed');
        if (btn) {
            btn.disabled = false;
            btn.textContent = '🔒';
        }
    }
}
