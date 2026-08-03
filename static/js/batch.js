// --- LISTE DE SÉRIES : FILTRAGE, SÉLECTION, SYNCHRONISATION UNITAIRE/LOT, IGNORER ---
// Dépend de utils.js (getRootPath).

const BATCH_SELECTION_PREFIX = 'mk_batch_selection:';

/** Stop pendant l'envoi des paquets ×50 : coupe la boucle + AbortController. */
var batchEnqueueAbort = false;
var batchEnqueueController = null;

// --- Sélection index-first (BF94 / #30 / C63) ---
// Source de vérité = Sets JS. Le DOM (checkbox) n'est qu'un reflet des rows montées.
// « Visible » = matched (filtre), jamais le viewport virtualisé.
var selectedIds = new Set();
var matchedIds = [];
var matchedSet = new Set();

function getFilteredSelectedIds() {
    var out = [];
    for (var i = 0; i < matchedIds.length; i++) {
        var id = matchedIds[i];
        if (selectedIds.has(id)) out.push(id);
    }
    return out;
}

function syncSelectAllCheckbox() {
    var selectAll = document.getElementById('selectAll');
    if (!selectAll) return;
    selectAll.checked = matchedIds.length > 0 && getFilteredSelectedIds().length === matchedIds.length;
}

function syncMountedCheckboxes() {
    document.querySelectorAll('.series-cb').forEach(function (cb) {
        cb.checked = selectedIds.has(String(cb.value));
    });
}

function setSeriesSelected(seriesId, checked) {
    var id = String(seriesId);
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
}

function clearSeriesSelection() {
    selectedIds.clear();
}

function replaceSelectionWithMatched() {
    selectedIds = new Set(matchedIds);
}

function uncheckSeriesIdForBatchResume(seriesId) {
    var id = String(seriesId);
    selectedIds.delete(id);
    document.querySelectorAll('.series-cb').forEach(function (cb) {
        if (String(cb.value) === id) cb.checked = false;
    });
    syncSelectAllCheckbox();
    saveBatchSelection();
}

/** Total du batch courant (fixé au lancement UI ; barre via événement batch_progress). */
var batchProgressTotal = 0;
var batchProgressDone = 0;
var batchProgressHideTimer = null;
/** Évite un double overlay supporter à la fin du même batch. */
var batchNagFired = false;
/** Empêche syncMainBatchBtnLabel d’écraser « Envoi… / Lancé / Stop ». */
var mainBatchBtnBusy = false;
/** Empêche un 2ᵉ launchBatch d’abort le premier envoi (×50). */
var batchEnqueueInFlight = false;

function isBatchInProgress() {
    return batchProgressTotal > 0;
}

function mainBatchIdleLabel() {
    const T = window.AppTranslations || {};
    if (isBatchInProgress()) {
        return T.launch_batch_append || T.launchBatch || '➕ Add to waiting list';
    }
    return T.launchBatch || '▶ Run selection';
}

function mainBatchIdleHint() {
    const T = window.AppTranslations || {};
    if (isBatchInProgress()) {
        return T.launch_batch_append_hint || T.launch_batch_hint || '';
    }
    return T.launch_batch_hint || '';
}

function syncMainBatchBtnLabel() {
    const btn = document.getElementById('mainBatchBtn');
    if (!btn || mainBatchBtnBusy) return;
    btn.innerText = mainBatchIdleLabel();
    const hint = mainBatchIdleHint();
    if (hint) btn.title = hint;
}

function showBatchProgress(total) {
    batchProgressTotal = Math.max(0, parseInt(total, 10) || 0);
    batchProgressDone = 0;
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
    syncMainBatchBtnLabel();
}

/** Ajoute au total UI sans remettre la barre à 0 % (append / paquets suivants). */
function bumpBatchProgressTotal(delta) {
    const d = Math.max(0, parseInt(delta, 10) || 0);
    if (d === 0) return;
    if (batchProgressHideTimer) {
        clearTimeout(batchProgressHideTimer);
        batchProgressHideTimer = null;
    }
    batchProgressTotal += d;
    const wrap = document.getElementById('batchProgressWrap');
    if (wrap) {
        wrap.style.display = '';
        wrap.setAttribute('aria-hidden', 'false');
    }
    updateBatchProgressUI(batchProgressDone, batchProgressTotal);
    syncMainBatchBtnLabel();
}

function hideBatchProgress() {
    batchProgressTotal = 0;
    batchProgressDone = 0;
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
    syncMainBatchBtnLabel();
}

