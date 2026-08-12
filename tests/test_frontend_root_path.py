"""
MetaKavita se déploie couramment derrière un reverse-proxy avec sous-chemin
(`ROOT_PATH`, ex. `https://host/metakavita`). Toute URL d'application écrite en
absolu depuis le JS part alors sur `https://host/api/...` : hors de
l'application, donc 404 — ou pire, la page de connexion d'un autre service.

`static/js/library_audit.js` construisait ses 22 appels ainsi : sur une
installation en sous-chemin, la totalité de l'inventaire (analyse, rapport
volumes, doublons, exports, exclusion, attendu forcé, suppression Kavita)
répondait 404 sans que rien ne l'explique à l'écran.

Ce test couvre tout le frontend : les appels passent par `getRootPath()` (ou un
wrapper qui l'applique — `api()`, `postJson()`, `root()`).
"""
import os
import re

_JS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static", "js")
)

# Chemins servis par Flask, pas par le CDN : eux doivent porter le préfixe.
_APP_PATH = r"/(?:api|companion|force-sync|batch-sync|save-config|stop-batch|login|logout)"


def _js_files():
    for name in sorted(os.listdir(_JS_DIR)):
        if name.endswith(".js"):
            with open(os.path.join(_JS_DIR, name), encoding="utf-8") as fh:
                yield name, fh.read()


def test_no_fetch_targets_an_absolute_app_path():
    offenders = []
    for name, src in _js_files():
        for m in re.finditer(r"""fetch\(\s*["'`](""" + _APP_PATH + r""")""", src):
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"{name}:{line} → fetch('{m.group(1)}…')")
    assert offenders == [], (
        "URL d'application en absolu : 404 derrière un reverse-proxy avec "
        "sous-chemin. Préfixer par getRootPath().\n" + "\n".join(offenders)
    )


def test_no_link_or_redirect_targets_an_absolute_app_path():
    offenders = []
    pattern = re.compile(
        r"""(?:href|action|src)\s*=\s*["'`](""" + _APP_PATH + r""")"""
    )
    for name, src in _js_files():
        for m in pattern.finditer(src):
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"{name}:{line} → '{m.group(1)}…'")
    assert offenders == [], (
        "lien/téléchargement en absolu (exports CSV/TXT notamment) :\n"
        + "\n".join(offenders)
    )


def test_the_inventory_module_uses_the_root_path_everywhere():
    """Garde ciblée : c'est ce module qui avait les 22 appels en absolu."""
    with open(os.path.join(_JS_DIR, "library_audit.js"), encoding="utf-8") as fh:
        src = fh.read()
    bare = re.findall(r"(?<!getRootPath\(\) \+ )['\"]/api/", src)
    assert bare == [], f"{len(bare)} URL(s) d'inventaire sans getRootPath()"
    assert src.count("getRootPath() + '/api/") >= 20
