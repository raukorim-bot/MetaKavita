"""
Durcissement de l'extension Companion (audit du 12 août 2026).

Trois constats vérifiés ici, tous invisibles depuis les tests serveur :

* le panneau de réglages vivait dans un shadow root ouvert, avec le jeton
  webhook déjà écrit dedans à chaque fiche série — donc lisible par n'importe
  quel script de la page Kavita via `host.shadowRoot` ;
* `watch.js` acceptait les messages `metakavita-companion-overlay` de n'importe
  quelle fenêtre, sans contrôle d'origine ni d'émetteur, et ouvrait l'URL
  fournie ou recouvrait Kavita d'une iframe arbitraire ;
* `web_accessible_resources` exposait `lib/`, `overlay/` et `_locales/` à tous
  les sites alors que seule l'icône est chargée depuis la page.
"""
from __future__ import annotations

import json
from pathlib import Path

COMPANION = Path(__file__).resolve().parents[1] / "companion"


def _read(rel: str) -> str:
    return (COMPANION / rel).read_text(encoding="utf-8")


def test_the_settings_panel_is_out_of_reach_of_the_kavita_page():
    src = _read("content/page-ui.js")

    assert 'attachShadow({ mode: "closed" })' in src, \
        "un shadow root ouvert se traverse depuis la page (host.shadowRoot)"
    assert 'mode: "open"' not in src


def test_the_webhook_token_is_only_written_while_the_panel_is_open():
    src = _read("content/page-ui.js")

    # Une seule écriture du champ, et elle est gardée par includeToken.
    assignments = [
        line.strip()
        for line in src.splitlines()
        if "els.token.value" in line and "=" in line
    ]
    assert assignments, "le champ jeton doit encore être rempli à l'ouverture"
    for line in assignments:
        assert 'settings.webhookToken' not in line or "opts" in src.split(line)[0][-400:], \
            "le jeton ne doit être écrit que sous garde"
    assert "opts && opts.includeToken" in src, \
        "fillForm doit pouvoir se passer du jeton"
    assert 'fillForm({ includeToken: true })' in src, \
        "openConfig est le seul appel qui remplit le jeton"
    assert 'els.token.value = "";' in src, \
        "la fermeture du panneau doit vider le champ"


def test_no_unauthenticated_message_bridge_remains():
    src = _read("content/watch.js")

    assert "metakavita-companion-overlay" not in src, \
        "le pont hérité prenait ses ordres de n'importe quelle fenêtre"
    assert "mk:open-mr-tab" not in src
    assert "window.open(String(data.url)" not in src
    # La branche restante, elle, reste contrôlée en origine ET en émetteur.
    assert "ev.source !== mrState.iframe.contentWindow" in src
    assert "ev.origin !== mrState.metaOrigin" in src


def test_the_dead_overlay_is_gone_from_the_tree_and_the_pack():
    assert not (COMPANION / "overlay").exists(), \
        "overlay/ n'était plus chargé par personne et restait packé"
    pack = _read("scripts/pack.mjs")
    assert '"overlay"' not in pack


def test_web_accessible_resources_expose_only_the_icon():
    for name in ("manifest.json", "manifest.firefox.json"):
        manifest = json.loads(_read(name))
        resources = manifest["web_accessible_resources"][0]["resources"]
        assert resources == ["icons/logo.png"], (
            f"{name} : seule l'icône du bouton flottant est chargée depuis la page ; "
            "le reste ne servait qu'à identifier l'extension"
        )


def _entry_names(path: Path) -> list[str]:
    """Noms lus dans le répertoire central, tels qu'ils sont écrits.

    `zipfile.namelist()` ne convient pas ici : il traduit les antislashs en `/`
    à la lecture, donc il déclare saine l'archive même que ce test cherche.
    """
    import struct

    raw = path.read_bytes()
    eocd = raw.rfind(b"PK\x05\x06")
    assert eocd != -1, f"{path.name} : fin d'archive introuvable"
    count, _size, offset = struct.unpack_from("<HLL", raw, eocd + 10)

    names = []
    for _ in range(count):
        assert raw[offset:offset + 4] == b"PK\x01\x02", "entrée centrale corrompue"
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", raw, offset + 28)
        names.append(raw[offset + 46:offset + 46 + name_len].decode("utf-8"))
        offset += 46 + name_len + extra_len + comment_len
    return names


