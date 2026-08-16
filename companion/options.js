import { applyI18n, setUiLang, t } from "./lib/i18n.js";
import { originFromUrl, normalizeBaseUrl, isMetaKavitaUrl, tokenFromPastedUrl } from "./lib/storage.js";
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

function testFailMessage(result) {
  const reason = result && result.reason;
  if (reason === "permission") return t("toastPermissionDenied");
  if (reason === "no_url") return t("toastTestFailNoUrl");
  if (reason === "no_token" || reason === "config") return t("toastTestFailNoToken");
  if (reason === "token") return t("toastTestFailToken");
  if (reason === "healthz") return t("toastTestFailHealth");
  if (reason === "network") return t("toastTestFailNetwork");
  if (reason === "unexpected") {
    return t("toastTestFailUnexpected").replace("$1$", String((result && result.status) || "?"));
  }
  return t("toastTestFail");
}

function tokenFromForm() {
  const typed = (document.getElementById("token").value || "").trim();
  const pasted = tokenFromPastedUrl(document.getElementById("metaUrl").value);
  return typed || pasted;
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
      webhookToken: tokenFromForm(),
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
  const stored = await chrome.runtime.sendMessage({ type: "getSettings" });
  const tokenField = document.getElementById("token");
  const webhookToken =
    tokenFromForm() || ((stored && stored.settings && stored.settings.webhookToken) || "").trim();
  if (!tokenField.value && webhookToken) tokenField.value = webhookToken;
  const trial = {
    metaBaseUrl: document.getElementById("metaUrl").value,
    webhookToken,
  };
  if (!normalizeBaseUrl(trial.metaBaseUrl)) {
    status.textContent = t("toastTestFailNoUrl");
    return;
  }
  if (!webhookToken) {
    status.textContent = t("toastTestFailNoToken");
    return;
  }
  // Persist before the permission prompt (popup may close).
  await chrome.runtime.sendMessage({ type: "saveSettings", settings: trial });
  if (metaOrigin) {
    const granted = await requestOriginPermission(metaOrigin);
    if (!granted) {
      status.textContent = t("toastSavedNeedPermission");
      return;
    }
  }
  const res = await chrome.runtime.sendMessage({
    type: "testConnection",
    settings: trial,
  });
  status.textContent =
    res && res.result && res.result.ok ? t("toastTestOk") : testFailMessage(res && res.result);
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
    const metaBase = normalizeBaseUrl(document.getElementById("metaUrl").value);
    // Path-aware: same host + /kavita vs /metakavita must not be blocked (#34).
    if (isMetaKavitaUrl(url, metaBase)) {
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
      pageUrl: url,
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
