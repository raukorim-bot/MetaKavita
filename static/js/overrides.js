// --- SURCHARGES PAR SÉRIE (ID/URL forcé, titre alternatif, champs ciblés, provider) ---
// Dépend de utils.js (getRootPath).
// BF96 / #30 : panneau Options construit à la demande (template unique).

// Miroir de ALL_TARGETED_FIELDS (services/enrichment_engine.py). « format »
// (Sens lecture) en a été retiré : Kavita n'accepte aucun sens de lecture par
// série, la case ne pilotait donc aucune écriture.
const TARGETED_FIELD_KEYS = [
    'summary', 'cover', 'staff', 'genres', 'tags', 'year',
    'status', 'publisher', 'age', 'weblinks', 'alt_titles', 'language'
];

function isForcedProvider(raw) {
    var v = String(raw == null ? 'AUTO' : raw).trim();
    return v !== '' && v.toUpperCase() !== 'AUTO';
}

function isGranularTargetedFields(raw) {
    var v = String(raw == null ? '' : raw).trim();
    if (!v || v.toUpperCase() === 'ALL') return false;
    if (v.toUpperCase() === 'NONE') return true;
    var keys = v.split(',').map(function (f) { return f.trim(); }).filter(Boolean);
    if (!keys.length) return false;
    if (keys.length !== TARGETED_FIELD_KEYS.length) return true;
    return !TARGETED_FIELD_KEYS.every(function (k) { return keys.indexOf(k) >= 0; });
}

function altTitleIsOverride(altTitle, seriesName) {
    var alt = String(altTitle == null ? '' : altTitle).trim();
    var name = String(seriesName == null ? '' : seriesName).trim();
    return !!alt && alt.toLowerCase() !== name.toLowerCase();
}

function publisherPrefIsOverride(raw) {
    var v = String(raw == null ? 'GLOBAL' : raw).trim().toUpperCase();
    return v !== '' && v !== 'GLOBAL';
}

function altLangsIsOverride(raw) {
    return !!String(raw == null ? '' : raw).trim();
}

function publisherPrefChipLabel(raw) {
    var v = String(raw == null ? 'GLOBAL' : raw).trim().toUpperCase();
    if (v === 'ORIGINAL' || v === 'VO') return 'VO';
    if (v === 'LOCALIZED' || v === 'VF' || v === 'VA' || v === 'VF/VA') return 'VF/VA';
    return String(raw == null ? '' : raw).trim();
}

function altLangsChipLabel(raw) {
    return String(raw == null ? '' : raw).split(',').map(function (x) {
        return x.trim();
    }).filter(Boolean).join(', ');
}

function providerDisplayName(id) {
    var map = window.PROVIDER_LABELS || {};
    return map[id] || id;
}

function _overrideChipHtml(cls, title, label, openTargeted) {
    var extra = openTargeted ? ' data-open-targeted="1"' : '';
    return '<button type="button" class="badge badge-override ' + cls +
        '" data-action="open-options"' + extra + ' title="' + title + '">' +
        label + '</button>';
}

function overrideBadgesHtml(s, forcedId, targetedFields) {
    var series = (s && typeof s === 'object' && !Array.isArray(s))
        ? s
        : { forced_provider: s, forced_id: forcedId, targeted_fields: targetedFields };
    var escFn = window.escapeHtmlText || function (t) { return String(t == null ? '' : t); };
    var tr = window.AppTranslations || {};
    var html = '';
    var alt = series.alternative_title;
    if (altTitleIsOverride(alt, series.name)) {
        var altHint = String(alt).trim() + ' — ' + (tr.override_alt_title_badge_hint || '');
        html += _overrideChipHtml('badge-override-alt', escFn(altHint), escFn(String(alt).trim()), false);
    }
    if (publisherPrefIsOverride(series.publisher_pref)) {
        html += _overrideChipHtml(
            'badge-override-pub',
            escFn(tr.override_publisher_badge_hint || ''),
            escFn(publisherPrefChipLabel(series.publisher_pref)),
            false
        );
    }
    if (altLangsIsOverride(series.alt_title_langs)) {
        html += _overrideChipHtml(
            'badge-override-langs',
            escFn(tr.override_langs_badge_hint || ''),
            escFn(altLangsChipLabel(series.alt_title_langs)),
            true
        );
    }
    var forcedProvider = series.forced_provider;
    var fid = series.forced_id;
    if (isForcedProvider(forcedProvider)) {
        html += _overrideChipHtml(
            'badge-override-provider',
            escFn(tr.override_provider_badge_hint || ''),
            escFn(providerDisplayName(forcedProvider)),
            false
        );
    } else if (String(fid || '').trim()) {
        html += _overrideChipHtml(
            'badge-override-provider',
            escFn(tr.override_id_badge_hint || ''),
            escFn(tr.override_id_badge || 'Forced ID'),
            false
        );
    }
    if (isGranularTargetedFields(series.targeted_fields)) {
        html += _overrideChipHtml(
            'badge-override-fields',
            escFn(tr.override_fields_badge_hint || ''),
            escFn(tr.override_fields_badge || 'Targeted'),
            true
        );
    }
    return html;
}

