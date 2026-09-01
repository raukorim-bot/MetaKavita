/** Rapport de la dernière vague Auto-sync (C97). Pas le lot du tableau de bord. */

var _asrModalOpen = false;
var autoSyncSeriesIds = new Set();
window.autoSyncSeriesIds = autoSyncSeriesIds;

function _asrT(key, fallback) {
    var T = window.AppTranslations || {};
    return T[key] || fallback;
}

function _asrEsc(value) {
    return (typeof escapeHtmlText === 'function')
        ? escapeHtmlText(value)
        : String(value == null ? '' : value);
}

function _asrIdsFromPayload(payload) {
    if (!payload) return null;
    if (Array.isArray(payload.series_ids)) return payload.series_ids;
    if (payload.report && Array.isArray(payload.report.series_ids)) {
        return payload.report.series_ids;
    }
    if (Array.isArray(payload.items)) {
        return payload.items.map(function (it) { return it && it.series_id; });
    }
    return null;
}

function _asrSameIdSet(next) {
    if (next.size !== autoSyncSeriesIds.size) return false;
    var same = true;
    next.forEach(function (id) {
        if (!autoSyncSeriesIds.has(id)) same = false;
    });
    return same;
}

function setAutoSyncSeriesIds(ids, opts) {
    var next = new Set();
    (ids || []).forEach(function (raw) {
        if (raw == null || raw === '') return;
        next.add(String(raw));
    });
    var same = _asrSameIdSet(next);
    autoSyncSeriesIds = next;
    window.autoSyncSeriesIds = next;
    var sel = document.getElementById('statusFilter');
    if (!same && sel && sel.value === 'AUTO_SYNC' && !(opts && opts.silent)) {
        if (typeof filterSeries === 'function') filterSeries();
    }
}

function applyAutoSyncListFilter() {
    var sel = document.getElementById('statusFilter');
    if (!sel) return;
    sel.value = 'AUTO_SYNC';
    if (typeof filterSeries === 'function') filterSeries();
    closeAutoSyncReportModal();
    var list = document.getElementById('seriesContainer');
    if (list && list.scrollIntoView) {
        list.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function applyAutoSyncReportBadge(data) {
    var badge = data && data.report ? data.report : data;
    if (!badge) return;
    var ids = _asrIdsFromPayload(badge);
    if (ids) setAutoSyncSeriesIds(ids);
    var btn = document.getElementById('asrOpenBtn');
    var val = document.getElementById('kpiAutoSyncReport');
    if (!btn) return;
    var visible = !!badge.visible;
    var unread = !!badge.unread;
    var running = !!badge.running;
    btn.hidden = !visible;
    btn.classList.toggle('has-unread', unread);
    btn.classList.toggle('is-running', running);
    if (val) {
        var n = badge.errors ? badge.errors : (badge.total || 0);
        val.textContent = String(n);
    }
    if (_asrModalOpen) {
        loadAutoSyncReportModal();
    }
}

function openAutoSyncReportModal() {
    var modal = document.getElementById('autoSyncReportModal');
    if (!modal) return;
    _asrModalOpen = true;
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    loadAutoSyncReportModal();
}

function closeAutoSyncReportModal() {
    var modal = document.getElementById('autoSyncReportModal');
    if (!modal) return;
    _asrModalOpen = false;
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
    fetch(getRootPath() + '/api/auto-sync/report/read', { method: 'POST' })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data && data.report) applyAutoSyncReportBadge(data.report);
        })
        .catch(function () { /* ignore */ });
}

function loadAutoSyncReportModal() {
    fetch(getRootPath() + '/api/auto-sync/report')
        .then(function (res) { return res.json(); })
        .then(renderAutoSyncReport)
        .catch(function () {
            renderAutoSyncReport({ run: null, items: [], counts: {}, badge: {} });
        });
}

function _asrTile(counts, key, labelKey, fallback, extraClass) {
    var n = counts[key] || 0;
    if (key !== 'total' && key !== 'ok' && key !== 'errors' && n === 0) return '';
    return (
        '<div class="asr-tile' + (extraClass ? ' ' + extraClass : '') + '">' +
            '<span class="asr-tile-val">' + _asrEsc(n) + '</span>' +
            '<span class="asr-tile-label">' + _asrEsc(_asrT(labelKey, fallback)) + '</span>' +
        '</div>'
    );
}

