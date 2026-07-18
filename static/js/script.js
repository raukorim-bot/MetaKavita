// --- GESTION DU THÈME ---
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// --- GESTION DE L'INTERFACE ---
function togglePanel(id) {
    var panel = document.getElementById(id);
    panel.style.display = (panel.style.display === 'block') ? 'none' : 'block';
}

function toggleConfig() {
    const configSection = document.getElementById('configSection');
    const isHidden = configSection.style.display === 'none';
    configSection.style.display = isHidden ? 'block' : 'none';
    localStorage.setItem('configHidden', !isHidden);
}

document.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('configHidden') === 'true') {
        const configSection = document.getElementById('configSection');
        if(configSection) configSection.style.display = 'none';
    }
    // Appel forcé pour mettre à jour le compteur dès le chargement !
    filterSeries();
});

// --- ACTIONS SUR LES SÉRIES ---
function saveOverride(seriesId, btn) {
    const forcedId = document.getElementById('id-' + seriesId).value;
    const altTitle = document.getElementById('title-' + seriesId).value;
    btn.innerText = "⏳...";
    
    fetch('/save-override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${seriesId}&forced_id=${forcedId}&alternative_title=${encodeURIComponent(altTitle)}`
    }).then(r => {
        if(r.ok) {
            btn.innerText = "✅"; 
            setTimeout(() => { btn.innerText = window.AppTranslations.save; }, 1500);
        }
    });
}

async function saveAllOverrides() {
    const panels = document.querySelectorAll('.override-panel');
    for (let panel of panels) {
        if (panel.style.display === 'block') {
            panel.querySelector('button.btn-success').click();
            await new Promise(r => setTimeout(r, 200));
        }
    }
}

function filterSeries() {
    const filter = document.getElementById('statusFilter').value;
    
    // On vérifie si la case (si elle existe sur la page) est cochée
    const hideIgnoredCb = document.getElementById('hideIgnoredCb');
    const hideIgnored = hideIgnoredCb ? hideIgnoredCb.checked : false;
    
    let count = 0;
    
    document.querySelectorAll('.series-item').forEach(item => {
        const status = item.dataset.status;
        let show = false;
        
        if (filter === 'ALL') {
            show = true;
            // Si la case est cochée et que c'est ignoré, on le cache quand même
            if (hideIgnored && status === 'IGNORED') {
                show = false;
            }
        } else if (status === filter) {
            // Si l'utilisateur demande explicitement "IGNORED" dans le menu, ça passe ici !
            show = true;
        }
        
        if (show) {
            item.style.display = 'flex';
            count++;
        } else {
            item.style.display = 'none';
            const cb = item.querySelector('.series-cb');
            if(cb) cb.checked = false; // On décoche les cachés pour la sécurité du batch
        }
    });
    
    document.getElementById('selectAll').checked = false;
    
    const countElem = document.getElementById('visibleCount');
    if(countElem) {
        countElem.innerText = count + (count > 1 ? window.AppTranslations.elements : window.AppTranslations.element);
    }
}

function toggleSelectAll() {
    const isChecked = document.getElementById('selectAll').checked;
    document.querySelectorAll('.series-item').forEach(item => {
        if (item.style.display !== 'none') {
            const cb = item.querySelector('.series-cb');
            if(cb) cb.checked = isChecked;
        }
    });
}

// --- SYNCHRONISATION ---
function syncSingle(id, name, btn) {
    const forcedIdInput = document.getElementById('id-' + id);
    const altTitleInput = document.getElementById('title-' + id);
    
    if(forcedIdInput && altTitleInput) {
        const forcedId = forcedIdInput.value;
        const altTitle = altTitleInput.value;
        
        btn.style.display = 'none';
        btn.previousElementSibling.style.display = 'none'; 
        let loading = btn.nextElementSibling;
        loading.style.display = 'inline-block';
        
        fetch('/save-override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `series_id=${id}&forced_id=${forcedId}&alternative_title=${encodeURIComponent(altTitle)}`
        }).then(() => proceedSyncSingle(id, name, btn, loading));
    } else {
        proceedSyncSingle(id, name, btn, null);
    }
}

function proceedSyncSingle(id, name, btn, loadingElem) {
    let loading = loadingElem;
    if(!loading) {
        btn.style.display = 'none';
        btn.previousElementSibling.style.display = 'none'; 
        loading = btn.nextElementSibling;
        loading.style.display = 'inline-block';
    }

    fetch('/force-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${id}&series_name=${encodeURIComponent(name)}`
    })
    .then(res => res.json())
    .then(data => {
        loading.style.display = 'none';
        btn.style.display = 'inline-block';
        btn.previousElementSibling.style.display = 'inline-block';
        if(data.success) {
            btn.innerText = "✅ OK";
        } else {
            btn.innerText = "❌ Fail";
        }
        setTimeout(() => { btn.innerText = window.AppTranslations.update; }, 3000);
    });
}

