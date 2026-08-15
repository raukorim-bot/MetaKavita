// --- WEBSOCKETS : journal, statuts, barre de lot ---
// Le liséré violet de la série en cours est posé par batch.js
// (`batch_progress.series_id`), plus par le texte du journal.
// Dépend de utils.js (getRootPath). La variable globale `socket` est réutilisée
// par covers.js (flux de couvertures en direct) : ce fichier doit donc être
// chargé AVANT covers.js.
// Companion Super Review: pass embed_token so Socket.IO works without a
// SameSite session cookie inside a cross-origin Kavita iframe.
(function () {
    var opts = { path: getRootPath() + '/socket.io' };
    var cfg = window.COMPANION_EMBED;
    if (cfg && cfg.embedToken) {
        opts.auth = {
            embed_token: cfg.embedToken,
            series_id: cfg.seriesId
        };
        opts.query = {
            embed_token: cfg.embedToken,
            series_id: cfg.seriesId
        };
    }
    window.socket = io(opts);
})();
var socket = window.socket;
var logConsole = document.getElementById('log-console');
socket.on('connect', function() {
    if (!logConsole) return;
    var ready = (window.AppTranslations && window.AppTranslations.terminal_ready) || 'Ready';
    logConsole.innerHTML += '<div class="log-line" style="color: var(--primary);">' + ready + '</div>';
});
socket.on('log_update', function(msg) {
    if (!logConsole) return;
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
});

function _handleHygieneProgress(payload) {
    if (typeof window._onHygieneProgress === 'function') {
        window._onHygieneProgress(payload || {});
    }
}
socket.on('hygiene_progress', _handleHygieneProgress);
socket.on('volume_hygiene_progress', _handleHygieneProgress);

// Passe d'enrichissement par tome : sa propre barre, distincte de l'analyse.
socket.on('volume_enrich_progress', function (payload) {
    if (typeof window._onVolumeEnrichProgress === 'function') {
        window._onVolumeEnrichProgress(payload || {});
    }
});

socket.on('series_status', function(payload) {
    if (!payload || payload.series_id == null) return;
    var sid = String(payload.series_id);
    var status = payload.status || '';
    var found = false;
    document.querySelectorAll('.series-item').forEach(function(item) {
        var cb = item.querySelector('.series-cb');
        if (!cb || String(cb.value) !== sid) return;
        found = true;
        if (typeof applySeriesStatusBadge === 'function') {
            applySeriesStatusBadge(item, status);
        }
        // QoS batch : état "traité" → décocher (Set + DOM) pour relancer sans la refaire.
        if (status === 'COMPLETED' || status === 'NEEDS_RELOCK') {
            uncheckSeriesForBatchResume(item, sid);
        }
    });
    // Row absente du DOM (virtual window) : quand même retirer du Set de sélection.
    if (!found && (status === 'COMPLETED' || status === 'NEEDS_RELOCK')) {
        uncheckSeriesForBatchResume(null, sid);
    }
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.updateStatus === 'function') {
        window.SeriesList.updateStatus(sid, status);
    }
});

// Sync unitaire : /force-sync ne fait plus qu'enfiler, c'est ce signal — émis par
// le worker à la fin de CHAQUE job unitaire — qui rend la main au bouton de la
// ligne. `series_status` ne suffirait pas : il ne part que si le statut change
// (Kavita injoignable, série déjà en traitement ailleurs : rien n'est diffusé),
// et une série garée en review manuelle n'est pas un échec.
socket.on('sync_settled', function(payload) {
    if (!payload || payload.series_id == null) return;
    if (typeof window.settleSingleSync === 'function') {
        window.settleSingleSync(String(payload.series_id), !!payload.ok);
    }
});

/** QoS batch : une série OK se décoche pour pouvoir relancer le lot sans re-scraper les déjà faits. */
function uncheckSeriesForBatchResume(item, seriesId) {
    var sid = seriesId;
    if (sid == null && item) {
        var cb0 = item.querySelector('.series-cb');
        sid = cb0 ? cb0.value : null;
    }
    if (sid != null && typeof uncheckSeriesIdForBatchResume === 'function') {
        uncheckSeriesIdForBatchResume(sid);
        return;
    }
    if (!item) return;
    const cb = item.querySelector('.series-cb');
    if (cb) cb.checked = false;
    const selectAll = document.getElementById('selectAll');
    if (selectAll) selectAll.checked = false;
    if (typeof saveBatchSelection === 'function') {
        saveBatchSelection();
    } else if (typeof updateSelectionCounters === 'function') {
        updateSelectionCounters();
    }
}

// Compteurs lifetime + session (reset à la fermeture de l'onglet via sessionStorage)
(function initLiveKpis() {
    var enrichedEl = document.getElementById('kpiEnriched');
    var matchesEl = document.getElementById('kpiMatches');
    var missedEl = document.getElementById('kpiMissed');
    var sessionEl = document.getElementById('kpiSession');
    if (!sessionEl) return;

    var SESSION_KEY = 'mk_session_processed';
    var sessionCount = parseInt(sessionStorage.getItem(SESSION_KEY) || '0', 10);
    if (isNaN(sessionCount) || sessionCount < 0) sessionCount = 0;
    sessionEl.textContent = String(sessionCount);

    function applyLifetime(life) {
        if (!life) return;
        if (enrichedEl) enrichedEl.textContent = String(life.series_enriched || 0);
        if (matchesEl) matchesEl.textContent = String(life.matches_won || 0);
        if (missedEl) missedEl.textContent = String(life.series_missed || 0);
    }

    function bump(el, delta) {
        if (!el || !delta) return;
        var cur = parseInt(el.textContent || '0', 10);
        if (isNaN(cur)) cur = 0;
        el.textContent = String(cur + delta);
    }

    socket.on('enrichment_stats', function(payload) {
        if (!payload) return;
        if (payload.lifetime) {
            applyLifetime(payload.lifetime);
        } else {
            bump(enrichedEl, payload.series_enriched_delta || 0);
            bump(matchesEl, payload.matches_won_delta || 0);
            bump(missedEl, payload.series_missed_delta || 0);
        }
        var processed = (payload.series_enriched_delta || 0) + (payload.series_missed_delta || 0);
        if (processed > 0) {
            sessionCount += processed;
            sessionStorage.setItem(SESSION_KEY, String(sessionCount));
            sessionEl.textContent = String(sessionCount);
        }
    });
})();

socket.on('batch_progress', function(payload) {
    if (typeof applyBatchProgressPayload === 'function') {
        applyBatchProgressPayload(payload);
    }
    if (typeof mrOnBatchProgress === 'function') {
        mrOnBatchProgress(payload);
    }
});

socket.on('batch_queue_updated', function(payload) {
    if (!payload) return;
    if (typeof updateBatchQueueBadge === 'function') {
        updateBatchQueueBadge(payload.count, payload.paused);
    }
    var modal = document.getElementById('batchQueueModal');
    if (modal && !modal.hidden && typeof loadBatchQueueModal === 'function') {
        loadBatchQueueModal();
    }
});
