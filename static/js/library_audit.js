/* Library Inventory UI — Analyser, chips, volume report, missing, duplicates. */

window.hygieneFilter = null;
var _volumeReportSeriesId = null;
var _volumeReportSeriesName = null;

function _auditT() {
    return window.AppTranslations || {};
}

function _escHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function _selectedLibraryId() {
    var sel = document.getElementById('lib_selector');
    return sel && sel.value ? sel.value : '';
}

/* États de complétion connus du backend (volume_report.resolve_completion_state).
 * La couleur porte l'information : `uptodate` = série en cours dont on possède
 * tout le publié (ce n'est pas un manque), `overshoot` = plus de tomes que
 * l'attendu (donnée douteuse, pas une réussite). */
var _AUDIT_STATES = ['complete', 'uptodate', 'near', 'partial', 'poor', 'overshoot', 'unknown', 'neutral'];

function _auditBadgeClass(state, forced) {
    var cls = 'badge badge-audit';
    if (state && _AUDIT_STATES.indexOf(state) !== -1) cls += ' badge-audit--' + state;
    if (forced) cls += ' badge-audit--forced';
    return cls;
}

function _auditBadgeTitle(state, forced, unit) {
    var tr = _auditT();
    var parts = [];
    var stateLabel = tr['audit_state_' + (state || '')];
    parts.push(stateLabel || tr.audit_badge_title || '');
    if (unit === 'chapters' && tr.audit_unit_chapters) parts.push(tr.audit_unit_chapters);
    if (forced && tr.audit_forced_expected) parts.push(tr.audit_forced_expected);
    return parts.filter(Boolean).join(' · ');
}

/** Numéros contigus en intervalles : « 2, 3, 4, 12 » → « 2–4, 12 ». Repli pour
 * les rapports mis en cache avant que le backend ne fournisse le libellé. */
function _rangesLabel(nums) {
    var ints = (nums || [])
        .map(function (n) { return parseInt(n, 10); })
        .filter(function (n) { return !isNaN(n); })
        .sort(function (a, b) { return a - b; });
    if (!ints.length) return '';
    var out = [];
    var start = ints[0];
    var prev = ints[0];
    for (var i = 1; i < ints.length; i++) {
        if (ints[i] === prev || ints[i] === prev + 1) { prev = ints[i]; continue; }
        out.push(start === prev ? String(start) : start + '\u2013' + prev);
        start = prev = ints[i];
    }
    out.push(start === prev ? String(start) : start + '\u2013' + prev);
    return out.join(', ');
}

function _missingLabel(row) {
    if (row && row.missing_label) return row.missing_label;
    return _rangesLabel((row && (row.missing_volumes || row.missing)) || []);
}

/** "Toutes les bibliothèques" (select vide) est un scope valide pour l'hygiène —
 * le backend le stocke/traite sous la clé "all" (voir hygiene_scan.py). */
function _selectedLibraryIdOrAll() {
    return _selectedLibraryId() || 'all';
}

function closeVolumeReportModal() {
    var m = document.getElementById('volumeReportModal');
    if (m) {
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
    }
}

function closeDuplicatesModal() {
    var m = document.getElementById('duplicatesModal');
    if (m) {
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
    }
}

function closeMissingVolumesModal() {
    var m = document.getElementById('missingVolumesModal');
    if (m) {
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
    }
}

document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    closeVolumeReportModal();
    closeDuplicatesModal();
    closeMissingVolumesModal();
});

function openVolumeReportModal(seriesId, seriesName) {
    var m = document.getElementById('volumeReportModal');
    var body = document.getElementById('volumeReportBody');
    var meta = document.getElementById('volumeReportMeta');
    var title = document.getElementById('volumeReportTitle');
    var tr = _auditT();
    if (!m || !body) return;
    _volumeReportSeriesId = seriesId;
    _volumeReportSeriesName = seriesName || seriesId;
    if (title) {
        // `textContent` effacerait l'icône du titre : on ne remplace que le libellé.
        var label = title.querySelector('.audit-modal-label');
        if (!label) {
            label = document.createElement('span');
            label.className = 'audit-modal-label';
            title.appendChild(label);
        }
        label.textContent = (tr.audit_volume_report || 'Volume report') + ' — ' + _volumeReportSeriesName;
    }
    body.innerHTML = _loadingHtml(tr);
    if (meta) meta.textContent = '';
    var csv = document.getElementById('volumeReportCsv');
    var txt = document.getElementById('volumeReportTxt');
    if (csv) csv.href = '/api/series/' + seriesId + '/volume-report?format=csv&refresh=1';
    if (txt) txt.href = '/api/series/' + seriesId + '/volume-report?format=txt&refresh=1';
    m.style.display = 'flex';
    m.setAttribute('aria-hidden', 'false');
    _loadVolumeReport(seriesId, false);
}

function refreshVolumeReport() {
    if (_volumeReportSeriesId == null) return;
    _loadVolumeReport(_volumeReportSeriesId, true);
}

function _loadVolumeReport(seriesId, forceRefresh) {
    var body = document.getElementById('volumeReportBody');
    var tr = _auditT();
    if (!body) return;
    body.innerHTML = _loadingHtml(tr);
    var url = forceRefresh
        ? '/api/series/' + seriesId + '/volume-report?refresh=1'
        : '/api/series/' + seriesId + '/volume-report/summary';
    fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
            if (r.status === 404 && !forceRefresh) {
                return fetch('/api/series/' + seriesId + '/volume-report?refresh=1', { credentials: 'same-origin' })
                    .then(function (r2) { return r2.json(); });
            }
            return r.json();
        })
        .then(function (data) {
            if (!data || !data.success) {
                body.innerHTML = _errorHtml(tr, data && data.error);
                return;
            }
            _renderVolumeReport(data);
            if (data.badge) {
                _applyAuditBadge(seriesId, data.badge, {
                    state: (data.completion || {}).state,
                    forced: !!(data.completion || {}).forced,
                    unit: (data.primary || {}).unit,
                });
            }
        })
        .catch(function () {
            body.innerHTML = _errorHtml(tr);
        });
}

function _catalogLabel(cat, tr) {
    var status = (cat && cat.status) || 'unknown';
    if (status === 'ok' && cat.expected != null) {
        var label = String(cat.expected) + (cat.provider ? ' (' + cat.provider + ')' : '');
        if (cat.source === 'backup') {
            label += ' · ' + (tr.audit_source_backup || 'backup');
        }
        return label;
    }
    if (status === 'error') return tr.audit_catalog_error || 'Error';
    if (status === 'skipped') return tr.audit_catalog_skipped || 'Skipped';
    return tr.audit_catalog_unknown || 'Unknown';
}

function _pubStatusLabel(status, tr) {
    var s = String(status || 'UNKNOWN').toUpperCase();
    if (s === 'FINISHED') return tr.audit_pub_finished || 'Finished';
    if (s === 'RELEASING' || s === 'HIATUS' || s === 'NOT_YET_RELEASED') {
        return tr.audit_pub_releasing || 'Ongoing';
    }
    if (s === 'CANCELLED') return tr.audit_pub_cancelled || 'Cancelled';
    return tr.audit_pub_unknown || 'Unknown';
}

