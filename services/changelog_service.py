"""
Lecture et rendu de CHANGELOG.md : numéro de version courant (affiché dans le
titre de l'UI) et rendu HTML de la modale « Nouveautés ».

Extrait de l'ancien `app.py`. Volontairement sans dépendance vers `app.py` ni
`routes/` pour être importable des deux côtés sans import circulaire :
`app.py` l'utilise pour le `context_processor` global, `routes/misc.py`
l'utilise pour l'endpoint `/api/changelog`.

Le rendu n'est pas une conversion markdown générique : il reconstruit la
**structure** du fichier — une version, ses sections, ses entrées — parce que
c'est cette structure qui rend la modale lisible. Trois décisions y tiennent :

* **Une seule langue.** Chaque version du fichier porte un bloc `EN` et un bloc
  `FR`. Les rendre tous les deux doublait la longueur de la modale et personne
  ne lit la moitié qui n'est pas la sienne. Une version qui n'aurait pas la
  langue demandée est rendue telle quelle plutôt que vide.
* **Seule la dernière version est ouverte.** Les précédentes deviennent des
  `<details>` : le fichier fait un millier de lignes, et ce qu'on vient lire
  après une mise à jour est ce qui vient de changer.
* **Titre et corps séparés.** Une entrée s'écrit `**Titre** — corps`. Aplatir
  les deux dans le même paragraphe donnait des pavés de quatre cents mots sans
  rien à survoler.

Les queues `Tests : …` sont retirées du rendu : elles servent au mainteneur, pas
à celui qui lit les nouveautés, et elles restent dans le fichier.
"""

import html
import logging
import os
import re

_cached_version = None

# Une entrée : `**C69. Titre** — corps`, `**Titre :** corps` ou `**Titre.**
# corps`. Le titre est le gras de tête, et il ne peut pas contenir d'astérisque :
# sinon le moteur élargit sa capture jusqu'au gras suivant et fabrique un titre
# de quatre lignes, ce qui est exactement ce qu'il s'est passé.
_ITEM_RE = re.compile(r'^\*\*(?P<head>[^*]+)\*\*\s*(?:[—–:-]\s*)?(?P<body>.*)$')
# Le code de suivi devient une pastille : c'est ce qui permet de survoler une
# liste de vingt correctifs.
_TAG_RE = re.compile(r'^(?P<tag>(?:C|BF)\d+)\s*\.\s*(?P<rest>.+)$')
# `Tests : `a`, `b`.` en fin d'entrée : utile au mainteneur, hors sujet pour qui
# lit les nouveautés. Le point de départ est ancré sur une frontière de phrase
# pour ne pas manger un « Tests » qui parlerait d'autre chose.
_TESTS_TAIL_RE = re.compile(
    r'\s*Tests?\s*:\s*(?:`[^`]+`[\s,;]*(?:et|and)?\s*)+(?:\([^)]*\))?\.?',
    flags=re.IGNORECASE,
)
_BULLET_RE = re.compile(r'^([*-])\s+(?P<text>.+)$')
_VERSION_RE = re.compile(r'^##\s*\[(?P<version>[^\]]+)\]\s*(?:-\s*(?P<date>[\d-]+))?\s*(?:\((?P<title>.*)\))?\s*$')

# Une section est typée par l'émoji de son titre, avec un repli par mot-clé pour
# les versions anciennes qui n'en portaient pas. Le type décide de la couleur et
# du pictogramme ; il ne décide jamais de ce qui est affiché.
_SECTION_KINDS = (
    ("warn", ("⚠️", "⚠"), ("before you update", "avant de mettre à jour", "breaking"), "mk-ico-alert"),
    ("new", ("✨", "🚀", "🧱"), ("what's new", "nouveauté", "nouvelle", "new in", "feature",
                               "fonctionnalité"), "mk-ico-sparkle"),
    ("fix", ("🐛",), ("bug", "correctif", "correction", "fixes", "hotfix"), "mk-ico-bug"),
    ("security", ("🔒", "🔐"), ("security", "sécurité", "authentication", "authentification"), "mk-ico-shield"),
    ("limits", ("🧭",), ("known limitations", "limitations connues"), "mk-ico-compass"),
)
# Marqueurs de langue admis sur une ligne seule. Les vieilles versions du
# fichier utilisaient le drapeau plutôt que le code.
_LANG_MARKERS = {"en": "en", "fr": "fr", "🇺🇸": "en", "🇬🇧": "en", "🇫🇷": "fr"}
_EMOJI_PREFIX_RE = re.compile(r'^[^\w\s]+\s*', flags=re.UNICODE)


