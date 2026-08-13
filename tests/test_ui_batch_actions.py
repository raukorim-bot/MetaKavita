"""
Barre d'actions de masse (C83).

Six boutons déclarés `flex: 1`, en majuscules interlettrées, se partageaient la
largeur à parts égales : « Ignorer la sélection » et « Arrêter (annuler la
file) » se coupaient en deux lignes, la case à cocher d'inventaire était posée
nue entre deux blocs, et la seule action qui écrit dans Kavita ne se distinguait
pas d'une amnistie d'erreurs. Ce que ces tests tiennent :

1. **Une seule action dominante.** Un bouton plein, dans le groupe de droite ;
   tout le reste est un contour. La largeur ne sert plus de hiérarchie.
2. **Un libellé sur une ligne.** `white-space: nowrap` et plus de `uppercase`
   dans la barre — c'est la mise en majuscules qui faisait déborder les libellés.
3. **Un libellé qui n'efface pas son pictogramme.** Le JS remplace le texte
   (« Envoi… », « Ajouter à la file ») : il doit écrire dans le `.ba-label`, pas
   dans le bouton, sinon le `<svg>` disparaît au premier changement d'état.
4. **Une pastille de file qui se masque vraiment.** `display` posé par une classe
   l'emporte sur `[hidden]` : la pastille restait à l'écran, vide, pour une file
   à zéro.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
SPRITE = (ROOT / "templates" / "partials" / "_icons_sprite.html").read_text(encoding="utf-8")
BATCH_JS = (ROOT / "static" / "js" / "batch.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")

# Les six libellés de la barre : le pictogramme est désormais un symbole du
# sprite, donc plus aucun émoji dans le texte lui-même.
LABEL_KEYS = (
    "reset_errors",
    "launch_ignore",
    "batch_queue_btn",
    "launch_batch",
    "launch_batch_append",
    "stop_batch",
)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u25B6\u2B1B]")


@pytest.fixture(scope="module")
def bar():
    soup = BeautifulSoup(INDEX, "html.parser")
    return soup.find("div", id="batchActions")


def _translations():
    from translations import translations

    return translations


# ===== La hiérarchie =====


def test_la_barre_existe_et_annonce_son_etat(bar):
    """Le bouton d'arrêt devient franc sur `data-state="running"` : sans état
    initial, il naîtrait rouge vif alors qu'il n'y a rien à arrêter."""
    assert bar is not None
    assert bar["data-state"] == "idle"


def test_une_seule_action_est_pleine_et_elle_est_a_droite(bar):
    pleins = bar.select(".ba-btn--primary")

    assert len(pleins) == 1
    assert pleins[0]["id"] == "mainBatchBtn"
    assert pleins[0]["type"] == "submit"
    assert "ba-cluster--run" in pleins[0].parent.get("class", [])


def test_les_gestes_dentretien_sont_des_contours(bar):
    tools = bar.select(".ba-cluster--tools .ba-btn")
    ids = [btn["id"] for btn in tools]

    assert ids == ["batchResetBtn", "batchIgnoreBtn", "batchQueueBtn"]
    for btn in tools:
        classes = btn.get("class", [])
        assert "ba-btn--quiet" in classes
        assert "ba-btn--primary" not in classes


def test_larret_reste_a_portee_meme_au_repos(bar):
    """Une file peut continuer à se vider côté serveur alors que cet onglet
    n'affiche aucune progression : masquer le bouton laisserait sans recours."""
    stop = bar.find("button", id="batchStopBtn")

    assert stop is not None
    assert "ba-btn--stop" in stop["class"]
    assert 'data-state="running"] .ba-btn--stop' in CSS


# ===== Les libellés =====


def test_aucun_libelle_ne_se_coupe_en_deux_lignes():
    bloc = CSS[CSS.index(".ba-btn {"):CSS.index(".ba-btn .mk-ico")]

    assert "white-space: nowrap" in bloc
    # La mise en majuscules ajoutait ~15 % de largeur à chaque libellé : c'est
    # elle qui les faisait passer à la ligne dans un bouton de largeur imposée.
    assert "text-transform: uppercase" not in CSS[CSS.index(".batch-actions {"):CSS.index(".ba-toggle-track")]