function _catalogReasonLabel(reason, tr) {
    var map = {
        ok: tr.audit_reason_ok || 'OK',
        manual: tr.audit_reason_manual || 'Manual',
        ongoing_no_count: tr.audit_reason_ongoing || 'Ongoing (no volume count)',
        volumes_null: tr.audit_reason_volumes_null || 'No volume count',
        no_id: tr.audit_reason_no_id || 'No provider id',
        title_mismatch: tr.audit_reason_title_mismatch || 'Title mismatch',
        provider_error: tr.audit_reason_provider_error || 'Provider error',
        provider_skipped: tr.audit_reason_provider_skipped || 'Provider skipped',
    };
    return map[reason] || reason || '—';
}

function _statCard(label, value, extraClass, hint) {
    // Un tiret seul sous la valeur (raison de catalogue vide) n'apporte rien et
    // décale la hauteur des cartes voisines.
    var useHint = hint && hint !== '—';
    return '<div class="audit-stat' + (extraClass ? ' ' + extraClass : '') + '">' +
        '<span class="audit-stat-label">' + _escHtml(label) + '</span>' +
        '<span class="audit-stat-value">' + value + '</span>' +
        (useHint ? '<span class="audit-stat-hint">' + _escHtml(hint) + '</span>' : '') +
        '</div>';
}

/* `data-label` reprend l'en-tête de colonne : sous 720 px le tableau se replie en
 * cartes et c'est cet attribut qui étiquette chaque valeur (cf. style.css).
 * La valeur est enveloppée pour ne former qu'un seul élément : en mode carte la
 * cellule est un conteneur flex, et « Terminée <span>(OK)</span> » s'y séparait
 * en deux morceaux collés aux deux bords. */
function _cell(value, label, extraClass, raw) {
    // Une cellule sans valeur n'apporte rien à une carte de six lignes : on la
    // marque pour la masquer en mode carte (elle reste dans le tableau).
    var empty = !raw && (value == null || value === '' || value === '—');
    return '<td' + (label ? ' data-label="' + _escHtml(label) + '"' : '') +
        (empty ? ' data-empty="1"' : '') +
        (extraClass ? ' class="' + extraClass + '"' : '') +
        '><span class="audit-cell-v">' + (raw ? value : _escHtml(value)) + '</span></td>';
}

/* États vides / chargement / erreur : illustration + phrase, plutôt qu'une
 * ligne de texte seule au milieu d'une modale large. `icon` = suffixe d'un
 * symbole du sprite (_icons_sprite.html), `tone` colore l'illustration. */
function _stateHtml(icon, title, hint, mods) {
    var cls = 'audit-state' + String(mods || '').split(/\s+/).filter(Boolean)
        .map(function (m) { return ' audit-state--' + m; }).join('');
    return '<div class="' + cls + '">' +
        '<svg class="audit-state-art" aria-hidden="true"><use href="#mk-ico-' + icon + '"></use></svg>' +
        '<p class="audit-state-title">' + _escHtml(title) + '</p>' +
        (hint ? '<p class="audit-state-hint">' + _escHtml(hint) + '</p>' : '') +
        '</div>';
}

function _loadingHtml(tr, inline) {
    return '<div class="audit-state audit-spinner' + (inline ? ' audit-state--inline' : '') + '">' +
        '<svg class="audit-state-art" aria-hidden="true"><use href="#mk-ico-spinner"></use></svg>' +
        '<p class="audit-state-title">' + _escHtml(tr.audit_loading || '…') + '</p>' +
        '</div>';
}

function _errorHtml(tr, message) {
    return _stateHtml('alert', message || tr.audit_err_generic || 'Error', '', 'error');
}

function _unitLabel(unit, tr) {
    if (unit === 'chapters') return tr.audit_unit_chapters || 'chapters';
    if (unit === 'issues') return tr.audit_unit_issues || 'issues';
    return tr.audit_unit_volumes || 'volumes';
}

