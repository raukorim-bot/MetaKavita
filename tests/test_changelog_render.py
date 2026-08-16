"""
Rendu de la modale « Nouveautés » (C82) et structure du CHANGELOG.

La modale lisait le fichier presque tel quel : les deux langues à la suite, une
seule liste à plat, chaque entrée étant un paragraphe de quatre cents mots dont
le titre était noyé dedans. Ce qui la rend lisible n'est pas d'écrire plus court
mais de rendre la structure du fichier : une version, des sections typées, un
titre par entrée qu'on peut survoler avant de décider de lire.

Ces tests tiennent donc trois promesses du rendu — une seule langue, la dernière
version ouverte et les autres repliées, titre et corps séparés — et deux
promesses du fichier : les nouveautés passent avant les correctifs, et les deux
langues décrivent exactement les mêmes entrées.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.changelog_service import (
    _lines_for_lang,
    _parse_sections,
    _render_item,
    _section_kind,
    get_full_changelog_html,
)

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
CODE_RE = re.compile(r'^\* \*\*((?:C|BF)\d+)\.')


def _sans_balises(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _bloc_derniere_version() -> list[str]:
    lignes = CHANGELOG.replace("\r\n", "\n").split("\n")
    fin = next(i for i, ligne in enumerate(lignes[1:], 1) if ligne.startswith("## ["))
    return lignes[:fin]


def _codes_par_langue() -> dict[str, list[str]]:
    codes: dict[str, list[str]] = {"en": [], "fr": []}
    langue = "en"
    for ligne in _bloc_derniere_version():
        if ligne.strip() in ("EN", "FR"):
            langue = ligne.strip().lower()
            continue
        match = CODE_RE.match(ligne)
        if match:
            codes[langue].append(match.group(1))
    return codes


# ===== Une seule langue =====


def test_le_rendu_ne_montre_que_la_langue_demandee():
    """Les deux blocs doublaient la longueur de la modale, et personne ne lit
    la moitié qui n'est pas la sienne."""
    fr = get_full_changelog_html("fr")
    en = get_full_changelog_html("en")

    assert "Avant de mettre à jour" in fr
    assert "Before you update" not in fr
    assert "Before you update" in en
    assert "Avant de mettre à jour" not in en


def test_les_marqueurs_de_langue_ne_sont_jamais_rendus():
    for langue in ("fr", "en"):
        rendu = _sans_balises(get_full_changelog_html(langue))
        assert not re.search(r"(?m)^\s*(EN|FR)\s*$", rendu)


def test_un_drapeau_seul_sur_sa_ligne_vaut_marqueur_de_langue():
    """Les vieilles versions du fichier écrivaient 🇫🇷 là où les récentes
    écrivent FR."""
    lignes = ["EN", "* english", "🇫🇷", "* français"]
    assert _lines_for_lang(lignes, "fr") == ["* français"]
    assert _lines_for_lang(lignes, "en") == ["* english"]


def test_une_version_sans_la_langue_demandee_est_rendue_quand_meme():
    """Mieux vaut de l'anglais qu'une version vide dans la modale."""
    lignes = ["EN", "* english only"]
    assert _lines_for_lang(lignes, "fr") == ["* english only"]


# ===== La dernière version ouverte, les autres repliées =====


def test_la_derniere_version_est_ouverte_et_les_autres_sont_repliees():
    rendu = get_full_changelog_html("fr")
    version = CHANGELOG.split("]", 1)[0].split("[", 1)[1]

    latest = rendu.index('class="cl-release cl-release--latest"')
    assert f">v{version}<" in rendu[latest:latest + 400]
    assert rendu.count("<details") >= 5
    assert rendu.index("<details") > latest


def test_chaque_section_porte_son_type_et_son_pictogramme():
    assert _section_kind("✨ Nouveautés") == ("new", "mk-ico-sparkle")
    assert _section_kind("🐛 Correctifs") == ("fix", "mk-ico-bug")
    assert _section_kind("⚠️ Avant de mettre à jour") == ("warn", "mk-ico-alert")
    assert _section_kind("🧭 Limitations connues") == ("limits", "mk-ico-compass")
    assert _section_kind("🔒 Security") == ("security", "mk-ico-shield")
    # Les anciennes versions n'avaient pas d'émoji : le libellé décide.
    assert _section_kind("What's new in 1.6.1")[0] == "new"


def test_les_pictogrammes_du_rendu_existent_dans_le_sprite():
    """`<use href="#…">` sur un symbole absent ne dessine rien, sans erreur."""
    sprite = (ROOT / "templates" / "partials" / "_icons_sprite.html").read_text(encoding="utf-8")
    for identifiant in set(re.findall(r'<use href="#(mk-ico-[\w-]+)">', get_full_changelog_html("fr"))):
        assert f'id="{identifiant}"' in sprite


def test_le_compteur_de_section_annonce_le_nombre_dentrees():
    sections = _parse_sections(["### ✨ Nouveautés", "* **A** — un", "* **B** — deux"])
    from services.changelog_service import _render_section

    assert '<span class="cl-section-count">2</span>' in _render_section(sections[0])


# ===== Titre et corps séparés =====


