/* Library Inventory UI — Analyser, chips, volume report, missing, duplicates. */

window.hygieneFilter = null;
var _volumeReportSeriesId = null;
var _volumeReportSeriesName = null;

function _auditT() {
    return window.AppTranslations || {};
}

// Échappement partagé (utils.js) : voir escapeHtmlText, l'apostrophe incluse.
function _escHtml(s) {
    return window.escapeHtmlText(s);
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

/** L'Inventaire est-il éteint ? Le rapport de tomes reste alors joignable pour
 * l'enrichissement par tome, mais amputé : les attendus de catalogue et les
 * exports appartiennent à l'Inventaire, et leurs routes répondent 403. On
 * n'affiche donc que le détail tome par tome, reconstruit depuis Kavita seul. */
function _inventoryOff() {
    return !!document.body && document.body.getAttribute('data-inventory') === '0';
}

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
    var refresh = document.getElementById('volumeReportRefresh');
    var reduced = _inventoryOff();
    if (csv) {
        csv.href = getRootPath() + '/api/series/' + seriesId + '/volume-report?format=csv&refresh=1';
        csv.hidden = reduced;
    }
    if (txt) {
        txt.href = getRootPath() + '/api/series/' + seriesId + '/volume-report?format=txt&refresh=1';
        txt.hidden = reduced;
    }
    if (refresh) refresh.hidden = reduced;
    var workshopLink = document.getElementById('btnVolumePreview');
    if (workshopLink) {
        workshopLink.href = getRootPath() + '/series/' + encodeURIComponent(seriesId) + '/volumes';
    }
    m.style.display = 'flex';
    m.setAttribute('aria-hidden', 'false');
    if (reduced) _loadVolumeReportUnits(seriesId);
    else _loadVolumeReport(seriesId, false);
}

function refreshVolumeReport() {
    if (_volumeReportSeriesId == null) return;
    if (_inventoryOff()) _loadVolumeReportUnits(_volumeReportSeriesId);
    else _loadVolumeReport(_volumeReportSeriesId, true);
}

function _loadVolumeReport(seriesId, forceRefresh) {
    var body = document.getElementById('volumeReportBody');
    var tr = _auditT();
    if (!body) return;
    body.innerHTML = _loadingHtml(tr);
    var url = forceRefresh
        ? getRootPath() + '/api/series/' + seriesId + '/volume-report?refresh=1'
        : getRootPath() + '/api/series/' + seriesId + '/volume-report/summary';
    fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
            if (r.status === 404 && !forceRefresh) {
                return fetch(getRootPath() + '/api/series/' + seriesId + '/volume-report?refresh=1', { credentials: 'same-origin' })
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
    // Le tableau des unités n'existe qu'une fois le rapport rendu. Sans
    // Inventaire, cet appel est le premier : l'état vide et l'erreur doivent
    // alors remplacer le chargement dans le corps de la modale, sinon elle
    // tourne indéfiniment.
    var showState = function (kind, message, extra) {
        var tbody = document.getElementById('volumeReportUnits');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="' + _unitsColspan() + '" class="audit-cell-state">' +
                _stateHtml(kind, message, '', extra) + '</td></tr>';
            return;
        }
        var body = document.getElementById('volumeReportBody');
        if (body) body.innerHTML = _stateHtml(kind, message, '', extra.replace(' inline', ''));
    };
    fetch(getRootPath() + '/api/series/' + encodeURIComponent(seriesId) + '/volume-report/units', {
        credentials: 'same-origin',
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (String(_volumeReportSeriesId) !== String(seriesId)) return;
            if (!data || !data.success || !(data.units || []).length) {
                showState('empty', (data && data.error) || tr.audit_units_empty || '—', 'inline');
                return;
            }
            _renderVolumeReport(data);
        })
        .catch(function () {
            showState('alert', tr.audit_err_generic || 'Error', 'error inline');
        });
}

