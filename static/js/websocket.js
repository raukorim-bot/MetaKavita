// --- WEBSOCKETS LOGS & INDICATEUR LIVE DE TRAITEMENT ---
// Dépend de utils.js (getRootPath). La variable globale `socket` est réutilisée
// par covers.js (flux de couvertures en direct) : ce fichier doit donc être
// chargé AVANT covers.js.
var socket = io({ path: getRootPath() + '/socket.io' });
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
                            uncheckSeriesForBatchResume(item);
                        } else if (msg.data.includes('⏭️') || msg.data.includes('déjà à jour') || msg.data.includes('already up to date')) {
                            item.dataset.status = 'COMPLETED';
                            badge.className = 'badge badge-completed';
                            badge.innerText = window.AppTranslations.filter_completed;
                            uncheckSeriesForBatchResume(item);
                        } else if (msg.data.includes('introuvable') || msg.data.includes('Aucun résultat') || msg.data.includes('No results')) {
                            item.dataset.status = 'NOT_FOUND';
                            badge.className = 'badge badge-notfound';
                            badge.innerText = window.AppTranslations.filter_notfound;
                        } else if (msg.data.includes('PENDING_REVIEW') || msg.data.includes('👁️')) {
                            item.dataset.status = 'PENDING_REVIEW';
                            badge.className = 'badge badge-review';
                            badge.innerText = window.AppTranslations.filter_pending_review || 'Review';
                        } else if (msg.data.includes('NEEDS_RELOCK') || msg.data.includes('À sceller') || msg.data.includes('Needs seal') || msg.data.includes('verrous non posés')) {
                            item.dataset.status = 'NEEDS_RELOCK';
                            badge.className = 'badge badge-needs-relock';
                            badge.innerText = window.AppTranslations.filter_needs_relock || 'Needs seal';
                            uncheckSeriesForBatchResume(item);
                        }
                    }
                }
            });
        }
    } catch(e) {
        console.error("[WebSockets] Erreur Live Highlight :", e);
    }
});

socket.on('series_status', function(payload) {
    if (!payload || payload.series_id == null) return;
    var sid = String(payload.series_id);
    var status = payload.status || '';
    document.querySelectorAll('.series-item').forEach(function(item) {
        var cb = item.querySelector('.series-cb');
        if (!cb || String(cb.value) !== sid) return;
        if (typeof applySeriesStatusBadge === 'function') {
            applySeriesStatusBadge(item, status);
        }
    });
});

/** QoS batch : une série OK se décoche pour pouvoir relancer le lot sans re-scraper les déjà faits. */
function uncheckSeriesForBatchResume(item) {
    if (!item) return;
    const cb = item.querySelector('.series-cb');
    if (cb) cb.checked = false;
    const selectAll = document.getElementById('selectAll');
    if (selectAll) selectAll.checked = false;
    if (typeof saveBatchSelection === 'function') {
        saveBatchSelection();
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
