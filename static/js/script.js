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
    let count = 0;
    document.querySelectorAll('.series-item').forEach(item => {
        if (filter === 'ALL' || item.dataset.status === filter) {
            item.style.display = 'flex';
            count++;
        } else {
            item.style.display = 'none';
            const cb = item.querySelector('.series-cb');
            if(cb) cb.checked = false; 
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