function setSeriesInventoryExcluded(seriesId, excluded) {
    var tr = _auditT();
    if (seriesId == null) return;
    fetch(getRootPath() + '/api/series/' + encodeURIComponent(seriesId) + '/inventory-exclude', {
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
    fetch(getRootPath() + '/api/series/' + encodeURIComponent(_volumeReportSeriesId) + '/catalog-expected', {
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
    // Séries dont l'analyse a échoué : sans segment dédié, les quatre chiffres
    // ne totalisaient plus les séries annoncées et le reliquat restait muet.
    var failed = Number(counts.failed || 0);
    var pct = function (n) { return series ? (100 * n) / series : 0; };
    var seg = function (name, value) {
        var el = wrap.querySelector('.hh-seg[data-seg="' + name + '"]');
        if (el) el.style.width = pct(value) + '%';
    };
    seg('healthy', healthy);
    seg('incomplete', incomplete);
    seg('unknown', unknown);
    seg('failed', failed);
    var setText = function (id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = String(value);
    };
    setText('hygieneHealthHealthy', healthy);
    setText('hygieneHealthIncomplete', incomplete);
    setText('hygieneHealthUnknown', unknown);
    setText('hygieneHealthFailed', failed);
    setText('hygieneHealthSeries', series);
    // Rien à signaler dans le cas normal (aucun échec) : la légende reste courte.
    var failedKey = document.getElementById('hygieneHealthFailedKey');
    if (failedKey) failedKey.style.display = failed ? '' : 'none';
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
    fetch(getRootPath() + '/api/hygiene-scan/cancel', { method: 'POST', credentials: 'same-origin' })
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
    fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/hygiene-scan/status', { credentials: 'same-origin' })
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

    fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/hygiene-scan', {
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

// Même rôle que ci-dessus pour l'enrichissement par tome : c'est `data-volumes`
// qui décide du groupe « Tomes » dans la barre d'outils et du bouton de rapport.
// L'attribut était posé par le gabarit seul, donc allumer la fonctionnalité ne
// faisait apparaître ses boutons qu'au rechargement suivant — alors que la barre
// latérale, elle, enregistre sans recharger.
function onVolumeEnrichmentToggle(input) {
    var on = !!(input && input.checked);
    document.body.setAttribute('data-volumes', on ? '1' : '0');
    if (typeof saveConfig === 'function') saveConfig();
}

function openDuplicatesModal(opts) {
    var m = document.getElementById('duplicatesModal');
    var body = document.getElementById('duplicatesBody');
    var tr = _auditT();
    var lib = _selectedLibraryIdOrAll();
    var keepBody = opts && opts.keepBody;
    if (!m || !body) return;
    m.style.display = 'flex';
    m.setAttribute('aria-hidden', 'false');
    if (!keepBody) body.innerHTML = _loadingHtml(tr);
    var csv = document.getElementById('duplicatesCsv');
    var txt = document.getElementById('duplicatesTxt');
    if (csv) csv.href = getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/duplicates?format=csv';
    if (txt) txt.href = getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/duplicates?format=txt';
    fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/duplicates', { credentials: 'same-origin' })
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
        csv.href = getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/missing-volumes?format=csv' +
            (includeUnknown ? '&include_unknown=1' : '');
    }
    if (txt) {
        txt.href = getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/missing-volumes?format=txt' +
            (includeUnknown ? '&include_unknown=1' : '');
    }
    fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/missing-volumes' + q, {
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
    fetch(getRootPath() + '/api/hygiene/catalog-overrides', { credentials: 'same-origin' })
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
                    fetch(getRootPath() + '/api/series/' + encodeURIComponent(sid) + '/catalog-expected', {
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

var _lastDupGroups = [];
/* Cases Jeter : « Pas un doublon » recharge la liste, sans ça on perdait
 * la sélection du script. Les id restent tant que la page est ouverte. */
var _dupDropMarked = {};

function _syncDupDropMarkedFromDom() {
    document.querySelectorAll('#duplicatesBody .audit-dup-drop-cb').forEach(function (cb) {
        var id = String(cb.value || '');
        if (!id) return;
        if (cb.checked) _dupDropMarked[id] = true;
        else delete _dupDropMarked[id];
    });
}

function _restoreDupDropMarked() {
    document.querySelectorAll('#duplicatesBody .audit-dup-drop-cb').forEach(function (cb) {
        cb.checked = !!_dupDropMarked[String(cb.value || '')];
    });
    _enforceAllDupKeepOne();
}

function _dupGroupCheckboxes(groupEl) {
    return Array.prototype.slice.call(
        (groupEl && groupEl.querySelectorAll('.audit-dup-drop-cb')) || []
    );
}

/** Au moins une série du groupe reste hors de Jeter : tout cocher viderait le groupe. */
function _enforceDupKeepOne(groupEl) {
    var boxes = _dupGroupCheckboxes(groupEl);
    if (!boxes.length) return;
    var members = groupEl.querySelectorAll('.audit-dup-row').length;
    var implicitKeep = members - boxes.length;
    var maxCheck = implicitKeep > 0 ? boxes.length : Math.max(0, boxes.length - 1);
    var checked = boxes.filter(function (cb) { return cb.checked; });
    if (checked.length > maxCheck) {
        checked.slice(maxCheck).forEach(function (cb) {
            cb.checked = false;
            delete _dupDropMarked[String(cb.value || '')];
        });
    }
    var stillChecked = boxes.filter(function (cb) { return cb.checked; }).length;
    var canCheckMore = stillChecked < maxCheck;
    var tr = _auditT();
    var keepHint = tr.audit_dup_keep_one || 'Keep at least one series in the group.';
    boxes.forEach(function (cb) {
        cb.disabled = !cb.checked && !canCheckMore;
        var label = cb.closest('.audit-dup-drop');
        if (label) {
            label.classList.toggle('is-locked', cb.disabled);
            label.title = cb.disabled ? keepHint : '';
        }
        cb.title = cb.disabled ? keepHint : '';
    });
}

function _enforceAllDupKeepOne() {
    document.querySelectorAll('#duplicatesBody .audit-dup-group').forEach(_enforceDupKeepOne);
}

function _folderPathPrefix() {
    var prefixEl = document.getElementById('dupFolderPathPrefix');
    var typed = prefixEl ? (prefixEl.value || '').trim() : '';
    return (typed || window.INVENTORY_FOLDER_PATH_PREFIX || '').trim().replace(/\/+$/, '');
}

function _resolvedFolderPath(path) {
    var prefix = _folderPathPrefix();
    var p = String(path || '').replace(/\\/g, '/');
    if (!p) return '';
    if (!prefix) return p;
    if (p === prefix || p.indexOf(prefix + '/') === 0) return p;
    return prefix + (p.charAt(0) === '/' ? p : '/' + p);
}

function _copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
    }
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } finally { document.body.removeChild(ta); }
    return Promise.resolve();
}

function updateInventoryFolderPreview() {
    var input = document.getElementById('dupFolderPathPrefix');
    var out = document.getElementById('inventoryFolderPrefixPreview');
    if (!input || !out) return;
    var prefix = (input.value || '').trim().replace(/\/+$/, '');
    var sample = window.INVENTORY_FOLDER_SAMPLE_PATH || '/library/Example Series';
    if (!prefix) {
        out.hidden = true;
        out.textContent = '';
        return;
    }
    var tr = _auditT();
    var label = tr.audit_folder_prefix_preview || 'Preview';
    out.hidden = false;
    out.textContent = label + ' : ' + _resolvedFolderPath(sample);
}

function _refreshDupFolderPaths() {
    document.querySelectorAll('#duplicatesBody .audit-dup-row[data-folder-path]').forEach(function (row) {
        var raw = row.getAttribute('data-folder-path') || '';
        var resolved = _resolvedFolderPath(raw);
        var code = row.querySelector('.audit-dup-path code');
        var copyBtn = row.querySelector('.audit-copy-path');
        if (code) code.textContent = resolved;
        if (copyBtn) copyBtn.setAttribute('data-path', resolved);
    });
}

function _readDupFolderFields() {
    var prefixEl = document.getElementById('dupFolderPathPrefix');
    var trashEl = document.getElementById('dupFolderTrash');
    return {
        prefix: prefixEl ? (prefixEl.value || '').trim() : (window.INVENTORY_FOLDER_PATH_PREFIX || ''),
        trash: trashEl ? (trashEl.value || '').trim() : (window.INVENTORY_FOLDER_TRASH || ''),
    };
}

function _applyDupFolderFields(prefix, trash) {
    var prefixEl = document.getElementById('dupFolderPathPrefix');
    var trashEl = document.getElementById('dupFolderTrash');
    if (prefixEl) {
        if (!(prefixEl.value || '').trim() && prefix) prefixEl.value = prefix;
        window.INVENTORY_FOLDER_PATH_PREFIX = (prefixEl.value || '').trim();
    } else if (prefix != null) {
        window.INVENTORY_FOLDER_PATH_PREFIX = prefix;
    }
    if (trashEl) {
        if (!(trashEl.value || '').trim() && trash) trashEl.value = trash;
        window.INVENTORY_FOLDER_TRASH = (trashEl.value || '').trim();
    } else if (trash != null) {
        window.INVENTORY_FOLDER_TRASH = trash;
    }
    updateInventoryFolderPreview();
    _refreshDupFolderPaths();
}

function saveDupFolderSettings() {
    var fields = _readDupFolderFields();
    window.INVENTORY_FOLDER_PATH_PREFIX = fields.prefix;
    window.INVENTORY_FOLDER_TRASH = fields.trash;
    updateInventoryFolderPreview();
    _refreshDupFolderPaths();
    var body = new URLSearchParams();
    body.set('INVENTORY_FOLDER_PATH_PREFIX', fields.prefix);
    body.set('INVENTORY_FOLDER_TRASH', fields.trash);
    return fetch(getRootPath() + '/save-config', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
    }).catch(function () { /* ignore */ });
}

function _bindDupFolderFields() {
    var prefixEl = document.getElementById('dupFolderPathPrefix');
    var trashEl = document.getElementById('dupFolderTrash');
    if (prefixEl && !prefixEl.dataset.bound) {
        prefixEl.dataset.bound = '1';
        prefixEl.addEventListener('input', function () {
            window.INVENTORY_FOLDER_PATH_PREFIX = (prefixEl.value || '').trim();
            updateInventoryFolderPreview();
            _refreshDupFolderPaths();
        });
        prefixEl.addEventListener('change', saveDupFolderSettings);
    }
    if (trashEl && !trashEl.dataset.bound) {
        trashEl.dataset.bound = '1';
        trashEl.addEventListener('input', function () {
            window.INVENTORY_FOLDER_TRASH = (trashEl.value || '').trim();
        });
        trashEl.addEventListener('change', saveDupFolderSettings);
    }
    updateInventoryFolderPreview();
}

function _renderDuplicatesModalBody(data) {
    var tr = _auditT();
    var body = document.getElementById('duplicatesBody');
    if (!body) return;
    _syncDupDropMarkedFromDom();
    var groups = (data && data.groups) || [];
    _lastDupGroups = groups;
    if (data && data.folder_path_prefix != null) {
        _applyDupFolderFields(data.folder_path_prefix || '', data.folder_trash || '');
    } else if (data && data.folder_trash != null) {
        _applyDupFolderFields(null, data.folder_trash || '');
    }
    if (!groups.length) {
        body.innerHTML = _dupThresholdControlHtml(tr) +
            _stateHtml('unique', tr.audit_dup_none || 'None',
                tr.audit_dup_none_hint || '', 'ok');
        _bindDupThresholdControl();
        return;
    }
    var html = _dupThresholdControlHtml(tr) +
        '<p class="audit-hint">' + _escHtml(tr.audit_dup_script_hint || '') + '</p>' +
        '<p class="audit-dup-count"><strong>' + groups.length + '</strong> ' +
        _escHtml(tr.audit_dup_groups || 'groups') + '</p>';
    groups.forEach(function (g, gi) {
        var scoreNum = parseFloat(g.score);
        var scoreCls = (scoreNum >= 0.99) ? 'audit-dup-tag--exact' : 'audit-dup-tag--score';
        html += '<div class="audit-dup-group" data-group-index="' + gi + '">';
        html += '<div class="audit-dup-head">' +
            '<span class="audit-dup-id">' + _escHtml(g.group_id) + '</span>' +
            '<span class="audit-dup-tag ' + scoreCls + '">score ' + _escHtml(g.score) + '</span>' +
            (g.reasons || []).map(function (reason) {
                return '<span class="audit-dup-tag" data-reason="' + _escHtml(reason) + '">' +
                    _escHtml(reason) + '</span>';
            }).join('') +
            '</div>';
        (g.series_ids || []).forEach(function (sid, i) {
            var name = (g.names && g.names[i]) || sid;
            var path = (g.folder_paths && g.folder_paths[i]) || '';
            var kavitaUrl = _kavitaSeriesUrl(sid);
            var resolved = _resolvedFolderPath(path);
            if (path && !window.INVENTORY_FOLDER_SAMPLE_PATH) {
                window.INVENTORY_FOLDER_SAMPLE_PATH = path;
                updateInventoryFolderPreview();
            }
            html += '<div class="audit-dup-row" data-series-id="' + _escHtml(sid) +
                '" data-folder-path="' + _escHtml(path) + '">' +
                '<button type="button" class="linkish audit-open-report audit-dup-name">' +
                _escHtml(name) + ' <span class="muted">#' + _escHtml(sid) + '</span></button>' +
                '<span class="audit-dup-row-actions">' +
                (kavitaUrl
                    ? '<a class="btn-opt audit-open-kavita" target="_blank" rel="noopener" href="' +
                      _escHtml(kavitaUrl) + '">' + _escHtml(tr.audit_open_kavita || 'Kavita') + '</a>'
                    : '') +
                (path
                    ? '<label class="audit-dup-drop"><input type="checkbox" class="audit-dup-drop-cb" value="' +
                      _escHtml(sid) + '"> ' + _escHtml(tr.audit_dup_drop || 'Trash') + '</label>'
                    : '<span class="muted">' + _escHtml(tr.audit_dup_no_path || 'No folder path') + '</span>') +
                '</span>';
            if (path) {
                html += '<div class="audit-dup-path">' +
                    '<code>' + _escHtml(resolved) + '</code>' +
                    '<button type="button" class="btn-opt audit-copy-path" data-path="' +
                    _escHtml(resolved) + '">' + _escHtml(tr.audit_dup_copy_path || 'Copy') + '</button>' +
                    '</div>';
            }
            html += '</div>';
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
    _restoreDupDropMarked();
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
            _dismissDupGroup(ids, reason, btn);
        });
    });
    body.querySelectorAll('.audit-copy-path').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var path = btn.getAttribute('data-path') || '';
            if (!path) return;
            _copyText(path).then(function () {
                btn.textContent = tr.audit_dup_path_copied || 'Copied';
                setTimeout(function () {
                    btn.textContent = tr.audit_dup_copy_path || 'Copy';
                }, 1500);
            }).catch(function () { /* ignore */ });
        });
    });
    body.querySelectorAll('.audit-dup-drop-cb').forEach(function (cb) {
        cb.addEventListener('change', function () {
            _enforceDupKeepOne(cb.closest('.audit-dup-group'));
            _syncDupDropMarkedFromDom();
        });
    });
}

