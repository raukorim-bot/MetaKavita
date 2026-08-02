/**
 * Page /diagnostics — préflight Internet/Kavita + probes scrapers.
 * Dépend de utils.js (CSRF patch + getRootPath + toggleTheme).
 */
(function () {
    const I18N = window.DIAG_I18N || {};
    const root = () => (typeof getRootPath === "function" ? getRootPath() : (window.ROOT_PATH || ""));

    function t(key, fallback) {
        return I18N[key] != null ? I18N[key] : (fallback || key);
    }

    function causeLabel(cause) {
        const map = {
            ok: "cause_ok",
            network: "cause_network",
            ban: "cause_ban",
            schema: "cause_schema",
            covers_schema: "cause_covers_schema",
            partial: "cause_partial",
            auth_missing: "cause_auth_missing",
        };
        return t(map[cause] || "cause_ok", cause || "—");
    }

    function statusLabel(status) {
        const map = {
            idle: "idle",
            running: "running",
            ok: "ok",
            degraded: "degraded",
            down: "down",
            skipped: "skipped",
            n_a: "n_a",
        };
        return t(map[status] || "idle", status);
    }

    function setPill(el, status, labelOverride) {
        if (!el) return;
        const pill = el.classList && el.classList.contains("diag-pill")
            ? el
            : el.querySelector(".diag-pill");
        if (!pill) return;
        pill.dataset.status = status || "idle";
        const label = pill.querySelector(".label");
        if (label) label.textContent = labelOverride != null ? labelOverride : statusLabel(status);
        // re-trigger fade
        pill.style.animation = "none";
        // eslint-disable-next-line no-unused-expressions
        pill.offsetHeight;
        pill.style.animation = "";
        pill.classList.add("is-visible");
    }

    function setPreflightCard(kind, data) {
        const card = document.getElementById(kind === "internet" ? "cardInternet" : "cardKavita");
        const pill = document.getElementById(kind === "internet" ? "pillInternet" : "pillKavita");
        const detail = document.getElementById(kind === "internet" ? "detailInternet" : "detailKavita");
        const meta = document.getElementById(kind === "internet" ? "metaInternet" : "metaKavita");
        if (!card || !data) return;

        const status = data.status || "down";
        card.dataset.status = status;
        setPill(pill, status);

        if (kind === "internet") {
            detail.textContent = status === "ok" ? t("internet_ok") : t("internet_down");
            meta.textContent = formatLatency(data.latency_ms) +
                (data.http_status != null ? ` · HTTP ${data.http_status}` : "") +
                (data.detail && data.detail !== "ok" && data.detail !== "ok_fallback" ? ` · ${data.detail}` : "");
        } else {
            if (status === "ok") {
                const libs = (t("kavita_libs") || "").replace("{0}", String(data.library_count != null ? data.library_count : 0));
                detail.textContent = t("kavita_ok") + (libs ? ` — ${libs}` : "");
            } else {
                detail.textContent = t("kavita_down") + (data.detail ? ` (${data.detail})` : "");
            }
            const host = data.kavita_url_host ? ` · ${data.kavita_url_host}` : "";
            meta.textContent = formatLatency(data.latency_ms) + host;
        }
    }

    function formatLatency(ms) {
        if (ms == null || ms === "") return "—";
        return (t("ms") || "{0} ms").replace("{0}", String(ms));
    }

    function formatDetail(result) {
        const bits = [];
        if (result.metadata && result.metadata.sample_title) {
            bits.push(result.metadata.sample_title);
        }
        if (result.covers && result.covers.count > 0) {
            bits.push(`${result.covers.count} cover(s)`);
        }
        if (result.detail && result.detail !== "ok") {
            bits.push(result.detail);
        }
        return bits.join(" · ") || "—";
    }

    function applyResultToRow(row, result) {
        if (!row || !result) return;
        row.classList.remove("is-probing");
        setPill(row.querySelector(".cell-global"), result.status);
        setPill(
            row.querySelector(".cell-meta"),
            (result.metadata && result.metadata.status) || "idle",
            result.metadata && result.metadata.sample_title
                ? undefined
                : undefined
        );
        const coversStatus = (result.covers && result.covers.status) || "n_a";
        const coversLabel = coversStatus === "ok" && result.covers
            ? `${statusLabel("ok")} (${result.covers.count})`
            : undefined;
        setPill(row.querySelector(".cell-covers"), coversStatus, coversLabel);

        const causeCell = row.querySelector(".cell-cause");
        if (causeCell) causeCell.textContent = causeLabel(result.cause);

        const latCell = row.querySelector(".cell-latency");
        if (latCell) latCell.textContent = formatLatency(result.latency_ms);

        const detCell = row.querySelector(".cell-detail");
        if (detCell) detCell.textContent = formatDetail(result);

        const btn = row.querySelector(".btn-probe-one");
        if (btn) btn.disabled = false;
    }

    function markRowRunning(row) {
        if (!row) return;
        row.classList.add("is-probing");
        setPill(row.querySelector(".cell-global"), "running");
        const btn = row.querySelector(".btn-probe-one");
        if (btn) btn.disabled = true;
    }

    async function postJson(path) {
        const res = await fetch(root() + path, {
            method: "POST",
            headers: {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: "{}",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const err = new Error((data && data.msg) || t("err_generic"));
            err.status = res.status;
            err.data = data;
            throw err;
        }
        return data;
    }

    async function runPreflight() {
        const pillNet = document.getElementById("pillInternet");
        const pillKav = document.getElementById("pillKavita");
        setPill(pillNet, "running");
        setPill(pillKav, "running");
        document.getElementById("cardInternet").dataset.status = "idle";
        document.getElementById("cardKavita").dataset.status = "idle";
        const warn = document.getElementById("netWarn");
        if (warn) warn.classList.remove("is-visible");

        try {
            const data = await postJson("/api/diagnostics/preflight");
            setPreflightCard("internet", data.internet || {});
            setPreflightCard("kavita", data.kavita || {});
            if (warn && data.internet && data.internet.status !== "ok") {
                warn.classList.add("is-visible");
            }
        } catch (e) {
            setPreflightCard("internet", { status: "down", detail: "error", latency_ms: null });
            setPreflightCard("kavita", { status: "down", detail: "error", latency_ms: null });
        }
    }

    async function probeOne(scraperId) {
        const row = document.querySelector(`tr[data-scraper-id="${scraperId}"]`);
        markRowRunning(row);
        try {
            const data = await postJson(`/api/scrapers/${encodeURIComponent(scraperId)}/probe`);
            applyResultToRow(row, data.result);
            return data.result;
        } catch (e) {
            applyResultToRow(row, {
                status: "down",
                cause: "network",
                latency_ms: null,
                detail: (e && e.message) || t("err_generic"),
                metadata: { status: "down" },
                covers: { status: "n_a", count: 0 },
            });
            return null;
        }
    }

    function setProbeButtonsDisabled(disabled) {
        const btnActive = document.getElementById("btnProbeActive");
        const btnAll = document.getElementById("btnProbeAll");
        if (btnActive) btnActive.disabled = disabled;
        if (btnAll) btnAll.disabled = disabled;
    }

    function setAllProbeOneEnabled(enabled) {
        document.querySelectorAll("#scrapersTable .btn-probe-one").forEach((btn) => {
            btn.disabled = !enabled;
        });
    }

    /**
     * Stream NDJSON probe-all with optional scope (active|all).
     * Per-row « Tester » stays usable for scrapers outside the current scope
     * (cascade vs all). Only the row currently being probed is disabled.
     */
    async function probeStream(scope) {
        const scopeNorm = scope === "active" ? "active" : "all";
        const allRows = Array.from(document.querySelectorAll("#scrapersTable tbody tr[data-scraper-id]"));
        const targetRows = scopeNorm === "active"
            ? allRows.filter((row) => row.getAttribute("data-active") === "1")
            : allRows;
        const targetIds = new Set(targetRows.map((row) => row.getAttribute("data-scraper-id")));
        const progress = document.getElementById("probeAllProgress");

        setProbeButtonsDisabled(true);
        // Reset only the rows that will be probed; never lock out-of-scope « Tester ».
        targetRows.forEach((row) => {
            row.classList.remove("is-probing");
            setPill(row.querySelector(".cell-global"), "idle");
        });
        // Ensure every non-target row keeps an enabled per-scraper Test button.
        allRows.forEach((row) => {
            const id = row.getAttribute("data-scraper-id");
            const b = row.querySelector(".btn-probe-one");
            if (!b) return;
            if (!targetIds.has(id)) {
                b.disabled = false;
            }
        });
        if (progress) progress.textContent = `0 / ${targetRows.length}`;

        try {
            const res = await fetch(
                root() + `/api/scrapers/probe-all?stream=1&scope=${encodeURIComponent(scopeNorm)}`,
                {
                    method: "POST",
                    headers: {
                        "Accept": "application/x-ndjson",
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: "{}",
                }
            );
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error((data && data.msg) || t("err_generic"));
            }
            if (!res.body || !res.body.getReader) {
                const data = await res.json();
                (data.results || []).forEach((r) => {
                    const row = document.querySelector(`tr[data-scraper-id="${r.id}"]`);
                    applyResultToRow(row, r);
                });
                if (progress) progress.textContent = `${(data.results || []).length} / ${targetRows.length}`;
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() || "";
                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].trim();
                    if (!line) continue;
                    let msg;
                    try {
                        msg = JSON.parse(line);
                    } catch (e) {
                        continue;
                    }
                    if (msg.type === "start" && progress) {
                        progress.textContent = `0 / ${msg.total || targetRows.length}`;
                    } else if (msg.type === "start_scraper") {
                        const row = document.querySelector(`tr[data-scraper-id="${msg.id}"]`);
                        markRowRunning(row);
                        if (progress) progress.textContent = `${msg.index - 1} / ${msg.total}`;
                    } else if (msg.type === "result" && msg.result) {
                        const row = document.querySelector(`tr[data-scraper-id="${msg.result.id}"]`);
                        applyResultToRow(row, msg.result);
                        if (progress) progress.textContent = `${msg.index} / ${msg.total}`;
                    } else if (msg.type === "done" && progress) {
                        progress.textContent = `${msg.total} / ${msg.total}`;
                    }
                }
            }
        } catch (e) {
            targetRows.forEach((row) => {
                const globalPill = row.querySelector(".cell-global .diag-pill");
                const st = globalPill && globalPill.dataset.status;
                if (st === "running" || st === "idle") {
                    applyResultToRow(row, {
                        status: "down",
                        cause: "network",
                        latency_ms: null,
                        detail: (e && e.message) || t("err_generic"),
                        metadata: { status: "down" },
                        covers: { status: "n_a", count: 0 },
                    });
                }
            });
        } finally {
            setProbeButtonsDisabled(false);
            setAllProbeOneEnabled(true);
        }
    }

    function probeActive() {
        return probeStream("active");
    }

    function probeAll() {
        return probeStream("all");
    }

    function initReveal() {
        const nodes = document.querySelectorAll(".reveal");
        if (!("IntersectionObserver" in window)) {
            nodes.forEach((n) => n.classList.add("is-in"));
            return;
        }
        const io = new IntersectionObserver((entries) => {
            entries.forEach((en) => {
                if (en.isIntersecting) {
                    en.target.classList.add("is-in");
                    io.unobserve(en.target);
                }
            });
        }, { threshold: 0.12 });
        nodes.forEach((n) => io.observe(n));
    }

    document.addEventListener("DOMContentLoaded", () => {
        initReveal();
        const btnPre = document.getElementById("btnPreflight");
        if (btnPre) btnPre.addEventListener("click", () => runPreflight());
        const btnActive = document.getElementById("btnProbeActive");
        if (btnActive) btnActive.addEventListener("click", () => probeActive());
        const btnAll = document.getElementById("btnProbeAll");
        if (btnAll) btnAll.addEventListener("click", () => probeAll());
        document.querySelectorAll(".btn-probe-one").forEach((btn) => {
            btn.addEventListener("click", () => probeOne(btn.getAttribute("data-id")));
        });
        // Préflight puis auto-probe de la cascade Config uniquement.
        (async () => {
            await runPreflight();
            await probeActive();
        })();
    });

    // Expose for providers modal reuse
    window.diagProbeScraper = probeOne;
})();
