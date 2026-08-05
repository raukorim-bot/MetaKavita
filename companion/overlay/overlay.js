import { applyI18n, setUiLang, t } from "../lib/i18n.js";
import { originFromUrl, normalizeBaseUrl } from "../lib/storage.js";
import { requestOriginPermission } from "../lib/permissions.js";

const params = new URLSearchParams(location.search);
const seriesIdParam = params.get("seriesId");
const kavitaOrigin = params.get("kavitaOrigin") || "";

const fabStack = document.getElementById("fabStack");
const fabActions = document.getElementById("fabActions");
const btnLogo = document.getElementById("btnLogo");
const btnSuper = document.getElementById("btnSuper");
const btnAuto = document.getElementById("btnAuto");
const btnConfig = document.getElementById("btnConfig");
const configPanel = document.getElementById("configPanel");
const toastEl = document.getElementById("toast");

let settings = null;
let toastTimer = null;
let menuOpen = false;
let boxTimer = null;

function resolvedSeriesId() {
  const n = parseInt(String(seriesIdParam || ""), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

// All FABs are the same 46px circle, so the arc math is a closed-form
// formula (chord length between two points on a circle) instead of a
// fragile per-pair collision loop — every gap comes out identical.
const FAB_DIAMETER = 46;
const FAB_GAP = 14;
const ARC_RANGES = {
  1: [135, 135],
  2: [118, 158],
  3: [104, 168],
  4: [98, 174],
  5: [93, 178],
};

function layoutArc() {
  const fabs = Array.from(fabActions.querySelectorAll(".fab")).filter(
    (el) => el.style.display !== "none"
  );
  const n = fabs.length;
  if (!n) return;

  const [start, end] = ARC_RANGES[Math.min(n, 5)] || ARC_RANGES[5];
  let radius;
  if (n === 1) {
    radius = 92;
  } else {
    const stepRad = (((end - start) / (n - 1)) * Math.PI) / 180;
    const chordMin = FAB_DIAMETER + FAB_GAP;
    radius = Math.round(chordMin / (2 * Math.sin(stepRad / 2)));
  }

  fabs.forEach((el, i) => {
    const t = n === 1 ? 0.5 : i / (n - 1);
    const rad = ((start + (end - start) * t) * Math.PI) / 180;
    el.style.setProperty("--x", `${Math.round(Math.cos(rad) * radius)}px`);
    el.style.setProperty("--y", `${Math.round(-Math.sin(rad) * radius)}px`);
    el.style.setProperty("--delay", `${(n - 1 - i) * 0.03}s`);
  });
}

function publishBox() {
  clearTimeout(boxTimer);
  boxTimer = setTimeout(() => {
    try {
      const nodes = [];
      if (!fabStack.hidden) {
        nodes.push(fabStack);
        if (menuOpen) {
          fabActions.querySelectorAll(".fab").forEach((el) => {
            if (el.style.display !== "none") nodes.push(el);
          });
        }
      }
      if (configPanel.classList.contains("is-open")) nodes.push(configPanel);
      let maxR = 0;
      let maxB = 0;
      const vw = window.innerWidth || 76;
      const vh = window.innerHeight || 76;
      nodes.forEach((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width && !r.height) return;
        maxR = Math.max(maxR, vw - r.left);
        maxB = Math.max(maxB, vh - r.top);
      });
      // +14 leaves room for the logo glow/shadow without clipping (overflow:hidden iframe)
      const width = Math.ceil(Math.max(88, maxR + 14));
      const height = Math.ceil(Math.max(88, maxB + 14));
      window.parent.postMessage(
        {
          source: "metakavita-companion-overlay",
          type: "mk:set-box",
          width,
          height,
        },
        "*"
      );
    } catch {
      /* ignore */
    }
  }, 16);
}

function setMenuOpen(open) {
  menuOpen = !!open;
  btnLogo.setAttribute("aria-expanded", menuOpen ? "true" : "false");
  if (menuOpen) {
    fabActions.hidden = false;
    layoutArc();
    requestAnimationFrame(() => {
      layoutArc();
      fabStack.classList.add("is-open");
      publishBox();
    });
  } else {
    fabStack.classList.remove("is-open");
    window.setTimeout(() => {
      if (!menuOpen) fabActions.hidden = true;
      publishBox();
    }, 320);
  }
  publishBox();
}

function showToast(msg, isError) {
  // Never show toast inside the extension iframe — it expands the opaque
  // chrome-extension canvas into a white/dark rectangle. Page toast only.
  try {
    window.parent.postMessage(
      {
        source: "metakavita-companion-overlay",
        type: "mk:page-toast",
        message: msg,
        error: !!isError,
      },
      "*"
    );
  } catch {
    /* ignore */
  }
  toastEl.classList.remove("is-show");
  clearTimeout(toastTimer);
}

function refreshFabVisibility() {
  const show = !settings || settings.showActionFabs !== false;
  const btnCover = document.getElementById("btnCover");
  btnSuper.style.display = show ? "" : "none";
  btnAuto.style.display = show ? "" : "none";
  if (btnCover) btnCover.style.display = show ? "" : "none";
  if (menuOpen) layoutArc();
  publishBox();
}

function fillForm() {
  document.getElementById("metaUrl").value = (settings && settings.metaBaseUrl) || "";
  document.getElementById("token").value = (settings && settings.webhookToken) || "";
  document.getElementById("showFabs").checked = !settings || settings.showActionFabs !== false;
  document.getElementById("cacheBust").checked = !settings || settings.cacheBustOnConfirm !== false;
  document.getElementById("uiLang").value = (settings && settings.uiLang) || "auto";
}

async function reloadSettings() {
  const res = await chrome.runtime.sendMessage({ type: "getSettings" });
  settings = (res && res.settings) || {};
  setUiLang(settings.uiLang || "auto");
  applyI18n(document);
  const lang =
    settings.uiLang === "en" || settings.uiLang === "fr"
      ? settings.uiLang
      : (chrome.i18n.getUILanguage() || "en").slice(0, 2);
  document.documentElement.lang = lang;
  fillForm();
  refreshFabVisibility();
}

function openConfig() {
  setMenuOpen(false);
  configPanel.classList.add("is-open");
  publishBox();
  const first = configPanel.querySelector("input, select, button");
  if (first) first.focus();
}

function closeConfig() {
  configPanel.classList.remove("is-open");
  publishBox();
}

async function openMr() {
  if (!settings || !settings.metaBaseUrl) {
    showToast(t("toastNeedConfig"), true);
    openConfig();
    return;
  }
  const sid = resolvedSeriesId();
  if (!sid) {
    showToast(t("toastNeedSeriesPage"), true);
    return;
  }
  closeConfig();
  setMenuOpen(false);
  const base = String(settings.metaBaseUrl).replace(/\/+$/, "");
  const parentOrigin = chrome.runtime.getURL("").replace(/\/$/, "");

  let embedToken = "";
  try {
    const tokRes = await chrome.runtime.sendMessage({
      type: "embedToken",
      seriesId: sid,
      parentOrigin,
    });
    if (tokRes && tokRes.ok && tokRes.embed_token) {
      embedToken = tokRes.embed_token;
    }
  } catch {
    /* fall through — session cookie may still work same-site */
  }

  const url = new URL(base + "/companion/embed");
  url.searchParams.set("series_id", String(sid));
  url.searchParams.set("parent_origin", parentOrigin);
  // The Kavita page is both the top ancestor (CSP) and the real postMessage
  // parent once watch.js injects the MR iframe directly into it (http-in-http).
  if (kavitaOrigin) url.searchParams.set("top_origin", kavitaOrigin);
  if (embedToken) url.searchParams.set("embed_token", embedToken);

  const finalUrl = url.toString();
  const metaOrigin = originFromUrl(normalizeBaseUrl(settings.metaBaseUrl));
  // HTTPS Kavita cannot load an HTTP MetaKavita iframe (mixed content).
  let kavitaIsHttps = false;
  try {
    kavitaIsHttps = new URL(kavitaOrigin || "http://local").protocol === "https:";
  } catch {
    kavitaIsHttps = false;
  }
  if (kavitaIsHttps && /^http:/i.test(base)) {
    showToast(t("toastMixedContentTab"));
    window.parent.postMessage(
      { source: "metakavita-companion-overlay", type: "mk:open-mr-tab", url: finalUrl },
      "*"
    );
    return;
  }

  // Inject Super Review into the Kavita page (same scheme → no mixed content).
  window.parent.postMessage(
    {
      source: "metakavita-companion-overlay",
      type: "mk:open-mr",
      url: finalUrl,
      metaOrigin,
      seriesId: sid,
      cacheBust: !(settings && settings.cacheBustOnConfirm === false),
      labels: {
        blocked: t("mrEmbedBlocked"),
        openTab: t("mrOpenInTab"),
        close: t("close"),
        timeout: t("toastMrTimeout"),
        login: t("toastNeedMetaLogin"),
      },
    },
    "*"
  );
}

async function runWebhook(payload) {
  const sid = resolvedSeriesId();
  if (!sid) {
    showToast(t("toastNeedSeriesPage"), true);
    return false;
  }
  try {
    const res = await chrome.runtime.sendMessage({
      type: "webhook",
      payload: { ...payload, seriesId: sid },
    });
    if (!res || !res.ok) {
      const err = (res && res.error) || "error";
      const code = res && res.code;
      if (err === "not_configured") {
        showToast(t("toastNeedConfig"), true);
        openConfig();
        return false;
      }
      if (err === "missing_series_id" || code === "missing_series_id") {
        showToast(t("toastNeedSeriesPage"), true);
        return false;
      }
      if (code === "kavita_unreachable" || code === "kavita_auth") {
        showToast(t("toastKavitaUnreachable"), true);
        return false;
      }
      if (code === "series_not_found") {
        showToast(t("toastSeriesNotFound"), true);
        return false;
      }
      showToast(t("toastError").replace("$1$", err) || err, true);
      return false;
    }
    return true;
  } catch {
    showToast(t("toastExtensionReloaded"), true);
    return false;
  }
}

btnLogo.addEventListener("click", () => {
  if (configPanel.classList.contains("is-open")) {
    closeConfig();
    return;
  }
  setMenuOpen(!menuOpen);
});

btnConfig.addEventListener("click", () => {
  setMenuOpen(false);
  if (configPanel.classList.contains("is-open")) closeConfig();
  else openConfig();
});

document.getElementById("btnBmc").addEventListener("click", () => {
  window.open("https://buymeacoffee.com/raukorim", "_blank", "noopener,noreferrer");
});

document.getElementById("btnCloseConfig").addEventListener("click", closeConfig);

document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  if (configPanel.classList.contains("is-open")) {
    closeConfig();
    return;
  }
  if (menuOpen) setMenuOpen(false);
});