function _dismissDupGroup(seriesIds, reason, btn) {
    var lib = _selectedLibraryIdOrAll();
    var tr = _auditT();
    if (seriesIds.length < 2) return;
    _syncDupDropMarkedFromDom();
    if (btn) btn.disabled = true;
    fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/duplicates/dismiss', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_ids: seriesIds.map(Number), reason: reason }),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data || !data.success) {
                if (btn) btn.disabled = false;
                alert((data && data.error) || (tr.audit_err_generic || 'Error'));
                return;
            }
            openDuplicatesModal({ keepBody: true });
            if (typeof filterSeries === 'function') filterSeries();
        })
        .catch(function () {
            if (btn) btn.disabled = false;
            alert(tr.audit_err_generic || 'Error');
        });
}

function _dupDropIds() {
    var ids = [];
    document.querySelectorAll('#duplicatesBody .audit-dup-drop-cb:checked').forEach(function (cb) {
        var n = parseInt(cb.value, 10);
        if (n) ids.push(n);
    });
    return ids;
}

function _dupGroupsFullyDropped(ids) {
    var marked = {};
    ids.forEach(function (id) { marked[id] = true; });
    var emptied = [];
    (_lastDupGroups || []).forEach(function (g) {
        var members = g.series_ids || [];
        if (!members.length) return;
        var all = members.every(function (sid) { return marked[sid]; });
        if (all) emptied.push(g.group_id || members.join(','));
    });
    return emptied;
}