function bindOverrideBadge(btn, seriesId) {
    if (!btn || btn.dataset.boundOverride === '1') return;
    btn.dataset.boundOverride = '1';
    btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openSeriesOverride(seriesId, btn.getAttribute('data-open-targeted') === '1');
    });
}

function syncSeriesOverrideBadges(item) {
    if (!item) return;
    var status = item.querySelector('.series-status');
    if (!status) return;
    status.querySelectorAll('.badge-override').forEach(function (el) {
        el.remove();
    });
    var wrap = document.createElement('div');
    wrap.innerHTML = overrideBadgesHtml({
        forced_provider: item.dataset.forcedProvider,
        forced_id: item.dataset.forcedId,
        targeted_fields: item.dataset.targetedFields,
        alternative_title: item.dataset.altTitle,
        name: item.dataset.seriesName,
        publisher_pref: item.dataset.publisherPref,
        alt_title_langs: item.dataset.altLangs
    });
    var cover = status.querySelector('.badge-cover-manual');
    var sid = item.dataset.seriesId;
    Array.prototype.slice.call(wrap.children).forEach(function (node) {
        if (cover) status.insertBefore(node, cover);
        else status.appendChild(node);
        bindOverrideBadge(node, sid);
    });
}

function openSeriesOverride(seriesId, openTargeted) {
    var panel = openSeriesPanel(seriesId);
    if (openTargeted && panel) {
        var details = panel.querySelector('.targeted-scraping-details');
        if (details) details.open = true;
    }
    return panel;
}

let allPanelsExpanded = false;

/** Survive virtual-list re-renders (innerHTML wipe). */
var _overridePanelCache = {};

/** Appelé par loadLibrary : évite panneaux orphelins / cache stale. */
function clearOverridePanelCache() {
    Object.keys(_overridePanelCache).forEach(function (sid) {
        const panel = _overridePanelCache[sid];
        if (panel && panel.parentNode) {
            try { panel.parentNode.removeChild(panel); } catch (e) { /* ignore */ }
        }
        delete _overridePanelCache[sid];
    });
    allPanelsExpanded = false;
}

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

/**
 * IDs to expand = set filtré courant (matchedIds), pas le viewport.
 * Workflow cleanup : filtrer NOT_FOUND / erreurs → Déplier tout → éditer → Tout sauvegarder.
 */
function _matchedSeriesIdsForPanels() {
    if (typeof matchedIds !== 'undefined' && Array.isArray(matchedIds) && matchedIds.length) {
        return matchedIds.slice();
    }
    // Fallback : rows DOM non filtrées (liste non virtualisée / avant premier filterSeries).
    return Array.from(document.querySelectorAll('.series-item'))
        .filter(function (item) { return !item.classList.contains('is-filtered-out'); })
        .map(function (item) {
            return item.dataset.seriesId
                || (item.querySelector('.series-cb') && item.querySelector('.series-cb').value);
        })
        .filter(Boolean)
        .map(String);
}

/**
 * Expand/collapse Options for every series in the current filter (matched),
 * including those outside the virtual viewport. Warns before expand (can be slow).
 */
function toggleAllOverridePanels() {
    if (allPanelsExpanded) {
        allPanelsExpanded = false;
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

    const ids = _matchedSeriesIdsForPanels();
    if (ids.length === 0) return;

    const T = window.AppTranslations || {};
    const warn = (T.toggle_all_overrides_warn ||
        'Open Options for {0} series? This can take a while and freeze the tab briefly.')
        .replace('{0}', String(ids.length));
    if (!window.confirm(warn)) return;

    allPanelsExpanded = true;
    // Pin all first (one virtual re-render), then attach/open each panel.
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.pinOpenPanels === 'function') {
        window.SeriesList.pinOpenPanels(ids);
    }
    ids.forEach(function (sid) {
        const panel = ensureOverridePanel(sid);
        if (panel) panel.style.display = 'block';
    });
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.afterPanelOpened === 'function') {
        window.SeriesList.afterPanelOpened();
    }
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

    // Aucune case cochée : 'NONE' explicite. Toutes cochées : 'ALL', pas la
    // liste CSV, sinon le granulaire se lirait actif à tort.
    const checked = TARGETED_FIELD_KEYS.filter(f => {
        const cb = _panelField(panel, sid, 'field-' + f + '-');
        return cb && cb.checked;
    });
    const activeFields = checked.length === 0
        ? 'NONE'
        : (checked.length === TARGETED_FIELD_KEYS.length ? 'ALL' : checked.join(','));

    const item = findSeriesItemById(sid);
    if (item) {
        item.dataset.forcedId = forcedId;
        item.dataset.altTitle = altTitle;
        item.dataset.forcedProvider = forcedProvider;
        item.dataset.publisherPref = publisherPref;
        item.dataset.altLangs = altTitleLangs;
        item.dataset.targetedFields = activeFields;
        syncSeriesOverrideBadges(item);
    }
    if (typeof window.SeriesList !== 'undefined' && window.SeriesList && typeof window.SeriesList.patchOverride === 'function') {
        window.SeriesList.patchOverride(sid, {
            forced_id: forcedId,
            alternative_title: altTitle,
            forced_provider: forcedProvider,
            publisher_pref: publisherPref,
            alt_title_langs: altTitleLangs,
            targeted_fields: activeFields,
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
