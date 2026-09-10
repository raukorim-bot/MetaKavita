// --- MODAL DE CONFIGURATION GLOBALE ---
// Dépend de utils.js (getRootPath).

// --- AFFICHAGE CONDITIONNEL DU FOURNISSEUR DE TRADUCTION ---
function toggleTranslationFields() {
    const provider = document.getElementById('translationProvider');
    if (!provider) return;
    
    const deeplFields = document.getElementById('deepl_fields');
    const azureFields = document.getElementById('azure_fields');
    
    if (provider.value === 'DEEPL') {
        deeplFields.style.display = 'block';
        azureFields.style.display = 'none';
    } else if (provider.value === 'AZURE') {
        deeplFields.style.display = 'none';
        azureFields.style.display = 'block';
    } else {
        // Mode Google (Gratuit) OU Mode Désactivé (NONE) : On masque toutes les clés API !
        deeplFields.style.display = 'none';
        azureFields.style.display = 'none';
    }
}

function toggleLocalizedTitleLangs() {
    const mode = document.getElementById('localizedTitleMode');
    const group = document.getElementById('localizedTitleLangsGroup');
    if (!mode || !group) return;
    group.style.display = mode.value === 'prefer' ? 'block' : 'none';
}

function toggleAutoSyncCard() {
    const enabled = document.getElementById('config_auto_sync_enabled');
    const body = document.getElementById('autoSyncCardBody');
    const intervalRow = document.getElementById('autoSyncIntervalRow');
    const catchupRow = document.getElementById('autoSyncCatchupRow');
    const forceRow = document.getElementById('autoSyncForceUpdateRow');
    const modeSel = document.getElementById('config_auto_sync_mode');
    if (!enabled || !body) return;
    const on = !!enabled.checked;
    body.classList.toggle('is-disabled', !on);
    body.setAttribute('aria-disabled', on ? 'false' : 'true');
    const scan = document.querySelector('input[name="AUTO_SYNC_TRIGGER"][value="scan"]');
    const isScan = !!(scan && scan.checked);
    if (intervalRow) intervalRow.hidden = isScan;
    if (catchupRow) catchupRow.hidden = !isScan;
    const mode = modeSel ? modeSel.value : 'auto';
    if (forceRow) forceRow.hidden = mode !== 'auto';
    const intervalInput = document.getElementById('config_auto_sync_interval');
    if (intervalInput) {
        const minutesRequired = on && !isScan;
        intervalInput.min = minutesRequired ? '1' : '0';
        if (minutesRequired && Number(intervalInput.value) < 1) {
            intervalInput.value = intervalInput.getAttribute('data-default') || '360';
        }
    }
    refreshAutoSyncHubStatus();
}

var autoSyncHubTimer = null;

function refreshAutoSyncHubStatus() {
    const el = document.getElementById('autoSyncHubStatus');
    if (!el) return;
    const T = window.AppTranslations || {};
    const enabled = document.getElementById('config_auto_sync_enabled');
    const scan = document.querySelector('input[name="AUTO_SYNC_TRIGGER"][value="scan"]');
    const prefix = T.auto_sync_hub_status || 'Kavita hub:';
    if (!enabled || !enabled.checked || !scan || !scan.checked) {
        el.textContent = prefix + ' ' + (T.auto_sync_hub_idle || 'idle');
        return;
    }
    fetch(getRootPath() + '/api/auto-sync/status')
        .then(function (res) { return res.json(); })
        .then(function (data) {
            const st = (data && data.hub && data.hub.status) || 'disconnected';
            const labels = {
                disconnected: T.auto_sync_hub_disconnected,
                connecting: T.auto_sync_hub_connecting,
                connected: T.auto_sync_hub_connected,
                reconnecting: T.auto_sync_hub_reconnecting,
                error: T.auto_sync_hub_error,
                idle: T.auto_sync_hub_idle,
            };
            let line = prefix + ' ' + (labels[st] || st);
            if (data && data.hub && data.hub.last_error && st === 'error') {
                line += ' — ' + data.hub.last_error;
            }
            el.textContent = line;
        })
        .catch(function () { /* ignore */ });
}