function _requestDupScript(download) {
    var tr = _auditT();
    var ids = _dupDropIds();
    if (!ids.length) {
        alert(tr.audit_dup_script_empty || 'Tick at least one series to trash.');
        return;
    }
    var emptied = _dupGroupsFullyDropped(ids);
    if (emptied.length) {
        alert(tr.audit_dup_keep_one || 'Keep at least one series in each group.');
        return;
    }
    var modeEl = document.getElementById('dupScriptMode');
    var mode = (modeEl && modeEl.value) || 'trash';
    var lib = _selectedLibraryIdOrAll();
    saveDupFolderSettings().then(function () {
    return fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/duplicates/script', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_ids: ids, mode: mode }),
    });
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data || !data.success || !data.script) {
                alert((data && data.error) || (tr.audit_err_generic || 'Error'));
                return;
            }
            if (download) {
                var blob = new Blob([data.script], { type: 'text/x-sh' });
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'metakavita-duplicates.sh';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);
                return;
            }
            _copyText(data.script).then(function () {
                alert(tr.audit_dup_script_copied || 'Script copied.');
            }).catch(function () {
                alert(tr.audit_dup_script_failed || 'Could not copy.');
            });
        })
        .catch(function () { alert(tr.audit_err_generic || 'Error'); });
}