document.getElementById("btnSave").addEventListener("click", async () => {
  const partial = {
    metaBaseUrl: document.getElementById("metaUrl").value,
    webhookToken: document.getElementById("token").value,
    showActionFabs: document.getElementById("showFabs").checked,
    cacheBustOnConfirm: document.getElementById("cacheBust").checked,
    uiLang: document.getElementById("uiLang").value,
  };
  const metaOrigin = originFromUrl(normalizeBaseUrl(partial.metaBaseUrl));
  if (metaOrigin) await requestOriginPermission(metaOrigin);
  const res = await chrome.runtime.sendMessage({ type: "saveSettings", settings: partial });
  if (!res || !res.ok) {
    showToast(t("toastPermissionDenied"), true);
    return;
  }
  settings = res.settings;
  setUiLang(settings.uiLang || "auto");
  applyI18n(document);
  refreshFabVisibility();
  showToast(res.permissionOk === false ? t("toastSavedNeedPermission") : t("toastSaved"));
});

document.getElementById("btnTest").addEventListener("click", async () => {
  const trial = {
    metaBaseUrl: document.getElementById("metaUrl").value,
    webhookToken: document.getElementById("token").value,
  };
  const metaOrigin = originFromUrl(normalizeBaseUrl(trial.metaBaseUrl));
  if (metaOrigin && !(await requestOriginPermission(metaOrigin))) {
    showToast(t("toastPermissionDenied"), true);
    return;
  }
  const res = await chrome.runtime.sendMessage({ type: "testConnection", settings: trial });
  if (res && res.result && res.result.ok) showToast(t("toastTestOk"));
  else {
    const reason = res && res.result && res.result.reason;
    if (reason === "token") showToast(t("toastTestFailToken"), true);
    else if (reason === "healthz") showToast(t("toastTestFailHealth"), true);
    else if (reason === "network") showToast(t("toastTestFailNetwork"), true);
    else showToast(t("toastTestFail"), true);
  }
});

