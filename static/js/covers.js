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
    const grid = document.getElementById('coversGrid');
    grid.innerHTML = '';
    grid.appendChild(_buildCoverStreamStatus(
        window.AppTranslations.cover_streaming_start || 'Recherche en direct...'
    ));

    triggerCoverStream(seriesId, seriesName);
}

function _buildCoverStreamStatus(message) {
    const bar = document.createElement('div');
    bar.className = 'stream-status-bar';
    bar.id = 'coverStreamStatus';
    bar.style.gridColumn = '1 / -1';
    const spinner = document.createElement('span');
    spinner.className = 'stream-spinner';
    const label = document.createElement('span');
    label.textContent = message;
    bar.appendChild(spinner);
    bar.appendChild(label);
    return bar;
}

function _buildCoverItem(seriesId, cover) {
    const coverDiv = document.createElement('div');
    coverDiv.className = 'cover-item';
    coverDiv.dataset.url = cover.url || '';
    coverDiv.title = cover.title || '';
    coverDiv.onclick = () => applyCover(seriesId, cover.url);

    const img = document.createElement('img');
    img.src = cover.display_url || '';
    img.alt = 'Cover';
    img.loading = 'lazy';

    const titleDiv = document.createElement('div');
    titleDiv.className = 'cover-title';
    titleDiv.style.cssText = 'font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 8px;';
    titleDiv.title = cover.title || '';
    titleDiv.textContent = cover.title || '';

    const providerDiv = document.createElement('div');
    providerDiv.className = 'cover-provider';
    providerDiv.style.cssText = 'font-size: 11px; color: var(--primary); margin-top: 2px;';
    providerDiv.textContent = cover.provider || '';

    coverDiv.appendChild(img);
    coverDiv.appendChild(titleDiv);
    coverDiv.appendChild(providerDiv);
    return coverDiv;
}

function _setCoverGridError(message) {
    const grid = document.getElementById('coversGrid');
    grid.innerHTML = '';
    const err = document.createElement('div');
    err.className = 'alert error';
    err.style.gridColumn = '1 / -1';
    err.textContent = message;
    grid.appendChild(err);
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
        if (data.success && data.covers.length > 0) {
            const grid = document.getElementById('coversGrid');
            grid.innerHTML = '';
            data.covers.forEach(c => {
                grid.appendChild(_buildCoverItem(seriesId, c));
            });
        } else {
            _setCoverGridError('❌ Aucune image trouvée.');
        }
    })
    .catch(() => {
        _setCoverGridError('❌ Erreur réseau ou de scraping.');
    });
}

function triggerManualCoverSearch() {
    const modalSearchInput = document.getElementById('modalCoverSearchInput');
    if (modalSearchInput && currentCoverModalSeriesId) {
        const query = modalSearchInput.value.trim();
        if (query) {
            const grid = document.getElementById('coversGrid');
            grid.innerHTML = '';
            grid.appendChild(_buildCoverStreamStatus(`Recherche en direct pour "${query}"...`));
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
    const grid = document.getElementById('coversGrid');
    grid.innerHTML = '';
    const loader = document.createElement('div');
    loader.className = 'loader-spinner';
    loader.textContent = window.AppTranslations.modal_cover_sending;
    grid.appendChild(loader);

    fetch(`${getRootPath()}/api/series/${seriesId}/update-cover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cover_url: coverUrl })
    })
    .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(data => {
        if (data.success) {
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
    })
    .catch(() => {
        alert("Erreur réseau lors de l'envoi de la couverture.");
        closeCoverModal();
    });
}

// --- ÉCOUTE DES FLUX DE COUVERTURES EN DIRECT (SOCKET.IO) ---
if (typeof socket !== 'undefined') {
    socket.on('cover_stream_data', function(data) {
        if (parseInt(currentCoverModalSeriesId) !== parseInt(data.series_id)) return;

        const grid = document.getElementById('coversGrid');
        if (!grid) return;

        data.covers.forEach(c => {
            let already = false;
            grid.querySelectorAll('.cover-item').forEach(el => {
                if (el.dataset.url === c.url) already = true;
            });
            if (already) return;

            grid.appendChild(_buildCoverItem(data.series_id, c));
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
            _setCoverGridError(noImgMsg);
        }
    });
}