function _bindDupScriptButtons() {
    var copyBtn = document.getElementById('dupCopyScript');
    var dlBtn = document.getElementById('dupDownloadScript');
    if (copyBtn && !copyBtn.dataset.bound) {
        copyBtn.dataset.bound = '1';
        copyBtn.addEventListener('click', function () { _requestDupScript(false); });
    }
    if (dlBtn && !dlBtn.dataset.bound) {
        dlBtn.dataset.bound = '1';
        dlBtn.addEventListener('click', function () { _requestDupScript(true); });
    }
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
window.updateInventoryFolderPreview = updateInventoryFolderPreview;
window.saveDupFolderSettings = saveDupFolderSettings;
_bindDupScriptButtons();
_bindDupFolderFields();
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
        _bindDupScriptButtons();
        _bindDupFolderFields();
    });
}
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

/* ===== Enrichissement par tome et par album (issue #27) =====
 *
 * L'aperçu remplace le tableau des unités dans la modale du rapport : une ligne
 * par tome, une colonne par champ. La valeur actuelle est montrée barrée quand
 * elle serait comblée, et grisée avec son motif quand elle ne le sera pas
 * (verrouillée, déjà remplie, ISBN invalide) — sans quoi l'utilisateur ne
 * comprendrait pas pourquoi la case est absente. */

var _volumePlan = null;

var _VOL_FIELDS = ['title', 'summary', 'release_date', 'isbn', 'cover_url'];

function _volFieldLabel(field, tr) {
    return tr['vol_field_' + field] || field;
}

function _volReason(reason, tr) {
    return reason ? (tr['vol_reason_' + reason] || reason) : '';
}

/** Valeur affichée dans une cellule : compacte, la modale a cinq colonnes. */
function _volShort(value) {
    var text = String(value == null ? '' : value);
    if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return text.slice(0, 10);
    if (/^https?:/i.test(text)) return '🖼';
    return text.length > 60 ? text.slice(0, 57) + '…' : text;
}

/**
 * Vignette de la couverture proposée.
 *
 * L'aperçu affichait « 🖼 » : l'utilisateur devait cocher une couverture sans
 * l'avoir vue, alors que c'est précisément le champ où l'erreur se repère d'un
 * coup d'œil — et le seul que MangaDex apporte aux mangas. Le proxy est
 * indispensable ici : MangaDex et ComicVine refusent le hotlink.
 */
