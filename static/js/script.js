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

window.addEventListener('load', () => {
    if (localStorage.getItem('configHidden') === 'true') {
        const configSection = document.getElementById('configSection');
        if(configSection) configSection.style.display = 'none';
    }
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
            panel.querySelector('button').click();
            await new Promise(r => setTimeout(r, 200));
        }
    }
}

function filterSeries() {
    const filter = document.getElementById('statusFilter').value;
    document.querySelectorAll('.series-item').forEach(item => {
        if (filter === 'ALL' || item.dataset.status === filter) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
            const cb = item.querySelector('.series-cb');
            if(cb) cb.checked = false; 
        }
    });
    document.getElementById('selectAll').checked = false;
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
    btn.style.display = 'none';
    btn.previousElementSibling.style.display = 'none'; 
    let loading = btn.nextElementSibling;
    loading.style.display = 'inline-block';

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
        btn.innerText = "❌ Aucun élément";
        setTimeout(() => { btn.innerText = window.AppTranslations.launchBatch; }, 2000);
        return;
    }

    btn.innerText = "⏳ Envoi par paquets...";
    
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

    btn.innerText = "✅ Batch de " + ids.length + " séries lancé !";
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
    logConsole.innerHTML += '<div class="log-line" style="color: var(--primary);">Terminal prêt.</div>'; 
});
socket.on('log_update', function(msg) {
    var newLog = document.createElement('div');
    newLog.className = 'log-line';
    newLog.textContent = msg.data;
    if (msg.data.includes('ERROR') || msg.data.includes('Échec') || msg.data.includes('🛑')) {
        newLog.className += ' log-error';
    } else if (msg.data.includes('WARNING') || msg.data.includes('Introuvable')) {
        newLog.className += ' log-warning';
    }
    logConsole.appendChild(newLog);
    logConsole.scrollTop = logConsole.scrollHeight;
});