def get_app_version() -> str:
    """Extrait automatiquement le numéro de la version la plus récente dans CHANGELOG.md."""
    # Dédoublonnage des chemins d'accès possibles
    possible_paths = list(dict.fromkeys([
        os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "CHANGELOG.md")),
        os.path.abspath(os.path.join(os.getcwd(), "CHANGELOG.md")),
        "CHANGELOG.md"
    ]))

    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read(4096)
                    # Expression plus souple qui accepte les numéros SemVer et les suffixes (ex: 1.5.5-rc1)
                    match = re.search(r'##\s*\[([^\]]+)\]', content)
                    if match:
                        return match.group(1).strip()
            except Exception as e:
                logging.error(f"[App Version Parser] Erreur lors de la lecture de {p} : {e}")

    return "1.0.0"


def get_current_version() -> str:
    """Version mise en cache en mémoire process (recalculée une seule fois au démarrage)."""
    global _cached_version
    if _cached_version is None:
        _cached_version = get_app_version()
    return _cached_version


def _format_inline_markdown(text: str) -> str:
    """Échappe le HTML puis applique **gras**, *italique*, `code` et liens markdown.

    L'échappement DOIT précéder le wrapping : un CHANGELOG contenant
    `` `<script>` `` injecté via innerHTML ferait sinon fermer le document
    HTML du navigateur et tronquerait toute la suite de la modale.
    Liens : uniquement ``http(s)://`` (pas de ``javascript:``).
    """
    safe = html.escape(text, quote=True)
    safe = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', safe)
    safe = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<em>\1</em>', safe)
    safe = re.sub(r'`([^`]+)`', r'<code class="cl-code">\1</code>', safe)
    safe = re.sub(
        r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
        r'<a class="cl-link" href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        safe,
    )
    return safe


def _ui_lang() -> str:
    try:
        from config_manager import load_config

        lang = str(load_config().get("UI_LANG", "fr")).lower()
    except Exception:
        lang = "fr"
    return "en" if lang.startswith("en") else "fr"


def _read_changelog() -> str | None:
    for path in (
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "CHANGELOG.md"),
        os.path.join(os.getcwd(), "CHANGELOG.md"),
        "CHANGELOG.md",
    ):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().replace("\r\n", "\n")
    return None


def _split_releases(lines: list[str]) -> tuple[list[str], list[tuple[dict, list[str]]]]:
    """Sépare l'en-tête du document et les versions, dans l'ordre du fichier."""
    header: list[str] = []
    releases: list[tuple[dict, list[str]]] = []
    current: list[str] | None = None

    for line in lines:
        match = _VERSION_RE.match(line.strip())
        if match:
            meta = {
                "version": (match.group("version") or "").strip(),
                "date": (match.group("date") or "").strip(),
                "title": (match.group("title") or "").strip(),
            }
            current = []
            releases.append((meta, current))
            continue
        (current if current is not None else header).append(line)

    return header, releases