function _volCoverCell(url) {
    var display = typeof toDisplayCoverUrl === 'function' ? toDisplayCoverUrl(url) : url;
    if (!display) return '🖼';
    return '<img class="vol-cover-thumb" src="' + _escHtml(display) + '" alt="" ' +
        'loading="lazy" title="' + _escHtml(url) + '">';
}

/**
 * Libellé d'une ligne : le numéro sur lequel l'appariement s'est fait.
 *
 * Ce n'est pas toujours celui du tome. Kavita range souvent tout un run de
 * comics sous le volume 1 et fait de chaque numéro un chapitre : afficher le
 * tome donnerait cinquante lignes intitulées « 1 », impossibles à départager.
 */
function _volUnitLabel(entry, tr) {
    var num = entry.matched_on != null
        ? entry.matched_on
        : (entry.volume_number != null ? entry.volume_number : entry.chapter_number);
    var label = num == null ? (entry.name || '—') : String(num);
    if (entry.name && num != null) label += ' — ' + entry.name;
    return label;
}

/**
 * Marque une unité que la passe précédente n'a pas réussi à écrire.
 *
 * Les autres états ne valent pas d'être montrés : une unité déjà écrite a vu
 * ses champs verrouillés, donc sa ligne a disparu de l'aperçu d'elle-même. Un
 * échec, lui, revient à l'identique — le dire évite de le retenter à l'aveugle.
 */
function _volPreviousFailure(entry, states, tr) {
    if (!states || states[String(entry.chapter_id)] !== 'FAILED') return '';
    return ' <span class="vol-retry" title="' +
        _escHtml(tr.vol_state_failed_hint || '') + '">⚠</span>';
}

/**
 * Marque une unité qui partage son album avec une autre.
 *
 * Le cas se rencontre pour de vrai : une bibliothèque peut détenir deux fichiers
 * du même album, l'un rattaché à son tome, l'autre resté « hors tome » faute
 * d'avoir été reconnu par le scanner. Les deux reçoivent alors les mêmes
 * métadonnées, couverture téléchargée et téléversée deux fois.
 *
 * Les deux fichiers *sont* cet album : la ligne reste cochée, parce que les
 * priver de métadonnées serait pire que la redite. Mais l'utilisateur est le seul
 * à savoir si son doublon est voulu, et sans ce marqueur la duplication ne se
 * voyait qu'en repérant deux fois le même numéro dans une longue liste.
 */
function _volDuplicate(entry, tr) {
    if (entry.duplicate_of == null) return '';
    var hint = (tr.vol_duplicate_hint || '')
        .replace('{0}', String(entry.duplicate_of))
        .replace('{1}', String(entry.duplicate_count || 2));
    return ' <span class="vol-dup" title="' + _escHtml(hint) + '">' +
        _escHtml(tr.vol_duplicate_badge || '⧉') + '</span>';
}

function openVolumeEnrichPreview() {
    if (_volumeReportSeriesId == null) return;
    window.location.href = getRootPath() + '/series/' + encodeURIComponent(_volumeReportSeriesId) + '/volumes';
}

/** `{chapter_id: null}` = tous les champs autorisés de cette unité. */
function _volSelection() {
    var selection = {};
    document.querySelectorAll('#volumeReportBody tr[data-chapter]').forEach(function (row) {
        var cb = row.querySelector('.vol-pick');
        if (cb && cb.checked) selection[row.getAttribute('data-chapter')] = null;
    });
    return selection;
}

/** Rend son état cliquable au bouton d'écriture de la modale, s'il est là. */
function _resetVolApplyBtn() {
    var btn = document.getElementById('volApplyBtn');
    if (!btn) return;
    btn.disabled = false;
    btn.textContent = _auditT().vol_apply_btn || 'Write';
}

/**
 * Lance l'écriture de la série en tâche de fond.
 *
 * La route rendait le résultat : elle écrivait tome par tome dans le greenlet de
 * la requête, et le bouton restait sur « Écriture en cours… » pendant des
 * minutes, sans progression ni moyen d'arrêter. Elle rend maintenant le
 * démarrage ; le verdict arrive par `volume_enrich_progress`, ce qui a une
 * conséquence voulue : fermer la modale ne perd plus l'écriture en cours, la
 * barre de la barre d'outils continue de la montrer et le bouton Annuler
 * l'arrête.
 */