function updateBatchProgressUI(done, total) {
    const label = document.getElementById('batchProgressLabel');
    const fill = document.getElementById('batchProgressFill');
    const track = document.querySelector('#batchProgressWrap .batch-progress-track');
    const safeTotal = Math.max(0, total || 0);
    const safeDone = Math.max(0, Math.min(safeTotal, done || 0));
    batchProgressDone = safeDone;
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
    localStorage.setItem(getBatchSelectionKey(), JSON.stringify(Array.from(selectedIds)));
    updateSelectionCounters();
}

function restoreBatchSelection() {
    let saved;
    try {
        saved = JSON.parse(localStorage.getItem(getBatchSelectionKey()) || '[]');
    } catch (e) {
        saved = [];
    }
    selectedIds = new Set(Array.isArray(saved) ? saved.map(String) : []);
    syncMountedCheckboxes();
    if (typeof filterSeries === 'function') filterSeries();
    else {
        syncSelectAllCheckbox();
        saveBatchSelection();
    }
}

function isSeriesItemVisible(item) {
    return !!(item && !item.classList.contains('is-filtered-out'));
}

/** Cases cochées parmi les séries actuellement affichées (filtre + recherche). */
function getVisibleCheckedSeriesCbs(root) {
    const want = new Set(getFilteredSelectedIds());
    const scope = root || document;
    return Array.from(scope.querySelectorAll('.series-cb')).filter(cb => {
        return want.has(String(cb.value)) && isSeriesItemVisible(cb.closest('.series-item'));
    });
}

function getVisibleCheckedSeriesIds(root) {
    // root ignoré volontairement : source = Set ∩ matched (C63 / virtual-safe).
    return getFilteredSelectedIds();
}

/** Badge : cochées *visibles* = ce que le prochain batch / Ajouter à la file emportera. */
function updateSelectionCounters() {
    const el = document.getElementById('selectedCount');
    if (!el) return;
    const T = window.AppTranslations || {};
    const batchCount = getFilteredSelectedIds().length;
    // Toujours garder un libellé (même à 0) pour réserver la largeur du badge
    // et éviter que « Tout sélectionner » bouge à l’apparition du compteur.
    const tpl = T.selected_count || '{0} selected';
    el.textContent = tpl.replace('{0}', String(batchCount));
    el.hidden = batchCount === 0;
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
    
    matchedIds = [];
    matchedSet = new Set();

    // Si une liste virtualisée est active, elle recalcule matched + rend la fenêtre.
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.filterAndRender === 'function') {
        const usedVirtual = window.SeriesList.filterAndRender({
            filter: filter,
            hideIgnored: hideIgnored,
            searchQuery: searchQuery,
            searchInside: searchInside,
        });
        if (usedVirtual !== false) {
            const countElemV = document.getElementById('visibleCount');
            if (countElemV) {
                const n = matchedIds.length;
                countElemV.textContent = n + (n > 1 ? window.AppTranslations.elements : window.AppTranslations.element);
            }
            syncSelectAllCheckbox();
            updateSelectionCounters();
            return;
        }
    }

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
        item.classList.toggle('is-filtered-out', !show);
        if (show) {
            const cb = item.querySelector('.series-cb');
            const sid = cb ? String(cb.value) : '';
            if (sid) {
                matchedIds.push(sid);
                matchedSet.add(sid);
            }
        }
    });

    syncSelectAllCheckbox();

    const countElem = document.getElementById('visibleCount');
    if (countElem) {
        const count = matchedIds.length;
        countElem.textContent = count + (count > 1 ? window.AppTranslations.elements : window.AppTranslations.element);
    }
    updateSelectionCounters();
}

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    if (!selectAll) return;
    if (selectAll.checked) {
        replaceSelectionWithMatched();
    } else {
        clearSeriesSelection();
    }
    syncMountedCheckboxes();
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.refreshMountedChecks === 'function') {
        window.SeriesList.refreshMountedChecks();
    }
    saveBatchSelection();
}

