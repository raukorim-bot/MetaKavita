// --- SURCHARGES PAR SÉRIE (ID/URL forcé, titre alternatif, champs ciblés, provider) ---
// Dépend de utils.js (getRootPath).

let allPanelsExpanded = false; // Mémorise l'état global du déploiement des options

function togglePanel(id) {
    var panel = document.getElementById(id);
    panel.style.display = (panel.style.display === 'block') ? 'none' : 'block';
}

// Fonction de déploiement/repli global de tous les panneaux d'options
function toggleAllOverridePanels() {
    allPanelsExpanded = !allPanelsExpanded;
    const targetDisplay = allPanelsExpanded ? 'block' : 'none';
    
    document.querySelectorAll('.override-panel').forEach(panel => {
        panel.style.display = targetDisplay;
    });
}

function lookupAniListId(seriesName) {
    const url = `https://anilist.co/search/manga?search=${encodeURIComponent(seriesName)}`;
    window.open(url, '_blank');
}

function saveOverride(seriesId, btn) {
    const forcedId = document.getElementById('id-' + seriesId).value;
    const altTitle = document.getElementById('title-' + seriesId).value;
    
    const providerSelect = document.getElementById('provider-' + seriesId);
    const forcedProvider = providerSelect ? providerSelect.value : 'AUTO';
    
    const pubPrefInput = document.querySelector(`input[name="pubpref-${seriesId}"]:checked`);
    const publisherPref = pubPrefInput ? pubPrefInput.value : 'GLOBAL';
    const altLangsInput = document.getElementById('alt-langs-' + seriesId);
    const altTitleLangs = altLangsInput ? altLangsInput.value.trim() : '';
    
    const fields = ['summary', 'cover', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles'];
    const activeFields = fields.filter(f => {
        const cb = document.getElementById(`field-${f}-${seriesId}`);
        return cb && cb.checked;
    }).join(',');

    btn.innerText = "⏳...";
    
    fetch(getRootPath() + '/save-override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `series_id=${seriesId}&forced_id=${encodeURIComponent(forcedId)}&alternative_title=${encodeURIComponent(altTitle)}&forced_provider=${encodeURIComponent(forcedProvider)}&targeted_fields=${encodeURIComponent(activeFields)}&publisher_pref=${encodeURIComponent(publisherPref)}&alt_title_langs=${encodeURIComponent(altTitleLangs)}`
    }).then(r => {
        if(r.ok) {
            btn.innerText = "✅"; 
            setTimeout(() => { btn.innerText = window.AppTranslations.save; }, 1500);
        }
    });
}

async function saveAllOverrides(btn) {
    const panels = document.querySelectorAll('.override-panel');
    const originalText = btn.innerHTML;
    
    btn.classList.add('btn-saving');
    btn.innerHTML = "⏳ " + window.AppTranslations.saving_progress;
    btn.disabled = true;

    for (let panel of panels) {
        if (panel.style.display === 'block' || panel.style.display === 'flex') {
            const saveBtn = panel.querySelector('button.btn-success');
            if(saveBtn) {
                saveBtn.click();
                await new Promise(r => setTimeout(r, 250));
            }
        }
    }
    
    btn.innerHTML = "✅ " + window.AppTranslations.save_done;
    btn.classList.remove('btn-saving');
    btn.classList.add('btn-success');
    
    setTimeout(() => { 
        btn.innerHTML = originalText;
        btn.classList.remove('btn-success');
        btn.disabled = false;
    }, 2000);
}