function startAutoSyncHubPoll() {
    refreshAutoSyncHubStatus();
    if (autoSyncHubTimer) return;
    autoSyncHubTimer = setInterval(refreshAutoSyncHubStatus, 8000);
}

function stopAutoSyncHubPoll() {
    if (!autoSyncHubTimer) return;
    clearInterval(autoSyncHubTimer);
    autoSyncHubTimer = null;
}

function openConfigModal() {
    document.getElementById('configModal').style.display = 'flex';
    if (typeof toggleLocalizedTitleLangs === 'function') toggleLocalizedTitleLangs();
    if (typeof toggleAutoSyncCard === 'function') toggleAutoSyncCard();
    startAutoSyncHubPoll();
}

function closeConfigModal() {
    document.getElementById('configModal').style.display = 'none';
    stopAutoSyncHubPoll();
}

function openProvidersModal() {
    const modal = document.getElementById('providersModal');
    if (modal) modal.style.display = 'flex';
}

function closeProvidersModal() {
    const modal = document.getElementById('providersModal');
    if (modal) modal.style.display = 'none';
}

function openFieldMappingModal() {
    const modal = document.getElementById('fieldMappingModal');
    if (modal) modal.style.display = 'flex';
}

function closeFieldMappingModal() {
    const modal = document.getElementById('fieldMappingModal');
    if (modal) modal.style.display = 'none';
}

function switchLibraryTab(lib) {
    const modal = document.getElementById('fieldMappingModal');
    if (!modal) return;
    modal.querySelectorAll('.fm-tab').forEach(function (tab) {
        const on = tab.getAttribute('data-lib') === lib;
        tab.classList.toggle('is-active', on);
        tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    modal.querySelectorAll('.fm-panel').forEach(function (panel) {
        const on = panel.getAttribute('data-lib') === lib;
        panel.classList.toggle('is-active', on);
        panel.hidden = !on;
    });
}

function resetDiagInlinePill(selectName) {
    const pill = document.querySelector(`.diag-inline-pill[data-for="${selectName}"]`);
    if (!pill) return;
    pill.hidden = true;
    pill.dataset.status = '';
    pill.textContent = '—';
    pill.title = '';
}

function probeProviderFromModal(selectName, btn) {
    const select = document.querySelector(`#providersForm select[name="${selectName}"]`);
    const pill = document.querySelector(`.diag-inline-pill[data-for="${selectName}"]`);
    if (!select) return;
    const id = select.value;
    if (!id || id === 'NONE') {
        resetDiagInlinePill(selectName);
        return;
    }

    if (btn) btn.disabled = true;
    if (pill) {
        pill.hidden = false;
        pill.dataset.status = 'running';
        pill.textContent = '…';
        pill.title = '';
    }

    fetch(getRootPath() + '/api/scrapers/' + encodeURIComponent(id) + '/probe', {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: '{}',
    })
    .then(res => res.json().then(data => ({ ok: res.ok, data })))
    .then(({ ok, data }) => {
        const result = (data && data.result) || {};
        const status = ok ? (result.status || 'down') : 'down';
        if (pill) {
            // Si l'utilisateur a changé le provider pendant le fetch, ignorer le résultat
            if (select.value !== id) {
                resetDiagInlinePill(selectName);
                return;
            }
            pill.hidden = false;
            pill.dataset.status = status;
            const labels = { ok: 'OK', degraded: '!', down: '✕', skipped: '—', running: '…' };
            pill.textContent = labels[status] || status;
            const cause = result.cause || '';
            const meta = (result.metadata && result.metadata.status) || '';
            const covers = (result.covers && result.covers.status) || '';
            pill.title = [id, cause, 'meta=' + meta, 'covers=' + covers].filter(Boolean).join(' · ');
        }
    })
    .catch(() => {
        if (select.value !== id) {
            resetDiagInlinePill(selectName);
            return;
        }
        if (pill) {
            pill.hidden = false;
            pill.dataset.status = 'down';
            pill.textContent = '✕';
            pill.title = 'error';
        }
    })
    .finally(() => {
        if (btn) btn.disabled = false;
    });
}

document.addEventListener('click', function (e) {
    const btn = e.target.closest && e.target.closest('.btn-diag-probe');
    if (!btn) return;
    e.preventDefault();
    probeProviderFromModal(btn.getAttribute('data-provider-select'), btn);
});

function saveProvidersConfig() {
    const form = document.getElementById('providersForm');
    if (!form) return;
    const formData = new FormData(form);
    formData.append('PROVIDERS_SAVE', '1');

    const btn = form.querySelector('button[type="submit"]');
    const originalText = btn ? btn.innerText : '';
    if (btn) btn.innerText = '⏳...';

    fetch(getRootPath() + '/save-config', {
        method: 'POST',
        body: formData
    })
    .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
    })
    .then(data => {
        if (data.success) {
            if (btn) {
                btn.innerText = (window.AppTranslations && window.AppTranslations.action_ok) || '✅ OK';
                setTimeout(() => {
                    if (btn) btn.innerText = originalText;
                    closeProvidersModal();
                }, 700);
            } else {
                closeProvidersModal();
            }
        } else {
            if (btn) btn.innerText = originalText;
            alert((window.AppTranslations && window.AppTranslations.err_save_failed) || 'Erreur de sauvegarde');
        }
    })
    .catch(() => {
        if (btn) btn.innerText = originalText;
        alert((window.AppTranslations && window.AppTranslations.err_network) || 'Erreur réseau');
    });
}

