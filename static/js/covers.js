// --- MODAL COUVERTURES : recherche live (Socket.IO + repli HTTP) et application manuelle ---
// Dépend de utils.js (getRootPath) et de websocket.js (variable globale `socket`).
// Expose aussi startCoverSearch() pour la phase couverture Manual Review (fill URL, pas upload).

let currentCoverModalSeriesId = null;
let currentCoverModalSeriesName = null;

/** Session de recherche active (dashboard modal OU panneau MR). */
let _coverSearchSession = null;

document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        const modalSearchInput = document.getElementById('modalCoverSearchInput');
        if (document.activeElement === modalSearchInput) {
            e.preventDefault();
            triggerManualCoverSearch();
        }
    }
});

/**
 * Lance une recherche de couvertures vers une grille donnée.
 * @param {object} opts
 * @param {number|string} opts.seriesId
 * @param {string} opts.query
 * @param {HTMLElement} opts.gridEl
 * @param {function(string, object): void} opts.onPick - (url, coverMeta) => void
 * @param {string} [opts.statusMessage]
 */
function startCoverSearch(opts) {
    opts = opts || {};
    const seriesId = opts.seriesId;
    const query = (opts.query || "").trim();
    const gridEl = opts.gridEl;
    const onPick = typeof opts.onPick === "function" ? opts.onPick : null;
    if (!seriesId || !gridEl || !query) return;

    _coverSearchSession = {
        seriesId: parseInt(seriesId, 10),
        gridEl: gridEl,
        onPick: onPick
    };

    gridEl.innerHTML = "";
    gridEl.appendChild(_buildCoverStreamStatus(
        opts.statusMessage ||
        (window.AppTranslations && window.AppTranslations.cover_streaming_start) ||
        "Recherche en direct..."
    ));

    if (typeof socket !== "undefined" && socket.connected) {
        socket.emit("fetch_covers_stream", { series_id: seriesId, query: query });
    } else {
        _fetchCoversHttp(seriesId, query, gridEl, onPick);
    }
}

function stopCoverSearch() {
    _coverSearchSession = null;
}

function openCoverModal(seriesId, seriesName) {
    currentCoverModalSeriesId = seriesId;
    currentCoverModalSeriesName = seriesName;

    document.getElementById("modalSeriesName").innerText = seriesName;

    const modalSearchInput = document.getElementById("modalCoverSearchInput");
    if (modalSearchInput) modalSearchInput.value = seriesName;

    document.getElementById("coverModal").style.display = "flex";
    const grid = document.getElementById("coversGrid");
    startCoverSearch({
        seriesId: seriesId,
        query: seriesName,
        gridEl: grid,
        onPick: function (url) {
            applyCover(seriesId, url);
        }
    });
}

function _buildCoverStreamStatus(message) {
    const bar = document.createElement("div");
    bar.className = "stream-status-bar";
    bar.id = "coverStreamStatus";
    bar.style.gridColumn = "1 / -1";
    const spinner = document.createElement("span");
    spinner.className = "stream-spinner";
    const label = document.createElement("span");
    label.textContent = message;
    bar.appendChild(spinner);
    bar.appendChild(label);
    return bar;
}

function _buildCoverItem(cover, onPick) {
    const coverDiv = document.createElement("div");
    coverDiv.className = "cover-item";
    coverDiv.dataset.url = cover.url || "";
    coverDiv.title = cover.title || "";
    coverDiv.onclick = function () {
        if (typeof onPick === "function") onPick(cover.url, cover);
    };

    const img = document.createElement("img");
    img.src = cover.display_url || cover.url || "";
    img.alt = "Cover";
    img.loading = "lazy";
    img.referrerPolicy = "no-referrer";
    img.onerror = function () {
        // Proxy/CDN hiccup: fall back to raw URL once if display_url differed.
        if (cover.url && img.src && cover.url !== img.getAttribute("data-raw") && img.src.indexOf("/api/proxy-image") !== -1) {
            img.setAttribute("data-raw", cover.url);
            img.src = cover.url;
        }
    };

    const titleDiv = document.createElement("div");
    titleDiv.className = "cover-title";
    titleDiv.style.cssText =
        "font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 8px;";
    titleDiv.title = cover.title || "";
    titleDiv.textContent = cover.title || "";

    const providerDiv = document.createElement("div");
    providerDiv.className = "cover-provider";
    providerDiv.style.cssText = "font-size: 11px; color: var(--primary); margin-top: 2px;";
    providerDiv.textContent = cover.provider || "";

    coverDiv.appendChild(img);
    coverDiv.appendChild(titleDiv);
    coverDiv.appendChild(providerDiv);
    return coverDiv;
}

function _setCoverGridError(gridEl, message) {
    if (!gridEl) return;
    gridEl.innerHTML = "";
    const err = document.createElement("div");
    err.className = "alert error";
    err.style.gridColumn = "1 / -1";
    err.textContent = message;
    gridEl.appendChild(err);
}