def _lines_for_lang(lines: list[str], lang: str) -> list[str]:
    """Ne garde que le bloc de langue demandé, préambule compris.

    Un marqueur `EN` / `FR` seul sur sa ligne ouvre un bloc. Les lignes qui
    précèdent le premier marqueur appartiennent aux deux langues. Une version
    qui ne porte pas la langue demandée est rendue intégralement : mieux vaut de
    l'anglais qu'une version vide.
    """
    kept: list[str] = []
    current: str | None = None

    for line in lines:
        marker = _LANG_MARKERS.get(line.strip().lower())
        if marker:
            current = marker
            continue
        if current is None or current == lang:
            kept.append(line)

    if not any(line.strip() for line in kept):
        return [line for line in lines if not _LANG_MARKERS.get(line.strip().lower())]
    return kept


def _section_kind(label: str) -> tuple[str, str]:
    lowered = label.lower()
    for kind, emojis, keywords, icon in _SECTION_KINDS:
        if any(emoji in label for emoji in emojis) or any(word in lowered for word in keywords):
            return kind, icon
    return "plain", "mk-ico-info"


def _clean_section_label(label: str) -> str:
    """Retire l'émoji de tête : le pictogramme du sprite le remplace."""
    stripped = _EMOJI_PREFIX_RE.sub("", label)
    return stripped or label


def _parse_sections(lines: list[str]) -> list[dict]:
    """Sections d'une version, chacune avec ses paragraphes et ses entrées."""
    sections: list[dict] = []

    def _open(label: str | None) -> dict:
        kind, icon = _section_kind(label or "")
        section = {
            "label": _clean_section_label(label) if label else None,
            "kind": kind if label else "plain",
            "icon": icon,
            "paragraphs": [],
            "items": [],
        }
        sections.append(section)
        return section

    current: dict | None = None

    for raw in lines:
        text = raw.strip()
        if not text or set(text) <= {"-", "*", "_"} and len(text) >= 3:
            # Ligne vide ou filet horizontal : la structure sépare déjà.
            continue

        if text.startswith("### ") or text.startswith("#### "):
            current = _open(text.lstrip("#").strip())
            continue

        bullet = _BULLET_RE.match(text)
        if bullet:
            if current is None:
                current = _open(None)
            indented = (len(raw) - len(raw.lstrip())) >= 2
            item_text = bullet.group("text").strip()
            if indented and current["items"]:
                current["items"][-1]["subs"].append(item_text)
            else:
                current["items"].append({"text": item_text, "subs": []})
            continue

        if current is None:
            current = _open(None)
        current["paragraphs"].append(text)

    return sections


def _strip_tests_tail(text: str) -> str:
    return _TESTS_TAIL_RE.sub("", text).strip()


def _is_tests_only(text: str) -> bool:
    """Une puce entièrement consacrée aux tests n'a rien à dire à l'utilisateur."""
    return not _strip_tests_tail(text)


def _render_item(item: dict) -> str:
    text = _strip_tests_tail(item["text"])
    if not text:
        return ""

    match = _ITEM_RE.match(text)
    head = match.group("head").strip() if match else ""
    body = (match.group("body") if match else text).strip()

    tag = ""
    if head:
        tag_match = _TAG_RE.match(head)
        if tag_match:
            tag = tag_match.group("tag")
            head = tag_match.group("rest").strip()

    parts = ['<li class="cl-item{}">'.format("" if head else " cl-item--plain")]
    if head:
        parts.append('<p class="cl-item-title">')
        if tag:
            parts.append(f'<span class="cl-tag">{html.escape(tag)}</span>')
        parts.append(f'<span>{_format_inline_markdown(head)}</span></p>')
    parts.append(f'<p class="cl-item-body">{_format_inline_markdown(body)}</p>')

    subs = [sub for sub in item["subs"] if not _is_tests_only(sub)]
    if subs:
        parts.append('<ul class="cl-subitems">')
        for sub in subs:
            parts.append(f'<li>{_format_inline_markdown(_strip_tests_tail(sub))}</li>')
        parts.append("</ul>")

    parts.append("</li>")
    return "".join(parts)