async function launchBatch(event) {
    event.preventDefault();
    const form = event.target;
    const btn = document.getElementById('mainBatchBtn');
    const checkboxes = form.querySelectorAll('.series-cb:checked');
    const ids = Array.from(checkboxes).map(cb => cb.value);
    
    if (ids.length === 0) {
        btn.innerText = window.AppTranslations.batch_empty;
        setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 2000);
        return;
    }

    btn.innerText = window.AppTranslations.batch_sending;
    
    for (let i = 0; i < ids.length; i += 50) {
        const batch = ids.slice(i, i + 50);
        const formData = new FormData();
        
        const libInput = form.querySelector('[name="library_id"]');
        if(libInput) formData.append('library_id', libInput.value);
        
        const forceUpdateCb = form.querySelector('[name="force_update"]');
        if (forceUpdateCb && forceUpdateCb.checked) {
            formData.append('force_update', 'true');
        }
        
        batch.forEach(id => formData.append('selected_series', id));
        await fetch('/batch-sync', { method: 'POST', body: formData });
    }

    btn.innerText = window.AppTranslations.batch_ok;
    setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 4000);
}

function stopBatch() {
    fetch('/stop-batch', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        const btn = document.getElementById('mainBatchBtn');
        if (btn) btn.innerText = window.AppTranslations.launchBatch;
    });
}

// --- WEBSOCKETS LOGS ---
var socket = io();
var logConsole = document.getElementById('log-console');
socket.on('connect', function() { 
    logConsole.innerHTML += '<div class="log-line" style="color: var(--primary);">' + window.AppTranslations.terminal_ready + '</div>'; 
});
socket.on('log_update', function(msg) {
    var newLog = document.createElement('div');
    newLog.className = 'log-line';
    newLog.textContent = msg.data;
    if (msg.data.includes('ERROR') || msg.data.includes('❌') || msg.data.includes('💥')) {
        newLog.className += ' log-error';
    } else if (msg.data.includes('WARNING') || msg.data.includes('⚠️')) {
        newLog.className += ' log-warning';
    }
    logConsole.appendChild(newLog);
    logConsole.scrollTop = logConsole.scrollHeight;
});

// --- GESTION DE L'AFFICHAGE DES CLÉS API ---
function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (input.type === 'password') {
        input.type = 'text';
        btn.innerText = '🙈'; // Symbole masqué
    } else {
        input.type = 'password';
        btn.innerText = '👁️';  // Symbole visible
    }
}
// --- SAUVEGARDE DE LA CONFIGURATION (AJAX) ---
function saveConfig() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    const btn = form.querySelector('.btn-primary');
    const originalText = btn.innerText;
    btn.innerText = "⏳...";

    fetch('/save-config', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            btn.innerText = "✅ OK";
            setTimeout(() => { btn.innerText = originalText; }, 2000);
            
            // Si la langue de l'UI a changé, on rafraîchit la page
            // window.location.reload() conserve les paramètres de l'URL (?library_id=...) !
            const currentLang = document.documentElement.lang;
            const newLang = formData.get('UI_LANG');
            if (currentLang !== newLang) {
                window.location.reload();
            }
        }
    });
}

// --- AMNISTIE DES ERREURS (AJAX) ---
function resetErrors(btn) {
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    
    fetch('/reset-errors', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            btn.innerText = "✅ OK";
            setTimeout(() => { btn.innerText = originalText; }, 2000);
            
            // Mise à jour de l'interface en direct sans recharger la page
            document.querySelectorAll('.series-item[data-status="NOT_FOUND"]').forEach(item => {
                item.dataset.status = 'PENDING';
                const badge = item.querySelector('.badge-notfound');
                if (badge) {
                    badge.className = 'badge badge-pending';
                    badge.innerText = window.AppTranslations.filter_pending;
                }
            });
            filterSeries(); // Réapplique le filtre actuel proprement
        }
    });
}