function _renderVolumeReport(data) {
    var tr = _auditT();
    var meta = document.getElementById('volumeReportMeta');
    var body = document.getElementById('volumeReportBody');
    var stats = data.stats || {};
    var cat = data.catalog || {};
    var primary = data.primary || {};
    var completion = data.completion || {};
    var chapters = data.chapters || {};
    var unit = primary.unit || cat.unit || 'volumes';
    var unitMode = data.unit_mode || 'volumes';
    var pub = data.publication_status || cat.publication_status || 'UNKNOWN';
    var forced = !!completion.forced || cat.provider === 'MANUAL';
    var expected = primary.expected != null ? primary.expected : cat.expected;
    var forcedVal = (forced && expected != null) ? String(expected) : '';
    var missingLabel = primary.missing_label || _rangesLabel(primary.missing || data.missing_volumes || []);
    var gapsLabel = primary.gaps_label || _rangesLabel(primary.gaps || data.gaps || []);
    var outOfRangeLabel = primary.out_of_range_label ||
        _rangesLabel(primary.out_of_range || data.out_of_range || []);
    if (meta) {
        var ownedValue = '<span class="' + _auditBadgeClass(completion.state, forced) + '">' +
            _escHtml(data.badge || '—') + '</span>';
        var expectedValue = forced
            ? _escHtml(String(expected)) + ' <span class="muted">(' +
              _escHtml(tr.audit_forced_expected || 'forced') + ')</span>'
            : _escHtml(_catalogLabel(cat, tr));
        meta.innerHTML =
            _statCard(tr.audit_owned || 'Possédés', ownedValue, null, _unitLabel(unit, tr)) +
            // En mode tomes, « Volumes Kavita » répéterait « Possédés ». Sur une
            // série en chapitres, la carte n'a d'intérêt que s'il reste des tomes
            // numérotés à côté des feuilles volantes.
            (unitMode === 'chapters' && stats.kavita_count
                ? _statCard(tr.audit_kavita_count || 'Kavita',
                    _escHtml(stats.kavita_count), null, _unitLabel('volumes', tr))
                : '') +
            _statCard(tr.audit_attendu || 'Attendu', expectedValue, null,
                _catalogReasonLabel(cat.reason, tr)) +
            _statCard(tr.audit_pub_status || 'Publication',
                _escHtml(_pubStatusLabel(pub, tr))) +
            // Rien ne manque : une carte « — » pleine largeur ne dit rien et
            // repousse le reste vers le bas.
            (missingLabel
                ? _statCard(
                    (unit === 'chapters' ? (tr.audit_missing_chapters || 'Chapitres manquants')
                                         : (tr.audit_missing_volumes || 'Volumes manquants')),
                    _escHtml(missingLabel),
                    'audit-stat--missing audit-stat--wide',
                    tr.audit_missing_hint || ''
                )
                : '') +
            // Trous locaux identiques aux manquants : la seconde carte n'apprend
            // rien (cas d'une série où l'on ne possède que les extrémités).
            (gapsLabel && gapsLabel !== missingLabel
                ? _statCard(tr.audit_local_gaps || 'Trous locaux', _escHtml(gapsLabel),
                    'audit-stat--gaps audit-stat--wide', tr.audit_local_gaps_hint || '')
                : '') +
            // Hors plage : nomme le tome isolé (intégrale, hors-série) qui est
            // écarté du compte, au lieu de le laisser gonfler le badge en douce.
            (outOfRangeLabel
                ? _statCard(tr.audit_out_of_range || 'Hors plage', _escHtml(outOfRangeLabel),
                    'audit-stat--gaps', tr.audit_out_of_range_hint || '')
                : '') +
            // Hygiène des unités : le tableau ne montre plus les colonnes vides,
            // donc le total remonte ici — et seulement s'il manque quelque chose.
            (stats.total && stats.missing_summary
                ? _statCard(tr.audit_missing_summary || 'Sans résumé',
                    _escHtml(stats.missing_summary + ' / ' + stats.total))
                : '') +
            (stats.total && stats.missing_isbn
                ? _statCard(tr.audit_missing_isbn || 'Sans ISBN',
                    _escHtml(stats.missing_isbn + ' / ' + stats.total))
                : '') +
            // En mode chapitres, « Possédés » porte déjà le compte de chapitres ;
            // et sur un comic à un chapitre par tome, il le répète à l'identique.
            (chapters.count && unitMode !== 'chapters' && chapters.count !== primary.count
                ? _statCard(tr.audit_chapter_count || 'Chapitres',
                    _escHtml(chapters.count) +
                    (chapters.expected ? ' / ' + _escHtml(chapters.expected) : ''))
                : '');
    }
    var units = data.units || [];
    var hasUnits = !!units.length;
    // Colonnes déduites du contenu : un comic « un chapitre par tome » remplissait
    // Tome et Ch. avec le même nombre, et une série sans titres ni ISBN alignait
    // quatre colonnes de tirets. `always` garde le contrôle de résumé, dont
    // l'absence est justement ce que le rapport doit montrer.
    var colDefs = [
        { label: tr.audit_col_volume || 'Vol', cls: 'audit-cell-num',
          get: function (u) { return u.volume_number == null ? '' : String(u.volume_number); } },
        { label: tr.audit_col_chapter || 'Ch', cls: 'audit-cell-num',
          get: function (u) {
              return (u.chapter_number == null || u.chapter_number === u.volume_number)
                  ? '' : String(u.chapter_number);
          } },
        { label: tr.audit_col_name || 'Nom', get: function (u) { return u.name || ''; } },
        { label: tr.audit_col_summary || 'Résumé', always: true,
          get: function (u) { return u.has_summary ? '✓' : ''; } },
        { label: tr.audit_col_isbn || 'ISBN', get: function (u) { return u.isbn || ''; } },
        { label: tr.audit_col_flags || '', get: function (u) {
              return u.is_special ? (tr.audit_flag_special || 'SP')
                  : (u.is_loose ? (tr.audit_flag_loose || 'loose') : '');
          } },
    ];
    var colsUsed = colDefs.filter(function (c) {
        // Avant le chargement paresseux des unités, on garde l'en-tête complet.
        return c.always || !hasUnits || units.some(function (u) { return c.get(u) !== ''; });
    });
    var cols = colsUsed.map(function (c) { return c.label; });
    var rows = units.map(function (u) {
        return '<tr>' + colsUsed.map(function (c) {
            return _cell(c.get(u) || '—', c.label, c.cls);
        }).join('') + '</tr>';
    }).join('');
    var excluded = !!data.inventory_excluded;
    body.innerHTML =
        '<div class="audit-override-row' + (forced ? ' is-active' : '') + '">' +
        '<label class="audit-override-label" for="catalogExpectedInput">' +
        _escHtml(tr.audit_forced_expected || 'Attendu forcé') +
        ' <span class="muted">(' + _escHtml(_unitLabel(unit, tr)) + ')</span></label>' +
        '<input type="number" min="1" id="catalogExpectedInput" class="audit-override-input" ' +
        'value="' + _escHtml(forcedVal) + '" placeholder="' + _escHtml(tr.audit_forced_placeholder || '12') + '">' +
        '<button type="button" class="btn-opt" id="catalogExpectedSave">' +
        _escHtml(tr.audit_forced_save || 'Save') + '</button>' +
        '<button type="button" class="btn-secondary" id="catalogExpectedClear">' +
        _escHtml(tr.audit_forced_clear || 'Clear') + '</button>' +
        '<p class="audit-hint">' + _escHtml(tr.audit_forced_hint || '') + '</p>' +
        '</div>' +
        '<div class="audit-exclude-row">' +
        '<label class="checkbox-label"><input type="checkbox" id="auditExcludeCb"' +
        (excluded ? ' checked' : '') + '> ' +
        _escHtml(tr.audit_exclude_series || 'Exclure de l\'inventaire') + '</label>' +
        '<span class="audit-hint">' + _escHtml(tr.audit_exclude_hint || '') + '</span>' +
        '</div>' +
        '<div class="audit-table-wrap"><table class="audit-table">' +
        '<thead><tr>' +
        cols.map(function (c) { return '<th>' + _escHtml(c) + '</th>'; }).join('') +
        '</tr></thead>' +
        '<tbody id="volumeReportUnits">' +
        (rows || '<tr><td colspan="' + cols.length + '" class="muted">' +
            _escHtml(tr.audit_units_loading || '…') + '</td></tr>') +
        '</tbody></table></div>';
    var saveBtn = document.getElementById('catalogExpectedSave');
    var clearBtn = document.getElementById('catalogExpectedClear');
    if (saveBtn) {
        saveBtn.addEventListener('click', function () {
            var inp = document.getElementById('catalogExpectedInput');
            var v = inp && inp.value ? parseInt(inp.value, 10) : NaN;
            if (!(v >= 1)) {
                alert(tr.audit_forced_invalid || 'Enter a number >= 1');
                return;
            }
            saveCatalogExpected(v);
        });
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', function () { saveCatalogExpected(null); });
    }
    var excludeCb = document.getElementById('auditExcludeCb');
    if (excludeCb) {
        excludeCb.addEventListener('change', function () {
            setSeriesInventoryExcluded(_volumeReportSeriesId, excludeCb.checked);
        });
    }
    // Le cache ne contient que le résumé : sans ce chargement paresseux, le
    // tableau restait vide (« — ») à chaque première ouverture de la modale.
    if (!hasUnits && _volumeReportSeriesId != null) _loadVolumeReportUnits(_volumeReportSeriesId);
}

function _unitsColspan() {
    // Le nombre de colonnes varie (la colonne Ch. peut être masquée) : on le lit
    // sur l'en-tête plutôt que de le figer à 6.
    return document.querySelectorAll('#volumeReportBody .audit-table thead th').length || 6;
}

