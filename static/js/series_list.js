// BF97 / #30 — liste virtualisée (DOM fenêtre) + index mémoire.
// Dépend de batch.js (selectedIds, matchedIds, matchedSet, titleMatchesSearch).
// Activée quand #seriesContainer[data-virtual="1"] + #seriesIndexData.

(function () {
    var ROW_HEIGHT = 72;
    var OVERSCAN = 8;
    /** Several Options panels can stay open; all are pinned against recycle. */
    var pinnedPanelIds = new Set();

    var items = []; // full index
    var byId = {};
    var root = null;
    var spacer = null;
    var windowEl = null;
    var kavitaUiUrl = '';
    var scrollRaf = 0;
    var T = function () { return window.AppTranslations || {}; };

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function escAttr(s) {
        return esc(s).replace(/'/g, '&#39;');
    }

    function badgeHtml(status) {
        var tr = T();
        if (status === 'COMPLETED') {
            return '<span class="badge badge-completed">' + esc(tr.filter_completed || 'Completed') + '</span>';
        }
        if (status === 'NEEDS_RELOCK') {
            return '<span class="badge badge-needs-relock" title="' + escAttr(tr.filter_needs_relock_hint || '') + '">' +
                esc(tr.filter_needs_relock || 'Needs seal') + '</span>' +
                '<button type="button" class="btn-icon btn-seal-locks" data-seal="1" title="' +
                escAttr(tr.seal_locks_btn || 'Seal') + '">🔒</button>';
        }
        if (status === 'NOT_FOUND') {
            return '<span class="badge badge-notfound">' + esc(tr.filter_notfound || 'Not found') + '</span>';
        }
        if (status === 'IGNORED') {
            return '<span class="badge badge-ignored">' + esc(tr.filter_ignored || 'Ignored') + '</span>';
        }
        if (status === 'PENDING_REVIEW') {
            return '<span class="badge badge-review">' + esc(tr.filter_pending_review || 'Review') + '</span>';
        }
        return '<span class="badge badge-pending">' + esc(tr.filter_pending || 'Pending') + '</span>';
    }

    function buildRowHtml(s) {
        var tr = T();
        var sid = String(s.id);
        var name = s.name || '';
        var lib = s.libraryId;
        var href = kavitaUiUrl + '/library/' + lib + '/series/' + sid;
        var ignTitle = s.status === 'IGNORED' ? (tr.unignore_btn || 'Unignore') : (tr.ignore_btn || 'Ignore');
        var ignIcon = s.status === 'IGNORED' ? '🔄' : '🚫';
        var checked = (typeof selectedIds !== 'undefined' && selectedIds.has(sid)) ? ' checked' : '';
        // Pinned + open Options: auto height so the panel is not clipped to 72px.
        var pinned = pinnedPanelIds.has(sid);
        var heightStyle = pinned
            ? 'min-height:' + ROW_HEIGHT + 'px;height:auto;overflow:visible;'
            : 'height:' + ROW_HEIGHT + 'px;overflow:hidden;';
        return (
            '<div class="series-item' + (pinned ? ' is-pinned-panel' : '') + '"' +
            ' data-status="' + escAttr(s.status || 'PENDING') + '"' +
            ' data-search-title="' + escAttr(s.searchTitle || name.toLowerCase()) + '"' +
            ' data-series-id="' + escAttr(sid) + '"' +
            ' data-library-id="' + escAttr(lib) + '"' +
            ' data-series-name="' + escAttr(name) + '"' +
            ' data-forced-id="' + escAttr(s.forced_id || '') + '"' +
            ' data-alt-title="' + escAttr(s.alternative_title || name) + '"' +
            ' data-forced-provider="' + escAttr(s.forced_provider || 'AUTO') + '"' +
            ' data-targeted-fields="' + escAttr(s.targeted_fields || 'ALL') + '"' +
            ' data-publisher-pref="' + escAttr(s.publisher_pref || 'GLOBAL') + '"' +
            ' data-alt-langs="' + escAttr(s.alt_title_langs || '') + '"' +
            ' style="' + heightStyle + 'box-sizing:border-box;">' +
            '<div class="series-row">' +
            '<div class="series-title-line">' +
            '<input type="checkbox" name="selected_series" value="' + escAttr(sid) + '" class="series-cb"' + checked + '>' +
            '<a href="' + escAttr(href) + '" target="_blank" class="series-link"><span class="series-name">' + esc(name) + '</span></a>' +
            '</div>' +
            '<div class="series-status">' + badgeHtml(s.status) + '</div>' +
            '<div class="series-actions">' +
            '<button type="button" class="btn-icon" data-action="ignore" title="' + escAttr(ignTitle) + '">' + ignIcon + '</button>' +
            '<button type="button" class="btn-icon" data-action="covers" title="' + escAttr(tr.manage_covers || 'Covers') + '">🖼️</button>' +
            '<button type="button" class="btn-opt" data-action="options">' + esc(tr.options || 'Options') + '</button>' +
            '<button type="button" class="btn-sync" data-action="sync">' + esc(tr.update || 'Update') + '</button>' +
            '<span class="loading" data-action="loading" style="display: none;">' + esc(tr.processing || '...') + '</span>' +
            '</div></div></div>'
        );
    }

    function bindRow(el, s) {
        var sid = String(s.id);
        var ignoreBtn = el.querySelector('[data-action="ignore"]');
        if (ignoreBtn) ignoreBtn.addEventListener('click', function () { toggleIgnore(sid, ignoreBtn); });
        var coversBtn = el.querySelector('[data-action="covers"]');
        if (coversBtn) coversBtn.addEventListener('click', function () { openCoverModal(sid, s.name || ''); });
        var optBtn = el.querySelector('[data-action="options"]');
        if (optBtn) optBtn.addEventListener('click', function () { toggleSeriesPanel(sid); });
        var syncBtn = el.querySelector('[data-action="sync"]');
        if (syncBtn) syncBtn.addEventListener('click', function () { syncSingle(sid, s.name || '', syncBtn); });
        var sealBtn = el.querySelector('[data-seal]');
        if (sealBtn) sealBtn.addEventListener('click', function () { sealSeriesLocks(sid, sealBtn); });
        // Re-attach cached open panel after virtual recycle (innerHTML wipe).
        if (pinnedPanelIds.has(sid) && typeof reattachOverridePanelIfAny === 'function') {
            var existing = reattachOverridePanelIfAny(sid, el);
            if (existing) existing.style.display = 'block';
        }
    }

    function _openPanelExtraHeight() {
        var extra = 0;
        pinnedPanelIds.forEach(function (sid) {
            var panel = (typeof _overridePanelCache !== 'undefined' && _overridePanelCache[sid])
                || document.getElementById('panel-' + sid);
            if (!panel || panel.style.display !== 'block') return;
            extra += Math.max(0, panel.offsetHeight || 420);
        });
        return extra;
    }

    function renderWindow() {
        if (!root || !windowEl || !spacer) return;
        var matched = matchedIds || [];
        spacer.style.height = (matched.length * ROW_HEIGHT + _openPanelExtraHeight()) + 'px';

        var scrollTop = root.scrollTop;
        var viewH = root.clientHeight || 400;
        var start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
        var end = Math.min(matched.length, Math.ceil((scrollTop + viewH) / ROW_HEIGHT) + OVERSCAN);

        // Keep every pinned (open Options) row in the mounted window.
        pinnedPanelIds.forEach(function (sid) {
            var pinIdx = matched.indexOf(String(sid));
            if (pinIdx >= 0) {
                start = Math.min(start, pinIdx);
                end = Math.max(end, pinIdx + 1);
            }
        });

        var html = [];
        for (var i = start; i < end; i++) {
            var id = matched[i];
            var s = byId[id];
            if (s) html.push(buildRowHtml(s));
        }
        windowEl.style.transform = 'translateY(' + (start * ROW_HEIGHT) + 'px)';
        windowEl.innerHTML = html.join('');
        var nodes = windowEl.children;
        for (var j = 0; j < nodes.length; j++) {
            var node = nodes[j];
            var nid = node.dataset.seriesId;
            if (byId[nid]) bindRow(node, byId[nid]);
        }
    }

    function onScroll() {
        if (scrollRaf) return;
        scrollRaf = requestAnimationFrame(function () {
            scrollRaf = 0;
            renderWindow();
        });
    }

    function filterAndRender(opts) {
        opts = opts || {};
        var filter = opts.filter || 'ALL';
        var hideIgnored = !!opts.hideIgnored;
        var searchQuery = opts.searchQuery || '';
        var searchInside = !!opts.searchInside;

        matchedIds = [];
        matchedSet = new Set();
        for (var i = 0; i < items.length; i++) {
            var s = items[i];
            var status = s.status || 'PENDING';
            var title = s.searchTitle || String(s.name || '').toLowerCase();
            var show = false;
            if (filter === 'ALL') {
                show = !(hideIgnored && status === 'IGNORED');
            } else if (status === filter) {
                show = true;
            }
            if (show && searchQuery) {
                if (typeof titleMatchesSearch === 'function') {
                    show = titleMatchesSearch(title, searchQuery, searchInside);
                } else if (searchInside) {
                    show = title.indexOf(searchQuery) !== -1;
                } else {
                    show = title.indexOf(searchQuery) === 0;
                }
            }
            if (show) {
                var sid = String(s.id);
                matchedIds.push(sid);
                matchedSet.add(sid);
            }
        }
        renderWindow();
    }

    function refreshMountedChecks() {
        if (!windowEl) return;
        windowEl.querySelectorAll('.series-cb').forEach(function (cb) {
            cb.checked = typeof selectedIds !== 'undefined' && selectedIds.has(String(cb.value));
        });
    }

    function updateStatus(seriesId, status) {
        var s = byId[String(seriesId)];
        if (!s) return;
        s.status = status;
        renderWindow();
    }

    function patchOverride(seriesId, patch) {
        var s = byId[String(seriesId)];
        if (!s || !patch) return;
        Object.keys(patch).forEach(function (k) { s[k] = patch[k]; });
    }

    function pinOpenPanel(seriesId) {
        pinnedPanelIds.add(String(seriesId));
        renderWindow();
    }

    /** Pin many at once (Expand all) — single re-render. */
    function pinOpenPanels(seriesIds) {
        (seriesIds || []).forEach(function (id) {
            pinnedPanelIds.add(String(id));
        });
        renderWindow();
    }

    function unpinPanel(seriesId) {
        pinnedPanelIds.delete(String(seriesId));
        renderWindow();
    }

    function unpinAllPanels() {
        pinnedPanelIds.clear();
        renderWindow();
    }

    function afterPanelOpened(/* seriesId */) {
        if (spacer) {
            spacer.style.height = ((matchedIds || []).length * ROW_HEIGHT + _openPanelExtraHeight()) + 'px';
        }
    }

    function getItem(seriesId) {
        return byId[String(seriesId)] || null;
    }

    function init() {
        root = document.getElementById('seriesContainer');
        if (!root || root.getAttribute('data-virtual') !== '1') return false;

        var dataEl = document.getElementById('seriesIndexData');
        var metaEl = document.getElementById('seriesListMeta');
        if (!dataEl) return false;

        try {
            items = JSON.parse(dataEl.textContent || '[]');
        } catch (e) {
            console.error('[SeriesList] bad JSON', e);
            return false;
        }
        if (!Array.isArray(items)) items = [];

        byId = {};
        items.forEach(function (s) {
            s.id = s.id;
            s.searchTitle = (s.searchTitle || String(s.name || '')).toLowerCase();
            byId[String(s.id)] = s;
        });

        kavitaUiUrl = '';
        if (metaEl) {
            try {
                var meta = JSON.parse(metaEl.textContent || '{}');
                kavitaUiUrl = meta.kavita_ui_url || '';
            } catch (e2) { /* ignore */ }
        }

        spacer = document.getElementById('seriesVirtualSpacer');
        windowEl = document.getElementById('seriesVirtualWindow');
        if (!spacer || !windowEl) {
            root.innerHTML = '';
            spacer = document.createElement('div');
            spacer.id = 'seriesVirtualSpacer';
            spacer.className = 'series-virtual-spacer';
            windowEl = document.createElement('div');
            windowEl.id = 'seriesVirtualWindow';
            windowEl.className = 'series-virtual-window';
            root.appendChild(spacer);
            root.appendChild(windowEl);
        }

        root.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('resize', onScroll);

        window.SeriesList = {
            filterAndRender: filterAndRender,
            refreshMountedChecks: refreshMountedChecks,
            updateStatus: updateStatus,
            patchOverride: patchOverride,
            pinOpenPanel: pinOpenPanel,
            pinOpenPanels: pinOpenPanels,
            unpinPanel: unpinPanel,
            unpinAllPanels: unpinAllPanels,
            afterPanelOpened: afterPanelOpened,
            getItem: getItem,
            renderWindow: renderWindow,
            isPinned: function (id) { return pinnedPanelIds.has(String(id)); },
        };
        return true;
    }

    // Run early so filterSeries / restore can see SeriesList.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
