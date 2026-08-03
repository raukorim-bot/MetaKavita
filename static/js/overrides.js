// --- SURCHARGES PAR SÉRIE (ID/URL forcé, titre alternatif, champs ciblés, provider) ---
// Dépend de utils.js (getRootPath).
// BF96 / #30 : panneau Options construit à la demande (template unique).

const TARGETED_FIELD_KEYS = [
    'summary', 'cover', 'staff', 'genres', 'tags', 'year',
    'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles', 'language'
];

let allPanelsExpanded = false;

/** Survive virtual-list re-renders (innerHTML wipe). */
var _overridePanelCache = {};

function setSeriesTargetedFields(seriesId, checked) {
    TARGETED_FIELD_KEYS.forEach(f => {
        const cb = document.getElementById(`field-${f}-${seriesId}`);
        if (cb) cb.checked = !!checked;
    });
}

function setBatchTargetedFields(checked) {
    document.querySelectorAll('.batch-field-cb').forEach(cb => {
        cb.checked = !!checked;
    });
}

/** null = tout coché (pas d'override batch) ; sinon CSV ou NONE. */
function getBatchTargetedFieldsMask() {
    const boxes = Array.from(document.querySelectorAll('.batch-field-cb'));
    if (boxes.length === 0) return null;
    const active = boxes.filter(cb => cb.checked).map(cb => cb.value);
    if (active.length === boxes.length) return null;
    return active.length ? active.join(',') : 'NONE';
}

function findSeriesItemById(seriesId) {
    const sid = String(seriesId);
    let found = null;
    document.querySelectorAll('.series-item').forEach(function (item) {
        if (found) return;
        if (String(item.dataset.seriesId || '') === sid) found = item;
        else {
            const cb = item.querySelector('.series-cb');
            if (cb && String(cb.value) === sid) found = item;
        }
    });
    return found;
}

function _buildOverridePanelFromTemplate(sid) {
    const tpl = document.getElementById('override-panel-template');
    if (!tpl) {
        console.error('[MetaKavita] #override-panel-template missing');
        return null;
    }
    // <template>.content is a DocumentFragment; clone then rewrite __SID__.
    const frag = tpl.content.cloneNode(true);
    const root = frag.querySelector('.override-panel') || frag.firstElementChild;
    if (!root) return null;

    const html = root.outerHTML.split('__SID__').join(sid);
    const wrap = document.createElement('div');
    wrap.innerHTML = html;
    return wrap.firstElementChild;
}

function _fillOverridePanelFields(panel, sid, item) {
    const ds = item.dataset;
    const titleEl = panel.querySelector('#title-' + sid) || document.getElementById('title-' + sid);
    if (titleEl) titleEl.value = ds.altTitle || ds.seriesName || '';
    const idEl = panel.querySelector('#id-' + sid) || document.getElementById('id-' + sid);
    if (idEl) idEl.value = ds.forcedId || '';
    const prov = panel.querySelector('#provider-' + sid) || document.getElementById('provider-' + sid);
    if (prov) prov.value = ds.forcedProvider || 'AUTO';
    const altLangs = panel.querySelector('#alt-langs-' + sid) || document.getElementById('alt-langs-' + sid);
    if (altLangs) altLangs.value = ds.altLangs || '';

    const pub = ds.publisherPref || 'GLOBAL';
    const pubId = pub === 'LOCALIZED' ? 'pub-loc-' + sid : pub === 'ORIGINAL' ? 'pub-orig-' + sid : 'pub-global-' + sid;
    const pubRadio = panel.querySelector('#' + pubId) || document.getElementById(pubId);
    if (pubRadio) pubRadio.checked = true;

    const tfRaw = ds.targetedFields || 'ALL';
    const tfList = (tfRaw !== 'ALL' && tfRaw !== 'NONE') ? tfRaw.split(',') : [];
    TARGETED_FIELD_KEYS.forEach(function (f) {
        const cb = panel.querySelector('#field-' + f + '-' + sid) || document.getElementById('field-' + f + '-' + sid);
        if (!cb) return;
        cb.checked = tfRaw === 'ALL' || tfList.indexOf(f) !== -1;
    });

    if (!panel.dataset.bound) {
        panel.dataset.bound = '1';
        const saveBtn = panel.querySelector('[data-save-override]');
        if (saveBtn) {
            saveBtn.addEventListener('click', function () {
                saveOverride(sid, saveBtn);
            });
        }
        const tfAll = panel.querySelector('[data-tf-all]');
        if (tfAll) tfAll.addEventListener('click', function () { setSeriesTargetedFields(sid, true); });
        const tfNone = panel.querySelector('[data-tf-none]');
        if (tfNone) tfNone.addEventListener('click', function () { setSeriesTargetedFields(sid, false); });
    }
}