// --- BAROMÈTRE DE FIABILITÉ (seuil de match) ---
let _matchThresholdSaveTimer = null;

function onMatchThresholdCustomChange() {
    const custom = document.getElementById('sidebar_match_threshold_custom');
    const slider = document.getElementById('sidebar_match_accept_threshold');
    const wrap = document.getElementById('match_threshold_slider_wrap');
    const label = document.getElementById('match_threshold_value');
    if (!custom) return;

    if (custom.checked) {
        if (slider) slider.disabled = false;
        if (wrap) wrap.classList.remove('is-hidden');
    } else {
        if (slider) {
            slider.value = '0.60';
            slider.disabled = true;
        }
        if (label) label.textContent = '0.60';
        if (wrap) wrap.classList.add('is-hidden');
    }
    saveConfig();
}

function onMatchThresholdInput(el) {
    const label = document.getElementById('match_threshold_value');
    if (label && el) {
        label.textContent = Number(el.value).toFixed(2);
    }
    clearTimeout(_matchThresholdSaveTimer);
    _matchThresholdSaveTimer = setTimeout(function () { saveConfig(); }, 300);
}

function syncManualReviewCoverSwitch() {
    const mr = document.getElementById('sidebar_manual_review_mode');
    const cover = document.getElementById('sidebar_manual_review_cover');
    const coverWrap = document.getElementById('sidebar_manual_review_cover_wrap');
    const superCb = document.getElementById('sidebar_manual_review_super');
    const superWrap = document.getElementById('sidebar_manual_review_super_wrap');
    const soundsCb = document.getElementById('sidebar_manual_review_sounds');
    const soundsWrap = document.getElementById('sidebar_manual_review_sounds_wrap');
    const on = !!(mr && mr.checked);

    if (cover) {
        cover.disabled = !on;
        if (coverWrap) coverWrap.classList.toggle('is-disabled-by-mr', !on);
    }
    if (superCb) {
        if (!on) {
            superCb.checked = false;
            superCb.disabled = true;
        } else {
            superCb.disabled = false;
        }
        if (superWrap) {
            superWrap.classList.toggle('is-disabled-by-mr', !on);
        }
    }
    if (soundsCb) {
        soundsCb.disabled = !on;
        if (!on) soundsCb.checked = false;
        if (soundsWrap) soundsWrap.classList.toggle('is-disabled-by-mr', !on);
    }
}

function syncEditBeforeConfirmCheckbox() {
    const mr = document.getElementById('sidebar_manual_review_mode');
    const edit = document.getElementById('sidebar_manual_review_edit');
    if (!edit) return;
    const useMr = !!(mr && mr.checked);
    const flag = useMr ? (edit.dataset.mrEdit || 'true') : (edit.dataset.confirmWrite || 'false');
    edit.checked = flag === 'true';
}

function onEditBeforeConfirmToggle() {
    const mr = document.getElementById('sidebar_manual_review_mode');
    const edit = document.getElementById('sidebar_manual_review_edit');
    if (!edit) return;
    const val = edit.checked ? 'true' : 'false';
    if (mr && mr.checked) {
        edit.dataset.mrEdit = val;
    } else {
        edit.dataset.confirmWrite = val;
    }
}