def test_the_zip_entry_names_use_forward_slashes():
    """ZIP APPNOTE 4.4.17 : les noms d'entrée s'écrivent avec des `/`. Packée
    sous PowerShell, la 1.0.23 stockait « lib\\storage.js » comme un seul nom de
    fichier, et s'extrayait sous Linux en un tas de fichiers à plat."""
    for name in ("metakavita-companion-chrome.zip", "metakavita-companion-firefox.zip"):
        names = _entry_names(COMPANION / "dist" / name)

        backslashed = [n for n in names if "\\" in n]
        assert not backslashed, f"{name} : noms en antislash — {backslashed[:3]}"

        escaping = [n for n in names if n.startswith("/") or ".." in n.split("/")]
        assert not escaping, f"{name} : sort du dossier d'extraction — {escaping}"

        # Et l'arborescence est bien là : un zip aplati passerait les deux
        # contrôles ci-dessus sans broncher.
        for prefix in ("content/", "lib/", "_locales/", "icons/"):
            assert any(n.startswith(prefix) for n in names), \
                f"{name} : rien sous {prefix}"


def test_the_zips_carry_lf_whatever_the_machine_that_packed_them():
    """Les zips sont packés à la main, le plus souvent sous Windows, où git
    sort les fichiers texte en CRLF ; le runner CI, lui, les sort en LF. Une
    comparaison octet à octet échouait alors sur les fichiers packés depuis une
    copie CRLF — et aurait continué jusqu'à un repack sous Linux."""
    import zipfile

    for name in ("metakavita-companion-chrome.zip", "metakavita-companion-firefox.zip"):
        with zipfile.ZipFile(COMPANION / "dist" / name) as zf:
            for entry in zf.namelist():
                if not entry.endswith((".js", ".json", ".html", ".css")):
                    continue
                assert b"\r\n" not in zf.read(entry), (
                    f"{name} : {entry} packé en CRLF — l'artefact dépend de la "
                    "machine qui l'a construit"
                )


def test_both_manifests_agree_on_the_version():
    chrome = json.loads(_read("manifest.json"))["version"]
    firefox = json.loads(_read("manifest.firefox.json"))["version"]
    assert chrome == firefox
    readme = _read("README.md")
    assert f"**{chrome}**" in readme, \
        "le README annonce la version téléchargée : il doit suivre le manifeste"


def test_a_lan_host_with_a_port_yields_a_usable_origin():
    """« localhost:5011 » passait pour le schéma « localhost: » (origine null),
    et l'échec se présentait comme un problème de permission."""
    for src_name in ("lib/storage.js", "content/page-ui.js"):
        src = _read(src_name)
        assert "/^https?:\\/\\//i.test(u)" in src, (
            f"{src_name} : seul http(s):// doit compter comme un schéma"
        )
        assert "[a-zA-Z][a-zA-Z0-9+.-]*:" not in src


def test_the_embed_token_never_travels_in_an_image_url():
    """`<img src>` is plain DOM: the Kavita page reads it. That token unlocks
    every review route of its series."""
    bg = _read("background.js")

    assert "searchParams.set(\"embed_token\"" not in bg, \
        "le jeton ne doit plus être injecté dans display_url"
    assert 'parsed.searchParams.delete("embed_token")' in bg, \
        "un display_url déjà porteur d'un jeton doit en être débarrassé"
    assert 'target.searchParams.delete("embed_token")' in bg
    assert '"X-Companion-Embed-Token": embedToken' in bg, \
        "il passe en en-tête, sur les appels que le service worker fait lui-même"


def test_a_proxied_preview_goes_through_the_service_worker():
    """Sans jeton dans l'URL, une `<img>` sur /api/proxy-image reçoit la page de
    login : la prévisualisation doit passer par le worker, qui a l'en-tête."""
    watch = _read("content/watch.js")

    assert 'url.indexOf("/api/proxy-image") !== -1' in watch
    # Et le cas historique — contenu mixte — reste couvert.
    assert 'location.protocol === "https:"' in watch


def test_one_token_per_series_serves_the_whole_picker():
    """Une grille de vingt couvertures demandait vingt jetons à MetaKavita, et
    laissait autant d'accès vivants derrière elle."""
    bg = _read("background.js")

    assert "embedTokenCache" in bg
    assert "getEmbedToken(" in bg
    assert bg.count("mintEmbedToken(") == 2, \
        "un seul appelant : le cache. L'autre occurrence est la définition"
    assert "forgetEmbedTokens()" in bg, \
        "changer d'adresse ou de jeton webhook doit invalider le cache"
    # Le TTL local reste sous celui du serveur (15 min) pour éviter un jeton
    # qui meurt pendant la requête.
    assert "EMBED_TOKEN_REUSE_MS = 10 * 60 * 1000" in bg


def test_the_three_missing_translation_keys_are_declared():
    """Elles s'affichaient brutes : « toastMixedContentWindow » sur le parcours
    contenu mixte, « coverPreviewFail » sur un aperçu refusé."""
    src = _read("content/page-ui.js")
    for key in ("toastMixedContentWindow", "coverPreviewFail", "coverPreviewLogin"):
        assert f'{key}: "' in src, f"{key} appelée mais jamais déclarée"