function applyVolumeEnrich() {
    var tr = _auditT();
    var out = document.getElementById('volApplyResult');
    var btn = document.getElementById('volApplyBtn');
    if (_volumeReportSeriesId == null) return;
    var selection = _volSelection();
    if (!Object.keys(selection).length) {
        if (out) out.textContent = tr.vol_nothing_selected || '—';
        return;
    }
    if (btn) {
        btn.disabled = true;
        btn.textContent = tr.vol_applying || '…';
    }
    if (out) out.textContent = tr.vol_apply_started || '…';

    fetch(getRootPath() + '/api/series/' + encodeURIComponent(_volumeReportSeriesId) + '/volume-enrich/apply', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selection: selection }),
    })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
        .then(function (res) {
            var body = res.body || {};
            if (!body.success) {
                // Refus (409 : une passe tourne déjà, ou cette série est déjà en
                // cours d'écriture) : rien n'a démarré, le bouton doit revenir.
                _resetVolApplyBtn();
                if (out) out.textContent = body.error || (tr.audit_err_generic || 'Error');
            }
        })
        .catch(function () {
            _resetVolApplyBtn();
            if (out) out.textContent = tr.audit_err_generic || 'Error';
        });
}

/* ===== Progression, commune à la passe de bibliothèque et à une série ===== */

/* L'état de progression est global côté serveur : une seule passe à la fois,
 * qu'elle porte sur une bibliothèque ou sur une série. Retenu ici pour qu'un
 * aperçu rouvert pendant une écriture n'affiche pas un bouton actif. */
var _volumeEnrichRunning = false;

function _setVolumeEnrichRunningUi(running) {
    var tr = _auditT();
    var start = document.getElementById('btnVolumeEnrich');
    var cancel = document.getElementById('btnVolumeEnrichCancel');
    var apply = document.getElementById('volApplyBtn');
    _volumeEnrichRunning = !!running;
    if (start) start.disabled = !!running;
    if (cancel) cancel.style.display = running ? '' : 'none';
    // Une passe démarrée continue de tourner quoi qu'on décoche dans la barre
    // latérale : l'interrupteur ne commande que le départ. Le groupe qui porte
    // Annuler doit donc survivre à son extinction, sinon on éteint et l'écriture
    // continue sans plus rien pour l'arrêter. Le CSS lit cet attribut.
    if (document.body) {
        if (running) document.body.setAttribute('data-volume-pass', 'running');
        else document.body.removeAttribute('data-volume-pass');
    }
    // Le bouton de la modale et celui de la barre d'outils commandent la même
    // tâche de fond : l'un ne peut pas rester cliquable pendant que l'autre
    // tourne, sinon le second clic part pour se faire refuser.
    if (apply) {
        apply.disabled = !!running;
        apply.textContent = running
            ? (tr.vol_applying || '…')
            : (tr.vol_apply_btn || 'Write');
    }
}

/**
 * Verdict d'une écriture terminée, tel qu'il s'affiche dans la modale.
 *
 * Un tome peut réussir son texte et se faire refuser sa couverture : le compte
 * de réussites seul laisserait croire que tout est passé.
 */
function _volumeEnrichVerdict(payload, tr) {
    var counts = payload.counts || {};
    var written = counts.done || 0;
    var message = payload.was_cancelled
        ? (tr.vol_apply_cancelled || '{0}').replace('{0}', written)
        : (tr.vol_applied || '{0}').replace('{0}', written);
    if (counts.failed) {
        message += ' — ' + (tr.vol_apply_failed || '{0}').replace('{0}', counts.failed);
    }
    var warnings = payload.errors || [];
    if (warnings.length) {
        message += ' — ' + (tr.vol_apply_warning || '{0}').replace('{0}', warnings[0]);
    }
    return message;
}

/** Écrit dans la modale, mais seulement si elle est ouverte sur cette série. */
function _volumeEnrichSayInModal(payload, message) {
    if (payload.series_id == null) return;
    if (String(payload.series_id) !== String(_volumeReportSeriesId)) return;
    var out = document.getElementById('volApplyResult');
    if (out) out.textContent = message;
}

/* ===== Passe sur les séries cochées ===== */

/**
 * Message éphémère sur le bouton, puis retour au libellé.
 *
 * Même geste que `launchBatch` pour une sélection vide : un bouton qui se répond
 * à lui-même vaut mieux qu'une alerte à congédier, et cette passe se lance
 * depuis la même barre d'outils que le lot.
 */
function _flashVolumeEnrichBtn(message) {
    var btn = document.getElementById('btnVolumeEnrich');
    if (!btn) return;
    var label = btn.dataset.label || btn.textContent;
    btn.dataset.label = label;
    btn.textContent = message;
    window.setTimeout(function () {
        // Une passe démarrée entre-temps a repris la main sur le bouton : on ne
        // lui réécrit pas son libellé par-dessus.
        if (!_volumeEnrichRunning) btn.textContent = btn.dataset.label || label;
    }, 2000);
}

