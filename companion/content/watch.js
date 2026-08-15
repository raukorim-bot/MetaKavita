(function () {
  "use strict";

  if (window.__mkCompanionWatch) {
    window.dispatchEvent(new Event("mk-companion-nav"));
    return;
  }
  window.__mkCompanionWatch = true;

  // Series detail only — not /manga/, /book/, /chapter/ reader subpaths.
  const SERIES_RE = /\/library\/(\d+)\/series\/(\d+)\/?$/;
  const MR_ID = "mk-companion-mr";
  const COVER_ID = "mk-companion-cover";
  let appearTimer = null;
  let lastSeriesId = null;
  let mrState = null;

  function parseSeriesId(pathname) {
    const m = SERIES_RE.exec(pathname || "");
    return m ? m[2] : null;
  }

  function showPageToast(text, isError) {
    let el = document.getElementById("mk-companion-page-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "mk-companion-page-toast";
      Object.assign(el.style, {
        position: "fixed",
        right: "16px",
        bottom: "88px",
        zIndex: "2147483647",
        maxWidth: "280px",
        padding: "10px 12px",
        borderRadius: "10px",
        background: "#1e293b",
        color: "#e2e8f0",
        border: "1px solid rgba(148,163,184,0.4)",
        font: "600 12px/1.35 Segoe UI, system-ui, sans-serif",
        pointerEvents: "none",
        opacity: "0",
        transition: "opacity 0.2s ease",
      });
      document.documentElement.appendChild(el);
    }
    el.textContent = text || "";
    el.style.borderColor = isError ? "#f87171" : "rgba(148,163,184,0.4)";
    el.style.opacity = "1";
    clearTimeout(el.__mkTimer);
    el.__mkTimer = setTimeout(() => {
      el.style.opacity = "0";
    }, 3200);
  }

  window.__mkCompanionShowToast = showPageToast;

  function softCacheBust(seriesId) {
    const ts = Date.now();
    const imgs = document.querySelectorAll(
      "img.cover, img.card-img-top, img[class*='cover'], img[src*='/api/image'], img[src*='cover']"
    );
    const list = imgs.length ? imgs : document.querySelectorAll("img[src]");
    list.forEach((img) => {
      const src = img.getAttribute("src") || "";
      if (!src) return;
      const lower = src.toLowerCase();
      if (
        lower.includes(String(seriesId)) ||
        lower.includes("cover") ||
        lower.includes("/api/image")
      ) {
        try {
          const u = new URL(src, location.origin);
          u.searchParams.set("_mkcb", String(ts));
          img.src = u.toString();
        } catch {
          img.src = src + (src.includes("?") ? "&" : "?") + "_mkcb=" + ts;
        }
      }
    });
  }

  function removeUi() {
    if (window.__mkCompanionPageUI) window.__mkCompanionPageUI.unmount();
    lastSeriesId = null;
  }

  function mountUi(seriesId) {
    if (lastSeriesId === seriesId && document.getElementById("mk-companion-page-host")) {
      if (window.__mkCompanionPageUI) window.__mkCompanionPageUI.setSeriesId(seriesId);
      return;
    }
    if (!chrome.runtime?.id) {
      removeUi();
      return;
    }
    lastSeriesId = seriesId;
    if (window.__mkCompanionPageUI) {
      window.__mkCompanionPageUI.mount(seriesId);
    }
  }

  function schedule() {
    if (appearTimer) {
      clearTimeout(appearTimer);
      appearTimer = null;
    }
    if (!chrome.runtime?.id) {
      removeUi();
      removeMr();
      removeCover();
      return;
    }
    const seriesId = parseSeriesId(location.pathname);
    if (!seriesId) {
      removeUi();
      removeMr();
      removeCover();
      return;
    }
    appearTimer = setTimeout(function () {
      if (parseSeriesId(location.pathname) === seriesId) {
        mountUi(seriesId);
      }
    }, 400);
  }

  function patchHistory() {
    const wrap = (fn) =>
      function () {
        const ret = fn.apply(this, arguments);
        window.dispatchEvent(new Event("mk-companion-nav"));
        return ret;
      };
    try {
      history.pushState = wrap(history.pushState.bind(history));
      history.replaceState = wrap(history.replaceState.bind(history));
    } catch {
      /* ignore */
    }
    window.addEventListener("popstate", schedule);
    window.addEventListener("mk-companion-nav", schedule);
  }

  function removeMr() {
    const el = document.getElementById(MR_ID);
    if (el) el.remove();
    if (mrState && mrState.readyTimer) clearTimeout(mrState.readyTimer);
    mrState = null;
  }

  function showMrFallback() {
    if (!mrState || !mrState.fallback) return;
    mrState.fallback.hidden = false;
    showPageToast(mrState.labels.timeout, true);
  }

  function openMrOverlay(opts) {
    removeMr();
    removeCover();
    const labels = (opts && opts.labels) || {};
    const backdrop = document.createElement("div");
    backdrop.id = MR_ID;
    Object.assign(backdrop.style, {
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      background: "rgba(2, 6, 23, 0.72)",
      backdropFilter: "blur(2px)",
      WebkitBackdropFilter: "blur(2px)",
    });
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) removeMr();
    });

    const iframe = document.createElement("iframe");
    iframe.title = "MetaKavita Super Review";
    iframe.setAttribute("allow", "clipboard-write");
    Object.assign(iframe.style, {
      position: "absolute",
      top: "3%",
      left: "3%",
      width: "94%",
      height: "94%",
      border: "0",
      borderRadius: "12px",
      background: "#0f1419",
      boxShadow: "0 24px 64px rgba(0, 0, 0, 0.55)",
    });
    iframe.src = opts.url;

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.textContent = labels.close || "Close";
    Object.assign(closeBtn.style, {
      position: "absolute",
      top: "calc(3% - 6px)",
      right: "3.2%",
      transform: "translateY(-100%)",
      zIndex: "1",
      padding: "6px 14px",
      borderRadius: "8px",
      border: "1px solid rgba(148,163,184,0.5)",
      background: "rgba(15,23,42,0.9)",
      color: "#e2e8f0",
      font: "600 12px/1 Segoe UI, system-ui, sans-serif",
      cursor: "pointer",
    });
    closeBtn.addEventListener("click", removeMr);

    const fallback = document.createElement("div");
    fallback.hidden = true;
    Object.assign(fallback.style, {
      position: "absolute",
      top: "50%",
      left: "50%",
      transform: "translate(-50%, -50%)",
      maxWidth: "26rem",
      padding: "24px",
      textAlign: "center",
      borderRadius: "12px",
      background: "#1e293b",
      color: "#e2e8f0",
      boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
      font: "500 13px/1.5 Segoe UI, system-ui, sans-serif",
    });
    const fbText = document.createElement("p");
    fbText.textContent = labels.blocked || "Super Review couldn't load here.";
    Object.assign(fbText.style, { margin: "0 0 14px", color: "#94a3b8" });
    const fbLink = document.createElement("a");
    fbLink.textContent = labels.openTab || "Open in a new tab";
    fbLink.href = opts.url;
    fbLink.target = "_blank";
    // Keep opener so the tab can focus Kavita + close itself when MR finishes.
    Object.assign(fbLink.style, {
      display: "inline-block",
      padding: "8px 14px",
      borderRadius: "8px",
      background: "#38bdf8",
      color: "#0b1220",
      fontWeight: "650",
      textDecoration: "none",
    });
    fbLink.addEventListener("click", (ev) => {
      ev.preventDefault();
      window.open(opts.url, "_blank");
      window.setTimeout(removeMr, 150);
    });
    fallback.appendChild(fbText);
    fallback.appendChild(fbLink);

    backdrop.appendChild(iframe);
    backdrop.appendChild(closeBtn);
    backdrop.appendChild(fallback);
    document.documentElement.appendChild(backdrop);

    mrState = {
      iframe,
      fallback,
      labels,
      metaOrigin: opts.metaOrigin || "",
      cacheBust: !!opts.cacheBust,
      seriesId: opts.seriesId || lastSeriesId,
      ready: false,
      readyTimer: null,
    };
    mrState.readyTimer = setTimeout(() => {
      if (mrState && !mrState.ready) showMrFallback();
    }, 7000);
  }

  window.__mkCompanionOpenMr = openMrOverlay;

  function removeCover() {
    const el = document.getElementById(COVER_ID);
    if (el) el.remove();
  }

  /**
   * Cover previews go through the service worker in two cases.
   *
   * A proxied preview needs MetaKavita credentials, and an <img> carries
   * neither cookies (cross-site) nor headers. Putting the embed token in the
   * URL did work, and handed a token good for every review route of the series
   * to any script reading the src attribute. The worker sends it as a header
   * and returns the bytes inline.
   *
   * And an http:// preview is blocked outright as mixed content on an https://
   * Kavita page; worker fetches are exempt.
   */
  function coverNeedsImageBridge(url) {
    if (!url || /^data:/i.test(url)) return false;
    if (url.indexOf("/api/proxy-image") !== -1) return true;
    return location.protocol === "https:" && /^http:\/\//i.test(url);
  }

  async function bridgeCoverImage(img, url, seriesId, onFail) {
    let error = "unavailable";
    try {
      const res = await chrome.runtime.sendMessage({
        type: "fetchImageData",
        url,
        seriesId,
      });
      if (res && res.ok && res.dataUrl) {
        img.src = res.dataUrl;
        return true;
      }
      error = (res && res.error) || error;
    } catch {
      error = "extension_reloaded";
    }
    if (typeof onFail === "function") onFail(error, url);
    return false;
  }

  function setCoverImageSrc(img, url, seriesId, onFail) {
    if (!url) return;
    if (coverNeedsImageBridge(url)) {
      bridgeCoverImage(img, url, seriesId, onFail);
      return;
    }
    img.addEventListener(
      "error",
      () => {
        bridgeCoverImage(img, url, seriesId, onFail);
      },
      { once: true }
    );
    img.src = url;
  }

  function openCoverPicker(opts) {
    removeCover();
    removeMr();
    const labels = (opts && opts.labels) || {};
    const seriesId = opts.seriesId;
    const seriesName = opts.seriesName || "";

    const backdrop = document.createElement("div");
    backdrop.id = COVER_ID;
    Object.assign(backdrop.style, {
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      background: "rgba(2, 6, 23, 0.72)",
      backdropFilter: "blur(2px)",
      WebkitBackdropFilter: "blur(2px)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
    });
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) removeCover();
    });

    const panel = document.createElement("div");
    Object.assign(panel.style, {
      width: "min(920px, 100%)",
      maxHeight: "min(86vh, 820px)",
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      borderRadius: "14px",
      background: "#1e293b",
      color: "#e2e8f0",
      boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
      border: "1px solid rgba(148,163,184,0.28)",
    });

    const header = document.createElement("div");
    Object.assign(header.style, {
      display: "flex",
      alignItems: "center",
      gap: "10px",
      padding: "14px 16px",
      borderBottom: "1px solid rgba(148,163,184,0.2)",
    });
    const title = document.createElement("strong");
    title.textContent = labels.title || "Cover";
    title.style.flex = "1";
    title.style.font = "650 15px/1.2 Segoe UI, system-ui, sans-serif";

    const search = document.createElement("input");
    search.type = "text";
    search.value = seriesName;
    Object.assign(search.style, {
      flex: "1.4",
      padding: "8px 10px",
      borderRadius: "8px",
      border: "1px solid rgba(148,163,184,0.35)",
      background: "#0f172a",
      color: "#e2e8f0",
      font: "500 13px Segoe UI, system-ui, sans-serif",
    });

    const btnSearch = document.createElement("button");
    btnSearch.type = "button";
    btnSearch.textContent = labels.search || "Search";
    Object.assign(btnSearch.style, {
      padding: "8px 12px",
      borderRadius: "8px",
      border: "0",
      background: "#38bdf8",
      color: "#0b1220",
      font: "650 12px Segoe UI, system-ui, sans-serif",
      cursor: "pointer",
    });

    const btnClose = document.createElement("button");
    btnClose.type = "button";
    btnClose.textContent = labels.close || "Close";
    Object.assign(btnClose.style, {
      padding: "8px 12px",
      borderRadius: "8px",
      border: "1px solid rgba(148,163,184,0.4)",
      background: "transparent",
      color: "#e2e8f0",
      font: "650 12px Segoe UI, system-ui, sans-serif",
      cursor: "pointer",
    });
    btnClose.addEventListener("click", removeCover);

    header.appendChild(title);
    header.appendChild(search);
    header.appendChild(btnSearch);
    header.appendChild(btnClose);

    const status = document.createElement("div");
    Object.assign(status.style, {
      padding: "8px 16px",
      font: "500 12px Segoe UI, system-ui, sans-serif",
      color: "#94a3b8",
    });

    const grid = document.createElement("div");
    Object.assign(grid.style, {
      padding: "12px 16px 18px",
      overflow: "auto",
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
      gap: "12px",
      minHeight: "200px",
    });

    async function loadCovers() {
      const q = (search.value || seriesName || "").trim();
      grid.innerHTML = "";
      status.textContent = labels.searching || "Searching…";
      btnSearch.disabled = true;
      try {
        const res = await chrome.runtime.sendMessage({
          type: "fetchCovers",
          seriesId,
          seriesName: q,
        });
        btnSearch.disabled = false;
        if (!res || !res.ok) {
          status.textContent = (res && res.error) || labels.empty || "No covers";
          return;
        }
        const covers = res.covers || [];
        if (!covers.length) {
          status.textContent = labels.empty || "No covers found";
          return;
        }
        status.textContent = covers.length + " cover(s)";
        let previewErrorReported = false;
        const reportPreviewError = (error, failedUrl) => {
          console.warn(
            "[MetaKavita Companion] cover preview failed (" + error + "):",
            failedUrl
          );
          if (previewErrorReported) return;
          previewErrorReported = true;
          status.textContent =
            error === "meta_login_required"
              ? labels.previewLogin || "Previews refused by MetaKavita"
              : (labels.previewFail || "Preview unavailable") + " (" + error + ")";
        };
        covers.forEach((cover) => {
          const card = document.createElement("button");
          card.type = "button";
          Object.assign(card.style, {
            border: "1px solid rgba(148,163,184,0.25)",
            borderRadius: "10px",
            padding: "6px",
            background: "#0f172a",
            cursor: "pointer",
            color: "#e2e8f0",
            textAlign: "left",
          });
          const img = document.createElement("img");
          img.alt = "";
          img.title = cover.title || "";
          img.loading = "lazy";
          Object.assign(img.style, {
            width: "100%",
            aspectRatio: "2 / 3",
            objectFit: "cover",
            borderRadius: "6px",
            display: "block",
            background: "#020617",
          });
          setCoverImageSrc(
            img,
            cover.display_url || cover.url || "",
            seriesId,
            reportPreviewError
          );
          const cap = document.createElement("div");
          Object.assign(cap.style, {
            marginTop: "6px",
            font: "600 11px/1.3 Segoe UI, system-ui, sans-serif",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          });
          cap.textContent = cover.provider || cover.title || "";
          card.appendChild(img);
          card.appendChild(cap);
          card.addEventListener("click", async () => {
            status.textContent = "…";
            const apply = await chrome.runtime.sendMessage({
              type: "applyCover",
              seriesId,
              seriesName,
              coverUrl: cover.url,
            });
            if (apply && apply.ok) {
              showPageToast(labels.applied || "Cover applied");
              softCacheBust(seriesId);
              removeCover();
            } else {
              showPageToast(labels.fail || "Failed", true);
              status.textContent = labels.fail || "Failed";
            }
          });
          grid.appendChild(card);
        });
      } catch {
        btnSearch.disabled = false;
        status.textContent = labels.fail || "Failed";
      }
    }

    btnSearch.addEventListener("click", loadCovers);
    search.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        loadCovers();
      }
    });

    panel.appendChild(header);
    panel.appendChild(status);
    panel.appendChild(grid);
    backdrop.appendChild(panel);
    document.documentElement.appendChild(backdrop);
    loadCovers();
  }

  window.__mkCompanionOpenCover = openCoverPicker;

  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (document.getElementById(COVER_ID)) {
      removeCover();
      return;
    }
    if (mrState) removeMr();
  });

  window.addEventListener("message", (ev) => {
    const data = ev.data;
    if (!data) return;

    // Only the MetaKavita embed talks to this page. The extension UI is a
    // shadow root in this same document, not an iframe, so there is no second
    // sender to accept — the old overlay bridge took orders from any window
    // and opened the URL it was handed.
    if (data.source !== "metakavita-companion") return;

    // Super Review opened as a top-level tab (mixed content) posts mk:mr-done
    // to window.opener — no in-page iframe involved.
    if (data.type === "mk:mr-done" && (!mrState || !mrState.iframe)) {
      if (data.outcome === "confirm" && data.seriesId) {
        softCacheBust(String(data.seriesId));
      }
      return;
    }

    if (!mrState || !mrState.iframe || ev.source !== mrState.iframe.contentWindow) return;
    if (mrState.metaOrigin && ev.origin !== mrState.metaOrigin) return;
    if (data.type === "mk:embed-ready") {
      mrState.ready = true;
      clearTimeout(mrState.readyTimer);
      mrState.readyTimer = null;
      if (mrState.fallback) mrState.fallback.hidden = true;
      return;
    }
    if (data.type === "mk:mr-timeout") {
      showPageToast(mrState.labels.timeout, true);
      return;
    }
    if (data.type === "mk:mr-done") {
      if (data.outcome === "confirm" && mrState.cacheBust) {
        softCacheBust(mrState.seriesId || lastSeriesId);
      }
      removeMr();
    }
  });

  patchHistory();
  schedule();
})();