function _loadVolumeReportUnits(seriesId) {
    var tr = _auditT();
    fetch('/api/series/' + encodeURIComponent(seriesId) + '/volume-report/units', {
        credentials: 'same-origin',
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (String(_volumeReportSeriesId) !== String(seriesId)) return;
            var tbody = document.getElementById('volumeReportUnits');
            if (!tbody) return;
            if (!data || !data.success || !(data.units || []).length) {
                tbody.innerHTML = '<tr><td colspan="' + _unitsColspan() + '" class="audit-cell-state">' +
                    _stateHtml('empty', tr.audit_units_empty || '—', '', 'inline') + '</td></tr>';
                return;
            }
            _renderVolumeReport(data);
        })
        .catch(function () {
            var tbody = document.getElementById('volumeReportUnits');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="' + _unitsColspan() + '" class="audit-cell-state">' +
                    _stateHtml('alert', tr.audit_err_generic || 'Error', '', 'error inline') + '</td></tr>';
            }
        });
}

function setSeriesInventoryExcluded(seriesId, excluded) {
    var tr = _auditT();
    if (seriesId == null) return;
    fetch('/api/series/' + encodeURIComponent(seriesId) + '/inventory-exclude', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ excluded: !!excluded }),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data || !data.success) {
                alert((data && data.error) || (tr.audit_err_generic || 'Error'));
                return;
            }
            if (excluded) _applyAuditBadge(seriesId, '');
            if (window.SeriesList && typeof window.SeriesList.patchOverride === 'function') {
                window.SeriesList.patchOverride(seriesId, {
                    inventory_excluded: !!excluded,
                    audit_badge: excluded ? '' : undefined,
                });
            }
            if (typeof filterSeries === 'function') filterSeries();
        })
        .catch(function () { alert(tr.audit_err_generic || 'Error'); });
}

function saveCatalogExpected(expected) {
    var tr = _auditT();
    if (_volumeReportSeriesId == null) return;
    fetch('/api/series/' + encodeURIComponent(_volumeReportSeriesId) + '/catalog-expected', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected: expected }),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data || !data.success) {
                alert((data && data.error) || (tr.audit_err_generic || 'Error'));
                return;
            }
            var report = data.report || {};
            if (data.report) _renderVolumeReport(data.report);
            if (data.badge) {
                _applyAuditBadge(_volumeReportSeriesId, data.badge, {
                    state: (report.completion || {}).state,
                    forced: !!(report.completion || {}).forced,
                    unit: (report.primary || {}).unit,
                });
            }
            if (window.SeriesList && typeof window.SeriesList.patchOverride === 'function') {
                window.SeriesList.patchOverride(_volumeReportSeriesId, {
                    audit_badge: data.badge,
                    missing_count: ((report.primary || {}).missing || data.missing_volumes || []).length,
                    publication_status: data.publication_status || '',
                    catalog_expected: data.expected,
                    completion_state: (report.completion || {}).state || '',
                    forced_expected: !!(report.completion || {}).forced,
                });
            }
            if (typeof filterSeries === 'function') filterSeries();
        })
        .catch(function () { alert(tr.audit_err_generic || 'Error'); });
}

function _applyAuditBadge(seriesId, badge, opts) {
    var sid = String(seriesId);
    opts = opts || {};
    var state = opts.state || '';
    var forced = !!opts.forced;
    var unit = opts.unit || '';
    if (window.SeriesList && typeof window.SeriesList.applyAuditBadges === 'function') {
        var map = {};
        map[sid] = badge;
        window.SeriesList.applyAuditBadges(map);
    } else if (window.SeriesList && typeof window.SeriesList.getItem === 'function') {
        var item = window.SeriesList.getItem(sid);
        if (item) item.audit_badge = badge;
        if (typeof window.SeriesList.renderWindow === 'function') window.SeriesList.renderWindow();
    }
    if (window.SeriesList && typeof window.SeriesList.patchOverride === 'function' && state) {
        window.SeriesList.patchOverride(sid, {
            completion_state: state,
            forced_expected: forced,
            audit_unit: unit,
        });
    }
    document.querySelectorAll('.series-item[data-series-id="' + sid + '"]').forEach(function (el) {
        el.setAttribute('data-audit-badge', badge);
        if (state) el.setAttribute('data-completion-state', state);
        var status = el.querySelector('.series-status');
        if (!status) return;
        var existing = status.querySelector('.badge-audit');
        if (!badge) {
            if (existing) existing.remove();
            return;
        }
        var span = existing;
        if (!span) {
            span = document.createElement('span');
            status.appendChild(span);
        }
        span.textContent = badge;
        span.className = _auditBadgeClass(state || el.getAttribute('data-completion-state'), forced);
        span.title = _auditBadgeTitle(state, forced, unit);
    });
}

function applyHygieneFilter(mode) {
    window.hygieneFilter = mode || null;
    document.querySelectorAll('.hygiene-chip[data-hygiene]').forEach(function (btn) {
        btn.classList.toggle('is-active', window.hygieneFilter === btn.getAttribute('data-hygiene'));
    });
    if (typeof filterSeries === 'function') filterSeries();
}

function _updateHygieneCounts(counts) {
    counts = counts || {};
    var m = document.getElementById('hygieneCountMissing');
    var d = document.getElementById('hygieneCountDups');
    var n = document.getElementById('hygieneCountNoId');
    if (m) m.textContent = String(counts.missing != null ? counts.missing : 0);
    if (d) d.textContent = String(counts.duplicates != null ? counts.duplicates : 0);
    if (n) n.textContent = String(counts.no_external_id != null ? counts.no_external_id : 0);
    var chips = document.getElementById('hygieneChips');
    if (chips) chips.setAttribute('data-scanned', '1');
    document.querySelectorAll(
        '.hygiene-chip, #btnAuditDuplicates, #btnAuditMissing, #btnHygieneAnalyseQuick'
    ).forEach(function (el) {
        el.disabled = false;
    });
    _updateHygieneHealth(counts);
}

/** Barre de santé de la bibliothèque : « combien de séries vont bien » est la
 * question qu'on se pose en ouvrant l'inventaire, elle n'était nulle part. */
function _updateHygieneHealth(counts) {
    var wrap = document.getElementById('hygieneHealth');
    if (!wrap) return;
    var series = Number(counts.series || 0);
    if (!series || counts.healthy == null) {
        wrap.hidden = true;
        return;
    }
    var healthy = Number(counts.healthy || 0);
    var incomplete = Number(counts.incomplete || 0);
    var unknown = Number(counts.unknown_expected || 0);
    var pct = function (n) { return series ? (100 * n) / series : 0; };
    var seg = function (name, value) {
        var el = wrap.querySelector('.hh-seg[data-seg="' + name + '"]');
        if (el) el.style.width = pct(value) + '%';
    };
    seg('healthy', healthy);
    seg('incomplete', incomplete);
    seg('unknown', unknown);
    var setText = function (id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = String(value);
    };
    setText('hygieneHealthHealthy', healthy);
    setText('hygieneHealthIncomplete', incomplete);
    setText('hygieneHealthUnknown', unknown);
    setText('hygieneHealthSeries', series);
    wrap.hidden = false;
}

/** « analysé il y a 3 h » — sans repère de fraîcheur, impossible de savoir si
 * les compteurs affichés datent de ce matin ou du mois dernier. */