function _asrSection(items, outcome, titleKey, fallback, rowClass) {
    var rows = items.filter(function (it) { return it.outcome === outcome; });
    if (!rows.length) return '';
    var html = '<section class="asr-section">' +
        '<h4 class="asr-section-title">' + _asrEsc(_asrT(titleKey, fallback)) +
        ' <span class="asr-section-count">' + rows.length + '</span></h4>';
    rows.forEach(function (it) {
        var chip = _asrT('asr_outcome_' + outcome, outcome);
        html += '<div class="asr-row ' + rowClass + '">' +
            '<span class="asr-row-name">' + _asrEsc(it.series_name) + '</span>' +
            '<span class="asr-row-chip">' + _asrEsc(chip) + '</span>' +
            (it.message && it.message !== 'stopped'
                ? '<span class="asr-row-msg">' + _asrEsc(it.message) + '</span>'
                : '') +
            '</div>';
    });
    html += '</section>';
    return html;
}

function renderAutoSyncReport(payload) {
    var flavor = document.getElementById('asrFlavor');
    var triggerEl = document.getElementById('asrTrigger');
    var tiles = document.getElementById('asrTiles');
    var list = document.getElementById('asrList');
    if (!flavor || !tiles || !list) return;

    var run = payload && payload.run;
    var items = (payload && payload.items) || [];
    var counts = (payload && payload.counts) || {};
    var badge = (payload && payload.badge) || {};

    if (badge && typeof applyAutoSyncReportBadge === 'function') {
        applyAutoSyncReportBadge(badge);
    }

    if (!run) {
        flavor.textContent = _asrT('asr_empty', 'No Auto-sync report yet.');
        triggerEl.hidden = true;
        tiles.hidden = true;
        tiles.innerHTML = '';
        list.innerHTML = '';
        var emptyBtn = document.getElementById('asrShowInListBtn');
        if (emptyBtn) emptyBtn.hidden = true;
        return;
    }

    if (badge.running) {
        flavor.textContent = _asrT('asr_flavor_running', 'This wave is still running.');
    } else if (run.stopped) {
        flavor.textContent = _asrT('asr_flavor_stopped', 'Stop removed the rest of the queue.');
    } else {
        flavor.textContent = _asrT('asr_flavor_done', 'Here is what Auto-sync just processed.');
    }

    var trig = String(run.trigger || '');
    if (trig === 'scan') {
        triggerEl.hidden = false;
        triggerEl.textContent = _asrT('asr_trigger_scan', 'Triggered by a Kavita scan');
    } else if (trig === 'interval') {
        triggerEl.hidden = false;
        triggerEl.textContent = _asrT('asr_trigger_interval', 'Triggered on an interval');
    } else {
        triggerEl.hidden = true;
    }

    tiles.hidden = false;
    tiles.innerHTML = (
        _asrTile(counts, 'total', 'asr_tile_total', 'Series', 'asr-tile--total') +
        _asrTile(counts, 'ok', 'asr_tile_ok', 'Completed', 'asr-tile--ok') +
        _asrTile(counts, 'errors', 'asr_tile_errors', 'Errors', 'asr-tile--err') +
        _asrTile(counts, 'review', 'asr_tile_review', 'In review', 'asr-tile--review') +
        _asrTile(counts, 'stopped', 'asr_tile_stopped', 'Stopped', 'asr-tile--stopped') +
        _asrTile(counts, 'pending', 'asr_tile_pending', 'Pending', 'asr-tile--pending')
    );

    list.innerHTML = (
        _asrSection(items, 'error', 'asr_section_errors', 'Errors', 'asr-row--error') +
        _asrSection(items, 'review', 'asr_section_review', 'Parked in review', 'asr-row--review') +
        _asrSection(items, 'relock', 'asr_section_relock', 'Need relock', 'asr-row--relock') +
        _asrSection(items, 'stopped', 'asr_section_stopped', 'Removed (Stop)', 'asr-row--stopped') +
        _asrSection(items, 'pending', 'asr_section_pending', 'Still queued', 'asr-row--pending') +
        _asrSection(items, 'completed', 'asr_section_ok', 'Completed', 'asr-row--ok')
    );
    if (!list.innerHTML) {
        list.innerHTML = '<p class="asr-empty-list">' + _asrEsc(_asrT('asr_empty', '')) + '</p>';
    }

    var ids = _asrIdsFromPayload(payload);
    if (ids) setAutoSyncSeriesIds(ids);
    var showBtn = document.getElementById('asrShowInListBtn');
    if (showBtn) showBtn.hidden = !items.length;
}

(function wireAutoSyncReportSocket() {
    if (typeof socket === 'undefined' || !socket || !socket.on) return;
    socket.on('auto_sync_report', applyAutoSyncReportBadge);
})();

if (Array.isArray(window.AUTO_SYNC_SERIES_IDS)) {
    setAutoSyncSeriesIds(window.AUTO_SYNC_SERIES_IDS, { silent: true });
}