function appendEditBeforeConfirmFlags(formData) {
    const edit = document.getElementById('sidebar_manual_review_edit');
    if (!edit) return;
    // Garantit la synchro dataset ↔ checkbox avant envoi
    onEditBeforeConfirmToggle();
    formData.append('MANUAL_REVIEW_EDIT', (edit.dataset.mrEdit || 'true') === 'true' ? 'true' : 'false');
    formData.append('CONFIRM_BEFORE_WRITE', (edit.dataset.confirmWrite || 'false') === 'true' ? 'true' : 'false');
}

/* ===== Mode léger : les catégories que la barre latérale n'a pas à montrer =====
 *
 * Masquer une catégorie éteint sa fonctionnalité dans le même geste. Ce n'est
 * pas un raccourci : une fonctionnalité dont les réglages ne sont plus à l'écran
 * ne se commande plus, et deux des trois écrivent. Le serveur applique la même
 * règle (`config_manager.apply_light_mode`), celle-ci est la version visible —
 * l'interrupteur de la barre latérale se décoche sous les yeux de l'utilisateur,
 * plutôt que de le laisser découvrir au rechargement suivant que sa relecture
 * manuelle s'est arrêtée.
 *
 * Réafficher ne rallume rien : la catégorie revient, éteinte, et c'est à
 * l'utilisateur de décider.
 */
function setUiSectionHidden(section, hidden) {
    if (!document.body) return;
    const raw = document.body.getAttribute('data-ui-hidden') || '';
    const tokens = raw.split(/\s+/).filter(function (tok) { return tok && tok !== section; });
    if (hidden) tokens.push(section);
    document.body.setAttribute('data-ui-hidden', tokens.join(' '));
}

function turnUiSectionFeatureOff(section) {
    if (section === 'manual') {
        const mr = document.getElementById('sidebar_manual_review_mode');
        if (mr) mr.checked = false;
        // Les mêmes synchros que la case de la barre latérale : sans elles, les
        // réglages dépendants resteraient cochés et actifs à l'écran.
        if (typeof syncEditBeforeConfirmCheckbox === 'function') syncEditBeforeConfirmCheckbox();
        if (typeof syncManualReviewCoverSwitch === 'function') syncManualReviewCoverSwitch();
        return;
    }
    if (section === 'inventory') {
        const inv = document.getElementById('sidebar_library_inventory');
        if (inv) inv.checked = false;
        if (document.body) document.body.setAttribute('data-inventory', '0');
        return;
    }
    if (section === 'volumes') {
        const vol = document.getElementById('sidebar_volume_enrichment');
        if (vol) vol.checked = false;
        if (document.body) document.body.setAttribute('data-volumes', '0');
        return;
    }
    if (section === 'mapping') {
        const map = document.getElementById('sidebar_field_mapping');
        if (map) map.checked = false;
    }
}

function onUiSectionToggle(input, section) {
    const show = !!(input && input.checked);
    setUiSectionHidden(section, !show);
    if (!show) turnUiSectionFeatureOff(section);
    // Un seul enregistrement pour les deux effets : `saveConfig()` sérialise les
    // interrupteurs de la barre latérale depuis le DOM, qui vient d'être mis à
    // jour. Sans rechargement, comme toutes les bascules.
    saveConfig();
}