document.getElementById("btnEnableSite").addEventListener("click", async () => {
  if (!kavitaOrigin) {
    showToast(t("toastNeedHosts"), true);
    return;
  }
  const metaOrigin = originFromUrl(normalizeBaseUrl((settings && settings.metaBaseUrl) || ""));
  if (metaOrigin && kavitaOrigin === metaOrigin) {
    showToast(t("toastMetaIsNotKavita"), true);
    return;
  }
  await chrome.runtime.sendMessage({ type: "pendingEnable", origin: kavitaOrigin });
  if (!(await requestOriginPermission(kavitaOrigin))) {
    showToast(t("toastPermissionDenied"), true);
    return;
  }
  const res = await chrome.runtime.sendMessage({
    type: "enableKavitaOrigin",
    origin: kavitaOrigin,
  });
  if (res && res.ok) showToast(t("toastSiteEnabled"));
  else showToast(t("toastPermissionDenied"), true);
});

btnAuto.addEventListener("click", async () => {
  btnAuto.disabled = true;
  try {
    const ok = await runWebhook({ force: true, auto: true });
    if (ok) {
      setMenuOpen(false);
      showToast(t("toastQueued"));
    }
  } finally {
    btnAuto.disabled = false;
  }
});

btnSuper.addEventListener("click", async () => {
  btnSuper.disabled = true;
  try {
    const ok = await runWebhook({ force: true, super_review: true });
    if (ok) await openMr();
  } finally {
    btnSuper.disabled = false;
  }
});

window.addEventListener("resize", publishBox);

reloadSettings()
  .then(() => {
    requestAnimationFrame(() => {
      fabStack.classList.add("is-visible");
      publishBox();
    });
    if (!settings || !settings.metaBaseUrl || !settings.webhookToken) {
      openConfig();
    }
  })
  .catch(() => {
    showToast(t("toastExtensionReloaded"), true);
  });