function _formatFreshness(iso) {
    var tr = _auditT();
    if (!iso) return tr.audit_never_scanned || '';
    var ts = Date.parse(iso);
    if (isNaN(ts)) return '';
    var mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
    var value;
    if (mins < 1) value = tr.audit_freshness_now || 'just now';
    else if (mins < 60) value = mins + ' min';
    else if (mins < 60 * 24) value = Math.round(mins / 60) + ' h';
    else value = Math.round(mins / 1440) + ' j';
    var age = mins < 1 ? value : (tr.audit_freshness_ago || '{age} ago').replace('{age}', value);
    return (tr.audit_freshness_prefix || 'analysé') + ' ' + age;
}

function _refreshFreshnessLabel(iso) {
    var el = document.getElementById('hygieneFreshness');
    if (!el) return;
    if (iso) el.setAttribute('data-scanned-at', iso);
    el.textContent = _formatFreshness(el.getAttribute('data-scanned-at'));
}

function cancelHygieneScan() {
    var tr = _auditT();
    var label = document.getElementById('hygieneScanLabel');
    fetch('/api/hygiene-scan/cancel', { method: 'POST', credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function () {
            if (label) label.textContent = tr.audit_cancelling || '…';
        })
        .catch(function () { /* ignore */ });
}

function _setScanRunningUi(running) {
    var cancelBtn = document.getElementById('btnHygieneCancel');
    if (cancelBtn) cancelBtn.style.display = running ? '' : 'none';
    ['btnHygieneAnalyse', 'btnHygieneAnalyseQuick'].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        if (running) el.disabled = true;
        else if (id === 'btnHygieneAnalyse') el.disabled = false;
        else {
            var chips = document.getElementById('hygieneChips');
            el.disabled = !(chips && chips.getAttribute('data-scanned') === '1');
        }
    });
}

/* Socket.io peut être indisponible (proxy inverse mal configuré, extension,
 * reconnexion en cours…) — sans repli, la scan tourne côté serveur mais l'UI
 * (chips, bouton doublons) reste bloquée à "lancée" pour toujours (= "boutons
 * morts"). Ce polling est un filet de sécurité qui finalise l'UI dans tous les cas. */
var _hygienePollTimer = null;
var _hygienePollLib = null;

function _stopHygienePolling() {
    if (_hygienePollTimer) {
        clearTimeout(_hygienePollTimer);
        _hygienePollTimer = null;
    }
    _hygienePollLib = null;
}

function _pollHygieneStatus(lib, attempt) {
    if (_hygienePollLib !== lib) return; // superseded by a newer scan/poll
    fetch('/api/libraries/' + encodeURIComponent(lib) + '/hygiene-scan/status', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (_hygienePollLib !== lib) return;
            if (!data || !data.success) {
                if (attempt > 20) { _stopHygienePolling(); return; }
                _hygienePollTimer = setTimeout(function () { _pollHygieneStatus(lib, attempt + 1); }, 1500);
                return;
            }
            _onHygieneProgress({
                running: !!data.running,
                done: data.done || 0,
                total: data.total || 0,
                name: data.current_name || '',
                library_id: data.library_id,
                phase: data.phase,
                counts: data.counts,
                cancelled: !!data.cancelled,
                scanned_at: (data.meta || {}).scanned_at || '',
            });
            // Grosse bibliothèque + throttle catalogue (AniList/MAL) = scan potentiellement
            // long ; 800 tentatives × 1.5 s ≈ 20 min avant d'abandonner le polling.
            if (!data.running || attempt > 800) {
                _stopHygienePolling();
                return;
            }
            _hygienePollTimer = setTimeout(function () { _pollHygieneStatus(lib, attempt + 1); }, 1500);
        })
        .catch(function () {
            if (_hygienePollLib !== lib) return;
            if (attempt > 20) { _stopHygienePolling(); return; }
            _hygienePollTimer = setTimeout(function () { _pollHygieneStatus(lib, attempt + 1); }, 1500);
        });
}

/** `startHygieneScan(ids)` (case batch) ou `startHygieneScan({ mode, ids })`. */
function startHygieneScan(arg) {
    var tr = _auditT();
    var lib = _selectedLibraryIdOrAll();
    var opts = Array.isArray(arg) ? { ids: arg } : (arg || {});
    var ids = opts.ids || [];
    var mode = opts.mode === 'incremental' ? 'incremental' : 'full';
    var wrap = document.getElementById('hygieneScanProgress');
    var label = document.getElementById('hygieneScanLabel');
    var fill = document.getElementById('hygieneScanFill');
    if (wrap) {
        wrap.style.display = 'block';
        wrap.setAttribute('aria-hidden', 'false');
    }
    if (label) label.textContent = tr.audit_scan_started || '…';
    if (fill) fill.style.width = '0%';
    _setScanRunningUi(true);

    fetch('/api/libraries/' + encodeURIComponent(lib) + '/hygiene-scan', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_ids: ids || [], catalog: true, mode: mode }),
    })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
        .then(function (res) {
            if (res.status === 409 || (res.body && res.body.busy)) {
                if (label) label.textContent = tr.audit_scan_busy || 'Busy';
                _hygienePollLib = lib;
                _hygienePollTimer = setTimeout(function () { _pollHygieneStatus(lib, 0); }, 500);
                return;
            }
            if (!res.body || !res.body.success) {
                if (label) label.textContent = (res.body && res.body.error) || (tr.audit_err_generic || 'Error');
                _setScanRunningUi(false);
                return;
            }
            _hygienePollLib = lib;
            _hygienePollTimer = setTimeout(function () { _pollHygieneStatus(lib, 0); }, 800);
        })
        .catch(function () {
            if (label) label.textContent = tr.audit_err_generic || 'Error';
            _setScanRunningUi(false);
        });
}

/** Alias for batch checkbox */
function startVolumeHygieneScan(explicitIds) {
    return startHygieneScan(explicitIds);
}

function _onHygieneProgress(payload) {
    var tr = _auditT();
    var wrap = document.getElementById('hygieneScanProgress');
    var label = document.getElementById('hygieneScanLabel');
    var fill = document.getElementById('hygieneScanFill');
    if (!payload) return;
    if (wrap) {
        wrap.style.display = 'block';
        wrap.setAttribute('aria-hidden', 'false');
    }
    var done = payload.done || 0;
    var total = payload.total || 0;
    var pct = total ? Math.round((100 * done) / total) : 0;
    if (fill) fill.style.width = pct + '%';
    _setScanRunningUi(!!payload.running);
    if (payload.series_id && payload.badge) {
        _applyAuditBadge(payload.series_id, payload.badge, {
            state: payload.completion_state,
            unit: payload.unit_mode,
        });
        if (window.SeriesList && typeof window.SeriesList.patchOverride === 'function') {
            window.SeriesList.patchOverride(payload.series_id, {
                audit_badge: payload.badge,
                missing_count: payload.missing_count || 0,
                has_external_id: !!payload.has_external_id,
                publication_status: payload.publication_status || '',
                completion_state: payload.completion_state || '',
            });
        }
    }
    if (label) {
        var name = payload.name ? (' — ' + payload.name) : '';
        label.textContent = done + ' / ' + total + name;
        if (!payload.running) {
            _stopHygienePolling();
            label.textContent = (payload.cancelled
                ? (tr.audit_scan_cancelled || 'Cancelled')
                : (tr.audit_scan_done || 'Done')) + ' (' + done + '/' + total + ')';
            // Un scan annulé laisse volontairement les compteurs précédents :
            // un parcours partiel donnerait des totaux faux.
            if (payload.counts && !payload.cancelled) _updateHygieneCounts(payload.counts);
            if (!payload.cancelled) _refreshFreshnessLabel(payload.scanned_at || new Date().toISOString());
            if (typeof window.hydrateAuditBadges === 'function') window.hydrateAuditBadges();
            setTimeout(function () {
                if (wrap && !payload.running) {
                    wrap.style.display = 'none';
                    wrap.setAttribute('aria-hidden', 'true');
                }
            }, 4000);
        }
    }
}

