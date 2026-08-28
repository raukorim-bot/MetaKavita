// C88 — hydratation de la modale mapping (DOM déjà posé en G1).
// Remplit les <select> existants. Ne reconstruit pas la grille.

var _fmLoadGen = 0;
var _fmReady = false;

function _fmModal() {
    return document.getElementById('fieldMappingModal');
}

function _fmT(key, fallback) {
    const dict = window.AppTranslations || {};
    return dict[key] || fallback;
}

function markOverrideState(sel) {
    if (!sel || sel.tagName !== 'SELECT') return;
    const field = sel.closest('.fm-field');
    const def = sel.closest('.fm-default');
    if (field) field.classList.toggle('is-override', !!sel.value);
    if (def) def.classList.toggle('is-override', !!(sel.value && sel.value !== 'CASCADE'));
}

function _fmSetStatus(kind, visible) {
    const modal = _fmModal();
    if (!modal) return;
    const el = modal.querySelector('.fm-' + kind);
    if (!el) return;
    el.hidden = !visible;
    if (kind === 'error' && visible && el.dataset.default && !el.textContent.trim()) {
        el.textContent = el.dataset.default;
    }
}

function _fmSetBusy(busy) {
    const btn = document.getElementById('fmSaveBtn');
    if (btn) btn.disabled = !!busy || !_fmReady;
    _fmSetStatus('loading', !!busy);
    if (busy) _fmSetStatus('error', false);
}

function _fmFillSelect(sel, extra, selected) {
    if (!sel) return;
    const first = sel.options[0];
    const firstVal = first ? first.value : '';
    const firstText = first ? first.textContent : '';
    while (sel.options.length) sel.remove(0);
    const opt0 = document.createElement('option');
    opt0.value = firstVal;
    opt0.textContent = firstText;
    sel.appendChild(opt0);
    (extra || []).forEach(function (p) {
        if (!p || !p.id || p.id === firstVal) return;
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.display_name || p.id;
        sel.appendChild(opt);
    });
    const want = selected == null ? firstVal : String(selected);
    const known = Array.prototype.some.call(sel.options, function (o) { return o.value === want; });
    sel.value = known ? want : firstVal;
    markOverrideState(sel);
}

function fillWaveBlock(waveEl, payload) {
    if (!waveEl || !payload) return;
    const providers = payload.providers || [];
    _fmFillSelect(
        waveEl.querySelector('[data-role="default"]'),
        providers,
        payload.default || 'CASCADE'
    );
    const overrides = payload.overrides || {};
    waveEl.querySelectorAll('[data-role="override"]').forEach(function (sel) {
        const field = sel.getAttribute('data-field');
        _fmFillSelect(sel, providers, overrides[field] || '');
    });
}

function loadFieldMapping() {
    const modal = _fmModal();
    if (!modal) return;
    _fmReady = false;
    const gen = ++_fmLoadGen;
    _fmSetBusy(true);
    fetch(getRootPath() + '/api/config/field-mapping', {
        method: 'GET',
        headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    })
    .then(function (result) {
        if (gen !== _fmLoadGen) return;
        if (!result.ok || !result.data || !result.data.success) {
            throw new Error('load');
        }
        const plans = result.data.plans || {};
        modal.querySelectorAll('.fm-wave[data-plan]').forEach(function (wave) {
            const id = wave.getAttribute('data-plan');
            if (plans[id]) fillWaveBlock(wave, plans[id]);
        });
        _fmReady = true;
        _fmSetStatus('error', false);
    })
    .catch(function () {
        if (gen !== _fmLoadGen) return;
        _fmReady = false;
        const err = modal.querySelector('.fm-error');
        if (err) {
            err.textContent = err.dataset.default || _fmT('field_mapping_error', 'Error');
            err.hidden = false;
        }
    })
    .finally(function () {
        if (gen !== _fmLoadGen) return;
        _fmSetBusy(false);
    });
}

function _fmCollectPlans() {
    const plans = {};
    const modal = _fmModal();
    if (!modal) return plans;
    modal.querySelectorAll('.fm-wave[data-plan]').forEach(function (wave) {
        const id = wave.getAttribute('data-plan');
        const defSel = wave.querySelector('[data-role="default"]');
        const overrides = {};
        wave.querySelectorAll('[data-role="override"]').forEach(function (sel) {
            if (sel.value) overrides[sel.getAttribute('data-field')] = sel.value;
        });
        plans[id] = {
            default: defSel ? defSel.value : 'CASCADE',
            overrides: overrides,
        };
    });
    return plans;
}

function saveFieldMapping() {
    if (!_fmReady) return;
    const form = document.getElementById('fieldMappingForm');
    if (!form) return;
    const btn = document.getElementById('fmSaveBtn');
    const originalText = btn ? btn.innerText : '';
    _fmSetBusy(true);
    if (btn) btn.innerText = '⏳...';

    fetch(getRootPath() + '/api/config/field-mapping', {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ plans: _fmCollectPlans() }),
    })
    .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    })
    .then(function (result) {
        if (!result.ok || !result.data || !result.data.success) {
            throw new Error('save');
        }
        if (btn) {
            btn.innerText = _fmT('action_ok', 'OK');
            setTimeout(function () {
                if (btn) btn.innerText = originalText;
                closeFieldMappingModal();
            }, 400);
        } else {
            closeFieldMappingModal();
        }
        _fmSetStatus('error', false);
    })
    .catch(function () {
        const modal = _fmModal();
        const err = modal && modal.querySelector('.fm-error');
        if (err) {
            err.textContent = err.dataset.default || _fmT('field_mapping_error', 'Error');
            err.hidden = false;
        }
        if (btn) btn.innerText = originalText;
    })
    .finally(function () {
        _fmSetBusy(false);
    });
}

function openFieldMappingModal() {
    const modal = _fmModal();
    if (modal) modal.style.display = 'flex';
    loadFieldMapping();
}

document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('btnOpenFieldMapping');
    if (btn) btn.disabled = false;
    const modal = _fmModal();
    if (!modal) return;
    const saveBtn = document.getElementById('fmSaveBtn');
    if (saveBtn) saveBtn.disabled = true;
    modal.addEventListener('change', function (e) {
        const sel = e.target && e.target.closest ? e.target.closest('select') : e.target;
        markOverrideState(sel);
    });
});
