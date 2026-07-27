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
    if (slider && custom) {
        slider.disabled = !custom.checked;
    }
    if (wrap && custom) {
        wrap.style.opacity = custom.checked ? '1' : '0.45';
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

// --- SAUVEGARDE CONFIGURATION (AJAX HYBRIDE) ---
function saveConfig() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    
    const smartScoring = document.getElementById('sidebar_smart_scoring');
    const smartCompletion = document.getElementById('sidebar_smart_completion');
    const autoCover = document.getElementById('sidebar_auto_cover');
    const autoReadingDir = document.getElementById('sidebar_auto_reading_dir');
    const resetContext = document.getElementById('sidebar_reset_context');
    const matchThresholdCustom = document.getElementById('sidebar_match_threshold_custom');
    const matchAcceptThreshold = document.getElementById('sidebar_match_accept_threshold');
    if (resetContext) formData.append('RESET_CONTEXT_ON_FORCE', resetContext.checked ? 'true' : 'false');
    if (smartScoring) formData.append('SMART_SCORING', smartScoring.checked ? 'true' : 'false');
    if (smartCompletion) formData.append('SMART_COMPLETION', smartCompletion.checked ? 'true' : 'false');
    if (matchThresholdCustom) formData.append('MATCH_THRESHOLD_CUSTOM', matchThresholdCustom.checked ? 'true' : 'false');
    if (matchAcceptThreshold) formData.append('MATCH_ACCEPT_THRESHOLD', matchAcceptThreshold.value);
    if (autoCover) formData.append('AUTO_COVER', autoCover.checked ? 'true' : 'false');
    if (autoReadingDir) formData.append('AUTO_READING_DIR', autoReadingDir.checked ? 'true' : 'false');
    
    const titleFallback = document.getElementById('config_title_fallback');
    if (titleFallback) formData.append('TITLE_FALLBACK_TRANSLATION', titleFallback.checked ? 'true' : 'false');

    const playfulStats = document.getElementById('config_playful_stats');
    if (playfulStats) formData.append('ENABLE_PLAYFUL_STATS', playfulStats.checked ? 'true' : 'false');

    const btn = form.querySelector('.btn-primary');
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
            
            const currentLang = document.documentElement.lang;
            const newLang = formData.get('UI_LANG');
            if (newLang && currentLang !== newLang) {
                window.location.reload();
            }
        } else {
            if (btn) btn.innerText = originalText;
            alert("Erreur de sauvegarde");
        }
    })
    .catch(() => {
        if (btn) btn.innerText = originalText;
        alert("Erreur réseau");
    });
}

/** Sauvegarde puis recharge pour appliquer le filtre de bibliothèques (toolbar / liste). */
function saveConfigAndReloadLibraries() {
    const form = document.getElementById('configForm');
    if (!form) return;
    const formData = new FormData(form);

    const smartScoring = document.getElementById('sidebar_smart_scoring');
    const smartCompletion = document.getElementById('sidebar_smart_completion');
    const autoCover = document.getElementById('sidebar_auto_cover');
    const autoReadingDir = document.getElementById('sidebar_auto_reading_dir');
    const resetContext = document.getElementById('sidebar_reset_context');
    const matchThresholdCustom = document.getElementById('sidebar_match_threshold_custom');
    const matchAcceptThreshold = document.getElementById('sidebar_match_accept_threshold');
    if (resetContext) formData.append('RESET_CONTEXT_ON_FORCE', resetContext.checked ? 'true' : 'false');
    if (smartScoring) formData.append('SMART_SCORING', smartScoring.checked ? 'true' : 'false');
    if (smartCompletion) formData.append('SMART_COMPLETION', smartCompletion.checked ? 'true' : 'false');
    if (matchThresholdCustom) formData.append('MATCH_THRESHOLD_CUSTOM', matchThresholdCustom.checked ? 'true' : 'false');
    if (matchAcceptThreshold) formData.append('MATCH_ACCEPT_THRESHOLD', matchAcceptThreshold.value);
    if (autoCover) formData.append('AUTO_COVER', autoCover.checked ? 'true' : 'false');
    if (autoReadingDir) formData.append('AUTO_READING_DIR', autoReadingDir.checked ? 'true' : 'false');

    const titleFallback = document.getElementById('config_title_fallback');
    if (titleFallback) formData.append('TITLE_FALLBACK_TRANSLATION', titleFallback.checked ? 'true' : 'false');
    const playfulStats = document.getElementById('config_playful_stats');
    if (playfulStats) formData.append('ENABLE_PLAYFUL_STATS', playfulStats.checked ? 'true' : 'false');

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
            window.location.reload();
        } else {
            alert("Erreur de sauvegarde");
        }
    })
    .catch(() => alert("Erreur réseau"));
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
            const webhookInput = document.getElementById('webhookUrlInput');
            if (webhookInput) {
                webhookInput.value = `${getRootPath()}/webhook?token=${data.new_token}`;
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