// --- CHARGEMENT DYNAMIQUE DES BIBLIOTHÈQUES (AJAX / DOM Swap) ---
function loadLibrary(libraryId) {
    const contentArea = document.querySelector('.content');
    contentArea.style.opacity = '0.5'; // Petit effet visuel pour montrer que ça charge
    contentArea.style.pointerEvents = 'none'; // Empêche le clic pendant le chargement
    
    // On requête la page complète en arrière-plan
    fetch('/?library_id=' + libraryId)
        .then(res => res.text())
        .then(html => {
            // On convertit le texte HTML en un vrai "Document" manipulable par le navigateur
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            
            // 1. On remplace uniquement la zone principale (les séries et boutons)
            const newContent = doc.querySelector('.content');
            if (newContent) {
                contentArea.innerHTML = newContent.innerHTML;
            }
            
            // 2. On en profite pour mettre à jour la carte des statistiques (au cas où)
            const currentStats = document.querySelectorAll('.sidebar .card')[0];
            const newStats = doc.querySelectorAll('.sidebar .card')[0];
            if (currentStats && newStats) {
                currentStats.innerHTML = newStats.innerHTML;
            }
            
            // 3. On met à jour l'URL dans la barre du navigateur SANS recharger la page
            const newUrl = libraryId ? '/?library_id=' + libraryId : '/';
            window.history.pushState({ path: newUrl }, '', newUrl);
            
            // 4. On restaure l'interface
            contentArea.style.opacity = '1';
            contentArea.style.pointerEvents = 'auto';
            
            // On relance le filtre pour mettre à jour le compteur d'éléments
            filterSeries();
        })
        .catch(err => {
            console.error("Erreur lors du chargement de la bibliothèque :", err);
            contentArea.style.opacity = '1';
            contentArea.style.pointerEvents = 'auto';
        });
}

// On gère le cas où l'utilisateur clique sur le bouton "Précédent" ou "Suivant" du navigateur
window.addEventListener('popstate', () => {
    window.location.reload();
});

// --- BASCULER LE STATUT "À IGNORER" (AJAX) ---
function toggleIgnore(seriesId, btn) {
    const seriesItem = btn.closest('.series-item');
    const currentStatus = seriesItem.dataset.status;
    
    // Désactiver le bouton temporairement pour éviter le double clic
    const originalText = btn.innerText;
    btn.innerText = "⏳";
    btn.disabled = true;

    fetch('/toggle-ignore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${seriesId}&current_status=${currentStatus}`
    })
    .then(res => res.json())
    .then(data => {
        btn.disabled = false;
        if(data.success) {
            seriesItem.dataset.status = data.new_status;
            
            // Mettre à jour l'icône et le titre du bouton
            if (data.new_status === 'IGNORED') {
                btn.innerText = '🔄';
                btn.title = window.AppTranslations.unignore_btn;
            } else {
                btn.innerText = '🚫';
                btn.title = window.AppTranslations.ignore_btn;
            }
            
            // Mettre à jour le badge visuel
            const badge = seriesItem.querySelector('.badge');
            if (badge) {
                if (data.new_status === 'IGNORED') {
                    badge.className = 'badge badge-ignored';
                    badge.innerText = window.AppTranslations.filter_ignored;
                } else {
                    badge.className = 'badge badge-pending';
                    badge.innerText = window.AppTranslations.filter_pending;
                }
            }
            
            filterSeries(); // Réappliquer le filtre en cours (le cache instantanément si on filtre par PENDING)
        } else {
            btn.innerText = originalText;
        }
    })
    .catch(() => {
        btn.disabled = false;
        btn.innerText = originalText;
    });
}

// --- IGNORER TOUTE LA SÉLECTION (AJAX) ---
async function ignoreSelection() {
    const checkboxes = document.querySelectorAll('.series-cb:checked');
    if (checkboxes.length === 0) return;

    const btn = document.getElementById('batchIgnoreBtn');
    const originalText = btn.innerText;
    btn.innerText = "⏳...";
    btn.disabled = true;

    for (let cb of checkboxes) {
        const seriesItem = cb.closest('.series-item');
        const seriesId = cb.value;
        const currentStatus = seriesItem.dataset.status;

        // On ignore uniquement si ce n'est pas déjà ignoré
        if (currentStatus !== 'IGNORED') {
            try {
                const res = await fetch('/toggle-ignore', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `series_id=${seriesId}&current_status=${currentStatus}`
                });
                const data = await res.json();
                
                if (data.success) {
                    // Mise à jour visuelle instantanée pour cet élément
                    seriesItem.dataset.status = 'IGNORED';
                    const badge = seriesItem.querySelector('.badge');
                    if (badge) {
                        badge.className = 'badge badge-ignored';
                        badge.innerText = window.AppTranslations.filter_ignored;
                    }
                    // Mise à jour de l'icône du petit bouton individuel
                    const ignoreBtn = seriesItem.querySelector('.series-actions .btn-icon');
                    if (ignoreBtn) {
                        ignoreBtn.innerText = '🔄';
                        ignoreBtn.title = window.AppTranslations.unignore_btn;
                    }
                }
            } catch(e) {
                console.error("[MetaKavita] Erreur lors de l'ignorance en masse:", e);
            }
        }
    }
    
    // Animation de fin et rafraîchissement
    btn.innerText = "✅ OK";
    setTimeout(() => { 
        btn.innerText = originalText; 
        btn.disabled = false;
        filterSeries(); // Fait disparaître les séries ignorées de l'écran principal
    }, 1000);
}