@pytest.mark.parametrize("lang", ["fr", "en"])
@pytest.mark.parametrize("key", LABEL_KEYS)
def test_les_libelles_ne_portent_plus_demoji(lang, key):
    texte = _translations()[lang][key]

    assert not EMOJI_RE.search(texte), f"{lang}/{key} : {texte!r}"


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_larret_explique_dans_son_infobulle_ce_quil_annule(lang):
    """« Arrêter (annuler la file) » ne tenait pas sur une ligne. Le libellé est
    court, et la conséquence — la file est vidée — passe en infobulle."""
    t = _translations()[lang]

    assert len(t["stop_batch"]) <= 12
    assert len(t["stop_batch_hint"]) > 30


@pytest.mark.parametrize(
    "key",
    ["reset_errors_hint", "launch_ignore_hint", "stop_batch_hint", "audit_scan_with_batch_hint"],
)
def test_les_deux_langues_ont_les_nouvelles_infobulles(key):
    tr = _translations()

    assert tr["fr"].get(key) and tr["en"].get(key)
    assert tr["fr"][key] != tr["en"][key]


def test_chaque_bouton_range_son_texte_dans_un_slot(bar):
    """Le JS écrit dans `.ba-label`. Un bouton sans slot verrait son pictogramme
    remplacé par le texte au premier « Envoi… »."""
    for btn in bar.select(".ba-btn"):
        assert btn.select_one(".ba-label") is not None, btn.get("id")


def _corps_de_fonction(nom: str) -> str:
    debut = BATCH_JS.index("function " + nom + "(")
    return BATCH_JS[debut:BATCH_JS.index("\n}\n", debut)]


def test_le_helper_existe_et_retombe_sur_le_bouton_sans_slot():
    helper = _corps_de_fonction("setBatchBtnLabel")

    assert ".ba-label" in helper
    assert "btn.innerText = text" in helper


@pytest.mark.parametrize(
    "nom",
    ["syncMainBatchBtnLabel", "launchBatch", "stopBatch", "resetErrors", "ignoreSelection"],
)
def test_les_fonctions_de_la_barre_ecrivent_dans_le_slot(nom):
    """Une seule écriture directe oubliée suffit : le pictogramme disparaît au
    premier changement d'état, et ne revient qu'au rechargement de la page."""
    corps = _corps_de_fonction(nom)

    assert "btn.innerText" not in corps
    assert "setBatchBtnLabel" in corps


# ===== Pictogrammes =====


def test_chaque_bouton_porte_un_pictogramme_qui_existe(bar):
    refs = [use["href"].lstrip("#") for use in bar.select("use[href]")]

    assert len(refs) >= 6
    for ref in refs:
        assert f'id="{ref}"' in SPRITE, ref


def test_le_bouton_principal_change_de_pictogramme_avec_son_role(bar):
    """Lancer un lot et en ajouter un à celui qui tourne ne sont pas le même
    geste : le triangle et la croix le disent avant qu'on lise le libellé."""
    main = bar.find("button", id="mainBatchBtn")

    assert main["data-mode"] == "run"
    assert main.select_one(".ba-ico--run use")["href"] == "#mk-ico-play"
    assert main.select_one(".ba-ico--append use")["href"] == "#mk-ico-plus"
    assert '[data-mode="run"] .ba-ico--append' in CSS
    assert '[data-mode="append"] .ba-ico--run' in CSS
    assert "dataset.mode = isBatchInProgress() ? 'append' : 'run'" in BATCH_JS


# ===== L'option du lot, et la pastille de file =====


def test_loption_dinventaire_est_un_interrupteur(bar):
    toggle = bar.select_one(".ba-toggle")

    assert toggle is not None
    assert toggle["for"] == "hygieneWithBatchCb"
    assert toggle.find("input", id="hygieneWithBatchCb") is not None
    assert toggle.select_one(".ba-toggle-track .ba-toggle-dot") is not None
    # L'infobulle répétait mot pour mot le libellé : elle n'apprenait rien.
    assert "audit_scan_with_batch_hint" in toggle["title"]
    assert ".ba-toggle:has(input:checked)" in CSS


def test_une_file_vide_naffiche_pas_de_pastille(bar):
    badge = bar.find("span", id="batchQueueBadge")

    assert badge is not None
    assert badge.has_attr("hidden")
    assert ".batch-queue-badge[hidden] { display: none; }" in CSS
