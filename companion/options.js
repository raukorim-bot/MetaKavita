import { applyI18n, setUiLang, t } from "./lib/i18n.js";
import { originFromUrl, normalizeBaseUrl } from "./lib/storage.js";
import { requestOriginPermission } from "./lib/permissions.js";

async function load() {
  const res = await chrome.runtime.sendMessage({ type: "getSettings" });
  const s = (res && res.settings) || {};
  setUiLang(s.uiLang || "auto");
  applyI18n(document);
  document.documentElement.lang = (s.uiLang === "en" || s.uiLang === "fr") ? s.uiLang : (navigator.language || "en").slice(0, 2);
  document.getElementById("metaUrl").value = s.metaBaseUrl || "";
  document.getElementById("token").value = s.webhookToken || "";
  document.getElementById("showFabs").checked = s.showActionFabs !== false;
  document.getElementById("cacheBust").checked = s.cacheBustOnConfirm !== false;
  document.getElementById("uiLang").value = s.uiLang || "auto";
}

function metaOriginFromForm() {
  return originFromUrl(normalizeBaseUrl(document.getElementById("metaUrl").value));
}

function testFailMessage(reason) {
  if (reason === "permission") return t("toastPermissionDenied");
  if (reason === "token") return t("toastTestFailToken");
  if (reason === "healthz") return t("toastTestFailHealth");
  if (reason === "network") return t("toastTestFailNetwork");
  if (reason === "config") return t("toastNeedConfig");
  return t("toastTestFail");
}

document.getElementById("btnSave").addEventListener("click", async () => {
  const status = document.getElementById("status");
  const metaOrigin = metaOriginFromForm();
  // C1 — Persist FIRST. Chrome closes the toolbar popup when the permission
  // prompt appears, which would kill the JS before a save that ran after it.
  const res = await chrome.runtime.sendMessage({
    type: "saveSettings",
    settings: {
      metaBaseUrl: document.getElementById("metaUrl").value,
      webhookToken: document.getElementById("token").value,
      showActionFabs: document.getElementById("showFabs").checked,
      cacheBustOnConfirm: document.getElementById("cacheBust").checked,
      uiLang: document.getElementById("uiLang").value,
    },
  });
  if (!res || !res.ok) {
    status.textContent = t("toastTestFail");
    return;
  }
  setUiLang(res.settings.uiLang || "auto");
  applyI18n(document);
  status.textContent = t("toastSaved");
  // Now request host access (popup may close here — settings are already saved).
  if (metaOrigin && res.permissionOk === false) {
    const granted = await requestOriginPermission(metaOrigin);
    status.textContent = granted ? t("toastSaved") : t("toastSavedNeedPermission");
  }
});

document.getElementById("btnTest").addEventListener("click", async () => {
  const status = document.getElementById("status");
  const metaOrigin = metaOriginFromForm();
  // Persist before the permission prompt (popup may close).
  await chrome.runtime.sendMessage({
    type: "saveSettings",
    settings: {
      metaBaseUrl: document.getElementById("metaUrl").value,
      webhookToken: document.getElementById("token").value,
    },
  });
  if (metaOrigin) {
    const granted = await requestOriginPermission(metaOrigin);
    if (!granted) {
      status.textContent = t("toastSavedNeedPermission");
      return;
    }
  }
  const res = await chrome.runtime.sendMessage({
    type: "testConnection",
    settings: {
      metaBaseUrl: document.getElementById("metaUrl").value,
      webhookToken: document.getElementById("token").value,
    },
  });
  const reason = res && res.result && res.result.reason;
  status.textContent =
    res && res.result && res.result.ok ? t("toastTestOk") : testFailMessage(reason);
});

document.getElementById("btnEnableSite").addEventListener("click", async () => {
  const status = document.getElementById("status");
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs && tabs[0];
    const url = tab && tab.url ? tab.url : "";
    let origin = "";
    try {
      origin = url ? new URL(url).origin : "";
    } catch {
      origin = "";
    }
    if (!origin || /^(chrome|edge|about|devtools|chrome-extension):/i.test(origin)) {
      status.textContent = t("toastNeedHosts");
      return;
    }
    const metaOrigin = metaOriginFromForm();
    if (metaOrigin && origin === metaOrigin) {
      status.textContent = t("toastMetaIsNotKavita");
      return;
    }
    // C1: persist intent before permission prompt (popup may close)
    await chrome.runtime.sendMessage({ type: "pendingEnable", origin });
    const granted = await requestOriginPermission(origin);
    if (!granted) {
      status.textContent = t("toastPermissionDenied");
      return;
    }
    const res = await chrome.runtime.sendMessage({
      type: "enableKavitaOrigin",
      origin,
      tabId: tab.id,
    });
    if (!res || !res.ok) {
      status.textContent = t("toastPermissionDenied");
      return;
    }
    // U4: always confirm site saved; optional series hint
    const path = (() => {
      try {
        return new URL(url).pathname;
      } catch {
        return "";
      }
    })();
    status.textContent = /\/library\/\d+\/series\/\d+\/?$/.test(path)
      ? t("toastSiteEnabled")
      : t("toastSiteEnabledHintSeries");
  } catch {
    status.textContent = t("toastPermissionDenied");
  }
});

load();
