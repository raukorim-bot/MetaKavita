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

function openConfigModal() {
    document.getElementById('configModal').style.display = 'flex';
    if (typeof toggleLocalizedTitleLangs === 'function') toggleLocalizedTitleLangs();
}

function closeConfigModal() {
    document.getElementById('configModal').style.display = 'none';
}

function openProvidersModal() {
    const modal = document.getElementById('providersModal');
    if (modal) modal.style.display = 'flex';
}

function closeProvidersModal() {
    const modal = document.getElementById('providersModal');
    if (modal) modal.style.display = 'none';
}

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
                btn.innerText = '✅ OK';
                setTimeout(() => {
                    if (btn) btn.innerText = originalText;
                    closeProvidersModal();
                }, 700);
            } else {
                closeProvidersModal();
            }
        } else {
            if (btn) btn.innerText = originalText;
            alert('Erreur de sauvegarde');
        }
    })
    .catch(() => {
        if (btn) btn.innerText = originalText;
        alert('Erreur réseau');
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

// --- SAUVEGARDE CONFIGURATION (AJAX HYBRIDE) ---
// options.reload : true uniquement pour la sauvegarde modale / changement de
// langue — les toggles sidebar ne doivent PAS recharger (sinon un champ clé
// API encore vide efface le travail utilisateur, et l'autofill peut corrompre).
function saveConfig(options) {
    options = options || {};
    const shouldReload = !!options.reload;
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
    const autoReadingDir = document.getElementById('sidebar_auto_reading_dir');
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
    if (autoReadingDir) formData.append('AUTO_READING_DIR', autoReadingDir.checked ? 'true' : 'false');
    
    const titleFallback = document.getElementById('config_title_fallback');
    if (titleFallback) formData.append('TITLE_FALLBACK_TRANSLATION', titleFallback.checked ? 'true' : 'false');

    const playfulStats = document.getElementById('config_playful_stats');
    if (playfulStats) formData.append('ENABLE_PLAYFUL_STATS', playfulStats.checked ? 'true' : 'false');

    const btn = shouldReload ? form.querySelector('.btn-primary') : null;
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
            if (btn) {
                btn.innerText = "✅ OK";
                setTimeout(() => { btn.innerText = originalText; }, 2000);
            }
            if (shouldReload) {
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
                    alert(msg + "\n\nURL enregistrée : " + (data.kavita_url || "(vide)"));
                }
                window.location.reload();
            }
        } else {
            if (btn) btn.innerText = originalText;
            alert((data && data.msg) || "Erreur de sauvegarde");
        }
    })
    .catch(() => {
        if (btn) btn.innerText = originalText;
        alert("Erreur réseau");
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

    if (newValue !== 'NONE') {
        selects.forEach(otherSelect => {
            if (otherSelect && otherSelect !== changedSelect && otherSelect.value === newValue) {
                otherSelect.value = 'NONE';
            }
        });
    }

    const p1 = selects[0];
    if (p1 && (!p1.value || p1.value === 'NONE')) {
        const allProviders = Array.from(p1.options).map(opt => opt.value).filter(val => val !== 'NONE');
        const usedByOthers = [selects[1] ? selects[1].value : 'NONE', selects[2] ? selects[2].value : 'NONE'];
        const freeProvider = allProviders.find(p => !usedByOthers.includes(p));
        p1.value = freeProvider || allProviders[0];
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
        showFeedback('Erreur réseau.', false);
    });
}
