(function () {
    const hub = window.SCRAPER_HUB || { tab: "manage", i18n: {} };
    const t = hub.i18n || {};
    const root = () => window.ROOT_PATH || "";

    const grid = document.getElementById("hubGrid");
    const empty = document.getElementById("hubEmpty");
    const alerts = document.getElementById("hubAlerts");
    const toastEl = document.getElementById("hubToast");
    const searchEl = document.getElementById("hubSearch");
    const typeEl = document.getElementById("hubType");
    const scopeEl = document.getElementById("hubScope");
    const statusEl = document.getElementById("hubStatus");
    const gradeEl = document.getElementById("hubGrade");
    const coversEl = document.getElementById("hubCovers");
    const refreshBtn = document.getElementById("hubRefresh");

    const modal = document.getElementById("hubModal");
    const modalBody = document.getElementById("hubModalBody");
    const modalWarnings = document.getElementById("hubModalWarnings");
    const modalCheck = document.getElementById("hubModalCheck");
    const modalConfirm = document.getElementById("hubModalConfirm");
    const modalCancel = document.getElementById("hubModalCancel");

    let manageRows = [];
    let storeRows = [];
    let storeMeta = {};
    let pendingInstall = null;
    let toastTimer = null;

    function toast(msg) {
        if (!toastEl) return;
        toastEl.textContent = msg || "";
        toastEl.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastEl.classList.remove("is-visible"), 3200);
    }

    function badge(label, cls) {
        return `<span class="hub-badge ${cls || ""}">${escapeHtml(label)}</span>`;
    }

    function escapeHtml(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function matchesFilters(row) {
        const q = (searchEl && searchEl.value || "").trim().toLowerCase();
        const type = typeEl && typeEl.value || "";
        const scope = scopeEl && scopeEl.value || "";
        const status = statusEl && statusEl.value || "";
        const grade = gradeEl && gradeEl.value || "";
        const covers = coversEl && coversEl.value || "";

        if (q) {
            const hay = [
                row.display_name, row.id, row.file, row.summary,
                ...(row.tags || []), ...(row.supported_types || [])
            ].join(" ").toLowerCase();
            if (!hay.includes(q)) return false;
        }
        if (type && !(row.supported_types || []).includes(type)) return false;
        if (scope && !(row.scopes || []).includes(scope)) return false;
        if (status === "retired") {
            if (!row.retired && (row.status || "") !== "retired") return false;
        } else if (status && (row.status || "") !== status) {
            return false;
        }
        if (grade && ((row.quality || {}).grade || "") !== grade) return false;
        if (covers === "yes" && (row.quality || {}).covers_ok !== true) return false;
        if (covers === "no" && (row.quality || {}).covers_ok === true) return false;
        return true;
    }

    function renderManage() {
        const rows = manageRows.filter(matchesFilters);
        alerts.innerHTML = "";
        const warns = (window.__hubWarnings || []);
        if (warns.length) {
            alerts.hidden = false;
            alerts.innerHTML = warns.map((w) => {
                const tpl = w.type === "missing" ? t.warnMissing : t.warnDisabled;
                return `<div class="hub-alert">${escapeHtml((tpl || "{0} {1}").replace("{0}", w.slot).replace("{1}", w.id))}</div>`;
            }).join("");
        } else {
            alerts.hidden = true;
        }

        if (!rows.length) {
            grid.innerHTML = "";
            empty.hidden = false;
            return;
        }
        empty.hidden = true;
        grid.innerHTML = rows.map((row) => {
            const originCls = row.origin === "core" ? "hub-badge--core"
                : row.origin === "community" ? "hub-badge--community" : "hub-badge--custom";
            const originLabel = t[row.origin] || row.origin;
            const typeBadges = (row.supported_types || []).map((x) => badge(x)).join("");
            const scopeBadges = (row.scopes || []).map((s) =>
                badge(s === "volume" ? t.volume : t.series, s === "volume" ? "hub-badge--volume" : "")
            ).join("");
            const deleteBtn = row.is_core
                ? `<button type="button" class="btn-secondary" disabled title="${escapeHtml(t.coreNoDelete)}">${escapeHtml(t.delete)}</button>`
                : `<button type="button" class="btn-secondary" data-act="delete" data-id="${escapeHtml(row.id)}">${escapeHtml(t.delete)}</button>`;
            const toggleBtn = row.enabled
                ? `<button type="button" class="btn-secondary" data-act="disable" data-id="${escapeHtml(row.id)}">${escapeHtml(t.disable)}</button>`
                : `<button type="button" class="btn-primary" data-act="enable" data-id="${escapeHtml(row.id)}">${escapeHtml(t.enable)}</button>`;
            const flags = [];
            if (row.retired) flags.push(badge(t.retiredBadge || "Out of service", "hub-badge--retired"));
            if (row.removed_from_store) flags.push(badge(t.removedStoreBadge || "Removed", "hub-badge--removed"));
            const hints = [];
            if (!row.enabled && row.is_core) hints.push(t.coreDisabledHint);
            if (row.retired) hints.push(t.retiredHint);
            if (row.removed_from_store) hints.push(t.removedStoreHint);
            if (row.off_store) hints.push(t.offStoreHint);
            if (row.volume_ready_hint) hints.push(t.volumeHint);
            if (row.needs_api_key) hints.push(t.needsKey);
            return `<article class="hub-card ${row.enabled ? "" : "is-disabled"} ${row.retired ? "is-retired" : ""}">
                <div class="hub-card-top">
                    <div>
                        <h3 class="hub-card-title">${escapeHtml(row.display_name)}
                            <span class="hub-card-id">${escapeHtml(row.id)}${row.file ? " · " + escapeHtml(row.file) : ""}</span>
                        </h3>
                    </div>
                    <div class="hub-badges">${flags.join("")}${badge(originLabel, originCls)}${badge(row.enabled ? t.enabled : t.disabled)}</div>
                </div>
                <div class="hub-badges">${typeBadges}${scopeBadges}</div>
                ${hints.map((h) => `<p class="hub-hint">${escapeHtml(h)}</p>`).join("")}
                <div class="hub-actions">${toggleBtn}${deleteBtn}</div>
            </article>`;
        }).join("");
    }

    function renderStore() {
        const rows = storeRows.filter(matchesFilters);
        if (!rows.length) {
            grid.innerHTML = "";
            empty.hidden = false;
            empty.textContent = storeMeta._offline ? (t.offline || "") : (t.emptyStore || "");
            if (storeMeta.repo) {
                empty.innerHTML = `${escapeHtml(empty.textContent)}<br><br>
                    <a class="btn-secondary block-link" href="${escapeHtml(storeMeta.repo)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t.repoLink)}</a>`;
            }
            return;
        }
        empty.hidden = true;
        grid.innerHTML = rows.map((row) => {
            const q = row.quality || {};
            const typeBadges = (row.supported_types || []).map((x) => badge(x)).join("");
            const scopeBadges = (row.scopes || []).map((s) =>
                badge(s === "volume" ? t.volume : t.series, s === "volume" ? "hub-badge--volume" : "")
            ).join("");
            const grade = q.grade ? badge(q.grade, "hub-badge--grade") : "";
            const statusBadge = row.retired
                ? badge(t.retiredBadge || "Out of service", "hub-badge--retired")
                : (row.status ? badge(row.status) : "");
            const coversBadge = q.covers_ok === true
                ? badge(t.coversYes)
                : q.covers_ok === false ? badge(t.coversNo, "hub-badge--warn") : "";
            let action = "";
            const outdatedBadge = row.state === "update" && !row.retired
                ? badge(t.outdated || "Out of date", "hub-badge--outdated")
                : "";
            if (row.retired) {
                action = `<button type="button" class="btn-secondary" disabled title="${escapeHtml(t.retiredBlocked || "")}">${escapeHtml(t.retiredBadge || "Out of service")}</button>`;
            } else if (row.state === "core") {
                action = `<button type="button" class="btn-secondary" disabled>${escapeHtml(t.coreBadge)}</button>`;
            } else if (row.state === "update") {
                action = `<button type="button" class="btn-primary" data-act="install" data-id="${escapeHtml(row.id)}" data-force="1" data-update="1">${escapeHtml(t.update)}</button>`;
            } else if (row.state === "installed") {
                action = `<button type="button" class="btn-secondary" data-act="install" data-id="${escapeHtml(row.id)}" data-force="1">${escapeHtml(t.reinstall)}</button>`;
            } else if (row.state === "orphan" || row.orphan) {
                // Disk file without registry entry — replace (force) so Install is not a 409 dead-end.
                action = `<button type="button" class="btn-primary" data-act="install" data-id="${escapeHtml(row.id)}" data-force="1">${escapeHtml(t.reinstall || t.install)}</button>`;
            } else {
                action = `<button type="button" class="btn-primary" data-act="install" data-id="${escapeHtml(row.id)}">${escapeHtml(t.install)}</button>`;
            }
            const codeUrl = (row.install && row.install.url) || "";
            const docsUrl = row.docs
                ? `https://github.com/raukorim-bot/community-scraper-metakavita/blob/main/${row.docs}`
                : "";
            const links = [];
            if (codeUrl) links.push(`<a class="btn-secondary block-link" href="${escapeHtml(codeUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t.viewCode)}</a>`);
            if (docsUrl) links.push(`<a class="btn-secondary block-link" href="${escapeHtml(docsUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t.viewDocs)}</a>`);
            const hints = [];
            if (row.retired) hints.push(t.retiredHint || "");
            return `<article class="hub-card ${row.state === "update" ? "is-outdated" : ""} ${row.retired ? "is-retired" : ""}">
                <div class="hub-card-top">
                    <div>
                        <h3 class="hub-card-title">${escapeHtml(row.display_name)}
                            <span class="hub-card-id">${escapeHtml(row.id)}${row.version ? " · v" + escapeHtml(row.version) : ""}</span>
                        </h3>
                    </div>
                    <div class="hub-badges">${outdatedBadge}${grade}${statusBadge}</div>
                </div>
                <div class="hub-badges">${typeBadges}${scopeBadges}${coversBadge}${row.needs_api_key ? badge(t.needsKey, "hub-badge--warn") : ""}</div>
                <p class="hub-summary">${escapeHtml(row.summary || "")}</p>
                ${q.pick && !row.retired ? `<p class="hub-pick">${escapeHtml(t.pickIf)} ${escapeHtml(q.pick)}</p>` : ""}
                ${hints.filter(Boolean).map((h) => `<p class="hub-hint">${escapeHtml(h)}</p>`).join("")}
                <div class="hub-actions">${action}${links.join("")}</div>
            </article>`;
        }).join("");
    }

    function render() {
        if (hub.tab === "store") renderStore();
        else renderManage();
    }

    async function loadManage() {
        const res = await fetch(root() + "/api/scrapers/installed");
        const data = await res.json();
        if (!data.success) throw new Error(data.msg || "fail");
        manageRows = data.scrapers || [];
        window.__hubWarnings = data.warnings || [];
        render();
    }

    async function loadStore(force) {
        storeMeta._offline = false;
        const url = root() + "/api/scrapers/store" + (force ? "?refresh=1" : "");
        const res = await fetch(url);
        const data = await res.json();
        if (!data.success) {
            storeRows = [];
            storeMeta = { repo: data.repo, _offline: true };
            render();
            return;
        }
        storeMeta = data.catalog || {};
        storeRows = storeMeta.scrapers || [];
        render();
    }

    async function postJson(url, body) {
        const res = await fetch(root() + url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.success === false) {
            throw new Error(data.msg || t.toastError || "error");
        }
        return data;
    }

    function openInstallModal(row) {
        pendingInstall = row;
        modalBody.textContent = storeMeta.security || row.summary || "";
        modalWarnings.innerHTML = (row.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");
        modalCheck.checked = false;
        modalConfirm.disabled = true;
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
        pendingInstall = null;
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
    }

    async function doInstall(row, force) {
        const data = await postJson("/api/scrapers/store/install", { id: row.id, force: !!force });
        if (data.loaded === false) {
            throw new Error(data.msg || t.toastError || "load failed");
        }
        if (Array.isArray(data.proxy_cover_hosts)) {
            window.PROXY_COVER_HOSTS = data.proxy_cover_hosts;
        }
        const scopes = data.scopes || row.scopes || ["series"];
        const onlyVolume = scopes.includes("volume") && !scopes.includes("series");
        if (data.updated || data.action === "updated") {
            toast(t.okUpdate || t.okSeries);
        } else if (onlyVolume) {
            toast(t.okVolume);
        } else {
            toast(t.okSeries);
        }
        await loadStore(true);
    }

    grid.addEventListener("click", async (ev) => {
        const btn = ev.target.closest("[data-act]");
        if (!btn) return;
        const act = btn.getAttribute("data-act");
        const id = btn.getAttribute("data-id");
        try {
            if (act === "enable") {
                await postJson(`/api/scrapers/${encodeURIComponent(id)}/enable`);
                toast(t.toastEnabled);
                await loadManage();
            } else if (act === "disable") {
                await postJson(`/api/scrapers/${encodeURIComponent(id)}/disable`);
                toast(t.toastDisabled);
                await loadManage();
            } else if (act === "delete") {
                if (!window.confirm(t.deleteConfirm || "")) return;
                const res = await fetch(root() + `/api/scrapers/${encodeURIComponent(id)}`, { method: "DELETE" });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || data.success === false) throw new Error(data.msg || t.toastError);
                toast(t.toastDeleted);
                await loadManage();
            } else if (act === "install") {
                const row = storeRows.find((r) => r.id === id);
                if (!row) return;
                const force = btn.getAttribute("data-force") === "1";
                const understood = sessionStorage.getItem("mk_scraper_trust") === "1";
                if (!understood) {
                    openInstallModal(Object.assign({}, row, { _force: force }));
                    return;
                }
                btn.disabled = true;
                await doInstall(row, force);
            }
        } catch (e) {
            toast(e.message || t.toastError);
        } finally {
            if (btn && act === "install") btn.disabled = false;
        }
    });

    modalCheck.addEventListener("change", () => {
        modalConfirm.disabled = !modalCheck.checked;
    });
    modalCancel.addEventListener("click", closeModal);
    modal.addEventListener("click", (ev) => {
        if (ev.target === modal) closeModal();
    });
    modalConfirm.addEventListener("click", async () => {
        if (!pendingInstall || !modalCheck.checked) return;
        sessionStorage.setItem("mk_scraper_trust", "1");
        const row = pendingInstall;
        const force = !!row._force;
        closeModal();
        try {
            await doInstall(row, force);
        } catch (e) {
            toast(e.message || t.toastError);
        }
    });

    ["input", "change"].forEach((evt) => {
        [searchEl, typeEl, scopeEl, statusEl, gradeEl, coversEl].forEach((el) => {
            if (el) el.addEventListener(evt, render);
        });
    });
    if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {
            refreshBtn.disabled = true;
            try { await loadStore(true); }
            catch (e) { toast(e.message || t.toastError); }
            finally { refreshBtn.disabled = false; }
        });
    }

    document.querySelectorAll(".reveal").forEach((el, i) => {
        setTimeout(() => el.classList.add("is-in"), 40 + i * 40);
    });

    (async function init() {
        try {
            if (hub.tab === "store") await loadStore(false);
            else await loadManage();
        } catch (e) {
            toast(e.message || t.toastError);
            empty.hidden = false;
        }
    })();
})();
