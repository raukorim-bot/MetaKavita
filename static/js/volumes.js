/* Atelier des tomes — document autonome. */
(function () {
    var T = function () { return window.AppTranslations || {}; };
    var payload = window.WORKSHOP_PAYLOAD || { series: {}, units: [], history: [] };
    var rail = window.WORKSHOP_RAIL || [];
    var seriesId = window.WORKSHOP_SERIES_ID;
    var dirty = false;
    var reviewChapterId = null;
    var reviewCandidates = [];
    var VIRTUAL_MIN = 120;
    var ROW_H = 56;
    var filteredRail = [];
    var loadingSid = null;
    var pendingNav = null;
    var persistStatus = true;
    var persistLibrary = true;

    function esc(s) {
        if (window.escapeHtmlText) return window.escapeHtmlText(s);
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function fmt(tpl) {
        var out = tpl || '';
        for (var i = 1; i < arguments.length; i++) {
            out = out.replace('{' + (i - 1) + '}', String(arguments[i]));
        }
        return out;
    }

    function toast(msg) {
        if (typeof showAppToast === 'function') showAppToast(msg);
    }

    function titleMatchesSearch(title, query, searchInside) {
        if (!query) return true;
        var t = String(title || '').toLowerCase();
        if (searchInside) return t.includes(query);
        return t.startsWith(query);
    }

    function isTypingTarget(el) {
        if (!el) return false;
        var tag = (el.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
        if (el.isContentEditable) return true;
        if (document.getElementById('manualReviewModal') &&
            document.getElementById('manualReviewModal').style.display !== 'none') return true;
        if (document.getElementById('workshopCoverModal') &&
            document.getElementById('workshopCoverModal').style.display !== 'none') return true;
        return false;
    }

    function workshopUrl(sid) {
        if (sid == null || sid === '') return getRootPath() + '/volumes';
        return getRootPath() + '/series/' + encodeURIComponent(sid) + '/volumes';
    }

    var LAST_SID_KEY = 'workshop_last_sid';

    function rememberSid(sid) {
        if (sid == null || sid === '') return;
        try { localStorage.setItem(LAST_SID_KEY, String(sid)); } catch (e) { /* ignore */ }
    }

    function lastSid() {
        try { return localStorage.getItem(LAST_SID_KEY); } catch (e) { return null; }
    }

    function sidInRail(list, sid) {
        return (list || []).some(function (s) { return String(s.id) === String(sid); });
    }

    function pickLandingSeries() {
        var last = lastSid();
        if (last && sidInRail(filteredRail, last)) return last;
        if (last && sidInRail(rail, last)) return last;
        if (filteredRail.length) return filteredRail[0].id;
        if (rail.length) return rail[0].id;
        return null;
    }

    function setIdle(on) {
        var main = document.getElementById('workshopMain');
        if (main) main.classList.toggle('is-idle', !!on);
    }

    function kavitaSeriesUrl(s) {
        var base = String(window.KAVITA_UI_URL || '').replace(/\/+$/, '');
        var lib = s && s.libraryId;
        var id = s && s.id;
        if (!base || lib == null || lib === '' || id == null || id === '') return '';
        return base + '/library/' + encodeURIComponent(lib) + '/series/' + encodeURIComponent(id);
    }

    function api(path, opts) {
        opts = opts || {};
        opts.credentials = 'same-origin';
        if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
            opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
            opts.body = JSON.stringify(opts.body);
        }
        return fetch(getRootPath() + path, opts).then(function (r) {
            return r.json().then(function (data) {
                data._status = r.status;
                return data;
            }).catch(function () { return { success: false, _status: r.status }; });
        });
    }

    function bindCover(img, placeholder) {
        if (!img || img._mkCoverBound) return;
        img._mkCoverBound = true;
        img.addEventListener('error', function () {
            img.removeAttribute('src');
            img.hidden = true;
            if (placeholder) placeholder.hidden = false;
        });
        img.addEventListener('load', function () {
            img.hidden = false;
            if (placeholder) placeholder.hidden = true;
        });
    }

    function showCover(img, url, placeholder) {
        if (!img) return;
        bindCover(img, placeholder);
        if (!url) {
            img.removeAttribute('src');
            img.hidden = true;
            if (placeholder) placeholder.hidden = false;
            return;
        }
        img.hidden = false;
        img.src = url;
    }

    function setLoading(on) {
        var main = document.getElementById('workshopMain');
        var overlay = document.getElementById('workshopLoading');
        if (main) main.classList.toggle('is-loading', !!on);
        if (overlay) overlay.hidden = !on;
    }

    function confirmLeave() {
        if (!dirty) return true;
        return window.confirm(T().workshop_dirty_leave || '');
    }

    function goTo(sid) {
        if (String(sid) === String(seriesId) && loadingSid == null) return;
        if (!confirmLeave()) return;
        loadSeries(sid, true);
    }

    function loadSeries(sid, push) {
        if (loadingSid != null) {
            pendingNav = { sid: sid, push: push };
            return;
        }
        loadingSid = sid;
        setLoading(true);
        function settle() {
            loadingSid = null;
            setLoading(false);
            if (!pendingNav) return;
            var next = pendingNav;
            pendingNav = null;
            if (String(next.sid) === String(seriesId)) return;
            loadSeries(next.sid, next.push);
        }
        api('/api/series/' + encodeURIComponent(sid) + '/workshop').then(function (data) {
            if (!data || !data.success || !data.series) {
                toast((data && data.error) || T().workshop_err || T().err_network);
                settle();
                return;
            }
            applyPayload(data, false);
            seriesId = (data.series && data.series.id) || sid;
            window.WORKSHOP_SERIES_ID = seriesId;
            rememberSid(seriesId);
            setIdle(false);
            var name = (data.series && data.series.name) || '';
            document.title = 'MetaKavita · ' + (T().workshop_title || '') + ' · ' + name;
            if (push) {
                history.pushState({ workshopSid: seriesId }, '', workshopUrl(seriesId));
            } else {
                history.replaceState({ workshopSid: seriesId }, '', workshopUrl(seriesId));
            }
            markRailCurrent();
            scrollRailToCurrent();
            updateRailCount();
            settle();
        }).catch(function () {
            toast(T().err_network);
            settle();
        });
    }

    var VOLUME_EXTRAS = [
        { key: 'language', kind: 'text', size: 'short' },
        { key: 'webLinks', kind: 'text', wide: true, size: 'wide' },
        { key: 'ageRating', kind: 'select', size: 'short' },
        { key: 'genres', kind: 'csv', wide: true, size: 'wide' },
        { key: 'tags', kind: 'csv', wide: true, size: 'wide' },
        { key: 'writers', kind: 'csv', size: 'short' },
        { key: 'pencillers', kind: 'csv', size: 'short' },
        { key: 'coverArtists', kind: 'csv', size: 'short' },
        { key: 'translators', kind: 'csv', size: 'short' }
    ];

    function currentEdits(card) {
        var edits = {};
        card.querySelectorAll('[data-field]').forEach(function (el) {
            edits[el.getAttribute('data-field')] = el.value;
        });
        return edits;
    }

    function seriesEdits() {
        var edits = {};
        document.querySelectorAll('[data-series-field]').forEach(function (el) {
            edits[el.getAttribute('data-series-field')] = el.value;
        });
        return edits;
    }

    function seriesBaseline() {
        var base = {};
        ((payload.series && payload.series.form) || []).forEach(function (f) {
            base[f.key] = f.value || '';
        });
        return base;
    }

    function seriesCoverPending() {
        var card = document.getElementById('workshopSeriesCard');
        return !!(card && card.getAttribute('data-cover-url'));
    }

    function seriesIsDirty(edits) {
        if (seriesCoverPending()) return true;
        var base = seriesBaseline();
        return Object.keys(edits || {}).some(function (k) {
            return String(edits[k] || '') !== String(base[k] || '');
        });
    }

    function fieldLabel(key) {
        return T()['workshop_series_' + key] || T()['vol_field_' + key] || key;
    }

    function isEmptyValue(kind, key, value) {
        var v = String(value == null ? '' : value).trim();
        if (key === 'ageRating') return !v || v === '0' || v === '-1';
        return !v;
    }

    function showSeriesMorePref() {
        try {
            var v = localStorage.getItem('workshop_series_show_more');
            if (v === '1' || v === '0') return v === '1';
            return false;
        } catch (e) { return false; }
    }

    function setSeriesShowMorePref(on) {
        try { localStorage.setItem('workshop_series_show_more', on ? '1' : '0'); } catch (e) { /* ignore */ }
    }

    function showVolumeMorePref() {
        try {
            var v = localStorage.getItem('workshop_volume_show_more');
            if (v === '1' || v === '0') return v === '1';
            var fallback = localStorage.getItem('workshop_show_more');
            if (fallback === '1' || fallback === '0') return fallback === '1';
            return false;
        } catch (e) { return false; }
    }

    function setVolumeMorePref(on) {
        try {
            localStorage.setItem('workshop_volume_show_more', on ? '1' : '0');
            localStorage.setItem('workshop_show_more', on ? '1' : '0');
        } catch (e) { /* ignore */ }
    }

    function bindMoreToggles() {
        var seriesMore = document.getElementById('workshopSeriesMore');
        if (seriesMore && !seriesMore._mkMoreBound) {
            seriesMore._mkMoreBound = true;
            seriesMore.addEventListener('toggle', function () {
                setSeriesShowMorePref(seriesMore.open);
            });
        }

        document.querySelectorAll('.workshop-volume-card details.workshop-more').forEach(function (d) {
            if (d._mkMoreBound) return;
            d._mkMoreBound = true;
            d.addEventListener('toggle', function () {
                if (bindMoreToggles.applying) return;
                setVolumeMorePref(d.open);
                bindMoreToggles.applying = true;
                document.querySelectorAll('.workshop-volume-card details.workshop-more').forEach(function (other) {
                    if (other !== d) other.open = d.open;
                });
                bindMoreToggles.applying = false;
            });
        });
    }

    function fieldsByGroup(form, group) {
        return (form || []).filter(function (f) {
            return (f.group || 'primary') === group;
        });
    }

    function syncEmptyClass(el) {
        var label = el.closest('.workshop-field');
        if (!label) return;
        if (el.classList.contains('workshop-magic')) {
            label.classList.toggle('workshop-field--empty', !String(el.value || '').trim());
            return;
        }
        var key = el.getAttribute('data-field') || el.getAttribute('data-series-field') || '';
        var kind = el.tagName === 'SELECT' ? 'select' : (el.tagName === 'TEXTAREA' ? 'textarea' : 'text');
        label.classList.toggle('workshop-field--empty', isEmptyValue(kind, key, el.value));
    }

    function hostFromUrl(ref) {
        try {
            var host = new URL(String(ref || '')).hostname.replace(/^www\./, '');
            return host || '';
        } catch (e) {
            return '';
        }
    }

    function prettyProvider(name, ref) {
        var raw = String(name || '').trim();
        var map = {
            MANGANEWS: 'Manga-News',
            BEDETHEQUE: 'Bédéthèque',
            PLANETEBD: 'Planète BD',
            COMICVINE: 'ComicVine',
            METRON: 'Metron',
            MANGADEX: 'MangaDex',
            MANGASANCTUARY: 'Manga Sanctuary',
            OPENBD: 'openBD'
        };
        var upper = raw.toUpperCase();
        if (map[upper]) return map[upper];
        if (raw) return raw.replace(/_/g, ' ');
        return hostFromUrl(ref) || T().workshop_magic_linked || '';
    }

    function lockMark(locked) {
        if (!locked) return '';
        return ' <svg class="workshop-lock" aria-label="' + esc(T().workshop_locked || '') +
            '"><use href="#mk-ico-lock"></use></svg>';
    }

    function controlHtml(attr, key, value, kind, locked, options, rows) {
        var dis = locked && !forceOn() ? ' disabled' : '';
        var lockAttr = ' data-locked="' + (locked ? '1' : '0') + '"';
        var name = attr + '="' + esc(key) + '"';
        if (kind === 'textarea') {
            return '<textarea ' + name + lockAttr + ' rows="' + (rows || 5) + '"' + dis + '>' +
                esc(value || '') + '</textarea>';
        }
        if (kind === 'select') {
            var opts = (options || []).map(function (o) {
                return '<option value="' + esc(o.value) + '"' +
                    (String(o.value) === String(value || '0') ? ' selected' : '') + '>' +
                    esc(o.label) + '</option>';
            }).join('');
            return '<select ' + name + lockAttr + dis + '>' + opts + '</select>';
        }
        return '<input type="text" ' + name + lockAttr + ' value="' + esc(value || '') + '"' + dis + '>';
    }

    function labeledField(attr, f) {
        var locked = !!f.locked;
        var size = f.size || (f.wide ? 'wide' : 'short');
        var sizeClass = ' workshop-field--' + size;
        var options = f.options;
        if (f.kind === 'select' && !options) {
            options = ((payload.lookups || {})[f.key]) || [];
        }
        var empty = isEmptyValue(f.kind, f.key, f.value) ? ' workshop-field--empty' : '';
        return '<label class="workshop-field' + sizeClass + empty + '"><span class="workshop-field-label">' +
            esc(f.label || fieldLabel(f.key)) + lockMark(locked) + '</span>' +
            controlHtml(attr, f.key, f.value, f.kind, locked, options, f.rows) + '</label>';
    }

    function forceOn() {
        return true;
    }

    function applyForceLocks() {
        var force = forceOn();
        document.querySelectorAll('[data-field][data-locked], [data-series-field][data-locked]').forEach(function (el) {
            el.disabled = el.getAttribute('data-locked') === '1' && !force;
        });
    }

    function toastSend(data) {
        if (data && data.partial) {
            toast(data.error || T().workshop_partial || T().workshop_err);
            return;
        }
        if (data && data.success) {
            toast(data.noop ? (T().workshop_noop || '') : (T().workshop_sent || ''));
            return;
        }
        toast((data && data.error) || T().workshop_err);
    }

    function setSending(on) {
        document.querySelectorAll('.workshop-main button').forEach(function (b) {
            if (b.id === 'workshopCancelPass') return;
            b.disabled = !!on;
        });
    }

    function bindSeriesTitle(s) {
        var link = document.getElementById('workshopSeriesName');
        var text = document.getElementById('workshopSeriesNameText');
        if (text) text.textContent = (s && s.name) || '';
        if (!link) return;
        var href = kavitaSeriesUrl(s);
        if (href) {
            link.href = href;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.classList.add('is-link');
            link.setAttribute('title', T().workshop_open_kavita || '');
            link.setAttribute('aria-label', T().workshop_open_kavita || '');
        } else {
            link.removeAttribute('href');
            link.removeAttribute('target');
            link.removeAttribute('aria-label');
            link.classList.remove('is-link');
        }
    }

    function refreshSeriesDirty() {
        var card = document.getElementById('workshopSeriesCard');
        if (!card) return;
        if (seriesIsDirty(seriesEdits())) card.setAttribute('data-dirty', '1');
        else card.removeAttribute('data-dirty');
    }

    function openSeriesMoreIfNeeded(edits) {
        var more = document.getElementById('workshopSeriesMore');
        if (!more) return;
        var hit = false;
        more.querySelectorAll('[data-series-field]').forEach(function (el) {
            var k = el.getAttribute('data-series-field');
            if (edits && Object.prototype.hasOwnProperty.call(edits, k) && edits[k]) hit = true;
        });
        if (hit) {
            more.open = true;
            setSeriesShowMorePref(true);
        }
    }

    function updateBarStats() {
        var stats = document.getElementById('workshopBarStats');
        if (!stats) return;
        var selected = selectedCards().length;
        var dirtyVol = document.querySelectorAll('.workshop-volume-card[data-dirty="1"]').length;
        var bits = [fmt(T().workshop_selected_count || '{0}', selected)];
        if (dirtyVol) bits.push(fmt(T().workshop_dirty_n || '{0}', dirtyVol));
        stats.textContent = bits.join(' · ');
    }

    function setDirty() {
        dirty = true;
        refreshSeriesDirty();
        updateBarStats();
    }

    function renderSeries() {
        var s = payload.series || {};
        bindSeriesTitle(s);
        var primary = fieldsByGroup(s.form, 'primary');
        var extra = fieldsByGroup(s.form, 'more');
        var fields = document.getElementById('workshopSeriesFields');
        if (fields) {
            fields.innerHTML = primary.map(function (f) {
                return labeledField('data-series-field', f);
            }).join('');
        }
        var moreFields = document.getElementById('workshopSeriesMoreFields');
        var more = document.getElementById('workshopSeriesMore');
        if (moreFields) {
            moreFields.innerHTML = extra.map(function (f) {
                return labeledField('data-series-field', f);
            }).join('');
        }
        if (more) {
            more.hidden = !extra.length;
            more.open = showSeriesMorePref();
        }
        bindMoreToggles();
        var seriesCard = document.getElementById('workshopSeriesCard');
        if (seriesCard) {
            seriesCard.removeAttribute('data-cover-url');
            seriesCard.removeAttribute('data-cover-display');
            if (s.staged_cover_url) {
                seriesCard.setAttribute('data-cover-url', s.staged_cover_url);
                seriesCard.setAttribute('data-cover-display', s.staged_cover_url);
            }
        }
        var img = document.getElementById('workshopSeriesCover');
        var ph = img && img.parentNode.querySelector('.workshop-cover-placeholder');
        if (img) {
            img.alt = s.name || T().workshop_cover_alt || '';
            var displayCover = s.staged_cover_url || s.cover_url || '';
            showCover(img, displayCover, ph);
        }
        var banner = document.getElementById('workshopPassBanner');
        if (banner) banner.hidden = !payload.pass_running;
        setSending(!!payload.pass_running);
        applyForceLocks();
        if ((s.override && Object.keys(s.override).length) || s.staged_cover_url) {
            if (seriesCard) seriesCard.setAttribute('data-dirty', '1');
            setDirty();
        }
        refreshSeriesDirty();
    }

    function unitLabel(u) {
        if (u.volume_number != null && u.volume_number !== '') return 'T. ' + u.volume_number;
        if (u.chapter_number != null && u.chapter_number !== '') return 'Ch. ' + u.chapter_number;
        return u.name || ('#' + u.chapter_id);
    }

    function renderVolumes() {
        var root = document.getElementById('workshopVolumeList');
        if (!root) return;
        var units = payload.units || [];
        var reason = payload.skipped_reason || '';
        var hint = '';
        if (reason === 'oneshot') hint = T().vol_preview_oneshot_hint || T().vol_preview_oneshot || '';
        if (reason === 'specials') hint = T().vol_preview_specials_hint || T().vol_preview_specials || '';
        var banner = hint ? '<p class="workshop-empty">' + esc(hint) + '</p>' : '';
        if (!units.length) {
            root.innerHTML = banner || ('<p class="workshop-empty">' + esc(T().workshop_empty || '') + '</p>');
            updateBarStats();
            return;
        }
        root.innerHTML = banner + units.map(volumeCardHtml).join('');
        root.querySelectorAll('img').forEach(function (img) {
            bindCover(img, img.parentNode.querySelector('.workshop-cover-placeholder'));
        });
        root.querySelectorAll('input, textarea, select').forEach(function (el) {
            function markVolDirty() {
                if (el.classList.contains('workshop-vol-check')) {
                    updateBarStats();
                    return;
                }
                var card = el.closest('.workshop-volume-card');
                if (card) card.setAttribute('data-dirty', '1');
                syncEmptyClass(el);
                setDirty();
            }
            el.addEventListener('input', markVolDirty);
            el.addEventListener('change', markVolDirty);
        });
        root.querySelectorAll('[data-act]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var card = btn.closest('.workshop-volume-card');
                onVolumeAct(btn.getAttribute('data-act'), card);
            });
        });
        applyForceLocks();
        bindMoreToggles();
        updateBarStats();
    }

    function volumeFieldsOf(u) {
        var ins = u.inscribed || {};
        var primary = [
            { key: 'title', kind: 'text', size: 'wide', label: T().vol_field_title || 'Title', value: ins.title || '', locked: !!ins.title_locked },
            { key: 'isbn', kind: 'text', size: 'mid', label: T().vol_field_isbn || 'ISBN', value: ins.isbn || '', locked: !!ins.isbn_locked },
            { key: 'release_date', kind: 'text', size: 'mid', label: T().vol_field_release_date || '', value: ins.release_date || '', locked: !!ins.release_locked },
            { key: 'summary', kind: 'textarea', wide: true, size: 'wide', rows: 2, label: T().vol_field_summary || '', value: ins.summary || '', locked: !!ins.summary_locked }
        ];
        var extras = VOLUME_EXTRAS.map(function (spec) {
            return {
                key: spec.key,
                kind: spec.kind === 'select' ? 'select' : (spec.kind === 'textarea' ? 'textarea' : 'text'),
                wide: spec.wide,
                size: spec.size || (spec.wide ? 'wide' : 'short'),
                group: 'more',
                label: fieldLabel(spec.key),
                value: ins[spec.key] || (spec.kind === 'select' ? '0' : ''),
                locked: !!ins[spec.key + '_locked'],
                options: spec.kind === 'select' ? ((payload.lookups || {}).ageRating || []) : null
            };
        });
        return primary.concat(extras);
    }

    function magicChipHtml(u) {
        var ov = u.override || {};
        var ref = ov.provider_ref || '';
        if (!ref) return '';
        var name = prettyProvider(ov.provider, ref);
        return '<a class="workshop-magic-chip" href="' + esc(ref) + '" target="_blank" rel="noopener noreferrer" title="' + esc(ref) + '">' +
            esc(name) +
            '<svg class="workshop-ext" aria-hidden="true"><use href="#mk-ico-external"></use></svg></a>';
    }

    function magicFieldHtml(u) {
        var ref = (u.override && u.override.provider_ref) || '';
        var empty = ref ? '' : ' workshop-field--empty';
        return '<label class="workshop-field workshop-field--wide workshop-field--magic' + empty + '">' +
            '<span class="workshop-field-label">' +
            '<svg class="workshop-magic-ico" aria-hidden="true"><use href="#mk-ico-wand"></use></svg>' +
            esc(T().workshop_magic_label || T().workshop_event_magic || '') + '</span>' +
            '<div class="workshop-magic-row">' +
            '<input type="url" class="workshop-magic" placeholder="' + esc(T().workshop_magic_placeholder || '') + '"' +
            ' value="' + esc(ref) + '">' +
            '<button type="button" class="btn-secondary" data-act="magic">' + esc(T().workshop_magic_apply || '') + '</button>' +
            '</div></label>';
    }

    function volumeCardHtml(u) {
        var ins = u.inscribed || {};
        var ov = u.override || {};
        var stagedCover = (ov.payload && ov.payload.cover_url) || u.staged_cover_url || (ins && ins.cover_url) || '';
        var coverAttr = stagedCover
            ? ' data-cover-url="' + esc(stagedCover) + '" data-cover-display="' + esc(stagedCover) + '"'
            : '';
        var displayCover = stagedCover || u.cover_url || '';
        var all = volumeFieldsOf(u);
        var primary = all.filter(function (f) { return f.group !== 'more'; });
        var extra = all.filter(function (f) { return f.group === 'more'; });
        var extraBlock = extra.length
            ? '<details class="workshop-more"' + (showVolumeMorePref() ? ' open' : '') + '>' +
              '<summary>' + esc(T().workshop_more_fields || '') + '</summary>' +
              '<div class="workshop-more-body"><div class="workshop-volume-fields">' +
              extra.map(function (f) { return labeledField('data-field', f); }).join('') +
              '</div></div></details>'
            : '';
        return '<article class="workshop-volume-card" data-chapter-id="' + u.chapter_id + '"' +
            coverAttr +
            ' data-volume-id="' + esc(u.volume_id || '') + '"' +
            ' data-volume-number="' + esc(u.volume_number == null ? '' : u.volume_number) + '"' +
            ' data-chapter-number="' + esc(u.chapter_number == null ? '' : u.chapter_number) + '"' +
            ' data-title-locked="' + (ins.title_locked ? '1' : '0') + '"' +
            ' data-isbn-locked="' + (ins.isbn_locked ? '1' : '0') + '"' +
            ' data-release-locked="' + (ins.release_locked ? '1' : '0') + '"' +
            ' data-summary-locked="' + (ins.summary_locked ? '1' : '0') + '">' +
            '<input type="checkbox" class="workshop-vol-check" checked>' +
            '<div class="workshop-cover workshop-cover--volume">' +
            '<div class="workshop-cover-well workshop-cover-well--volume">' +
            (displayCover
                ? '<img src="' + esc(displayCover) + '" alt="' + esc(T().workshop_cover_alt || '') + '" loading="lazy">' +
                  '<div class="workshop-cover-placeholder" hidden></div>'
                : '<img alt="' + esc(T().workshop_cover_alt || '') + '" hidden>' +
                  '<div class="workshop-cover-placeholder"></div>') +
            '</div>' +
            '<button type="button" class="workshop-cover-pick" data-act="cover" title="' +
            esc(T().workshop_choose_cover || '') + '" aria-label="' + esc(T().workshop_choose_cover || '') + '">' +
            '<svg aria-hidden="true"><use href="#mk-ico-cover"></use></svg>' +
            '<span class="workshop-cover-pick-label">' + esc(T().workshop_pick || '') + '</span></button>' +
            '</div>' +
            '<div class="workshop-volume-meta">' +
            '<div class="workshop-volume-head">' +
            '<div class="workshop-volume-title">' + esc(unitLabel(u)) + magicChipHtml(u) + '</div>' +
            '</div>' +
            magicFieldHtml(u) +
            '<div class="workshop-volume-fields">' +
            primary.map(function (f) { return labeledField('data-field', f); }).join('') +
            '</div>' +
            extraBlock +
            '<div class="workshop-volume-actions">' +
            '<button type="button" class="btn-primary" data-act="send">' + esc(T().workshop_send_volume || '') + '</button>' +
            '<button type="button" class="btn-secondary" data-act="review">' + esc(T().workshop_review || '') + '</button>' +
            '<button type="button" class="btn-secondary" data-act="super">' + esc(T().workshop_super || '') + '</button>' +
            '<button type="button" class="btn-danger" data-act="reset">' + esc(T().workshop_reset_volume || '') + '</button>' +
            '</div></div></article>';
    }

    function formatWhen(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return String(iso);
        try {
            return d.toLocaleString();
        } catch (e) {
            return String(iso);
        }
    }

    function unitFromHistory(h) {
        var detail = (h && h.detail) || {};
        if (detail.volume_number != null && detail.volume_number !== '') return 'T. ' + detail.volume_number;
        if (detail.chapter_number != null && detail.chapter_number !== '') return 'Ch. ' + detail.chapter_number;
        var cid = h && h.chapter_id;
        if (cid == null) return '';
        var units = payload.units || [];
        var i;
        for (i = 0; i < units.length; i++) {
            if (String(units[i].chapter_id) === String(cid)) return unitLabel(units[i]);
        }
        return '';
    }

    function renderHistory() {
        var list = document.getElementById('workshopHistoryList');
        if (!list) return;
        var rows = payload.history || [];
        if (!rows.length) {
            list.innerHTML = '<li>' + esc(T().workshop_history_empty || '') + '</li>';
            return;
        }
        var labels = {
            send: T().workshop_event_send,
            'send-series': T().workshop_send_series,
            magic: T().workshop_event_magic,
            reset: T().workshop_event_reset,
            review: T().workshop_event_review
        };
        list.innerHTML = rows.map(function (h) {
            var bits = [labels[h.event] || h.event];
            var unit = unitFromHistory(h);
            if (unit) bits.push(unit);
            var detail = h.detail || {};
            if (detail.provider) bits.push(prettyProvider(detail.provider, detail.provider_ref));
            var fields = detail.fields || [];
            if (fields.length) {
                bits.push(fields.map(function (k) { return fieldLabel(k); }).join(', '));
            }
            bits.push(formatWhen(h.created_at));
            return '<li>' + esc(bits.join(' · ')) + '</li>';
        }).join('');
    }

    function snapshotDirty() {
        var snap = { series: null, volumes: {}, magic: {}, checks: {}, covers: {}, seriesCover: null };
        var edits = seriesEdits();
        if (seriesIsDirty(edits)) snap.series = edits;
        var seriesCard = document.getElementById('workshopSeriesCard');
        if (seriesCard && seriesCard.getAttribute('data-cover-url')) {
            snap.seriesCover = {
                url: seriesCard.getAttribute('data-cover-url'),
                display: seriesCard.getAttribute('data-cover-display') || ''
            };
        }
        document.querySelectorAll('.workshop-volume-card').forEach(function (card) {
            var cid = String(card.getAttribute('data-chapter-id'));
            var cb = card.querySelector('.workshop-vol-check');
            if (cb) snap.checks[cid] = cb.checked;
            if (card.getAttribute('data-cover-url')) {
                snap.covers[cid] = {
                    url: card.getAttribute('data-cover-url'),
                    display: card.getAttribute('data-cover-display') || ''
                };
            }
            if (card.getAttribute('data-dirty') !== '1') return;
            snap.volumes[cid] = currentEdits(card);
            var magic = card.querySelector('.workshop-magic');
            snap.magic[cid] = magic ? magic.value : '';
        });
        return snap;
    }

    function restoreDirty(snap) {
        if (!snap) return;
        if (snap.series && !seriesIsDirty(snap.series)) snap.series = null;
        if (snap.series) {
            Object.keys(snap.series).forEach(function (key) {
                var el = document.querySelector('[data-series-field="' + key + '"]');
                if (el) el.value = snap.series[key];
            });
            openSeriesMoreIfNeeded(snap.series);
            var seriesCard = document.getElementById('workshopSeriesCard');
            if (seriesCard) seriesCard.setAttribute('data-dirty', '1');
        }
        if (snap.seriesCover) {
            paintPickedCover(document.getElementById('workshopSeriesCard'), snap.seriesCover.url, snap.seriesCover.display);
        }
        Object.keys(snap.volumes).forEach(function (cid) {
            var card = document.querySelector('.workshop-volume-card[data-chapter-id="' + cid + '"]');
            if (!card) return;
            var edits = snap.volumes[cid] || {};
            Object.keys(edits).forEach(function (f) {
                var el = card.querySelector('[data-field="' + f + '"]');
                if (el) el.value = edits[f];
            });
            if (Object.prototype.hasOwnProperty.call(snap.magic, cid)) {
                var magic = card.querySelector('.workshop-magic');
                if (magic) magic.value = snap.magic[cid];
            }
            card.setAttribute('data-dirty', '1');
            var more = card.querySelector('.workshop-more');
            if (more) more.open = true;
        });
        Object.keys(snap.covers || {}).forEach(function (cid) {
            var card = document.querySelector('.workshop-volume-card[data-chapter-id="' + cid + '"]');
            if (!card) return;
            paintPickedCover(card, snap.covers[cid].url, snap.covers[cid].display);
        });
        Object.keys(snap.checks).forEach(function (cid) {
            var card = document.querySelector('.workshop-volume-card[data-chapter-id="' + cid + '"]');
            var cb = card && card.querySelector('.workshop-vol-check');
            if (cb) cb.checked = snap.checks[cid];
        });
        applyForceLocks();
        document.querySelectorAll('[data-field], [data-series-field], .workshop-magic').forEach(syncEmptyClass);
        dirty = !!(snap.series || snap.seriesCover || Object.keys(snap.volumes).length || Object.keys(snap.covers || {}).length);
        refreshSeriesDirty();
        updateBarStats();
    }

    function markDoneClean(results) {
        (results || []).forEach(function (r) {
            if (!r || r.status !== 'DONE' || r.chapter_id == null) return;
            var card = document.querySelector('.workshop-volume-card[data-chapter-id="' + r.chapter_id + '"]');
            if (card) card.removeAttribute('data-dirty');
        });
        updateBarStats();
    }

    function applyPayload(next, keepDirty) {
        if (!next) return;
        var snap = keepDirty === false ? null : snapshotDirty();
        payload = next;
        seriesId = (next.series && next.series.id) || seriesId;
        renderSeries();
        renderVolumes();
        renderHistory();
        if (snap) restoreDirty(snap);
        else {
            dirty = false;
            refreshSeriesDirty();
            updateBarStats();
        }
    }

    function persistRailFilters() {
        try {
            var search = document.getElementById('workshopRailSearch');
            var inside = document.getElementById('workshopSearchInside');
            var lib = document.getElementById('workshopRailLib');
            var status = document.getElementById('workshopRailStatus');
            var hide = document.getElementById('workshopHideIgnored');
            if (search) localStorage.setItem('filter_search', (search.value || '').toLowerCase().trim());
            if (inside) localStorage.setItem('filter_search_inside', inside.checked ? 'true' : 'false');
            if (lib && persistLibrary) localStorage.setItem('filter_library', lib.value || '');
            if (status && persistStatus && status.value !== 'AUTO_SYNC') {
                localStorage.setItem('filter_status', status.value);
            }
            if (hide) localStorage.setItem('filter_hide_ignored', hide.checked ? 'true' : 'false');
        } catch (e) { /* ignore */ }
    }

    function restoreRailFilters() {
        try {
            var savedStatus = localStorage.getItem('filter_status');
            var savedHide = localStorage.getItem('filter_hide_ignored');
            var savedSearch = localStorage.getItem('filter_search');
            var savedInside = localStorage.getItem('filter_search_inside');
            var savedLib = localStorage.getItem('filter_library');
            var search = document.getElementById('workshopRailSearch');
            var inside = document.getElementById('workshopSearchInside');
            var lib = document.getElementById('workshopRailLib');
            var status = document.getElementById('workshopRailStatus');
            var hide = document.getElementById('workshopHideIgnored');
            if (search && savedSearch) search.value = savedSearch;
            if (inside && savedInside === 'true') inside.checked = true;
            if (lib && savedLib && lib.querySelector('option[value="' + savedLib + '"]')) {
                lib.value = savedLib;
            } else if (savedLib) {
                persistLibrary = false;
            }
            if (status && savedStatus === 'AUTO_SYNC') {
                persistStatus = false;
            } else if (status && savedStatus && savedStatus !== 'DUPLICATES' &&
                       status.querySelector('option[value="' + savedStatus + '"]')) {
                status.value = savedStatus;
            }
            if (hide && savedHide === 'false') hide.checked = false;
        } catch (e) { /* ignore */ }
    }

    function matchingRail() {
        var q = ((document.getElementById('workshopRailSearch') || {}).value || '').trim().toLowerCase();
        var lib = (document.getElementById('workshopRailLib') || {}).value || '';
        var status = (document.getElementById('workshopRailStatus') || {}).value || 'ALL';
        var hideIgnored = !!(document.getElementById('workshopHideIgnored') || {}).checked;
        var searchInside = !!(document.getElementById('workshopSearchInside') || {}).checked;
        return rail.filter(function (s) {
            if (lib && String(s.libraryId) !== String(lib)) return false;
            var st = s.status || 'PENDING';
            if (status === 'ALL') {
                if (hideIgnored && st === 'IGNORED') return false;
            } else if (st !== status) {
                return false;
            }
            return titleMatchesSearch(s.search || (s.name || ''), q, searchInside);
        });
    }

    function railStatusLabel(st) {
        var sel = document.getElementById('workshopRailStatus');
        if (!sel) return st || '';
        var i;
        for (i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === st) return sel.options[i].textContent || st;
        }
        return st || '';
    }

    function renderRail() {
        var list = document.getElementById('workshopRailList');
        if (!list) return;
        filteredRail = matchingRail();
        if (filteredRail.length >= VIRTUAL_MIN) {
            var top = list.scrollTop || 0;
            var view = list.clientHeight || 480;
            var start = Math.max(0, Math.floor(top / ROW_H) - 4);
            var end = Math.min(filteredRail.length, start + Math.ceil(view / ROW_H) + 8);
            var padTop = start * ROW_H;
            var padBot = (filteredRail.length - end) * ROW_H;
            var slice = filteredRail.slice(start, end);
            list.innerHTML = '<div style="height:' + padTop + 'px"></div>' +
                slice.map(railItemHtml).join('') +
                '<div style="height:' + padBot + 'px"></div>';
            if (!list._virt) {
                list._virt = true;
                list.addEventListener('scroll', function () { renderRail(); });
            }
        } else {
            list.innerHTML = filteredRail.map(railItemHtml).join('');
        }
        list.querySelectorAll('a').forEach(function (a) {
            a.addEventListener('click', function (ev) {
                ev.preventDefault();
                var sid = a.getAttribute('data-sid');
                if (sid) goTo(sid);
            });
        });
        updateRailCount();
    }

    function markRailCurrent() {
        document.querySelectorAll('.workshop-rail-item').forEach(function (a) {
            if (String(a.getAttribute('data-sid')) === String(seriesId)) {
                a.classList.add('is-current');
            } else {
                a.classList.remove('is-current');
            }
        });
    }

    function scrollRailToCurrent() {
        var list = document.getElementById('workshopRailList');
        if (!list) return;
        var ids = filteredRail.map(function (s) { return String(s.id); });
        var i = ids.indexOf(String(seriesId));
        if (i < 0) return;
        if (filteredRail.length >= VIRTUAL_MIN) {
            var top = i * ROW_H - Math.max(0, (list.clientHeight / 2) - ROW_H);
            list.scrollTop = Math.max(0, top);
            renderRail();
            return;
        }
        markRailCurrent();
        var cur = list.querySelector('.workshop-rail-item.is-current');
        if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
    }

    function updateRailCount() {
        var el = document.getElementById('workshopRailCount');
        if (!el) return;
        var ids = filteredRail.map(function (s) { return String(s.id); });
        var i = ids.indexOf(String(seriesId));
        var pos = i < 0 ? 0 : i + 1;
        el.textContent = fmt(T().workshop_rail_count || '{0} / {1}', pos, filteredRail.length);
        updateNavButtons();
    }

    function updateNavButtons() {
        var prev = document.getElementById('workshopPrev');
        var next = document.getElementById('workshopNext');
        var ids = filteredRail.map(function (s) { return String(s.id); });
        var i = ids.indexOf(String(seriesId));
        if (prev) prev.disabled = i <= 0;
        if (next) next.disabled = !ids.length || (i >= 0 && i >= ids.length - 1);
    }

    function railItemHtml(s) {
        var cur = String(s.id) === String(seriesId) ? ' is-current' : '';
        var st = s.status || 'PENDING';
        var chipClass = 'workshop-rail-chip workshop-rail-chip--' + String(st).toLowerCase();
        return '<a class="workshop-rail-item' + cur + '" href="' + workshopUrl(s.id) + '" data-sid="' + s.id + '">' +
            '<img class="workshop-rail-thumb" src="' + esc(s.cover_url || '') + '" alt="" loading="lazy">' +
            '<span class="workshop-rail-text"><span class="workshop-rail-name">' + esc(s.name || '') + '</span>' +
            '<span class="' + chipClass + '">' + esc(railStatusLabel(st)) + '</span></span></a>';
    }

    function stepRail(delta) {
        var ids = filteredRail.map(function (s) { return String(s.id); });
        var i = ids.indexOf(String(seriesId));
        if (i < 0) {
            if (delta > 0 && filteredRail[0]) goTo(filteredRail[0].id);
            return;
        }
        var next = filteredRail[i + delta];
        if (next) goTo(next.id);
    }

    function selectedCards() {
        return Array.prototype.slice.call(document.querySelectorAll('.workshop-volume-card'))
            .filter(function (c) {
                var cb = c.querySelector('.workshop-vol-check');
                return cb && cb.checked;
            });
    }

    function itemFromCard(card) {
        return {
            chapter_id: parseInt(card.getAttribute('data-chapter-id'), 10),
            volume_id: card.getAttribute('data-volume-id'),
            volume_number: card.getAttribute('data-volume-number'),
            chapter_number: card.getAttribute('data-chapter-number'),
            edits: currentEdits(card),
            cover_url: card.getAttribute('data-cover-url') || ''
        };
    }

    function onVolumeAct(act, card) {
        if (!card) return;
        var cid = parseInt(card.getAttribute('data-chapter-id'), 10);
        if (act === 'send') {
            var item = itemFromCard(card);
            setSending(true);
            api('/api/series/' + seriesId + '/workshop/send', {
                method: 'POST',
                body: {
                    chapter_id: cid,
                    edits: item.edits,
                    force: true,
                    cover_url: item.cover_url || '',
                    volume_id: item.volume_id,
                    volume_number: item.volume_number,
                    chapter_number: item.chapter_number
                }
            }).then(function (data) {
                setSending(false);
                toastSend(data);
                if (data.success && !data.noop) card.removeAttribute('data-dirty');
                if (data.success || data.partial) reload();
            }).catch(function () { setSending(false); toast(T().err_network); });
            return;
        }
        if (act === 'magic') {
            var url = (card.querySelector('.workshop-magic') || {}).value || '';
            api('/api/series/' + seriesId + '/workshop/magic', {
                method: 'POST',
                body: { chapter_id: cid, url: url, volume_number: card.getAttribute('data-volume-number') }
            }).then(function (data) {
                toast(data.success ? (T().workshop_event_magic || '') : (data.error || T().workshop_no_match));
                if (data.success) {
                    card.removeAttribute('data-dirty');
                    reload();
                }
            });
            return;
        }
        if (act === 'cover') {
            openCoverPicker({ kind: 'volume', card: card });
            return;
        }
        if (act === 'review' || act === 'super') {
            openVolumeReview(cid, act === 'super');
            return;
        }
        if (act === 'reset') {
            if (!window.confirm(T().workshop_reset_volume_confirm || '')) return;
            api('/api/series/' + seriesId + '/volume-enrich/reset', {
                method: 'POST',
                body: { workshop: true, chapter_id: cid }
            }).then(function (data) {
                if (data.payload) {
                    card.removeAttribute('data-dirty');
                    applyPayload(data.payload);
                }
                toast(T().workshop_event_reset || '');
            });
        }
    }

    function reload() {
        api('/api/series/' + seriesId + '/workshop').then(function (data) {
            if (data.success) {
                applyPayload(data);
            }
        });
    }

    function openVolumeReview(cid, superReview) {
        reviewChapterId = cid;
        var modal = document.getElementById('manualReviewModal');
        if (!modal) return;
        modal.dataset.kind = 'volume';
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        ['mrWaitPanel', 'mrCoverPanel', 'mrEditPanel', 'mrRecapPanel', 'mrListPanel'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
        var pick = document.getElementById('mrPickPanel');
        if (pick) pick.style.display = 'block';
        var above = document.getElementById('mrAboveList');
        if (above) above.innerHTML = '<p>' + esc(T().vol_preview_loading || '…') + '</p>';
        api('/api/series/' + seriesId + '/workshop/review', {
            method: 'POST',
            body: { chapter_id: cid, super: !!superReview }
        }).then(function (data) {
            reviewCandidates = data.candidates || [];
            if (!above) return;
            if (!reviewCandidates.length) {
                above.innerHTML = '<p>' + esc(T().vol_preview_none || '') + '</p>';
                return;
            }
            above.innerHTML = reviewCandidates.map(function (c, i) {
                return '<button type="button" class="workshop-candidate" data-idx="' + i + '">' +
                    '<strong>' + esc(c.title || c.provider || '') + '</strong>' +
                    '<span>' + esc(c.isbn || '') + ' · ' + esc(c.release_date || '') + '</span>' +
                    '<p>' + esc((c.summary || '').slice(0, 280)) + '</p></button>';
            }).join('');
            above.querySelectorAll('.workshop-candidate').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    above.querySelectorAll('.workshop-candidate').forEach(function (b) {
                        b.classList.remove('is-picked');
                    });
                    btn.classList.add('is-picked');
                });
            });
        });
    }

    function applyVolumeReview(cid, data) {
        var card = document.querySelector('.workshop-volume-card[data-chapter-id="' + cid + '"]');
        if (!card) return;
        var edits = (data && data.edits) || {};
        Object.keys(edits).forEach(function (f) {
            var el = card.querySelector('[data-field="' + f + '"]');
            if (el && edits[f]) el.value = edits[f];
        });
        if (data && data.cover_url) {
            paintPickedCover(card, data.cover_url, data.cover_url);
        } else {
            card.setAttribute('data-dirty', '1');
            setDirty();
        }
        card.querySelectorAll('[data-field]').forEach(syncEmptyClass);
    }

    window.workshopApplyReview = function (detail) {
        if (!detail) return;
        var edits = detail.series_edits || {};
        Object.keys(edits).forEach(function (key) {
            var el = document.querySelector('[data-series-field="' + key + '"]');
            if (el && edits[key] != null && String(edits[key]).trim() !== '') {
                el.value = edits[key];
            }
        });
        openSeriesMoreIfNeeded(edits);
        var seriesCard = document.getElementById('workshopSeriesCard');
        if (seriesCard) seriesCard.setAttribute('data-dirty', '1');
        if (detail.cover_url) {
            paintPickedCover(seriesCard, detail.cover_url, detail.cover_url);
        } else {
            setDirty();
        }
        document.querySelectorAll('[data-series-field]').forEach(syncEmptyClass);
        toast(T().workshop_review_staged || '');
    };

    function confirmVolumeReview() {
        var picked = document.querySelector('#mrAboveList .workshop-candidate.is-picked');
        var idx = picked ? parseInt(picked.getAttribute('data-idx'), 10) : 0;
        var candidate = reviewCandidates[idx];
        if (!candidate || reviewChapterId == null) return;
        var cid = reviewChapterId;
        api('/api/series/' + seriesId + '/workshop/review/confirm', {
            method: 'POST',
            body: { chapter_id: cid, candidate: candidate }
        }).then(function (data) {
            if (!data.success) {
                toast(data.error || T().workshop_err || '');
                return;
            }
            applyVolumeReview(cid, data);
            closeVolumeModal();
            toast(T().workshop_review_staged || '');
        });
    }

    function closeVolumeModal() {
        var modal = document.getElementById('manualReviewModal');
        if (!modal) return;
        modal.dataset.kind = 'series';
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
        reviewChapterId = null;
        reviewCandidates = [];
    }

    var coverPickTarget = null;

    function paintPickedCover(host, url, display) {
        if (!host || !url) return;
        host.setAttribute('data-cover-url', url);
        host.setAttribute('data-cover-display', display || url);
        var img = host.querySelector('.workshop-cover-well img') || host.querySelector('img');
        var ph = host.querySelector('.workshop-cover-placeholder');
        showCover(img, display || url, ph);
        host.setAttribute('data-dirty', '1');
        setDirty();
    }

    function coverSearchQuery(target) {
        var name = (payload.series || {}).name || '';
        if (target && target.kind === 'volume' && target.card) {
            var vol = target.card.getAttribute('data-volume-number');
            var titleEl = target.card.querySelector('[data-field="title"]');
            var title = titleEl ? titleEl.value : '';
            if (vol) return (name + ' ' + vol).trim();
            if (title) return title;
        }
        return name;
    }

    function closeCoverPicker() {
        var modal = document.getElementById('workshopCoverModal');
        if (modal) {
            modal.style.display = 'none';
            modal.setAttribute('aria-hidden', 'true');
        }
        if (typeof stopCoverSearch === 'function') stopCoverSearch();
        coverPickTarget = null;
    }

    function onCoverPicked(url, meta) {
        if (!url || !coverPickTarget) return;
        var display = (meta && (meta.display_url || meta.url)) || url;
        if (coverPickTarget.kind === 'series') {
            paintPickedCover(document.getElementById('workshopSeriesCard'), url, display);
            if (typeof scheduleSeriesDraft === 'function') scheduleSeriesDraft();
        } else if (coverPickTarget.card) {
            paintPickedCover(coverPickTarget.card, url, display);
        }
        closeCoverPicker();
    }

    function runCoverSearch() {
        var input = document.getElementById('workshopCoverQuery');
        var grid = document.getElementById('workshopCoverGrid');
        var query = ((input && input.value) || '').trim();
        if (!query || !grid) return;
        if (typeof startCoverSearch === 'function') {
            startCoverSearch({
                seriesId: seriesId,
                query: query,
                gridEl: grid,
                statusMessage: (T().cover_streaming_start || ''),
                onPick: onCoverPicked
            });
            return;
        }
        grid.innerHTML = '<p>' + esc(T().waiting || '') + '</p>';
        api('/api/series/' + seriesId + '/covers?series_name=' + encodeURIComponent(query)).then(function (data) {
            var covers = (data && data.covers) || [];
            if (!covers.length) {
                grid.innerHTML = '<p>' + esc(T().vol_preview_none || '') + '</p>';
                return;
            }
            grid.innerHTML = '';
            covers.forEach(function (c) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'cover-item';
                btn.dataset.url = c.url || '';
                btn.innerHTML = '<img src="' + esc(c.display_url || c.url || '') + '" alt="" loading="lazy" referrerpolicy="no-referrer">' +
                    '<div class="cover-provider">' + esc(c.provider || '') + '</div>';
                btn.addEventListener('click', function () { onCoverPicked(c.url, c); });
                grid.appendChild(btn);
            });
        });
    }

    function openCoverPicker(target) {
        coverPickTarget = target || { kind: 'series' };
        var modal = document.getElementById('workshopCoverModal');
        var input = document.getElementById('workshopCoverQuery');
        var grid = document.getElementById('workshopCoverGrid');
        if (!modal) return;
        if (input) input.value = coverSearchQuery(coverPickTarget);
        if (grid) grid.innerHTML = '';
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        runCoverSearch();
        if (input) input.focus();
    }

    function forceSync(flags) {
        var s = payload.series || {};
        var modal = document.getElementById('manualReviewModal');
        if (modal) modal.dataset.kind = 'series';
        window.WORKSHOP_FORCE_REVIEW = {
            review: !!flags.review,
            super: !!flags.super,
            seriesId: s.id
        };
        if (typeof mrPrepareForBatch === 'function') {
            mrPrepareForBatch();
        } else if (typeof openManualReviewModal === 'function') {
            openManualReviewModal({ waiting: true, resetSession: true });
        }
        var body = 'series_id=' + encodeURIComponent(s.id) +
            '&series_name=' + encodeURIComponent(s.name || '');
        if (flags.super) body += '&super_review=true';
        if (flags.review) body += '&manual_review_override=true';
        fetch(getRootPath() + '/force-sync', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body
        }).then(function (r) { return r.json(); }).then(function (data) {
            toast(data.success ? (T().action_ok || '') : (data.msg || T().action_fail || ''));
        }).catch(function () { toast(T().err_network || ''); });
    }

    var seriesDraftTimer = null;
    function scheduleSeriesDraft() {
        if (!seriesId) return;
        clearTimeout(seriesDraftTimer);
        seriesDraftTimer = setTimeout(function () {
            var seriesCard = document.getElementById('workshopSeriesCard');
            var edits = seriesEdits();
            var coverUrl = (seriesCard && seriesCard.getAttribute('data-cover-url')) || '';
            api('/api/series/' + seriesId + '/workshop/draft-series', {
                method: 'POST',
                body: { edits: edits, cover_url: coverUrl }
            });
        }, 500);
    }

    function wire() {
        var seriesCard = document.getElementById('workshopSeriesCard');
        if (seriesCard) {
            seriesCard.addEventListener('input', function (ev) {
                if (ev.target && ev.target.getAttribute('data-series-field')) {
                    syncEmptyClass(ev.target);
                    setDirty();
                    scheduleSeriesDraft();
                }
            });
            seriesCard.addEventListener('change', function (ev) {
                if (ev.target && ev.target.getAttribute('data-series-field')) {
                    syncEmptyClass(ev.target);
                    setDirty();
                    scheduleSeriesDraft();
                }
            });
        }
        var search = document.getElementById('workshopRailSearch');
        var lib = document.getElementById('workshopRailLib');
        var status = document.getElementById('workshopRailStatus');
        var inside = document.getElementById('workshopSearchInside');
        var hide = document.getElementById('workshopHideIgnored');
        var filterTimer = null;
        function scheduleRail() {
            persistRailFilters();
            if (filterTimer) clearTimeout(filterTimer);
            filterTimer = setTimeout(renderRail, 150);
        }
        if (search) search.addEventListener('input', scheduleRail);
        if (lib) lib.addEventListener('change', function () {
            persistLibrary = true;
            scheduleRail();
        });
        if (status) status.addEventListener('change', function () {
            persistStatus = true;
            scheduleRail();
        });
        if (inside) inside.addEventListener('change', scheduleRail);
        if (hide) hide.addEventListener('change', scheduleRail);
        var prev = document.getElementById('workshopPrev');
        var next = document.getElementById('workshopNext');
        if (prev) prev.addEventListener('click', function () { stepRail(-1); });
        if (next) next.addEventListener('click', function () { stepRail(1); });
        var forceNote = document.getElementById('workshopForce');
        if (forceNote) forceNote.addEventListener('click', function () {
            toast(T().workshop_force || '');
        });
        var seriesCoverPick = document.getElementById('workshopSeriesCoverPick');
        if (seriesCoverPick) seriesCoverPick.addEventListener('click', function () {
            openCoverPicker({ kind: 'series' });
        });
        var coverModal = document.getElementById('workshopCoverModal');
        var coverClose = document.getElementById('workshopCoverClose');
        var coverSearch = document.getElementById('workshopCoverSearch');
        var coverQuery = document.getElementById('workshopCoverQuery');
        if (coverClose) coverClose.addEventListener('click', closeCoverPicker);
        if (coverSearch) coverSearch.addEventListener('click', runCoverSearch);
        if (coverQuery) coverQuery.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); runCoverSearch(); }
        });
        if (coverModal) coverModal.addEventListener('click', function (ev) {
            if (ev.target === coverModal) closeCoverPicker();
        });
        document.addEventListener('keydown', function (ev) {
            var coverOpen = document.getElementById('workshopCoverModal') &&
                document.getElementById('workshopCoverModal').style.display !== 'none';
            if (ev.key === 'Escape' && coverOpen) {
                ev.preventDefault();
                closeCoverPicker();
                return;
            }
            if (isTypingTarget(ev.target)) return;
            if (ev.key === '/' && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
                ev.preventDefault();
                var box = document.getElementById('workshopRailSearch');
                if (box) {
                    box.focus();
                    if (box.select) box.select();
                }
                return;
            }
            if (ev.key === 'ArrowLeft') { ev.preventDefault(); stepRail(-1); }
            if (ev.key === 'ArrowRight') { ev.preventDefault(); stepRail(1); }
        });
        document.getElementById('workshopSendSeries').addEventListener('click', function () {
            var seriesCard = document.getElementById('workshopSeriesCard');
            setSending(true);
            api('/api/series/' + seriesId + '/workshop/send-series', {
                method: 'POST',
                body: {
                    edits: seriesEdits(),
                    force: true,
                    cover_url: (seriesCard && seriesCard.getAttribute('data-cover-url')) || ''
                }
            }).then(function (data) {
                setSending(false);
                toastSend(data);
                if (data.success || data.partial) reload();
            }).catch(function () { setSending(false); });
        });
        document.getElementById('workshopSendSelection').addEventListener('click', function () {
            var items = selectedCards().map(itemFromCard);
            if (!items.length) { toast(T().vol_nothing_selected || ''); return; }
            setSending(true);
            api('/api/series/' + seriesId + '/workshop/send-selection', {
                method: 'POST',
                body: { items: items, force: true }
            }).then(function (data) {
                setSending(false);
                toastSend(data);
                markDoneClean(data.results);
                if (data.success || data.partial) reload();
            }).catch(function () { setSending(false); });
        });
        document.getElementById('workshopSendAll').addEventListener('click', function () {
            if (!window.confirm(T().workshop_send_all_confirm || '')) return;
            var items = Array.prototype.slice.call(document.querySelectorAll('.workshop-volume-card')).map(itemFromCard);
            setSending(true);
            api('/api/series/' + seriesId + '/workshop/send-selection', {
                method: 'POST',
                body: { items: items, force: true }
            }).then(function (data) {
                setSending(false);
                toastSend(data);
                markDoneClean(data.results);
                if (data.success || data.partial) reload();
            }).catch(function () { setSending(false); });
        });
        document.getElementById('workshopSelectAll').addEventListener('click', function () {
            document.querySelectorAll('.workshop-vol-check').forEach(function (c) { c.checked = true; });
            updateBarStats();
        });
        document.getElementById('workshopSelectNone').addEventListener('click', function () {
            document.querySelectorAll('.workshop-vol-check').forEach(function (c) { c.checked = false; });
            updateBarStats();
        });
        document.getElementById('workshopResetSeries').addEventListener('click', function () {
            if (!window.confirm(T().workshop_reset_confirm || '')) return;
            api('/api/series/' + seriesId + '/volume-enrich/reset', {
                method: 'POST',
                body: { workshop: true }
            }).then(function (data) {
                if (data.payload) applyPayload(data.payload, false);
                toast(T().workshop_event_reset || '');
            });
        });
        document.getElementById('workshopReviewSeries').addEventListener('click', function () {
            forceSync({ review: true });
        });
        document.getElementById('workshopSuperSeries').addEventListener('click', function () {
            forceSync({ super: true });
        });
        var cancel = document.getElementById('workshopCancelPass');
        if (cancel) cancel.addEventListener('click', function () {
            fetch(getRootPath() + '/api/volume-enrich/cancel', { method: 'POST', credentials: 'same-origin' });
        });
        var volBtn = document.getElementById('mrVolumeConfirmBtn');
        if (volBtn) volBtn.addEventListener('click', confirmVolumeReview);
        var origClose = window.closeManualReviewModal;
        window.closeManualReviewModal = function () {
            if (document.getElementById('manualReviewModal') &&
                document.getElementById('manualReviewModal').dataset.kind === 'volume') {
                closeVolumeModal();
                return;
            }
            if (typeof origClose === 'function') origClose();
        };
        if (window.socket) {
            window.socket.on('volume_enrich_progress', function (st) {
                var banner = document.getElementById('workshopPassBanner');
                var blocks = !!(st && st.running && String(st.series_id) === String(seriesId));
                if (banner) banner.hidden = !blocks;
                setSending(!!(st && st.running && blocks));
            });
        }
        window.addEventListener('beforeunload', function (ev) {
            if (!dirty) return;
            ev.preventDefault();
            ev.returnValue = '';
        });
        window.addEventListener('popstate', function (ev) {
            var sid = ev.state && ev.state.workshopSid;
            if (sid == null || sid === '') {
                if (!confirmLeave()) {
                    history.pushState({ workshopSid: seriesId }, '', workshopUrl(seriesId));
                    return;
                }
                seriesId = null;
                window.WORKSHOP_SERIES_ID = null;
                setIdle(true);
                markRailCurrent();
                updateRailCount();
                return;
            }
            if (String(sid) === String(seriesId)) return;
            if (!confirmLeave()) {
                history.pushState({ workshopSid: seriesId }, '', workshopUrl(seriesId));
                return;
            }
            loadSeries(sid, false);
        });
    }

    function boot() {
        if (boot.done) return;
        boot.done = true;
        restoreRailFilters();
        renderRail();
        if (seriesId) {
            rememberSid(seriesId);
            renderSeries();
            renderVolumes();
            renderHistory();
            scrollRailToCurrent();
            history.replaceState({ workshopSid: seriesId }, '', workshopUrl(seriesId));
        } else {
            setIdle(true);
            var pick = pickLandingSeries();
            if (pick) {
                loadSeries(pick, false);
            } else {
                history.replaceState({ workshopSid: null }, '', workshopUrl(null));
            }
        }
        wire();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