// --- SAUVEGARDE CONFIGURATION (AJAX HYBRIDE) ---
// options.notify : toast + retour visuel du bouton Sauvegarder, sans
// recharger. options.reload : uniquement le changement de langue UI
// (libellés rendus côté serveur). Les toggles sidebar ne passent ni l'un
// ni l'autre — un champ clé API encore vide ne doit pas partir, et
// l'autofill ne doit pas corrompre une sauvegarde partielle.
function saveConfig(options) {
    options = options || {};
    const shouldReload = !!options.reload;
    const notify = !!options.notify || shouldReload;
    const form = document.getElementById('configForm');
    if (!form) return;
    const formData = new FormData(form);

    // Force les champs Kavita depuis .value (certains navigateurs omettent les
    // champs type=password / autofill dans FormData(form) — setup frais cassé).
    const kavitaUrlInput = form.querySelector('[name="KAVITA_URL"]');
    const kavitaExtInput = form.querySelector('[name="KAVITA_EXTERNAL_URL"]');
    const kavitaKeyInput = document.getElementById('kavita_api_key');
    if (kavitaUrlInput) formData.set('KAVITA_URL', (kavitaUrlInput.value || '').trim());
    if (kavitaExtInput) formData.set('KAVITA_EXTERNAL_URL', (kavitaExtInput.value || '').trim());
    if (kavitaKeyInput) formData.set('KAVITA_API_KEY', (kavitaKeyInput.value || '').trim());
    const typedKavitaKey = kavitaKeyInput ? (kavitaKeyInput.value || '').trim() : '';
    
    const smartScoring = document.getElementById('sidebar_smart_scoring');
    const smartCompletion = document.getElementById('sidebar_smart_completion');
    const manualReviewMode = document.getElementById('sidebar_manual_review_mode');
    const manualReviewSounds = document.getElementById('sidebar_manual_review_sounds');
    const autoCover = document.getElementById('sidebar_auto_cover');
    const resetContext = document.getElementById('sidebar_reset_context');
    const matchThresholdCustom = document.getElementById('sidebar_match_threshold_custom');
    const matchAcceptThreshold = document.getElementById('sidebar_match_accept_threshold');
    if (resetContext) formData.append('RESET_CONTEXT_ON_FORCE', resetContext.checked ? 'true' : 'false');
    if (smartScoring) formData.append('SMART_SCORING', smartScoring.checked ? 'true' : 'false');
    if (smartCompletion) formData.append('SMART_COMPLETION', smartCompletion.checked ? 'true' : 'false');
    if (manualReviewMode) formData.append('MANUAL_REVIEW_MODE', manualReviewMode.checked ? 'true' : 'false');
    appendEditBeforeConfirmFlags(formData);
    if (manualReviewSounds) {
        const mrOn = !!(manualReviewMode && manualReviewMode.checked);
        formData.append('MANUAL_REVIEW_SOUNDS', (mrOn && manualReviewSounds.checked) ? 'true' : 'false');
    }
    const manualReviewSuper = document.getElementById('sidebar_manual_review_super');
    if (manualReviewSuper) {
        const mrOn = !!(manualReviewMode && manualReviewMode.checked);
        formData.append('MANUAL_REVIEW_SUPER', (mrOn && manualReviewSuper.checked) ? 'true' : 'false');
    }
    const manualReviewCover = document.getElementById('sidebar_manual_review_cover');
    if (manualReviewCover) {
        const mrOn = !!(manualReviewMode && manualReviewMode.checked);
        formData.append('MANUAL_REVIEW_COVER_PICK', (mrOn && manualReviewCover.checked) ? 'true' : 'false');
    }
    if (matchThresholdCustom) formData.append('MATCH_THRESHOLD_CUSTOM', matchThresholdCustom.checked ? 'true' : 'false');
    if (matchAcceptThreshold) formData.append('MATCH_ACCEPT_THRESHOLD', matchAcceptThreshold.value);
    if (autoCover) formData.append('AUTO_COVER', autoCover.checked ? 'true' : 'false');
    const coverForceOverwrite = document.getElementById('sidebar_cover_force_overwrite');
    if (coverForceOverwrite) formData.append('COVER_FORCE_OVERWRITE', coverForceOverwrite.checked ? 'true' : 'false');
    const inventoryEnabled = document.getElementById('sidebar_library_inventory');
    if (inventoryEnabled) formData.append('LIBRARY_INVENTORY_ENABLED', inventoryEnabled.checked ? 'true' : 'false');
    const fieldMappingEnabled = document.getElementById('sidebar_field_mapping');
    if (fieldMappingEnabled) formData.append('FIELD_MAPPING_ENABLED', fieldMappingEnabled.checked ? 'true' : 'false');
    const folderPrefix = document.getElementById('dupFolderPathPrefix');
    if (folderPrefix) formData.append('INVENTORY_FOLDER_PATH_PREFIX', folderPrefix.value || '');
    const folderTrash = document.getElementById('dupFolderTrash');
    if (folderTrash) formData.append('INVENTORY_FOLDER_TRASH', folderTrash.value || '');
    // Enrichissement par tome : les deux derniers n'existent dans le DOM que si
    // le premier est allumé, d'où le test d'existence sur chacun.
    [
        ['sidebar_volume_enrichment', 'VOLUME_ENRICHMENT_ENABLED'],
        ['sidebar_volume_force_overwrite', 'VOLUME_FORCE_OVERWRITE'],
        ['sidebar_volume_enrich_credits', 'VOLUME_ENRICH_CREDITS'],
        ['sidebar_volume_enrich_experimental', 'VOLUME_ENRICH_EXPERIMENTAL'],
        ['sidebar_volume_no_manga_fallback', 'VOLUME_NO_MANGA_FALLBACK'],
    ].forEach(function (pair) {
        const el = document.getElementById(pair[0]);
        if (el) formData.append(pair[1], el.checked ? 'true' : 'false');
    });
    // Une liste, pas un interrupteur : c'est sa valeur qui part, et « AUTO »
    // signifie « laisser la cascade décider ».
    const volumeProvider = document.getElementById('sidebar_volume_provider');
    if (volumeProvider) formData.append('VOLUME_PROVIDER', volumeProvider.value || 'AUTO');

    const titleFallback = document.getElementById('config_title_fallback');
    if (titleFallback) formData.append('TITLE_FALLBACK_TRANSLATION', titleFallback.checked ? 'true' : 'false');

    const playfulStats = document.getElementById('config_playful_stats');
    if (playfulStats) formData.append('ENABLE_PLAYFUL_STATS', playfulStats.checked ? 'true' : 'false');

    const autoUpdateCore = document.getElementById('config_auto_update_core_scrapers');
    if (autoUpdateCore) formData.append('AUTO_UPDATE_CORE_SCRAPERS', autoUpdateCore.checked ? 'true' : 'false');

    const autoSyncEnabled = document.getElementById('config_auto_sync_enabled');
    if (autoSyncEnabled) formData.append('AUTO_SYNC_ENABLED', autoSyncEnabled.checked ? 'true' : 'false');
    const autoSyncForce = document.getElementById('config_auto_sync_force_update');
    if (autoSyncForce) formData.append('AUTO_SYNC_FORCE_UPDATE', autoSyncForce.checked ? 'true' : 'false');

    // Mode léger : envoyé à chaque enregistrement, y compris depuis une bascule
    // de la barre latérale, pour que les trois cases ne dépendent pas de la
    // soumission de la modale.
    [
        ['config_ui_show_manual_review', 'UI_SHOW_MANUAL_REVIEW'],
        ['config_ui_show_inventory', 'UI_SHOW_INVENTORY'],
        ['config_ui_show_volumes', 'UI_SHOW_VOLUMES'],
        ['config_ui_show_field_mapping', 'UI_SHOW_FIELD_MAPPING'],
    ].forEach(function (pair) {
        const el = document.getElementById(pair[0]);
        if (el) formData.append(pair[1], el.checked ? 'true' : 'false');
    });

    const btn = notify ? form.querySelector('.btn-primary') : null;
    const originalText = btn ? btn.innerText : "";
    if (btn) btn.innerText = "⏳...";

    fetch(getRootPath() + '/save-config', {
        method: 'POST',
        body: formData
    })
    .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
    })
    .then(data => {
        if (data.success) {
            if (folderPrefix) {
                window.INVENTORY_FOLDER_PATH_PREFIX = (folderPrefix.value || '').trim();
            }
            if (folderTrash) {
                window.INVENTORY_FOLDER_TRASH = (folderTrash.value || '').trim();
            }
            if (typeof updateInventoryFolderPreview === 'function') {
                updateInventoryFolderPreview();
            }
            if (notify) {
                if (typedKavitaKey && !data.has_kavita_api_key) {
                    alert((window.AppTranslations && window.AppTranslations.config_key_not_saved) ||
                        "La clé API Kavita n'a pas été enregistrée sur le serveur. Vérifiez les logs.");
                    if (btn) btn.innerText = originalText;
                    return;
                }
                if (data.kavita_ok === false && data.kavita_error && data.kavita_error !== 'missing') {
                    const errMap = {
                        localhost: (window.AppTranslations && window.AppTranslations.err_kavita_localhost),
                        http_401: (window.AppTranslations && window.AppTranslations.err_kavita_unauthorized),
                        timeout: (window.AppTranslations && window.AppTranslations.err_kavita_timeout),
                        dns: (window.AppTranslations && window.AppTranslations.err_kavita_dns),
                        connection: (window.AppTranslations && window.AppTranslations.err_kavita_connection),
                        ssl: (window.AppTranslations && window.AppTranslations.err_kavita_ssl),
                    };
                    const msg = errMap[data.kavita_error] ||
                        ((window.AppTranslations && window.AppTranslations.err_kavita) || "Connexion à Kavita échouée.");
                    const urlPrefix = (window.AppTranslations && window.AppTranslations.url_saved_prefix) || "URL enregistrée :";
                    alert(msg + "\n\n" + urlPrefix + " " + (data.kavita_url || "(vide)"));
                }
            }
            if (btn) {
                btn.innerText = "✅ OK";
                setTimeout(() => { btn.innerText = originalText; }, 2000);
            }
            if (notify) {
                if (shouldReload) {
                    try { sessionStorage.setItem('mk_config_saved', '1'); } catch (e) { /* ignore */ }
                    window.location.reload();
                    return;
                }
                var savedMsg = (window.AppTranslations && window.AppTranslations.config_saved)
                    || 'Settings saved.';
                if (typeof showAppToast === 'function') showAppToast(savedMsg);
            }
        } else {
            if (btn) btn.innerText = originalText;
            alert((data && data.msg) || ((window.AppTranslations && window.AppTranslations.err_save_failed) || "Erreur de sauvegarde"));
        }
    })
    .catch(() => {
        if (btn) btn.innerText = originalText;
        alert((window.AppTranslations && window.AppTranslations.err_network) || "Erreur réseau");
    });
}