function ensureOverridePanel(seriesId) {
    const sid = String(seriesId);
    const item = findSeriesItemById(sid);
    if (!item) {
        console.error('[MetaKavita] series row not found for panel', sid);
        return null;
    }

    let panel = document.getElementById('panel-' + sid) || _overridePanelCache[sid];
    if (panel) {
        if (panel.parentNode !== item) item.appendChild(panel);
        _overridePanelCache[sid] = panel;
        return panel;
    }

    panel = _buildOverridePanelFromTemplate(sid);
    if (!panel) return null;

    item.appendChild(panel);
    _overridePanelCache[sid] = panel;
    _fillOverridePanelFields(panel, sid, item);
    return panel;
}

/** Re-attach a cached open panel after a virtual-list re-render. */
function reattachOverridePanelIfAny(seriesId, hostItem) {
    const sid = String(seriesId);
    const panel = _overridePanelCache[sid];
    if (!panel || !hostItem) return null;
    if (panel.parentNode !== hostItem) hostItem.appendChild(panel);
    return panel;
}

function isOverridePanelOpen(seriesId) {
    const sid = String(seriesId);
    const panel = document.getElementById('panel-' + sid) || _overridePanelCache[sid];
    return !!(panel && panel.style.display === 'block');
}

function openSeriesPanel(seriesId) {
    const sid = String(seriesId);
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.pinOpenPanel === 'function') {
        window.SeriesList.pinOpenPanel(sid);
    }
    const panel = ensureOverridePanel(sid);
    if (!panel) return null;
    panel.style.display = 'block';
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.afterPanelOpened === 'function') {
        window.SeriesList.afterPanelOpened(sid);
    }
    return panel;
}

function closeSeriesPanel(seriesId) {
    const sid = String(seriesId);
    const panel = document.getElementById('panel-' + sid) || _overridePanelCache[sid];
    if (panel) panel.style.display = 'none';
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.unpinPanel === 'function') {
        window.SeriesList.unpinPanel(sid);
    }
}

function toggleSeriesPanel(seriesId) {
    const sid = String(seriesId);
    if (isOverridePanelOpen(sid)) {
        closeSeriesPanel(sid);
        return;
    }
    openSeriesPanel(sid);
}

/** @deprecated use toggleSeriesPanel — kept for any leftover callers */
function togglePanel(id) {
    if (typeof id === 'string' && id.indexOf('panel-') === 0) {
        toggleSeriesPanel(id.slice('panel-'.length));
        return;
    }
    toggleSeriesPanel(id);
}

function _visibleSeriesItemsForPanels() {
    // Rows currently in the DOM and not filtered out. Virtual list ⇒ viewport only
    // (safe). Non-virtual ⇒ all non-filtered rows (≤119 below virtual threshold).
    return Array.from(document.querySelectorAll('.series-item')).filter(function (item) {
        return !item.classList.contains('is-filtered-out');
    });
}

/**
 * Expand/collapse Options for *currently visible* rows only.
 * Expanding every series on a 2000-library is intentionally unsupported (BF96).
 */
function toggleAllOverridePanels() {
    allPanelsExpanded = !allPanelsExpanded;

    if (!allPanelsExpanded) {
        // Collapse every open panel (cache + DOM), including off-viewport pinned ones.
        Object.keys(_overridePanelCache).forEach(function (sid) {
            const panel = _overridePanelCache[sid];
            if (panel) panel.style.display = 'none';
        });
        document.querySelectorAll('.override-panel').forEach(function (panel) {
            panel.style.display = 'none';
        });
        if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.unpinAllPanels === 'function') {
            window.SeriesList.unpinAllPanels();
        }
        return;
    }

    const items = _visibleSeriesItemsForPanels();
    items.forEach(function (item) {
        const sid = item.dataset.seriesId
            || (item.querySelector('.series-cb') && item.querySelector('.series-cb').value);
        if (sid) openSeriesPanel(sid);
    });
}

function lookupAniListId(seriesName) {
    const url = `https://anilist.co/search/manga?search=${encodeURIComponent(seriesName)}`;
    window.open(url, '_blank');
}