// --- MODAL COUVERTURES (OPTION 3) ---
function openCoverModal(seriesId, seriesName) {
    document.getElementById('modalSeriesName').innerText = seriesName;
    document.getElementById('coverModal').style.display = 'flex';
    document.getElementById('coversGrid').innerHTML = `<div class="loader-spinner">${window.AppTranslations.modal_cover_loading}</div>`;
    
    // On requête le backend qui va chercher sur tous les providers en même temps
    fetch(`/api/series/${seriesId}/covers?series_name=${encodeURIComponent(seriesName)}`)
    .then(r => r.json())
    .then(data => {
        if(data.success && data.covers.length > 0) {
            let html = '';
            data.covers.forEach(c => {
                // Utilisation du proxy pour éviter le blocage anti-hotlink de Nautiljon
                let displayUrl = c.provider === 'Nautiljon' ? `/api/proxy-image?url=${encodeURIComponent(c.url)}` : c.url;
                
                html += `
                <div class="cover-item" onclick="applyCover('${seriesId}', '${c.url}')" title="${c.title}">
                    <img src="${displayUrl}" alt="Cover" loading="lazy">
                    <div class="cover-title" style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 8px;" title="${c.title}">${c.title}</div>
                    <div class="cover-provider" style="font-size: 11px; color: var(--primary); margin-top: 2px;">${c.provider}</div>
                </div>`;
            });
            document.getElementById('coversGrid').innerHTML = html;
        } else {
            document.getElementById('coversGrid').innerHTML = `<div class="alert error" style="grid-column: 1 / -1;">❌ Aucune image trouvée.</div>`;
        }
    })
    .catch(err => {
        document.getElementById('coversGrid').innerHTML = `<div class="alert error" style="grid-column: 1 / -1;">❌ Erreur réseau.</div>`;
    });
}

function closeCoverModal() {
    document.getElementById('coverModal').style.display = 'none';
    document.getElementById('coversGrid').innerHTML = ''; // Nettoyer pour la prochaine fois
}

function applyCover(seriesId, coverUrl) {
    // Affiche le statut d'envoi
    document.getElementById('coversGrid').innerHTML = `<div class="loader-spinner">${window.AppTranslations.modal_cover_sending}</div>`;
    
    fetch(`/api/series/${seriesId}/update-cover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cover_url: coverUrl })
    })
    .then(r => r.json())
    .then(data => {
        if(data.success) {
            closeCoverModal();
            // On pourrait afficher un petit message de succès flottant ici (Toast), 
            // mais l'image sera déjà changée dans Kavita !
        } else {
            alert("Erreur lors de l'envoi de la couverture : " + data.msg);
            closeCoverModal();
        }
    });
}
// --- GESTION DES MENUS PROVIDERS (ANTI-DOUBLONS FLUIDE) ---
function handleProviderChange(changedSelect) {
    const selects = [
        document.querySelector('select[name="PROVIDER_1"]'),
        document.querySelector('select[name="PROVIDER_2"]'),
        document.querySelector('select[name="PROVIDER_3"]')
    ];
    
    const newValue = changedSelect.value;

    // 1. On gère le vol de sélection (Résolution des conflits)
    if (newValue !== 'NONE') {
        selects.forEach(otherSelect => {
            if (otherSelect !== changedSelect && otherSelect.value === newValue) {
                otherSelect.value = 'NONE'; // On efface la valeur de l'autre menu
            }
        });
    }

    // 2. PROTECTION VITALE : La Source 1 (Base) ne peut JAMAIS être vide
    const p1 = selects[0];
    
    if (!p1.value || p1.value === 'NONE') {
        // On récupère dynamiquement tous les providers possibles en lisant les options HTML
        const allProviders = Array.from(p1.options).map(opt => opt.value).filter(val => val !== 'NONE');
        const usedByOthers = [selects[1].value, selects[2].value];
        
        const freeProvider = allProviders.find(p => !usedByOthers.includes(p));
        p1.value = freeProvider || allProviders[0]; // Sécurité absolue
    }

    saveConfig();
}