// --- GESTION DES MENUS PROVIDERS ---
function handleProviderChange(changedSelect) {
    const name = changedSelect.name;
    let prefix = "";
    if (name.startsWith("COMIC_")) {
        prefix = "COMIC_";
    } else if (name.startsWith("BOOK_")) {
        prefix = "BOOK_";
    }
    
    const selects = [
        document.querySelector(`select[name="${prefix}PROVIDER_1"]`),
        document.querySelector(`select[name="${prefix}PROVIDER_2"]`),
        document.querySelector(`select[name="${prefix}PROVIDER_3"]`)
    ];
    
    const newValue = changedSelect.value;
    // Le résultat de test ne concerne que l'ancien provider : on invalide la pastille.
    resetDiagInlinePill(name);

    if (newValue !== 'NONE') {
        selects.forEach(otherSelect => {
            if (otherSelect && otherSelect !== changedSelect && otherSelect.value === newValue) {
                otherSelect.value = 'NONE';
                resetDiagInlinePill(otherSelect.name);
            }
        });
    }

    const p1 = selects[0];
    if (p1 && (!p1.value || p1.value === 'NONE')) {
        const allProviders = Array.from(p1.options).map(opt => opt.value).filter(val => val !== 'NONE');
        const usedByOthers = [selects[1] ? selects[1].value : 'NONE', selects[2] ? selects[2].value : 'NONE'];
        const freeProvider = allProviders.find(p => !usedByOthers.includes(p));
        const next = freeProvider || allProviders[0];
        if (p1.value !== next) {
            p1.value = next;
            resetDiagInlinePill(p1.name);
        }
    }

    saveConfig();
}