function _panelField(panel, sid, idSuffix) {
    const id = idSuffix + sid;
    return (panel && panel.querySelector('#' + id)) || document.getElementById(id);
}

function saveOverride(seriesId, btn) {
    const sid = String(seriesId);
    const panel = document.getElementById('panel-' + sid) || _overridePanelCache[sid];
    const forcedIdEl = _panelField(panel, sid, 'id-');
    const altTitleEl = _panelField(panel, sid, 'title-');
    if (!forcedIdEl || !altTitleEl) return;

    const forcedId = forcedIdEl.value;
    const altTitle = altTitleEl.value;

    const providerSelect = _panelField(panel, sid, 'provider-');
    const forcedProvider = providerSelect ? providerSelect.value : 'AUTO';

    const pubPrefInput = panel
        ? panel.querySelector(`input[name="pubpref-${sid}"]:checked`)
        : document.querySelector(`input[name="pubpref-${sid}"]:checked`);
    const publisherPref = pubPrefInput ? pubPrefInput.value : 'GLOBAL';
    const altLangsInput = _panelField(panel, sid, 'alt-langs-');
    const altTitleLangs = altLangsInput ? altLangsInput.value.trim() : '';

    const activeFields = TARGETED_FIELD_KEYS.filter(f => {
        const cb = _panelField(panel, sid, 'field-' + f + '-');
        return cb && cb.checked;
    }).join(',');

    const item = findSeriesItemById(sid);
    if (item) {
        item.dataset.forcedId = forcedId;
        item.dataset.altTitle = altTitle;
        item.dataset.forcedProvider = forcedProvider;
        item.dataset.publisherPref = publisherPref;
        item.dataset.altLangs = altTitleLangs;
        item.dataset.targetedFields = activeFields || 'NONE';
    }
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.patchOverride === 'function') {
        window.SeriesList.patchOverride(sid, {
            forced_id: forcedId,
            alternative_title: altTitle,
            forced_provider: forcedProvider,
            publisher_pref: publisherPref,
            alt_title_langs: altTitleLangs,
            targeted_fields: activeFields || 'NONE',
        });
    }

    if (btn) btn.innerText = "⏳...";

    return fetch(getRootPath() + '/save-override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${sid}&forced_id=${encodeURIComponent(forcedId)}&alternative_title=${encodeURIComponent(altTitle)}&forced_provider=${encodeURIComponent(forcedProvider)}&targeted_fields=${encodeURIComponent(activeFields)}&publisher_pref=${encodeURIComponent(publisherPref)}&alt_title_langs=${encodeURIComponent(altTitleLangs)}`
    }).then(r => {
        if (r.ok && btn) {
            btn.innerText = "✅";
            setTimeout(() => { btn.innerText = window.AppTranslations.save; }, 1500);
        }
        return r;
    });
}

function _openOverridePanels() {
    const bySid = {};
    Object.keys(_overridePanelCache).forEach(function (sid) {
        const panel = _overridePanelCache[sid];
        if (panel && (panel.style.display === 'block' || panel.style.display === 'flex')) {
            bySid[sid] = panel;
        }
    });
    document.querySelectorAll('.override-panel').forEach(function (panel) {
        if (panel.style.display !== 'block' && panel.style.display !== 'flex') return;
        const m = (panel.id || '').match(/^panel-(.+)$/);
        if (m) bySid[m[1]] = panel;
    });
    return bySid;
}

async function saveAllOverrides(btn) {
    const open = _openOverridePanels();
    const sids = Object.keys(open);
    const originalText = btn.innerHTML;

    if (sids.length === 0) {
        btn.innerHTML = window.AppTranslations.batch_empty || '—';
        setTimeout(function () { btn.innerHTML = originalText; }, 1500);
        return;
    }

    btn.classList.add('btn-saving');
    btn.innerHTML = "⏳ " + window.AppTranslations.saving_progress;
    btn.disabled = true;

    for (let i = 0; i < sids.length; i++) {
        const sid = sids[i];
        const panel = open[sid];
        const saveBtn = panel ? panel.querySelector('button.btn-success, [data-save-override]') : null;
        await saveOverride(sid, saveBtn);
        await new Promise(r => setTimeout(r, 250));
    }

    btn.classList.remove('btn-saving');
    btn.innerHTML = originalText;
    btn.disabled = false;
}
