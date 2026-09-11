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
import re
from pathlib import Path

COMPANION = Path(__file__).resolve().parents[1] / "companion"


def _read(rel: str) -> str:
    return (COMPANION / rel).read_text(encoding="utf-8")


# --- LECTURE DU PAQUET ------------------------------------------------------
# Ces tests portaient sur des fichiers nommés un par un (`background.js`,
# `content/watch.js`). Un invariant du genre « ce motif ne doit exister nulle
# part » ne disait donc rien d'un fichier voisin, ni d'un fichier à naître :
# déplacer le code suffisait à faire taire l'assertion sans rien corriger.
#
# Le périmètre scanné est DÉRIVÉ de la liste blanche de `pack.mjs`, donc il
# suit exactement ce qui part chez l'utilisateur : `companion/scripts/` et
# `companion/tests/` en sont dehors sans qu'on ait à les exclure.


def _between(src: str, start: str, end: str, where: str) -> str:
    """Découpe entre deux ancres, avec un échec qui NOMME l'ancre disparue.

    `src.split(a)[1].split(b)[0]` lève un IndexError muet quand un handler est
    renommé — on perd l'invariant et le message qui allait avec.
    """
    i = src.find(start)
    assert i != -1, f"{where} : ancre « {start} » introuvable — le test suivait un nom qui a changé"
    j = src.find(end, i + len(start))
    assert j != -1, f"{where} : ancre de fin « {end} » introuvable après « {start} »"
    return src[i + len(start):j]


def _include_list(script: str) -> list[str]:
    """La liste blanche de premier niveau, lue dans le script de pack ou de vérif."""
    block = _between(_read(f"scripts/{script}"), "const INCLUDE = [", "];", script)
    return re.findall(r'"([^"]+)"', block)


def _shipped_scripts() -> dict[str, str]:
    """Tout le JavaScript réellement packé, indexé par chemin POSIX."""
    out: dict[str, str] = {}
    for name in _include_list("pack.mjs"):
        src = COMPANION / name
        if not src.exists():
            continue
        paths = sorted(src.rglob("*.js")) if src.is_dir() else ([src] if src.suffix == ".js" else [])
        for path in paths:
            out[path.relative_to(COMPANION).as_posix()] = path.read_text(encoding="utf-8")
    return out


def _grep(needle: str, only: tuple[str, ...] | None = None) -> dict[str, int]:
    """Fichiers livrés contenant `needle`, avec le nombre d'occurrences."""
    return {
        rel: src.count(needle)
        for rel, src in _shipped_scripts().items()
        if (only is None or rel.startswith(only)) and needle in src
    }


def _assert_nowhere(needle: str, why: str) -> None:
    hits = _grep(needle)
    assert not hits, f"{why} — encore présent dans {', '.join(sorted(hits))}"


def _assert_somewhere(needle: str, why: str, only: tuple[str, ...] | None = None) -> None:
    assert _grep(needle, only), f"{why} — introuvable dans {only or 'companion/'}"


def _assert_defined_once(needle: str, why: str) -> None:
    hits = _grep(needle)
    total = sum(hits.values())
    assert total == 1, f"{why} — {total} occurrence(s) : {hits or 'aucune'}"


def test_the_settings_panel_is_out_of_reach_of_the_kavita_page():
    """Un shadow root ouvert se traverse depuis la page (`host.shadowRoot`).

    Le contrôle porte sur le paquet entier, pas sur `page-ui.js` seul : c'est un
    second `attachShadow` ailleurs — un overlay qui se fabriquerait son propre
    hôte — qui rouvrirait la brèche sans toucher au fichier surveillé.
    """
    _assert_defined_once(
        "attachShadow(",
        "un seul propriétaire de shadow root dans l'extension",
    )
    _assert_somewhere(
        'attachShadow({ mode: "closed" })',
        "le shadow root de l'extension doit être fermé",
    )
    _assert_nowhere(
        'mode: "open"',
        "un shadow root ouvert livrerait le panneau — jeton compris — à la page Kavita",
    )


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
    """Le pont hérité prenait ses ordres de n'importe quelle fenêtre.

    Négatives portées au paquet entier : `not in watch.js` ne disait rien d'un
    `overlay-mr.js`, et la formulation littérale ne couvrait qu'une orthographe
    de l'ouverture d'URL téléguidée.
    """
    _assert_nowhere(
        "metakavita-companion-overlay",
        "le pont sans authentification est mort avec overlay/",
    )
    _assert_nowhere("mk:open-mr-tab", "message du pont mort")
    for form in ("window.open(String(data.", "window.open(data.", "= data.url"):
        _assert_nowhere(
            form,
            "aucune fenêtre extérieure ne dicte l'URL que le Companion ouvre",
        )
    # La branche restante reste contrôlée en origine ET en émetteur. Le nom de
    # la variable d'état n'est plus dans le contrat : `mr-bridge.test.mjs`
    # vérifie le comportement, ceci ne garde que la présence des deux contrôles.
    _assert_somewhere(
        "ev.source !==",
        "le pont doit vérifier l'émetteur du message",
        only=("content/",),
    )
    _assert_somewhere(
        "ev.origin !==",
        "le pont doit vérifier l'origine du message",
        only=("content/",),
    )


