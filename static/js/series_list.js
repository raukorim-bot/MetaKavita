// BF97 / #30 — liste virtualisée (DOM fenêtre) + index mémoire.
// Dépend de batch.js (selectedIds, matchedIds, matchedSet, titleMatchesSearch).
// Activée quand #seriesContainer[data-virtual="1"] + #seriesIndexData.

(function () {
    var ROW_HEIGHT = 54;
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
    var processingId = null;
    var T = function () { return window.AppTranslations || {}; };

    // Échappement partagé (utils.js) : voir escapeHtmlText, l'apostrophe incluse.
    // `escAttr` reste un alias : les gabarits ci-dessous s'en servent pour marquer
    // les insertions en position d'attribut.
    function esc(s) {
        return window.escapeHtmlText(s);
    }

    var escAttr = esc;

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

    /* Cartouche d'inventaire : même couleur et même infobulle que le rendu Jinja
       (library_audit.js est la source unique, ce fichier ne fait que déléguer). */
    function auditBadgeClass(s) {
        if (typeof window.auditBadgeClass === 'function') {
            return window.auditBadgeClass(s.completion_state, s.forced_expected);
        }
        return 'badge badge-audit';
    }

    function auditBadgeTitle(s) {
        if (typeof window.auditBadgeTitle === 'function') {
            return window.auditBadgeTitle(s.completion_state, s.forced_expected, s.audit_unit);
        }
        return (T().audit_badge_title || '');
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
        // Pinned + open Options: auto height so the panel is not clipped to ROW_HEIGHT.
        var pinned = pinnedPanelIds.has(sid);
        var processing = processingId && sid === processingId;
        var heightStyle = pinned
            ? 'min-height:' + ROW_HEIGHT + 'px;height:auto;overflow:visible;'
            : 'height:' + ROW_HEIGHT + 'px;overflow:hidden;';
        return (
            '<div class="series-item' + (pinned ? ' is-pinned-panel' : '') + (processing ? ' is-processing' : '') + '"' +
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
            ' data-cover-manual="' + (s.cover_manual ? '1' : '0') + '"' +
            ' data-has-external-id="' + (s.has_external_id ? '1' : (s.has_external_id === false ? '0' : '')) + '"' +
            ' data-duplicate-group-id="' + escAttr(s.duplicate_group_id || '') + '"' +
            ' data-audit-badge="' + escAttr(s.audit_badge || '') + '"' +
            ' data-missing-count="' + escAttr(s.missing_count != null ? s.missing_count : 0) + '"' +
            ' data-catalog-expected="' + escAttr(s.catalog_expected != null ? s.catalog_expected : '') + '"' +
            ' data-publication-status="' + escAttr(s.publication_status || '') + '"' +
            ' data-completion-state="' + escAttr(s.completion_state || '') + '"' +
            ' data-forced-expected="' + (s.forced_expected ? '1' : '0') + '"' +
            ' data-inventory-excluded="' + (s.inventory_excluded ? '1' : '0') + '"' +
            ' style="' + heightStyle + 'box-sizing:border-box;">' +
            '<div class="series-row">' +
            '<div class="series-title-line">' +
            '<input type="checkbox" name="selected_series" value="' + escAttr(sid) + '" class="series-cb"' + checked + '>' +
            '<a href="' + escAttr(href) + '" target="_blank" class="series-link"><span class="series-name">' + esc(name) + '</span></a>' +
            '</div>' +
            '<div class="series-status">' + badgeHtml(s.status) +
            (s.audit_badge
                ? '<span class="' + auditBadgeClass(s) + '" title="' + escAttr(auditBadgeTitle(s)) + '">' +
                  esc(s.audit_badge) + '</span>'
                : '') +
            (s.inventory_excluded
                ? '<span class="badge badge-inventory-excluded" title="' +
                  escAttr(tr.audit_excluded_badge_hint || '') + '">' +
                  esc(tr.audit_excluded_badge || '') + '</span>'
                : '') +
            (typeof overrideBadgesHtml === 'function'
                ? overrideBadgesHtml(s)
                : '') +
            (s.cover_manual
                ? '<button type="button" class="badge badge-cover-manual" data-action="release-cover" title="' +
                  escAttr(tr.cover_manual_badge_hint || '') + '">🔒 ' + esc(tr.cover_manual_badge || '') + '</button>'
                : '') +
            '</div>' +
            '<div class="series-actions">' +
            '<button type="button" class="btn-icon" data-action="ignore" title="' + escAttr(ignTitle) + '">' + ignIcon + '</button>' +
            '<button type="button" class="btn-icon btn-audit-report" data-action="audit" title="' + escAttr(tr.audit_volume_report || 'Volumes') + '">📑</button>' +
            '<a class="btn-icon btn-workshop" data-action="workshop" href="' + (typeof getRootPath === 'function' ? getRootPath() : '') + '/series/' + encodeURIComponent(sid) + '/volumes" title="' + escAttr(tr.workshop_open_hint || tr.workshop_open || '') + '">📚</a>' +
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
        var auditBtn = el.querySelector('[data-action="audit"]');
        if (auditBtn) auditBtn.addEventListener('click', function () {
            if (typeof openVolumeReportModal === 'function') openVolumeReportModal(sid, s.name || '');
        });
        var optBtn = el.querySelector('[data-action="options"]');
        if (optBtn) optBtn.addEventListener('click', function () { toggleSeriesPanel(sid); });
        var syncBtn = el.querySelector('[data-action="sync"]');
        if (syncBtn) syncBtn.addEventListener('click', function () { syncSingle(sid, s.name || '', syncBtn); });
        var sealBtn = el.querySelector('[data-seal]');
        if (sealBtn) sealBtn.addEventListener('click', function () { sealSeriesLocks(sid, sealBtn); });
        var releaseCoverBtn = el.querySelector('[data-action="release-cover"]');
        if (releaseCoverBtn) releaseCoverBtn.addEventListener('click', function () {
            if (typeof releaseSeriesCover === 'function') releaseSeriesCover(sid, releaseCoverBtn);
        });
        el.querySelectorAll('[data-action="open-options"]').forEach(function (btn) {
            if (typeof bindOverrideBadge === 'function') bindOverrideBadge(btn, sid);
        });
        // Re-attach cached open panel after virtual recycle (innerHTML wipe).
        if (pinnedPanelIds.has(sid) && typeof reattachOverridePanelIfAny === 'function') {
            var existing = reattachOverridePanelIfAny(sid, el);
            if (existing) existing.style.display = 'block';
        }
    }

    function _panelHeight(sid) {
        var panel = (typeof _overridePanelCache !== 'undefined' && _overridePanelCache[sid])
            || document.getElementById('panel-' + sid);
        if (!panel || panel.style.display !== 'block') return 0;
        return Math.max(0, panel.offsetHeight || 420);
    }

    function _estimatedRowHeight(sid) {
        if (!pinnedPanelIds.has(String(sid))) return ROW_HEIGHT;
        return ROW_HEIGHT + _panelHeight(sid);
    }

    /** Cumulative Y offsets for matched rows (accounts for open Options panels). */
    function _cumulativeOffsets(matched) {
        var offs = new Array(matched.length + 1);
        offs[0] = 0;
        for (var i = 0; i < matched.length; i++) {
            offs[i + 1] = offs[i] + _estimatedRowHeight(matched[i]);
        }
        return offs;
    }

    function _indexAtOffset(offs, y) {
        var lo = 0;
        var hi = offs.length - 1;
        while (lo < hi) {
            var mid = (lo + hi + 1) >> 1;
            if (offs[mid] <= y) lo = mid;
            else hi = mid - 1;
        }
        return Math.min(lo, Math.max(0, offs.length - 2));
    }

    function renderWindow() {
        if (!root || !windowEl || !spacer) return;
        var matched = matchedIds || [];
        var useOffsets = pinnedPanelIds.size > 0;
        var offs = useOffsets ? _cumulativeOffsets(matched) : null;
        var totalH = useOffsets ? offs[matched.length] : matched.length * ROW_HEIGHT;
        spacer.style.height = totalH + 'px';

        var scrollTop = root.scrollTop;
        var viewH = root.clientHeight || 400;
        var start;
        var end;
        if (!useOffsets) {
            start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
            end = Math.min(matched.length, Math.ceil((scrollTop + viewH) / ROW_HEIGHT) + OVERSCAN);
        } else {
            start = Math.max(0, _indexAtOffset(offs, scrollTop) - OVERSCAN);
            end = Math.min(
                matched.length,
                _indexAtOffset(offs, scrollTop + viewH) + 1 + OVERSCAN
            );
        }

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
        var topY = useOffsets ? offs[start] : start * ROW_HEIGHT;
        windowEl.style.transform = 'translateY(' + topY + 'px)';
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
        if (!root || !windowEl || !spacer || root.getAttribute('data-virtual') !== '1') {
            return false;
        }
        opts = opts || {};
        var filter = opts.filter || 'ALL';
        var hideIgnored = !!opts.hideIgnored;
        var searchQuery = opts.searchQuery || '';
        var searchInside = !!opts.searchInside;
        var hygiene = (opts.hygieneFilter != null) ? opts.hygieneFilter : window.hygieneFilter;

        matchedIds = [];
        matchedSet = new Set();
        for (var i = 0; i < items.length; i++) {
            var s = items[i];
            var status = s.status || 'PENDING';
            var title = s.searchTitle || String(s.name || '').toLowerCase();
            var show = false;
            if (filter === 'ALL') {
                show = !(hideIgnored && status === 'IGNORED');
            } else if (filter === 'AUTO_SYNC') {
                show = !!(window.autoSyncSeriesIds && window.autoSyncSeriesIds.has(String(s.id)));
                if (show && hideIgnored && status === 'IGNORED') show = false;
            } else if (status === filter) {
                show = true;
            }
            if (show && hygiene) {
                if (hygiene === 'MISSING_VS_CATALOG') {
                    show = (Number(s.missing_count) || 0) > 0;
                } else if (hygiene === 'DUPLICATES') {
                    show = !!s.duplicate_group_id;
                } else if (hygiene === 'NO_EXTERNAL_ID') {
                    show = s.has_external_id === false || s.has_external_id === 0;
                } else if (hygiene === 'FINISHED') {
                    show = String(s.publication_status || '').toUpperCase() === 'FINISHED';
                } else if (hygiene === 'RELEASING') {
                    var pub = String(s.publication_status || '').toUpperCase();
                    show = pub === 'RELEASING' || pub === 'HIATUS' || pub === 'NOT_YET_RELEASED';
                }
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
        return true;
    }

    function _scrollToProcessing() {
        if (!root || !processingId) return;
        var matched = matchedIds || [];
        var idx = matched.indexOf(processingId);
        if (idx < 0) return;
        var y = pinnedPanelIds.size > 0 ? _cumulativeOffsets(matched)[idx] : idx * ROW_HEIGHT;
        var viewH = root.clientHeight || 400;
        if (y < root.scrollTop || y + ROW_HEIGHT > root.scrollTop + viewH) {
            root.scrollTop = Math.max(0, y - Math.floor(viewH / 3));
        }
    }

    function setProcessing(seriesId) {
        processingId = (seriesId == null || seriesId === '') ? null : String(seriesId);
        if (!root || root.getAttribute('data-virtual') !== '1') return false;
        if (processingId) _scrollToProcessing();
        renderWindow();
        var row = windowEl && windowEl.querySelector('.series-item.is-processing');
        if (row) row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return true;
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

    /** Apply audit flags from /duplicates (has_external_id + duplicate_group_id). */
    function applyAuditFlags(flags) {
        if (!flags) return;
        Object.keys(byId).forEach(function (sid) {
            if (byId[sid]) byId[sid].duplicate_group_id = '';
        });
        Object.keys(flags).forEach(function (sid) {
            var s = byId[String(sid)];
            if (!s) return;
            var f = flags[sid] || {};
            if (Object.prototype.hasOwnProperty.call(f, 'has_external_id')) {
                s.has_external_id = !!f.has_external_id;
            }
            s.duplicate_group_id = f.duplicate_group_id || '';
        });
    }

    function applyAuditBadges(map) {
        if (!map) return;
        Object.keys(map).forEach(function (sid) {
            var s = byId[String(sid)];
            if (s) s.audit_badge = map[sid] || '';
        });
        renderWindow();
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
        // Recalcule spacer + translateY (hauteurs de panneaux variables).
        renderWindow();
    }

    function getItem(seriesId) {
        return byId[String(seriesId)] || null;
    }

    function destroy() {
        if (root) {
            try { root.removeEventListener('scroll', onScroll); } catch (e) { /* ignore */ }
        }
        try { window.removeEventListener('resize', onScroll); } catch (e2) { /* ignore */ }
        if (scrollRaf) {
            cancelAnimationFrame(scrollRaf);
            scrollRaf = 0;
        }
        pinnedPanelIds.clear();
        processingId = null;
        items = [];
        byId = {};
        root = null;
        spacer = null;
        windowEl = null;
    }

    function _publishApi() {
        window.SeriesList = {
            filterAndRender: filterAndRender,
            refreshMountedChecks: refreshMountedChecks,
            updateStatus: updateStatus,
            patchOverride: patchOverride,
            applyAuditFlags: applyAuditFlags,
            applyAuditBadges: applyAuditBadges,
            pinOpenPanel: pinOpenPanel,
            pinOpenPanels: pinOpenPanels,
            unpinPanel: unpinPanel,
            unpinAllPanels: unpinAllPanels,
            afterPanelOpened: afterPanelOpened,
            getItem: getItem,
            setProcessing: setProcessing,
            renderWindow: renderWindow,
            isPinned: function (id) { return pinnedPanelIds.has(String(id)); },
            init: init,
            destroy: destroy,
        };
    }

    function init() {
        destroy();
        _publishApi();

        root = document.getElementById('seriesContainer');
        if (!root || root.getAttribute('data-virtual') !== '1') {
            return false;
        }

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
        _publishApi();
        return true;
    }

    // Run early so filterSeries / restore can see SeriesList.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