// --- REGÉNÉRATION DU JETON WEBHOOK (AJAX) ---
function regenerateWebhookToken(btn) {
    if (!confirm(window.AppTranslations.regen_webhook_confirm || "Régénérer le jeton Webhook ?")) {
        return;
    }
    
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    btn.disabled = true;

    fetch(getRootPath() + '/regenerate-webhook-token', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        btn.disabled = false;
        if (data.success) {
            // URL stays /webhook (no ?token=); only the separate token field changes.
            const tokenInput = document.getElementById('webhookTokenInput');
            if (tokenInput) {
                tokenInput.value = data.new_token;
            }
            btn.innerText = "✅ OK";
            setTimeout(() => { btn.innerText = originalText; }, 2000);
        } else {
            btn.innerText = originalText;
        }
    })
    .catch(() => {
        btn.disabled = false;
        btn.innerText = originalText;
    });
}

// --- CHANGEMENT DE MOT DE PASSE (écran Config) ---
// Requêtes indépendantes de #configForm : ces champs n'ont pas de `name`, donc
// saveConfig() (FormData sur tout le formulaire) ne les touche jamais.
function changeAccountPassword(btn) {
    const feedback = document.getElementById('accountPasswordFeedback');
    const currentInput = document.getElementById('account_current_password');
    const newInput = document.getElementById('account_new_password');
    const confirmInput = document.getElementById('account_new_password_confirm');
    if (!feedback || !currentInput || !newInput || !confirmInput) return;

    const current = currentInput.value;
    const newPwd = newInput.value;
    const confirm = confirmInput.value;

    const showFeedback = (text, ok) => {
        feedback.textContent = text;
        feedback.className = 'field-hint m-0' + (ok ? ' field-hint--ok' : ' field-hint--error');
    };

    if (!current || !newPwd || !confirm) {
        showFeedback(window.AppTranslations.account_fill_all || 'Remplissez les trois champs.', false);
        return;
    }
    if (newPwd !== confirm) {
        showFeedback(window.AppTranslations.account_err_mismatch || 'Les mots de passe ne correspondent pas.', false);
        return;
    }

    const originalText = btn.innerText;
    btn.innerText = '⏳...';
    btn.disabled = true;

    fetch(getRootPath() + '/account/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            current_password: current,
            new_password: newPwd,
            new_password_confirm: confirm,
        }),
    })
    .then(res => res.json())
    .then(data => {
        btn.innerText = originalText;
        btn.disabled = false;
        showFeedback(data.success ? data.message : data.error, !!data.success);
        if (data.success) {
            currentInput.value = '';
            newInput.value = '';
            confirmInput.value = '';
        }
    })
    .catch(() => {
        btn.innerText = originalText;
        btn.disabled = false;
        showFeedback((window.AppTranslations && window.AppTranslations.err_network_dot) || 'Erreur réseau.', false);
    });
}

