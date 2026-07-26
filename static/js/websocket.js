// --- WEBSOCKETS LOGS & INDICATEUR LIVE DE TRAITEMENT ---
// Dépend de utils.js (getRootPath). La variable globale `socket` est réutilisée
// par covers.js (flux de couvertures en direct) : ce fichier doit donc être
// chargé AVANT covers.js.
var socket = io({ path: getRootPath() + '/socket.io' });
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

    try {
        const matchStart = msg.data.match(/▶️\s+\[(.*?)\]\s+Début/i) || msg.data.match(/▶️\s+\[(.*?)\]\s+Starting/i);
        if (matchStart && matchStart[1]) {
            const activeTitle = matchStart[1].trim();
            
            document.querySelectorAll('.series-item.is-processing').forEach(item => {
                item.classList.remove('is-processing');
            });
            
            document.querySelectorAll('.series-item').forEach(item => {
                const nameElem = item.querySelector('.series-name');
                if (nameElem && nameElem.textContent.trim().toLowerCase() === activeTitle.toLowerCase()) {
                    item.classList.add('is-processing');
                    item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            });
        }

        const matchEnd = msg.data.match(/\[(.*?)\]\s+✅/i) || 
                         msg.data.match(/\[(.*?)\]\s+⏭️/i) || 
                         msg.data.match(/\[(.*?)\]\s+❌/i) || 
                         msg.data.match(/\[(.*?)\]\s+⚠️/i);
                         
        if (matchEnd && matchEnd[1]) {
            const finishedTitle = matchEnd[1].trim();
            document.querySelectorAll('.series-item').forEach(item => {
                const nameElem = item.querySelector('.series-name');
                if (nameElem && nameElem.textContent.trim().toLowerCase() === finishedTitle.toLowerCase()) {
                    item.classList.remove('is-processing');
                    
                    const badge = item.querySelector('.badge');
                    if (badge) {
                        if (msg.data.includes('✅') || msg.data.includes('réussi') || msg.data.includes('successfully')) {
                            item.dataset.status = 'COMPLETED';
                            badge.className = 'badge badge-completed';
                            badge.innerText = window.AppTranslations.filter_completed;
                        } else if (msg.data.includes('⏭️') || msg.data.includes('déjà à jour') || msg.data.includes('already up to date')) {
                            item.dataset.status = 'COMPLETED';
                            badge.className = 'badge badge-completed';
                            badge.innerText = window.AppTranslations.filter_completed;
                        } else if (msg.data.includes('introuvable') || msg.data.includes('Aucun résultat') || msg.data.includes('No results')) {
                            item.dataset.status = 'NOT_FOUND';
                            badge.className = 'badge badge-notfound';
                            badge.innerText = window.AppTranslations.filter_notfound;
                        }
                    }
                }
            });
        }
    } catch(e) {
        console.error("[WebSockets] Erreur Live Highlight :", e);
    }
});