def _render_section(section: dict) -> str:
    items = [rendered for rendered in (_render_item(item) for item in section["items"]) if rendered]
    if not items and not section["paragraphs"]:
        return ""

    parts = [f'<section class="cl-section cl-section--{section["kind"]}">']
    if section["label"]:
        parts.append('<h4 class="cl-section-title">')
        parts.append(f'<svg class="mk-ico" aria-hidden="true"><use href="#{section["icon"]}"></use></svg>')
        parts.append(f'<span>{_format_inline_markdown(section["label"])}</span>')
        if items:
            parts.append(f'<span class="cl-section-count">{len(items)}</span>')
        parts.append("</h4>")
    for paragraph in section["paragraphs"]:
        parts.append(f'<p class="cl-note">{_format_inline_markdown(paragraph)}</p>')
    if items:
        parts.append('<ul class="cl-items">')
        parts.extend(items)
        parts.append("</ul>")
    parts.append("</section>")
    return "".join(parts)


def _render_release(meta: dict, lines: list[str], lang: str, latest: bool) -> str:
    sections = _parse_sections(_lines_for_lang(lines, lang))
    body = "".join(_render_section(section) for section in sections)
    if not body:
        return ""

    version = html.escape(meta["version"])
    date = html.escape(meta["date"])
    title = _format_inline_markdown(meta["title"]) if meta["title"] else ""

    if latest:
        head = [f'<header class="cl-release-head"><span class="cl-release-version">v{version}</span>']
        if date:
            head.append(f'<span class="cl-release-date">{date}</span>')
        head.append("</header>")
        if title:
            head.append(f'<p class="cl-release-title">{title}</p>')
        return (
            '<article class="cl-release cl-release--latest">'
            + "".join(head)
            + body
            + "</article>"
        )

    summary = [f'<summary class="cl-release-summary"><span class="cl-release-version">v{version}</span>']
    if title:
        summary.append(f'<span class="cl-release-title">{title}</span>')
    if date:
        summary.append(f'<span class="cl-release-date">{date}</span>')
    summary.append("</summary>")
    return (
        '<details class="cl-release cl-release--past">'
        + "".join(summary)
        + f'<div class="cl-release-body">{body}</div>'
        + "</details>"
    )


def get_full_changelog_html(lang: str | None = None) -> str:
    """Rend CHANGELOG.md pour la modale « Nouveautés », dans une seule langue."""
    content = _read_changelog()
    if content is None:
        msg = _t("changelog_not_found", "Fichier CHANGELOG.md non trouvé (Version v{0}).").format(
            get_current_version()
        )
        return f'<p class="cl-note">{html.escape(msg)}</p>'

    try:
        wanted = (lang or _ui_lang()).lower()
        wanted = "en" if wanted.startswith("en") else "fr"

        header_lines, releases = _split_releases(content.split("\n"))

        parts = []
        for line in header_lines:
            text = line.strip()
            if text.startswith("# "):
                parts.append(f'<h2 class="cl-doc-title">{_format_inline_markdown(text[2:].strip())}</h2>')

        past = []
        for index, (meta, lines) in enumerate(releases):
            rendered = _render_release(meta, lines, wanted, latest=(index == 0))
            if not rendered:
                continue
            (parts if index == 0 else past).append(rendered)

        if past:
            label = _t("changelog_previous_versions", "Versions précédentes")
            parts.append(f'<h4 class="cl-past-title">{html.escape(label)}</h4>')
            parts.extend(past)

        return "".join(parts)

    except Exception as e:
        logging.error(f"[Changelog Parser] Erreur : {e}")
        msg = _t("changelog_version_active", "Version {0} activée.").format(get_current_version())
        return f'<p class="cl-note">{html.escape(msg)}</p>'


def _t(key: str, default: str) -> str:
    """UI string for changelog fallbacks (respects UI_LANG)."""
    try:
        from config_manager import load_config
        from translations import translations
        lang = load_config().get("UI_LANG", "fr")
        return translations.get(lang, translations["fr"]).get(key, default)
    except Exception:
        return default