function _fetchCoversHttp(seriesId, query, gridEl, onPick) {
    fetch(
        getRootPath() +
            "/api/series/" +
            seriesId +
            "/covers?series_name=" +
            encodeURIComponent(query)
    )
        .then(function (r) {
            return r.json();
        })
        .then(function (data) {
            if (!_coverSearchSession || _coverSearchSession.gridEl !== gridEl) return;
            if (data.success && data.covers && data.covers.length > 0) {
                gridEl.innerHTML = "";
                data.covers.forEach(function (c) {
                    gridEl.appendChild(_buildCoverItem(c, onPick));
                });
            } else {
                _setCoverGridError(
                    gridEl,
                    (window.AppTranslations && window.AppTranslations.cover_no_images_found) ||
                        "❌ Aucune image trouvée."
                );
            }
        })
        .catch(function () {
            if (!_coverSearchSession || _coverSearchSession.gridEl !== gridEl) return;
            _setCoverGridError(
                gridEl,
                (window.AppTranslations && window.AppTranslations.cover_err_network_scrape) ||
                    "❌ Erreur réseau ou de scraping."
            );
        });
}

function triggerCoverStream(seriesId, query) {
    const grid = document.getElementById("coversGrid");
    startCoverSearch({
        seriesId: seriesId,
        query: query,
        gridEl: grid,
        onPick: function (url) {
            applyCover(seriesId, url);
        }
    });
}

function fetchCovers(seriesId, query) {
    const grid = document.getElementById("coversGrid");
    _fetchCoversHttp(seriesId, query, grid, function (url) {
        applyCover(seriesId, url);
    });
}

function triggerManualCoverSearch() {
    const modalSearchInput = document.getElementById("modalCoverSearchInput");
    if (modalSearchInput && currentCoverModalSeriesId) {
        const query = modalSearchInput.value.trim();
        if (query) {
            const grid = document.getElementById("coversGrid");
            startCoverSearch({
                seriesId: currentCoverModalSeriesId,
                query: query,
                gridEl: grid,
                statusMessage: (
                    (window.AppTranslations && window.AppTranslations.cover_live_search_for) ||
                    'Recherche en direct pour "{0}"...'
                ).replace('{0}', query),
                onPick: function (url) {
                    applyCover(currentCoverModalSeriesId, url);
                }
            });
        }
    }
}

function closeCoverModal() {
    stopCoverSearch();
    document.getElementById("coverModal").style.display = "none";
    document.getElementById("coversGrid").innerHTML = "";
    currentCoverModalSeriesId = null;
    currentCoverModalSeriesName = null;
}

function applyCover(seriesId, coverUrl) {
    const grid = document.getElementById("coversGrid");
    grid.innerHTML = "";
    const loader = document.createElement("div");
    loader.className = "loader-spinner";
    loader.textContent = window.AppTranslations.modal_cover_sending;
    grid.appendChild(loader);

    fetch(getRootPath() + "/api/series/" + seriesId + "/update-cover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cover_url: coverUrl })
    })
        .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(function (data) {
            if (data.success) {
                // Le backend (/update-cover) retire 'cover' de targeted_fields pour protéger
                // ce choix manuel contre un futur scraping.
                const coverCheckbox = document.getElementById("field-cover-" + seriesId);
                if (coverCheckbox) coverCheckbox.checked = false;

                closeCoverModal();
            } else {
                alert(
                    ((window.AppTranslations && window.AppTranslations.cover_send_failed) ||
                        "Erreur lors de l'envoi de la couverture : ") + data.msg
                );
                closeCoverModal();
            }
        })
        .catch(function () {
            alert(
                (window.AppTranslations && window.AppTranslations.cover_send_network) ||
                    "Erreur réseau lors de l'envoi de la couverture."
            );
            closeCoverModal();
        });
}

if (typeof socket !== "undefined") {
    socket.on("cover_stream_data", function (data) {
        const session = _coverSearchSession;
        if (!session || parseInt(session.seriesId, 10) !== parseInt(data.series_id, 10)) return;

        const grid = session.gridEl;
        if (!grid) return;

        data.covers.forEach(function (c) {
            let already = false;
            grid.querySelectorAll(".cover-item").forEach(function (el) {
                if (el.dataset.url === c.url) already = true;
            });
            if (already) return;
            grid.appendChild(_buildCoverItem(c, session.onPick));
        });
    });

    socket.on("cover_stream_complete", function (data) {
        const session = _coverSearchSession;
        if (!session || parseInt(session.seriesId, 10) !== parseInt(data.series_id, 10)) return;

        const statusStatus = session.gridEl
            ? session.gridEl.querySelector("#coverStreamStatus")
            : null;
        if (statusStatus) statusStatus.remove();

        const grid = session.gridEl;
        if (grid && grid.querySelectorAll(".cover-item").length === 0) {
            const noImgMsg =
                (window.AppTranslations && window.AppTranslations.cover_no_images_found) ||
                "❌ Aucune image trouvée.";
            _setCoverGridError(grid, noImgMsg);
        }
    });
}