/** Bascule instantanée de l'inventaire : on ne recharge pas la page (un reload
 * après un toggle sidebar peut faire écraser une clé API par l'autofill). */
function onInventoryToggle(input) {
    var on = !!(input && input.checked);
    document.body.setAttribute('data-inventory', on ? '1' : '0');
    if (typeof saveConfig === 'function') saveConfig();
}

function openDuplicatesModal() {
    var m = document.getElementById('duplicatesModal');
    var body = document.getElementById('duplicatesBody');
    var tr = _auditT();
    var lib = _selectedLibraryIdOrAll();
    if (!m || !body) return;
    m.style.display = 'flex';
    m.setAttribute('aria-hidden', 'false');
    body.innerHTML = _loadingHtml(tr);
    var csv = document.getElementById('duplicatesCsv');
    var txt = document.getElementById('duplicatesTxt');
    if (csv) csv.href = '/api/libraries/' + encodeURIComponent(lib) + '/duplicates?format=csv';
    if (txt) txt.href = '/api/libraries/' + encodeURIComponent(lib) + '/duplicates?format=txt';
    fetch('/api/libraries/' + encodeURIComponent(lib) + '/duplicates', { credentials: 'same-origin' })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
        .then(function (res) {
            if (res.status === 404 || !res.body || !res.body.success) {
                // Jamais analysé : on garde le réglage du seuil accessible, c'est
                // le moment où l'on veut le choisir avant de lancer l'analyse.
                body.innerHTML = _dupThresholdControlHtml(tr) +
                    _stateHtml('scan',
                        (res.body && res.body.error) || (tr.audit_err_run_analyser || 'Run Analyser'),
                        tr.audit_duplicates_hint || '', 'todo');
                _bindDupThresholdControl();
                return;
            }
            if (typeof applyDuplicateFlagsToUi === 'function') applyDuplicateFlagsToUi(res.body);
            _renderDuplicatesModalBody(res.body);
        })
        .catch(function () {
            body.innerHTML = _errorHtml(tr);
        });
}

function openMissingVolumesModal() {
    var m = document.getElementById('missingVolumesModal');
    var body = document.getElementById('missingVolumesBody');
    var tr = _auditT();
    var lib = _selectedLibraryIdOrAll();
    if (!m || !body) return;
    m.style.display = 'flex';
    m.setAttribute('aria-hidden', 'false');
    body.innerHTML = _loadingHtml(tr);
    var includeUnknown = !!(document.getElementById('missingIncludeUnknownCb') || {}).checked;
    var q = includeUnknown ? '?include_unknown=1' : '';
    var csv = document.getElementById('missingVolumesCsv');
    var txt = document.getElementById('missingVolumesTxt');
    if (csv) {
        csv.href = '/api/libraries/' + encodeURIComponent(lib) + '/missing-volumes?format=csv' +
            (includeUnknown ? '&include_unknown=1' : '');
    }
    if (txt) {
        txt.href = '/api/libraries/' + encodeURIComponent(lib) + '/missing-volumes?format=txt' +
            (includeUnknown ? '&include_unknown=1' : '');
    }
    fetch('/api/libraries/' + encodeURIComponent(lib) + '/missing-volumes' + q, {
        credentials: 'same-origin',
    })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
        .then(function (res) {
            if (res.status === 404 || !res.body || !res.body.success) {
                body.innerHTML = _stateHtml('scan',
                    (res.body && res.body.error) || (tr.audit_err_run_analyser || 'Run Analyser'),
                    tr.audit_missing_detail_hint || '', 'todo');
                return;
            }
            _renderMissingVolumesModalBody(res.body);
        })
        .catch(function () {
            body.innerHTML = _errorHtml(tr);
        });
}

function _renderMissingVolumesModalBody(data) {
    var tr = _auditT();
    var body = document.getElementById('missingVolumesBody');
    if (!body) return;
    var rows = (data && data.rows) || [];
    if (!rows.length) {
        body.innerHTML = _stateHtml('complete', tr.audit_missing_none || 'None',
            tr.audit_missing_none_hint || '', 'ok');
        return;
    }
    var forcedCount = rows.filter(function (r) { return r.forced_expected; }).length;
    var html = '<p><strong>' + rows.length + '</strong> ' +
        _escHtml(tr.audit_missing_series || 'series') +
        (forcedCount
            ? ' · <button type="button" class="linkish" id="auditForcedListBtn">' + forcedCount + ' ' +
              _escHtml(tr.audit_forced_count || 'attendu(s) forcé(s)') + '</button>'
            : '') +
        '</p><div id="auditForcedList"></div>';
    var cols = [
        tr.audit_series || 'Series',
        tr.audit_col_badge || 'Badge',
        tr.audit_pub_status || 'Pub',
        tr.audit_col_missing || 'Missing',
        '',
    ];
    html += '<div class="audit-table-wrap"><table class="audit-table"><thead><tr>' +
        cols.map(function (c) { return '<th>' + _escHtml(c) + '</th>'; }).join('') +
        '</tr></thead><tbody>';
    rows.forEach(function (r) {
        var missing = _missingLabel(r) || '—';
        var unitSuffix = r.unit === 'chapters'
            ? ' <span class="muted">' + _escHtml(tr.audit_unit_chapters_short || 'ch') + '</span>'
            : '';
        html += '<tr data-series-id="' + _escHtml(r.series_id) + '">' +
            _cell('<span class="audit-missing-row-state" data-state="' +
                _escHtml(r.completion_state || 'unknown') + '"></span>' +
                _escHtml(r.name) + ' <span class="muted">#' + _escHtml(r.series_id) + '</span>',
                '', 'audit-cell-title', true) +
            _cell('<span class="' + _auditBadgeClass(r.completion_state, r.forced_expected) + '">' +
                _escHtml(r.badge || '—') + '</span>', cols[1], null, true) +
            _cell(_escHtml(_pubStatusLabel(r.publication_status, tr)) +
                (r.reason ? ' <span class="muted">(' + _escHtml(_catalogReasonLabel(r.reason, tr)) + ')</span>' : ''),
                cols[2], null, true) +
            _cell(_escHtml(missing) + unitSuffix, cols[3], 'audit-cell-num', true) +
            _cell('<button type="button" class="btn-opt audit-open-missing-report">' +
                _escHtml(tr.audit_volume_report || 'Report') + '</button>',
                '', 'audit-cell-actions', true) +
            '</tr>';
    });
    html += '</tbody></table></div>';
    body.innerHTML = html;
    var forcedBtn = document.getElementById('auditForcedListBtn');
    if (forcedBtn) forcedBtn.addEventListener('click', toggleForcedExpectedList);
    body.querySelectorAll('.audit-open-missing-report').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var trEl = btn.closest('tr');
            var sid = trEl && trEl.getAttribute('data-series-id');
            var name = trEl ? (trEl.querySelector('td') || {}).textContent : sid;
            openVolumeReportModal(sid, name);
        });
    });
}

