"""
Lecture et rendu de CHANGELOG.md : numéro de version courant (affiché dans le
titre de l'UI) et rendu HTML complet (modale "Nouveautés").

Extrait de l'ancien `app.py`. Volontairement sans dépendance vers `app.py` ni
`routes/` pour être importable des deux côtés sans import circulaire :
`app.py` l'utilise pour le `context_processor` global, `routes/misc.py`
l'utilise pour l'endpoint `/api/changelog`.
"""

import logging
import os
import re

_cached_version = None


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


def get_full_changelog_html() -> str:
    """Lit l'intégralité de CHANGELOG.md et le convertit proprement en HTML."""
    possible_paths = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "CHANGELOG.md"),
        os.path.join(os.getcwd(), "CHANGELOG.md"),
        "CHANGELOG.md"
    ]

    changelog_path = None
    for p in possible_paths:
        if os.path.exists(p):
            changelog_path = p
            break

    if not changelog_path:
        return f"<p style='color: var(--text-muted);'>Fichier CHANGELOG.md non trouvé (Version v{get_current_version()}).</p>"

    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            content = f.read().replace('\r\n', '\n')

        html = []
        in_list = False

        for line in content.split("\n"):
            line_str = line.strip()
            if not line_str:
                if in_list:
                    html.append("</ul>")
                    in_list = False
                continue

            if line_str.startswith("# "):
                if in_list: html.append("</ul>"); in_list = False
                title_text = line_str[2:].strip()
                html.append(f"<h2 style='color: var(--primary); margin-top: 10px; margin-bottom: 10px; border-bottom: 2px solid var(--border-color); padding-bottom: 5px; font-size: 18px;'>{title_text}</h2>")
            elif line_str.startswith("## "):
                if in_list: html.append("</ul>"); in_list = False
                version_text = line_str[3:].strip()
                html.append(f"<h3 style='color: var(--accent); margin-top: 20px; margin-bottom: 10px; border-bottom: 1px solid var(--border-color); padding-bottom: 4px; font-size: 15px;'>{version_text}</h3>")
            elif line_str.startswith("### "):
                if in_list: html.append("</ul>"); in_list = False
                subtitle_text = line_str[4:].strip()
                html.append(f"<h4 style='color: var(--text-main); margin-top: 12px; margin-bottom: 6px; font-size: 13px;'>{subtitle_text}</h4>")
            elif line_str.startswith("* ") or line_str.startswith("- "):
                if not in_list:
                    html.append("<ul style='padding-left: 20px; margin: 5px 0 15px 0;'>")
                    in_list = True
                item_text = line_str[2:].strip()
                item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
                item_text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', item_text)
                item_text = re.sub(r'`(.*?)`', r'<code style="background: var(--bg-input); padding: 2px 5px; border-radius: 4px; font-size: 11px;">\1</code>', item_text)
                html.append(f"<li style='margin-bottom: 6px;'>{item_text}</li>")
            elif line_str in ["FR", "EN"]:
                if in_list: html.append("</ul>"); in_list = False
                html.append(f"<div style='font-weight: bold; color: var(--warning); margin-top: 10px;'>{line_str}</div>")
            else:
                if in_list: html.append("</ul>"); in_list = False
                line_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line_str)
                line_text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', line_text)
                html.append(f"<p style='margin: 4px 0;'>{line_text}</p>")

        if in_list:
            html.append("</ul>")

        return "".join(html)

    except Exception as e:
        logging.error(f"[Changelog Parser] Erreur : {e}")
        return f"<p>Version {get_current_version()} activée.</p>"
