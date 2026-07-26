// --- MODAL COUVERTURES : recherche live (Socket.IO + repli HTTP) et application manuelle ---
// Dépend de utils.js (getRootPath) et de websocket.js (variable globale `socket`).

let currentCoverModalSeriesId = null;
let currentCoverModalSeriesName = null;

// Écouteur pour la touche "Entrée" sur la recherche de couverture de la modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        const modalSearchInput = document.getElementById('modalCoverSearchInput');
        if (document.activeElement === modalSearchInput) {
            e.preventDefault();
            triggerManualCoverSearch();
        }
    }
});

function openCoverModal(seriesId, seriesName) {
    currentCoverModalSeriesId = seriesId;
    currentCoverModalSeriesName = seriesName;
    
    document.getElementById('modalSeriesName').innerText = seriesName;
    
    const modalSearchInput = document.getElementById('modalCoverSearchInput');
    if (modalSearchInput) modalSearchInput.value = seriesName;
    
    document.getElementById('coverModal').style.display = 'flex';
    document.getElementById('coversGrid').innerHTML = `
        <div class="stream-status-bar" id="coverStreamStatus" style="grid-column: 1 / -1;">
            <span class="stream-spinner"></span>
            <span>${window.AppTranslations.cover_streaming_start || 'Recherche en direct...'}</span>
        </div>`;
    
    triggerCoverStream(seriesId, seriesName);
}

function triggerCoverStream(seriesId, query) {
    if (typeof socket !== 'undefined' && socket.connected) {
        socket.emit('fetch_covers_stream', { series_id: seriesId, query: query });
    } else {
        // Fallback HTTP classique si le WebSocket est déconnecté
        fetchCovers(seriesId, query);
    }
}

function fetchCovers(seriesId, query) {
    fetch(`${getRootPath()}/api/series/${seriesId}/covers?series_name=${encodeURIComponent(query)}`)
    .then(r => r.json())
    .then(data => {
        if(data.success && data.covers.length > 0) {
            let html = '';
            data.covers.forEach(c => {
                html += `
                <div class="cover-item" data-url="${c.url}" onclick="applyCover('${seriesId}', '${c.url}')" title="${c.title}">
                    <img src="${c.display_url}" alt="Cover" loading="lazy">
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
        document.getElementById('coversGrid').innerHTML = `<div class="alert error" style="grid-column: 1 / -1;">❌ Erreur réseau ou de scraping.</div>`;
    });
}

function triggerManualCoverSearch() {
    const modalSearchInput = document.getElementById('modalCoverSearchInput');
    if (modalSearchInput && currentCoverModalSeriesId) {
        const query = modalSearchInput.value.trim();
        if (query) {
            document.getElementById('coversGrid').innerHTML = `
                <div class="stream-status-bar" id="coverStreamStatus" style="grid-column: 1 / -1;">
                    <span class="stream-spinner"></span>
                    <span>Recherche en direct pour "${query}"...</span>
                </div>`;
            triggerCoverStream(currentCoverModalSeriesId, query);
        }
    }
}

function closeCoverModal() {
    document.getElementById('coverModal').style.display = 'none';
    document.getElementById('coversGrid').innerHTML = '';
    currentCoverModalSeriesId = null;
    currentCoverModalSeriesName = null;
}

function applyCover(seriesId, coverUrl) {
    document.getElementById('coversGrid').innerHTML = `<div class="loader-spinner">${window.AppTranslations.modal_cover_sending}</div>`;
    
    fetch(`${getRootPath()}/api/series/${seriesId}/update-cover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cover_url: coverUrl })
    })
    .then(r => r.json())
    .then(data => {
        if(data.success) {
            // Le backend (/update-cover) retire 'cover' de targeted_fields pour protéger
            // ce choix manuel contre un futur scraping. Sans ceci, la case "Couverture" du
            // panneau "⚙️ Options de scraping ciblé" resterait cochée (état de rendu de la
            // page, non rafraîchi) : un simple clic sur "Sync" ou "Sauvegarder" sur cette
            // même série ré-enverrait targeted_fields AVEC 'cover' et annulerait sans le
            // vouloir la protection qu'on vient d'obtenir, ré-exposant la couverture manuelle
            // à un écrasement automatique (AUTO_COVER) au prochain scraping.
            const coverCheckbox = document.getElementById(`field-cover-${seriesId}`);
            if (coverCheckbox) coverCheckbox.checked = false;

            closeCoverModal();
        } else {
            alert("Erreur lors de l'envoi de la couverture : " + data.msg);
            closeCoverModal();
        }
    });
}

// --- ÉCOUTE DES FLUX DE COUVERTURES EN DIRECT (SOCKET.IO) ---
if (typeof socket !== 'undefined') {
    socket.on('cover_stream_data', function(data) {
        if (parseInt(currentCoverModalSeriesId) !== parseInt(data.series_id)) return;

        const grid = document.getElementById('coversGrid');
        if (!grid) return;

        data.covers.forEach(c => {
            if (grid.querySelector(`div[data-url="${c.url}"]`)) return;

            const coverDiv = document.createElement('div');
            coverDiv.className = 'cover-item';
            coverDiv.dataset.url = c.url;
            coverDiv.title = c.title;
            coverDiv.onclick = () => applyCover(data.series_id, c.url);

            coverDiv.innerHTML = `
                <img src="${c.display_url}" alt="Cover" loading="lazy">
                <div class="cover-title" style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 8px;" title="${c.title}">${c.title}</div>
                <div class="cover-provider" style="font-size: 11px; color: var(--primary); margin-top: 2px;">${c.provider}</div>
            `;

            grid.appendChild(coverDiv);
        });
    });

    socket.on('cover_stream_complete', function(data) {
        if (parseInt(currentCoverModalSeriesId) !== parseInt(data.series_id)) return;
        
        const statusStatus = document.getElementById('coverStreamStatus');
        if (statusStatus) {
            statusStatus.remove();
        }

        const grid = document.getElementById('coversGrid');
        if (grid && grid.querySelectorAll('.cover-item').length === 0) {
            const noImgMsg = window.AppTranslations.cover_no_images_found || '❌ Aucune image trouvée.';
            grid.innerHTML = `<div class="alert error" style="grid-column: 1 / -1;">${noImgMsg}</div>`;
        }
    });
}