@pytest.mark.parametrize(
    "ligne",
    [
        "**C69. Un titre** — un corps.",
        "**C69. Un titre** : un corps.",
        "**C69. Un titre.** un corps.",
    ],
)
def test_le_titre_dune_entree_est_sorti_de_son_paragraphe(ligne):
    rendu = _render_item({"text": ligne, "subs": []})

    assert '<span class="cl-tag">C69</span>' in rendu
    titre = re.search(r'<p class="cl-item-title">(.*?)</p>', rendu).group(1)
    assert "Un titre" in _sans_balises(titre)
    assert "un corps" not in _sans_balises(titre)
    assert "un corps" in _sans_balises(re.search(r'<p class="cl-item-body">(.*?)</p>', rendu).group(1))


def test_un_gras_interne_ne_devient_pas_le_titre():
    """« **Install — Chrome** — Téléchargez **le zip** » : le titre s'arrête au
    premier gras, sinon il avale la moitié de l'entrée."""
    rendu = _render_item({"text": "**Install — Chrome** — Téléchargez **le zip** ici.", "subs": []})
    titre = _sans_balises(re.search(r'<p class="cl-item-title">(.*?)</p>', rendu).group(1))

    assert titre.strip() == "Install — Chrome"


def test_une_entree_sans_gras_reste_un_paragraphe():
    rendu = _render_item({"text": "Une phrase seule.", "subs": []})

    assert "cl-item-title" not in rendu
    assert "cl-item--plain" in rendu


def test_les_sous_puces_sont_imbriquees_et_non_aplaties():
    sections = _parse_sections([
        "### ✨ Nouveautés",
        "* **A** — un",
        "  * une précision",
        "* **B** — deux",
    ])

    assert [item["subs"] for item in sections[0]["items"]] == [["une précision"], []]


# ===== Ce que la modale n'a pas à montrer =====


def test_la_queue_des_tests_est_retiree_du_rendu():
    """Elle sert au mainteneur, pas à qui lit les nouveautés — et elle reste
    dans le fichier."""
    rendu = _render_item(
        {"text": "**A** — un corps. Tests : `tests/test_a.py`, `tests/test_b.py`.", "subs": []}
    )

    assert "tests/test_a.py" not in rendu
    assert "un corps" in rendu

    for langue in ("fr", "en"):
        assert not re.search(r"Tests?\s*:", get_full_changelog_html(langue))

    assert "Tests : `tests/" in CHANGELOG


def test_une_sous_puce_qui_ne_parle_que_de_tests_disparait():
    rendu = _render_item({"text": "**A** — un corps.", "subs": ["Tests : `tests/test_a.py`."]})

    assert "cl-subitems" not in rendu


def test_les_filets_horizontaux_ne_deviennent_pas_des_paragraphes():
    sections = _parse_sections(["### ✨ Nouveautés", "* **A** — un", "---"])

    assert sections[0]["paragraphs"] == []


# ===== Ce que le fichier promet =====


def test_les_nouveautes_passent_avant_les_correctifs_dans_les_deux_langues():
    bloc = "\n".join(_bloc_derniere_version())
    for nouveautes, correctifs in (("✨ What's new", "🐛 Bug Fixes"), ("✨ Nouveautés", "🐛 Correctifs")):
        assert bloc.index(nouveautes) < bloc.index(correctifs)


def test_les_deux_langues_decrivent_les_memes_entrees():
    """Une entrée retirée d'un seul côté laisse une version qui ne dit pas la
    même chose selon la langue de l'interface."""
    codes = _codes_par_langue()

    assert codes["en"] == codes["fr"]


def test_aucune_entree_nest_numerotee_deux_fois():
    codes = _codes_par_langue()["en"]

    doublons = {code for code in codes if codes.count(code) > 1}
    assert not doublons


def test_la_derniere_version_ne_raconte_plus_son_propre_developpement():
    """Les bugs d'une fonctionnalité jamais publiée n'ont été vus par personne :
    ils appartiennent au DEVELOPER, pas aux notes de version."""
    bloc = "\n".join(_bloc_derniere_version())

    for retire in ("BF143", "BF154", "BF155", "BF162", "BF164", "BF165", "BF166", "BF168", "BF169"):
        assert retire not in bloc

    # Ces quatre-là réparaient l'Inventaire et l'écriture de chapitre, tous deux
    # publiés pour la première fois par cette version : ce qu'ils garantissent
    # est repris dans l'entrée de la fonctionnalité (C66, C69).
    for fondu in ("BF127", "BF131", "BF132", "BF139"):
        assert fondu not in bloc


def test_une_version_jamais_publiee_na_pas_de_titre_a_elle():
    """La 1.6.6 est restée sur dev : pour qui met à jour depuis la 1.6.5, tout ce
    qu'elle contenait arrive avec la 1.7.0. Deux sections l'obligeraient à
    comparer des notes de version pour savoir ce qu'il reçoit."""
    versions = re.findall(r"^## \[([0-9.]+)\]", CHANGELOG, flags=re.M)

    assert versions[:2] == ["1.7.1", "1.7.0"]
    assert "1.6.6" not in versions


def test_la_derniere_version_dit_depuis_quand_elle_compte():
    """Un correctif nomme la version sur laquelle il s'appuie, pour que l'on
    sache ce que l'on a déjà."""
    bloc = "\n".join(_bloc_derniere_version())

    assert bloc.count("1.7.0") >= 2  # une mention par langue
    for code in ("C84", "C85", "C86", "C87", "BF171", "BF172", "1.0.28"):
        assert code in bloc