def test_the_pack_and_the_verifier_agree_on_what_ships():
    """Deux copies de la même liste blanche : celle qui pack, celle qui vérifie.

    Divergentes, un fichier partirait chez l'utilisateur sans jamais être
    comparé à sa source — et `verify-dist` resterait vert.
    """
    assert _include_list("pack.mjs") == _include_list("verify-dist.mjs")
    for excluded in ("tests", "scripts"):
        assert excluded not in _include_list("pack.mjs"), \
            f"companion/{excluded}/ n'a rien à faire chez l'utilisateur"


def test_every_content_script_is_actually_injected():
    """Un fichier ajouté sous `content/` mais absent de `WATCH_FILES` est packé,
    donc comparé octet à octet par `verify-dist` — et jamais chargé. La panne est
    entièrement muette : rien n'échoue, la fonction manque simplement.

    L'ordre compte aussi : ces scripts s'exécutent à la suite dans le même monde
    isolé, et `watch.js` amorce la surveillance de navigation en dernier.
    """
    block = _between(
        _read("lib/watch-files.js"), "WATCH_FILES = [", "];", "lib/watch-files.js"
    )
    declared = re.findall(r'"([^"]+)"', block)
    on_disk = sorted(p.name for p in (COMPANION / "content").glob("*.js"))

    assert sorted(f.split("/")[-1] for f in declared) == on_disk, \
        f"WATCH_FILES {declared} ≠ content/ {on_disk}"
    assert declared[-1].endswith("watch.js"), \
        "watch.js amorce : il doit être chargé en dernier"
    # Le littéral entre guillemets, pas le nom de fichier : ce dernier apparaît
    # légitimement dans les commentaires qui expliquent la contrainte.
    assert set(_grep('"content/page-ui.js"')) <= {"lib/watch-files.js"}, \
        "la liste des scripts injectés ne doit exister qu'à un seul endroit"


def test_content_scripts_stay_classic_scripts():
    """`chrome.scripting` injecte des scripts classiques.

    Un `import` sous `content/` ne casse rien au packaging ni à `node --check`
    sous Node 20 : il casse l'extension à l'exécution, chez l'utilisateur, et
    sans un mot.
    """
    for rel, src in _shipped_scripts().items():
        if not rel.startswith("content/"):
            continue
        assert not re.search(r"^\s*(?:import|export)\s", src, re.M), \
            f"{rel} : un content script ne peut ni importer ni exporter"


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


def test_connection_test_names_a_missing_token_instead_of_connection_failed():
    """Issue #37 : le toast générique « Connection failed » masquait un jeton vide."""
    _assert_somewhere(
        'reason === "no_token"',
        "l'UI de page doit distinguer un jeton vide d'une panne réseau",
        only=("content/",),
    )
    _assert_somewhere("toastTestFailNoToken", "clé du message dédié", only=("content/",))
    assert "toastTestFailNoToken" in _read("options.js")
    webhook = _read("lib/webhook.js")
    assert 'reason: "no_token"' in webhook
    assert 'reason: "no_url"' in webhook
    assert 'reason: "config"' not in webhook


def test_connection_test_does_not_save_an_empty_token_over_a_stored_one():
    """Tester avec le champ jeton vide ne doit pas écraser un jeton déjà enregistré."""
    handler = _between(
        _read("content/page-ui.js"),
        "btnTest.addEventListener",
        "btnEnableSite.addEventListener",
        "content/page-ui.js",
    )
    assert "settings.webhookToken" in handler
    assert "toastTestFailNoToken" in handler
    opt_handler = _between(
        _read("options.js"),
        'btnTest").addEventListener',
        'btnEnableSite").addEventListener',
        "options.js",
    )
    assert "stored.settings.webhookToken" in opt_handler


def test_a_pasted_webhook_url_is_reduced_to_the_instance_root():
    """L'URL affichée en Config Meta est `…/webhook?token=` — collée telle quelle,
    Test tapait `/webhook/healthz`."""
    src = _read("lib/storage.js")
    assert "/webhook$" in src, "lib/storage.js doit retirer un suffixe /webhook"
    # Ces fonctions étaient dupliquées dans content/page-ui.js, sans qu'aucun
    # test ne compare les deux versions (contrairement à la table i18n). Le
    # content script les demande maintenant au worker : une seule définition.
    _assert_defined_once("function normalizeBaseUrl", "une seule normalisation d'URL")
    _assert_defined_once("function tokenFromPastedUrl", "une seule extraction de jeton")
    _assert_defined_once("function isMetaKavitaUrl", "une seule détection de MetaKavita")

    chrome = json.loads(_read("manifest.json"))["version"]
    firefox = json.loads(_read("manifest.firefox.json"))["version"]
    assert chrome == firefox
    readme = _read("README.md")
    assert f"**{chrome}**" in readme, \
        "le README annonce la version téléchargée : il doit suivre le manifeste"