function dismissCoreScraperBanner() {
    const banner = document.getElementById('coreScrapersUpdateBanner');
    if (banner) banner.hidden = true;
    try { sessionStorage.setItem('mk_dismiss_core_scraper_banner', '1'); } catch (e) { /* ignore */ }
}

function applyCoreScraperUpdates(btn) {
    const t = window.AppTranslations || {};
    const el = btn || document.getElementById('coreScrapersUpdateBtn');
    const original = el ? el.innerText : '';
    if (el) {
        el.disabled = true;
        el.innerText = '⏳...';
    }
    fetch(getRootPath() + '/api/scrapers/core-updates/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
    })
        .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
        .then(function (result) {
            if (!result.ok || !result.data.success) {
                throw new Error((result.data && result.data.msg) || t.core_scrapers_updated_fail || 'Update failed');
            }
            showFeedback(result.data.msg || t.core_scrapers_updated_ok || 'OK', true);
            const banner = document.getElementById('coreScrapersUpdateBanner');
            if (banner) banner.hidden = true;
            try { sessionStorage.removeItem('mk_dismiss_core_scraper_banner'); } catch (e) { /* ignore */ }
        })
        .catch(function (err) {
            showFeedback(err.message || t.core_scrapers_updated_fail || 'Update failed', false);
            if (el) {
                el.disabled = false;
                el.innerText = original;
            }
        });
}

(function hideDismissedCoreBanner() {
    try {
        if (sessionStorage.getItem('mk_dismiss_core_scraper_banner') === '1') {
            const banner = document.getElementById('coreScrapersUpdateBanner');
            if (banner) banner.hidden = true;
        }
    } catch (e) { /* ignore */ }
})();

document.addEventListener('DOMContentLoaded', function () {
    try {
        if (sessionStorage.getItem('mk_config_saved') !== '1') return;
        sessionStorage.removeItem('mk_config_saved');
    } catch (e) {
        return;
    }
    var msg = (window.AppTranslations && window.AppTranslations.config_saved)
        || 'Settings saved.';
    if (typeof showAppToast === 'function') showAppToast(msg);
});
