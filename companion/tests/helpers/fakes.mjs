/**
 * Plateforme factice pour les tests unitaires de l'extension.
 *
 * Zéro dépendance : `node:test` et rien d'autre. Ce dossier n'est PAS dans la
 * liste blanche de `scripts/pack.mjs`, donc il ne part pas chez l'utilisateur
 * (même statut que `companion/scripts/`), et l'extension `.mjs` le garde hors
 * du `find … -name '*.js'` de la CI.
 */

/**
 * Réponse factice.
 *
 * ⚠️ Surtout pas un vrai `Response` : `res.url` y est en lecture seule et vaut
 * `""`, alors que `image-bridge.js` teste `/\/login\b/` dessus pour détecter
 * une redirection vers la page de login. Le test ne pourrait pas l'atteindre.
 */
export function reply({
  ok = true,
  status = 200,
  url = "",
  body = {},
  bytes = null,
  mime = "image/jpeg",
} = {}) {
  return {
    ok,
    status,
    url,
    headers: { get: (h) => (String(h).toLowerCase() === "content-type" ? mime : null) },
    json: async () => body,
    arrayBuffer: async () => (bytes ?? new Uint8Array([1, 2, 3])).buffer,
  };
}

/**
 * Installe un `fetch` factice et rend son journal.
 *
 * `route` reçoit l'URL et les options, et rend une `reply(...)`. Le journal
 * permet d'asserter ce qui est RÉELLEMENT parti sur le réseau — c'est lui qui
 * remplace les assertions textuelles sur le code source.
 */
export function installFetch(route) {
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    const entry = { url: String(url), method: opts.method || "GET", headers: opts.headers || {}, body: opts.body };
    calls.push(entry);
    const res = route(entry.url, opts);
    if (!res) throw new Error(`fetch non routé : ${entry.url}`);
    return res;
  };
  return calls;
}

/** Objet `chrome` minimal. Les modules le lisent paresseusement, dans les fonctions. */
export function installChrome({ settings = {}, granted = true } = {}) {
  const store = {
    metaBaseUrl: "",
    webhookToken: "",
    showActionFabs: true,
    cacheBustOnConfirm: true,
    uiLang: "auto",
    kavitaOrigins: [],
    pendingEnableOrigin: "",
    ...settings,
  };
  globalThis.chrome = {
    runtime: {
      id: "test-ext",
      getURL: (p) => `chrome-extension://testid/${p || ""}`,
      onMessage: { addListener() {} },
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
    },
    storage: {
      local: {
        async get(keys) {
          return Object.fromEntries((keys || Object.keys(store)).map((k) => [k, store[k]]));
        },
        async set(obj) {
          Object.assign(store, obj);
        },
      },
    },
    permissions: { contains: async () => granted, request: async () => granted, onAdded: { addListener() {} } },
    scripting: {
      getRegisteredContentScripts: async () => [],
      registerContentScripts: async () => {},
      updateContentScripts: async () => {},
      unregisterContentScripts: async () => {},
      executeScript: async () => {},
    },
    tabs: { query: async () => [], onUpdated: { addListener() {} } },
    i18n: { getUILanguage: () => "en", getMessage: () => "" },
  };
  return store;
}