def test_a_lan_host_with_a_port_yields_a_usable_origin():
    """« localhost:5011 » passait pour le schéma « localhost: » (origine null),
    et l'échec se présentait comme un problème de permission."""
    assert "/^https?:\\/\\//i.test(u)" in _read("lib/storage.js"), \
        "seul http(s):// doit compter comme un schéma"
    _assert_nowhere(
        "[a-zA-Z][a-zA-Z0-9+.-]*:",
        "ce motif faisait passer « localhost:5011 » pour un schéma (origine null)",
    )


def test_the_embed_token_never_travels_in_an_image_url():
    """`<img src>` is plain DOM: the Kavita page reads it. That token unlocks
    every review route of its series."""
    # Le négatif ne peut pas être global : l'URL de l'embed Super Review porte
    # légitimement le jeton, parce que c'est une NAVIGATION vers MetaKavita et
    # non un attribut que la page Kavita peut lire. L'exception est donc nommée
    # — et assertée dans les deux sens, pour qu'elle ne survive pas à son motif.
    legitimate = {"content/page-ui.js"}
    hits = set(_grep('searchParams.set("embed_token"'))
    assert hits <= legitimate, (
        "jeton d'embed injecté dans une URL hors embed Super Review : "
        f"{sorted(hits - legitimate)}"
    )
    assert legitimate <= hits, \
        "l'exception ne sert plus — la retirer plutôt que de la garder ouverte"

    # Le reste de l'invariant — retrait d'un jeton déjà posé, envoi en en-tête —
    # se vérifie sur la requête réellement émise, pas sur le source :
    # companion/tests/cover-url.test.mjs et image-bridge.test.mjs.


def test_a_proxied_preview_goes_through_the_service_worker():
    """Sans jeton dans l'URL, une `<img>` sur /api/proxy-image reçoit la page de
    login : la prévisualisation doit passer par le worker, qui a l'en-tête."""
    watch = _read("content/watch.js")

    assert 'url.indexOf("/api/proxy-image") !== -1' in watch
    # Et le cas historique — contenu mixte — reste couvert.
    assert 'location.protocol === "https:"' in watch


def test_only_one_module_can_mint_an_embed_token():
    """Un jeton d'embed ouvre les routes de review de sa série : leur nombre doit
    rester comptable, donc la route d'émission n'a qu'un seul appelant.

    Le comptage d'occurrences qui tenait ce rôle (`count("mintEmbedToken(") == 2`)
    portait sur le texte de `background.js` : il tombait sur un simple `export`,
    et ne disait rien du nombre de jetons réellement émis. Ce nombre-là est
    mesuré dans `companion/tests/embed-token.test.mjs`, sur les requêtes.
    """
    _assert_defined_once(
        "/companion/embed-token",
        "un seul module connaît la route d'émission",
    )
    assert "lib/embed-token.js" in _grep("/companion/embed-token")

    # Et l'invalidation reste câblée : changer d'adresse ou de jeton webhook
    # doit vider ce qu'on détient.
    _assert_somewhere(
        "forgetEmbedTokens()",
        "saveSettings doit invalider les jetons en cache",
    )


def test_the_translation_table_has_exactly_one_home():
    """Trois clés s'affichaient brutes — « toastMixedContentWindow » sur le
    parcours contenu mixte, « coverPreviewFail » sur un aperçu refusé — parce que
    `content/page-ui.js` portait une copie de la table qui avait dérivé.

    La copie a disparu : la table est servie par le service worker. Ce qui reste
    à vérifier, c'est qu'aucune seconde n'apparaisse — une copie redeviendrait
    aussitôt une chose à tenir à jour à la main. `selfcheck-i18n.mjs` couvre
    l'autre moitié : toute clé appelée a une traduction à rendre.
    """
    assert "toastMixedContentWindow" in _read("lib/i18n.js")
    for name in ("const FR = {", "const EN = {"):
        _assert_defined_once(name, "la table de traductions vit dans lib/i18n.js, et là seulement")

    # Les clés de secours, elles, doivent rester dans `_locales` : c'est le seul
    # recours synchrone quand l'aller-retour vers le worker vient d'échouer.
    for lang in ("en", "fr"):
        messages = json.loads(_read(f"_locales/{lang}/messages.json"))
        assert "toastExtensionReloaded" in messages, \
            f"_locales/{lang} : la clé affichée quand l'extension est rechargée"