function startVolumeEnrich() {
    var tr = _auditT();
    var lib = _selectedLibraryIdOrAll();
    // La passe porte sur les séries cochées, et sur elles seules — la même
    // sélection que le lot de scraping, avec la même case « Tout sélectionner »
    // pour couvrir une bibliothèque entière. Elle partait auparavant sur toutes
    // les séries de la bibliothèque affichée, ce qui est un engagement de
    // plusieurs heures d'écriture pour un clic, sans moyen de le restreindre.
    var ids = (typeof getFilteredSelectedIds === 'function') ? getFilteredSelectedIds() : [];
    if (!ids.length) {
        _flashVolumeEnrichBtn(tr.batch_empty || '—');
        return;
    }
    // Une passe d'écriture se confirme : elle touche autant de tomes que les
    // séries cochées en comptent, et ne se défait pas d'un clic.
    if (!window.confirm((tr.vol_library_confirm || 'Continue?').replace('{0}', ids.length))) return;

    var wrap = document.getElementById('volumeEnrichProgress');
    var label = document.getElementById('volumeEnrichLabel');
    var fill = document.getElementById('volumeEnrichFill');
    if (wrap) {
        wrap.style.display = 'block';
        wrap.setAttribute('aria-hidden', 'false');
    }
    if (fill) fill.style.width = '0%';
    if (label) label.textContent = tr.audit_scan_started || '…';
    _setVolumeEnrichRunningUi(true);

    fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/volume-enrich', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_ids: ids }),
    })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
        .then(function (res) {
            if (res.status === 409) {
                if (label) label.textContent = tr.vol_err_busy || 'Busy';
                return;
            }
            if (!res.body || !res.body.success) {
                if (label) label.textContent = (res.body && res.body.error) || (tr.audit_err_generic || 'Error');
                _setVolumeEnrichRunningUi(false);
            }
        })
        .catch(function () {
            if (label) label.textContent = tr.audit_err_generic || 'Error';
            _setVolumeEnrichRunningUi(false);
        });
}

function cancelVolumeEnrich() {
    var tr = _auditT();
    var label = document.getElementById('volumeEnrichLabel');
    fetch(getRootPath() + '/api/volume-enrich/cancel', { method: 'POST', credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function () {
            if (label) label.textContent = tr.audit_cancelling || '…';
        })
        .catch(function () { /* ignore */ });
}

/**
 * Progression d'une écriture en cours, quelle qu'en soit la portée.
 *
 * `payload.series_id` distingue les deux : renseigné, la passe porte sur une
 * seule série et la progression compte des tomes ; absent, elle porte sur une
 * bibliothèque et compte des séries. La barre de la barre d'outils sert dans les
 * deux cas — c'est elle qui permet de fermer la modale sans perdre de vue une
 * écriture lancée depuis l'aperçu.
 */
function _onVolumeEnrichProgress(payload) {
    var tr = _auditT();
    var wrap = document.getElementById('volumeEnrichProgress');
    var label = document.getElementById('volumeEnrichLabel');
    var fill = document.getElementById('volumeEnrichFill');
    if (!payload) return;
    if (wrap) {
        wrap.style.display = 'block';
        wrap.setAttribute('aria-hidden', 'false');
    }
    var done = payload.done || 0;
    var total = payload.total || 0;
    var oneSeries = payload.series_id != null;
    if (fill) fill.style.width = (total ? Math.round((100 * done) / total) : 0) + '%';
    _setVolumeEnrichRunningUi(!!payload.running);

    var message;
    if (payload.running) {
        message = ((oneSeries ? tr.vol_apply_progress : tr.vol_library_running) || '{0} / {1}')
            .replace('{0}', done).replace('{1}', total);
        if (!oneSeries && payload.current_name) message += ' — ' + payload.current_name;
        if (label) label.textContent = message;
        _volumeEnrichSayInModal(payload, message);
        return;
    }

    if (oneSeries) {
        message = _volumeEnrichVerdict(payload, tr);
    } else {
        message = (tr.vol_library_done || '{0}').replace('{0}', (payload.counts || {}).done || 0);
        if (payload.skipped) {
            message += ' ' + (tr.vol_library_resumed || '{0}').replace('{0}', payload.skipped);
        }
    }
    if (label) label.textContent = message;
    _volumeEnrichSayInModal(payload, message);
    // Le rapport compte les unités sans résumé et sans ISBN : il vient de
    // changer sous nos pieds. Seulement si la modale est encore là pour le lire.
    if (oneSeries && (payload.counts || {}).done
        && String(payload.series_id) === String(_volumeReportSeriesId)
        && document.getElementById('volApplyResult')) {
        refreshVolumeReport();
    }
    setTimeout(function () {
        if (wrap) {
            wrap.style.display = 'none';
            wrap.setAttribute('aria-hidden', 'true');
        }
    }, 6000);
}

window.openVolumeEnrichPreview = openVolumeEnrichPreview;
window.applyVolumeEnrich = applyVolumeEnrich;
window.startVolumeEnrich = startVolumeEnrich;
window.cancelVolumeEnrich = cancelVolumeEnrich;
window._onVolumeEnrichProgress = _onVolumeEnrichProgress;

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
        fetch(getRootPath() + '/api/libraries/' + encodeURIComponent(lib) + '/audit-badges?ids=' + ids.slice(0, 80).join(','), {
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