/* Les attendus forcés pilotent la complétion d'une série sans que rien ne le
 * dise : cette liste les rassemble et permet de les relâcher d'un endroit. */
function toggleForcedExpectedList() {
    var tr = _auditT();
    var wrap = document.getElementById('auditForcedList');
    if (!wrap) return;
    if (wrap.innerHTML) {
        wrap.innerHTML = '';
        return;
    }
    wrap.innerHTML = _loadingHtml(tr, true);
    fetch('/api/hygiene/catalog-overrides', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var rows = (data && data.rows) || [];
            if (!rows.length) {
                wrap.innerHTML = _stateHtml('empty', tr.audit_forced_none || '—', '', 'inline');
                return;
            }
            var fcols = [tr.audit_series || 'Series', tr.audit_forced_expected || 'Forced', ''];
            var html = '<div class="audit-table-wrap"><table class="audit-table"><thead><tr>' +
                fcols.map(function (c) { return '<th>' + _escHtml(c) + '</th>'; }).join('') +
                '</tr></thead><tbody>';
            rows.forEach(function (r) {
                html += '<tr data-series-id="' + _escHtml(r.series_id) + '">' +
                    _cell(r.name, '', 'audit-cell-title') +
                    _cell(_escHtml(r.expected) + ' <span class="muted">' +
                        _escHtml(_unitLabel(r.unit, tr)) + '</span>', fcols[1], null, true) +
                    _cell('<button type="button" class="btn-secondary audit-release-forced">' +
                        _escHtml(tr.audit_forced_release || 'Release') + '</button>',
                        '', 'audit-cell-actions', true) +
                    '</tr>';
            });
            wrap.innerHTML = html + '</tbody></table></div>';
            wrap.querySelectorAll('.audit-release-forced').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var row = btn.closest('tr');
                    var sid = row && row.getAttribute('data-series-id');
                    if (!sid) return;
                    btn.disabled = true;
                    fetch('/api/series/' + encodeURIComponent(sid) + '/catalog-expected', {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ expected: null }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (res) {
                            if (res && res.success) {
                                if (row) row.remove();
                                _applyAuditBadge(sid, res.badge || '', {
                                    state: ((res.report || {}).completion || {}).state,
                                });
                            } else {
                                btn.disabled = false;
                            }
                        })
                        .catch(function () { btn.disabled = false; });
                });
            });
        })
        .catch(function () {
            wrap.innerHTML = _stateHtml('alert', tr.audit_err_generic || 'Error', '', 'error inline');
        });
}

function applyDuplicateFlagsToUi(data) {
    var flags = (data && data.flags) || {};
    if (window.SeriesList && typeof window.SeriesList.applyAuditFlags === 'function') {
        window.SeriesList.applyAuditFlags(flags);
    }
    document.querySelectorAll('.series-item').forEach(function (item) {
        var sid = item.dataset.seriesId;
        if (!sid) return;
        var f = flags[sid];
        if (f) {
            item.dataset.hasExternalId = f.has_external_id ? '1' : '0';
            item.dataset.duplicateGroupId = f.duplicate_group_id || '';
        }
    });
    if (data && data.count != null) {
        _updateHygieneCounts({
            missing: (data.meta && data.meta.counts && data.meta.counts.missing) || undefined,
            duplicates: data.count,
            no_external_id: (data.meta && data.meta.counts && data.meta.counts.no_external_id) || undefined,
        });
    }
}

/* Le sélecteur de seuil vivait dans la barre d'outils, où il n'avait rien à
 * faire : on ne le règle qu'en regardant les groupes détectés. Il est aussi
 * rendu quand il n'y a aucun doublon — c'est précisément là qu'on veut assouplir. */
function _dupThresholdControlHtml(tr) {
    var current = String(window.DUP_ACCEPT_THRESHOLD || '0.92');
    var opt = function (value, label) {
        return '<option value="' + value + '"' +
            (Math.abs(parseFloat(current) - parseFloat(value)) < 0.005 ? ' selected' : '') +
            '>' + _escHtml(label) + '</option>';
    };
    return '<div class="audit-dup-threshold">' +
        '<label for="dupThresholdPreset">' + _escHtml(tr.audit_dup_preset || 'Seuil') + '</label>' +
        '<select id="dupThresholdPreset" class="toolbar-select hygiene-preset" ' +
        'title="' + _escHtml(tr.audit_dup_preset_hint || '') + '">' +
        opt('0.97', tr.audit_dup_strict || 'Strict 0.97') +
        opt('0.92', tr.audit_dup_medium || 'Medium 0.92') +
        opt('0.85', tr.audit_dup_soft || 'Soft 0.85') +
        '</select>' +
        '<span class="audit-hint">' + _escHtml(tr.audit_dup_preset_rescan || '') + '</span>' +
        '</div>';
}

function _bindDupThresholdControl() {
    var sel = document.getElementById('dupThresholdPreset');
    if (!sel) return;
    sel.addEventListener('change', function () {
        window.DUP_ACCEPT_THRESHOLD = sel.value;
        setDupThresholdPreset(sel.value);
    });
}

/** URL Kavita d'une série : le lien de la modale doublons était un `href="#"`
 * sans handler. La ligne du dashboard porte déjà la bonne URL (libraryId
 * compris), on la réutilise plutôt que de deviner. */
function _kavitaSeriesUrl(seriesId) {
    var row = document.querySelector('.series-item[data-series-id="' + String(seriesId) + '"]');
    var link = row && row.querySelector('a.series-link');
    if (link && link.href) return link.href;
    var lib = _selectedLibraryId();
    var base = window.KAVITA_UI_URL || '';
    if (lib && base) return base + '/library/' + encodeURIComponent(lib) + '/series/' + encodeURIComponent(seriesId);
    return '';
}

