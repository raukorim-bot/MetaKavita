/**
 * DOM minimal, juste assez pour charger les overlays du Companion.
 *
 * Pas de jsdom : aucune dépendance npm dans ce dépôt. Les deux overlays ont été
 * écrits SANS `innerHTML` ni `querySelector` structurel — uniquement
 * `createElement` + `className` + `textContent` — précisément pour que ce stub
 * reste court et que les tests portent sur du vrai comportement.
 */
import vm from "node:vm";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag || "").toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.attrs = {};
    // `style.setProperty` sert aux variables CSS de la constellation (--x/--y).
    const props = {};
    this.style = {
      setProperty(k, v) {
        props[k] = String(v);
        this[k] = String(v);
      },
      getPropertyValue: (k) => props[k] || "",
    };
    this.hidden = false;
    this.disabled = false;
    this._text = "";
    this._listeners = new Map();
  }

  get textContent() {
    if (this.childNodes.length) return this.childNodes.map((c) => c.textContent).join("");
    return this._text;
  }
  set textContent(v) {
    this.childNodes = [];
    this._text = String(v == null ? "" : v);
  }

  appendChild(node) {
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }
  append(...nodes) {
    nodes.forEach((n) => this.appendChild(n));
  }
  replaceChildren(...nodes) {
    this.childNodes = [];
    nodes.forEach((n) => this.appendChild(n));
  }
  remove() {
    if (!this.parentNode) return;
    const i = this.parentNode.childNodes.indexOf(this);
    if (i !== -1) this.parentNode.childNodes.splice(i, 1);
    this.parentNode = null;
  }

  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "id") this.id = String(v);
    if (k === "class") this.className = String(v);
  }
  getAttribute(k) {
    if (k === "class" && this.className != null) return String(this.className);
    if (k === "id" && this.id != null) return String(this.id);
    return k in this.attrs ? this.attrs[k] : null;
  }
  removeAttribute(k) {
    delete this.attrs[k];
    if (k === "class") this.className = "";
  }
  hasAttribute(k) {
    return this.getAttribute(k) !== null;
  }
  focus() {}

  get classList() {
    const owner = this;
    const list = () => String(owner.className || "").split(/\s+/).filter(Boolean);
    return {
      contains: (c) => list().includes(c),
      add(c) {
        if (!list().includes(c)) owner.className = [...list(), c].join(" ");
      },
      remove(c) {
        owner.className = list().filter((x) => x !== c).join(" ");
      },
      toggle(c, on) {
        if (on === undefined ? list().includes(c) : !on) this.remove(c);
        else this.add(c);
      },
    };
  }

  /**
   * Assez de HTML pour le gabarit statique de `page-ui.js` : balises, attributs
   * entre guillemets doubles, texte. Pas un parseur — le gabarit est écrit une
   * fois et ne contient ni commentaire, ni attribut sans valeur, ni CDATA.
   */
  set innerHTML(html) {
    this.childNodes = [];
    const stack = [this];
    // Les attributs SANS valeur comptent : `<div … hidden>` et `<input … checked>`
    // sont dans le gabarit, et les ignorer faisait silencieusement échouer la
    // balise entière — les enfants atterrissaient alors chez le grand-parent.
    const token =
      /<\/([a-zA-Z0-9-]+)>|<([a-zA-Z0-9-]+)((?:\s+[a-zA-Z0-9:_-]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
    let m;
    while ((m = token.exec(html)) !== null) {
      const [, closing, opening, rawAttrs, selfClose, text] = m;
      if (closing) {
        if (stack.length > 1) stack.pop();
        continue;
      }
      if (opening) {
        const node = new FakeNode(opening);
        for (const a of rawAttrs.matchAll(/([a-zA-Z0-9:_-]+)(?:="([^"]*)")?/g)) {
          if (a[1]) node.setAttribute(a[1], a[2] === undefined ? "" : a[2]);
        }
        if ("hidden" in node.attrs) node.hidden = true;
        if ("checked" in node.attrs) node.checked = true;
        if ("value" in node.attrs) node.value = node.attrs.value;
        stack[stack.length - 1].appendChild(node);
        const voidTag = /^(img|input|br|hr|meta|link)$/i.test(opening);
        if (!selfClose && !voidTag) stack.push(node);
        continue;
      }
      if (text && text.trim()) stack[stack.length - 1]._text += text;
    }
  }

  /** Sélecteurs réellement utilisés par le code : `.classe` et `[attribut]`. */
  querySelectorAll(selector) {
    return String(selector)
      .split(",")
      .map((s) => s.trim())
      .flatMap((sel) => {
        if (sel.startsWith(".")) return this.byClass(sel.slice(1));
        if (sel.startsWith("[") && sel.endsWith("]")) {
          const attr = sel.slice(1, -1);
          return this.findAll((n) => n.getAttribute(attr) !== null);
        }
        return this.findAll((n) => n.tagName === sel.toUpperCase());
      });
  }

  getElementById(id) {
    return this.find((n) => n.id === id);
  }

  attachShadow() {
    const shadow = new FakeNode("#shadow-root");
    this._shadow = shadow;
    // `mode: "closed"` : la page n'y accède pas. On imite fidèlement.
    this.shadowRoot = null;
    return shadow;
  }

  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  dispatchEvent(ev) {
    const fns = this._listeners.get(ev.type) || [];
    fns.slice().forEach((fn) => fn.call(this, ev));
    return true;
  }

  /** Descendants, dans l'ordre du document. Suffit aux assertions des tests. */
  walk() {
    const out = [];
    for (const c of this.childNodes) {
      out.push(c, ...c.walk());
    }
    return out;
  }
  find(predicate) {
    return this.walk().find(predicate) || null;
  }
  findAll(predicate) {
    return this.walk().filter(predicate);
  }
  byClass(cls) {
    return this.findAll((n) => String(n.className || "").split(/\s+/).includes(cls));
  }
}

/**
 * Monte un contexte vierge et y charge les content scripts demandés, dans
 * l'ordre RÉEL de production (`WATCH_FILES`) quand aucun n'est précisé.
 */
export function loadContentScripts({
  files,
  chrome,
  protocol = "https:",
  origin = "https://kavita.example",
  innerWidth = 1440,
  innerHeight = 900,
}) {
  const documentElement = new FakeNode("html");
  const document = {
    documentElement,
    createElement: (tag) => new FakeNode(tag),
    // Une vraie recherche, sinon le code qui RÉUTILISE un nœud existant (le
    // toast) en recrée un à chaque appel sans que rien ne le signale.
    getElementById: (id) => documentElement.getElementById(id),
    querySelectorAll: (sel) => documentElement.querySelectorAll(sel),
    addEventListener(type, fn) {
      documentElement.addEventListener(type, fn);
    },
    dispatchEvent: (ev) => documentElement.dispatchEvent(ev),
  };

  const windowListeners = new Map();
  const opened = [];
  const window = {
    addEventListener(type, fn) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(fn);
    },
    dispatchEvent(ev) {
      (windowListeners.get(ev.type) || []).slice().forEach((fn) => fn(ev));
      return true;
    },
    open(url) {
      const win = { url, closed: false, focus() {}, location: { replace() {} } };
      opened.push(win);
      return win;
    },
    setTimeout,
    clearTimeout,
    innerWidth,
    innerHeight,
  };

  const location = { protocol, origin, pathname: "/", href: origin + "/" };
  const ctx = vm.createContext({
    chrome,
    document,
    window,
    location,
    console,
    URL,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
  });
  ctx.globalThis = ctx;

  for (const rel of files) {
    vm.runInContext(readFileSync(join(ROOT, rel), "utf8"), ctx, { filename: rel });
  }

  /**
   * Point de montage de secours, pour tester un overlay SANS charger
   * `page-ui.js`. Quand ce dernier est chargé, c'est lui qui fournit le vrai
   * `createOverlayLayer` — on ne l'écrase surtout pas.
   */
  const shadow = new FakeNode("div");
  if (!window.__mkCompanionPageUI) window.__mkCompanionPageUI = {
    createOverlayLayer(name, onDestroy) {
      const node = shadow.appendChild(new FakeNode("div"));
      const handle = {
        node,
        destroy() {
          node.remove();
          if (typeof onDestroy === "function") onDestroy();
        },
      };
      return handle;
    },
  };

  /** Simule une navigation SPA : Kavita pousse l'URL puis Angular re-rend. */
  function navigate(pathname) {
    location.pathname = pathname;
    location.href = origin + pathname;
    window.dispatchEvent({ type: "mk-companion-nav" });
  }

  return { ctx, window, document, shadow, opened, location, navigate };
}

export { FakeNode };