// Délégation : toute case série → Set puis persistance
document.addEventListener('change', function(e) {
    if (e.target && e.target.classList && e.target.classList.contains('series-cb')) {
        setSeriesSelected(e.target.value, !!e.target.checked);
        syncSelectAllCheckbox();
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

    if (batchEnqueueInFlight) return;

    if (ids.length === 0) {
        mainBatchBtnBusy = true;
        btn.innerText = window.AppTranslations.batch_empty;
        setTimeout(function () {
            mainBatchBtnBusy = false;
            syncMainBatchBtnLabel();
        }, 2000);
        return;
    }

    const wasRunning = isBatchInProgress();
    // Total UI = ajouts réels (body.added / hydrate), pas ids.length (ignore les doublons).
    if (!wasRunning) {
        showBatchProgress(Math.min(ids.length, 50));
    }

    if (typeof mrPrepareForBatch === "function") {
        mrPrepareForBatch();
    }

    batchEnqueueAbort = false;
    batchEnqueueInFlight = true;
    batchEnqueueController = typeof AbortController !== 'undefined' ? new AbortController() : null;

    mainBatchBtnBusy = true;
    btn.innerText = window.AppTranslations.batch_sending;

    const batchFieldsMask = getBatchTargetedFieldsMask();
    let stopped = false;
    let totalAdded = 0;
    let totalDupes = 0;
    let lastPaused = false;
    let lastCount = null;
    let didResume = false;
    let resumeTotalLocked = false;

    try {
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
            const added = Number(body.added || 0);
            totalAdded += added;
            totalDupes += Number(body.skipped_dupes || 0);
            lastPaused = !!body.paused;
            if (body.count != null) lastCount = body.count;

            if (body.resumed) {
                didResume = true;
                const hydrated = Number(body.hydrated || 0);
                // 1ʳᵉ réponse reprise : total absolu = file hydratée. Paquets suivants : +added.
                if (!resumeTotalLocked && hydrated > 0) {
                    showBatchProgress(hydrated);
                    resumeTotalLocked = true;
                } else if (added > 0) {
                    bumpBatchProgressTotal(added);
                }
            } else if (added > 0) {
                if (!wasRunning && i === 0 && !didResume) {
                    showBatchProgress(added);
                } else {
                    bumpBatchProgressTotal(added);
                }
            }
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
    } finally {
        batchEnqueueController = null;
        batchEnqueueInFlight = false;
    }

    if (lastCount != null) updateBatchQueueBadge(lastCount, lastPaused);
    else refreshBatchQueueBadge();
    showBatchQueueToast(totalAdded, totalDupes);
    // Cacher seulement si rien n'a démarré / file pausée — pas si un batch tournait déjà
    // et que l'ajout n'était que des doublons.
    if (lastPaused) {
        hideBatchProgress();
    } else if (totalAdded === 0 && !didResume && !wasRunning) {
        hideBatchProgress();
    }
    if (document.getElementById('batchQueueModal') && !document.getElementById('batchQueueModal').hidden) {
        loadBatchQueueModal();
    }

    if (stopped || batchEnqueueAbort) {
        btn.innerText = window.AppTranslations.batch_stopped || '🛑 Batch stopped!';
    } else {
        btn.innerText = window.AppTranslations.batch_ok;
    }
    setTimeout(function () {
        mainBatchBtnBusy = false;
        syncMainBatchBtnLabel();
    }, 4000);
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
    syncMainBatchBtnLabel();
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
        mainBatchBtnBusy = true;
        if (btn) btn.innerText = window.AppTranslations.batch_stopped || window.AppTranslations.launchBatch;
        setTimeout(function () {
            mainBatchBtnBusy = false;
            syncMainBatchBtnLabel();
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

            // Nouveau DOM : vider les panneaux Options + ré-init liste virtualisée.
            if (typeof clearOverridePanelCache === 'function') {
                clearOverridePanelCache();
            }
            if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.init === 'function') {
                window.SeriesList.init();
            }

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
    // IDs filtrés cochés (Set) — pas le viewport (virtual / C63).
    const ids = getFilteredSelectedIds();
    if (ids.length === 0) return;

    const btn = document.getElementById('batchIgnoreBtn');
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    btn.disabled = true;

    for (let seriesId of ids) {
        let currentStatus = 'PENDING';
        if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.getItem === 'function') {
            const idx = window.SeriesList.getItem(seriesId);
            if (idx && idx.status) currentStatus = idx.status;
        } else {
            const seriesItem = document.querySelector('.series-item[data-series-id="' + seriesId + '"]')
                || Array.from(document.querySelectorAll('.series-item')).find(function (it) {
                    const cb = it.querySelector('.series-cb');
                    return cb && String(cb.value) === String(seriesId);
                });
            if (seriesItem) currentStatus = seriesItem.dataset.status || 'PENDING';
        }

        if (currentStatus !== 'IGNORED') {
            try {
                const res = await fetch(getRootPath() + '/toggle-ignore', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `series_id=${seriesId}&current_status=${currentStatus}`
                });
                const data = await res.json();

                if (data.success) {
                    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.updateStatus === 'function') {
                        window.SeriesList.updateStatus(seriesId, 'IGNORED');
                    }
                    const seriesItem = document.querySelector('.series-item[data-series-id="' + seriesId + '"]');
                    if (seriesItem) {
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
                }
            } catch (e) {
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