function _renderDuplicatesModalBody(data) {
    var tr = _auditT();
    var body = document.getElementById('duplicatesBody');
    if (!body) return;
    var groups = (data && data.groups) || [];
    if (!groups.length) {
        body.innerHTML = _dupThresholdControlHtml(tr) +
            _stateHtml('unique', tr.audit_dup_none || 'None',
                tr.audit_dup_none_hint || '', 'ok');
        _bindDupThresholdControl();
        return;
    }
    var html = _dupThresholdControlHtml(tr) +
        '<p><strong>' + groups.length + '</strong> ' + _escHtml(tr.audit_dup_groups || 'groups') + '</p>';
    groups.forEach(function (g, gi) {
        html += '<div class="audit-dup-group" data-group-index="' + gi + '">';
        html += '<div class="audit-dup-head">' +
            '<span class="audit-dup-id">' + _escHtml(g.group_id) + '</span>' +
            '<span class="audit-dup-tag">score ' + _escHtml(g.score) + '</span>' +
            (g.reasons || []).map(function (reason) {
                return '<span class="audit-dup-tag">' + _escHtml(reason) + '</span>';
            }).join('') +
            '</div>';
        (g.series_ids || []).forEach(function (sid, i) {
            var name = (g.names && g.names[i]) || sid;
            var kavitaUrl = _kavitaSeriesUrl(sid);
            html += '<div class="audit-dup-row" data-series-id="' + _escHtml(sid) + '">' +
                '<button type="button" class="linkish audit-open-report audit-dup-name">' +
                _escHtml(name) + ' <span class="muted">#' + _escHtml(sid) + '</span></button>' +
                '<span class="audit-dup-row-actions">' +
                (kavitaUrl
                    ? '<a class="btn-opt audit-open-kavita" target="_blank" rel="noopener" href="' +
                      _escHtml(kavitaUrl) + '">' + _escHtml(tr.audit_open_kavita || 'Kavita') + '</a>'
                    : '') +
                '<button type="button" class="btn-warning audit-delete-series" data-sid="' + _escHtml(sid) + '">' +
                _escHtml(tr.audit_delete_series || 'Delete') + '</button>' +
                '</span></div>';
        });
        html += '<div class="audit-dup-actions">' +
            '<button type="button" class="btn-opt audit-not-dup" data-ids="' +
            _escHtml((g.series_ids || []).join(',')) + '">' +
            _escHtml(tr.audit_not_duplicate || 'Not a duplicate') + '</button> ' +
            '<button type="button" class="btn-opt audit-ignore-dup" data-ids="' +
            _escHtml((g.series_ids || []).join(',')) + '">' +
            _escHtml(tr.audit_ignore_dup || 'Ignore') + '</button>' +
            '</div></div>';
    });
    body.innerHTML = html;
    _bindDupThresholdControl();
    body.querySelectorAll('.audit-open-report').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var row = btn.closest('.audit-dup-row');
            var sid = row && row.getAttribute('data-series-id');
            openVolumeReportModal(sid, (btn.firstChild || {}).textContent || btn.textContent);
        });
    });
    body.querySelectorAll('.audit-not-dup, .audit-ignore-dup').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var ids = (btn.getAttribute('data-ids') || '').split(',').filter(Boolean);
            var reason = btn.classList.contains('audit-ignore-dup') ? 'ignored' : 'not_duplicate';
            _dismissDupGroup(ids, reason);
        });
    });
    body.querySelectorAll('.audit-delete-series').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var sid = btn.getAttribute('data-sid');
            _deleteSeriesConfirm(sid);
        });
    });
}

function _dismissDupGroup(seriesIds, reason) {
    var lib = _selectedLibraryIdOrAll();
    var tr = _auditT();
    if (seriesIds.length < 2) return;
    fetch('/api/libraries/' + encodeURIComponent(lib) + '/duplicates/dismiss', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_ids: seriesIds.map(Number), reason: reason }),
    })
        .then(function (r) { return r.json(); })
        .then(function () { openDuplicatesModal(); if (typeof filterSeries === 'function') filterSeries(); })
        .catch(function () { alert(tr.audit_err_generic || 'Error'); });
}

function _deleteSeriesConfirm(seriesId) {
    var tr = _auditT();
    var msg = tr.audit_delete_warning ||
        'Delete this series from Kavita? Recovery = library rescan if files remain. No Meta undo.';
    if (!window.confirm(msg)) return;
    fetch('/api/series/' + encodeURIComponent(seriesId) + '/kavita-delete', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data || !data.success) {
                alert((data && data.error) || (tr.audit_err_generic || 'Error'));
                return;
            }
            openDuplicatesModal();
        })
        .catch(function () { alert(tr.audit_err_generic || 'Error'); });
}

function setDupThresholdPreset(value) {
    var v = parseFloat(value);
    if (!(v > 0)) return;
    var root = (typeof getRootPath === 'function') ? getRootPath() : '';
    var body = new URLSearchParams();
    body.set('DUP_PRESET_SAVE', '1');
    body.set('DUP_ACCEPT_THRESHOLD', String(v));
    fetch(root + '/save-config', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
    }).catch(function () { /* ignore */ });
}

window.startHygieneScan = startHygieneScan;
window.startInventoryScan = startHygieneScan;
window.startCompletionScan = startHygieneScan; // alias legacy
window.startVolumeHygieneScan = startVolumeHygieneScan;
window._onHygieneProgress = _onHygieneProgress;
window.applyHygieneFilter = applyHygieneFilter;
window.openDuplicatesModal = openDuplicatesModal;
window.openMissingVolumesModal = openMissingVolumesModal;
window.closeMissingVolumesModal = closeMissingVolumesModal;
window.openVolumeReportModal = openVolumeReportModal;
window.closeVolumeReportModal = closeVolumeReportModal;
window.closeDuplicatesModal = closeDuplicatesModal;
window.refreshVolumeReport = refreshVolumeReport;
window.applyDuplicateFlagsToUi = applyDuplicateFlagsToUi;
window.setDupThresholdPreset = setDupThresholdPreset;
window.saveCatalogExpected = saveCatalogExpected;
window.cancelHygieneScan = cancelHygieneScan;
window.auditBadgeClass = _auditBadgeClass;
window.auditBadgeTitle = _auditBadgeTitle;
window.onInventoryToggle = onInventoryToggle;
window.setSeriesInventoryExcluded = setSeriesInventoryExcluded;
/* Legacy no-op: do not short-circuit with empty groups */
window.ensureAuditFlags = function () {
    return Promise.resolve({ success: true, groups: [], flags: {} });
};

(function () {
    function hydrateVisibleBadges() {
        if (document.body.getAttribute('data-inventory') === '0') return;
        var ids = [];
        document.querySelectorAll('.series-item').forEach(function (el) {
            if (el.getAttribute('data-audit-badge')) return;
            if (el.getAttribute('data-inventory-excluded') === '1') return;
            var sid = el.getAttribute('data-series-id');
            if (sid) ids.push(sid);
        });
        if (!ids.length) return;
        var lib = _selectedLibraryIdOrAll();
        fetch('/api/libraries/' + encodeURIComponent(lib) + '/audit-badges?ids=' + ids.slice(0, 80).join(','), {
            credentials: 'same-origin',
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.success || !data.badges) return;
                if (window.SeriesList && typeof window.SeriesList.applyAuditBadges === 'function') {
                    window.SeriesList.applyAuditBadges(data.badges);
                } else {
                    Object.keys(data.badges).forEach(function (sid) {
                        _applyAuditBadge(sid, data.badges[sid]);
                    });
                }
            })
            .catch(function () { /* ignore */ });
    }
    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', function () {
            if (document.body.getAttribute('data-inventory') === '0') return;
            _refreshFreshnessLabel();
            setTimeout(hydrateVisibleBadges, 400);
        });
    }
    window.hydrateAuditBadges = hydrateVisibleBadges;
})();
