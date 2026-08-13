"""Les résumés d'album partent dans la langue cible, pas dans celle du fournisseur.

L'enrichissement par tome écrivait le texte du fournisseur tel quel — de
l'anglais sur toute une bibliothèque de comics — **et le verrouillait**, ce qui
le mettait hors de portée d'une correction ultérieure puisque la politique de
comblement épargne les champs verrouillés. Le module ne connaissait simplement
pas `translator`.

Ce qui est vérifié ici : que la traduction a lieu, qu'elle ne porte que sur les
résumés que le plan va **écrire**, qu'elle a lieu une seule fois par texte même
quand l'aperçu puis l'écriture reconstruisent le plan, que l'extinction du
traducteur est respectée, et qu'un traducteur en panne laisse passer la passe au
lieu de l'arrêter.

Le grain compte, et c'est le sujet de la moitié des tests : la traduction portait
sur l'index entier du fournisseur, en amont de l'appariement. Un run ComicVine
rend cent numéros pour dix tomes détenus, et sur une série déjà enrichie tous les
résumés sont remplis — donc retraduits pour rien, à chaque passe. Le journal
montrait un appel par seconde pendant des minutes.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.plan import build_plan
from services.volume_enrichment.translate import reset_cache, translate_plan_summaries


@pytest.fixture(autouse=True)
def _vide_le_cache():
    """Le cache est un état de module : sans cela, l'ordre des tests compterait."""
    reset_cache()
    yield
    reset_cache()


@pytest.fixture
def traducteur(monkeypatch):
    """Remplace `translate_texts` par un compteur de requêtes.

    Ce qui est compté est la **requête**, pas le texte : c'est l'unité qui fait
    bloquer une adresse, et l'unité que ce module cherche à économiser.
    """
    requetes = []

    def _fake(texts, target_lang="FR", quiet=False, config=None):
        requetes.append({"texts": list(texts), "target": target_lang, "quiet": quiet})
        return [f"[{target_lang}] {texte}" for texte in texts]

    monkeypatch.setattr("translator.translate_texts", _fake)
    return requetes


def _textes(requetes):
    return [texte for requete in requetes for texte in requete["texts"]]


CONFIG = {"TRANSLATION_PROVIDER": "DEEPL", "TARGET_LANG": "FR", "DEEPL_API_KEY": "k"}


def _unite(numero, chapitre=None, **etat):
    """Une unité écrivable, telle que `units_from_volumes` la rend."""
    return {
        "chapter_id": chapitre if chapitre is not None else 100 + int(numero),
        "volume_id": 900 + int(numero),
        "volume_number": float(numero),
        "chapter_number": None,
        "name": f"Tome {numero}",
        "chapter": etat,
    }


def _plan(index, unites=None, *, force=False):
    return build_plan(unites or [_unite(1)], index, force=force, provider="comicvine")


def test_le_resume_est_traduit_et_le_reste_intact(traducteur):
    plan = _plan(
        {
            "1": {
                "title": "Somewhere Within the Shadows",
                "summary": "Meet John Blacksad, a cat in the shadows.",
                "cover_url": "https://example.test/1.jpg",
                "isbn": "9782205055559",
            }
        }
    )

    out = translate_plan_summaries(plan, CONFIG)
    changes = out["units"][0]["changes"]

    assert changes["summary"]["proposed"] == "[FR] Meet John Blacksad, a cat in the shadows."
    # Le titre est un nom d'œuvre : il ne se traduit pas, comme sur le chemin série.
    assert changes["title"]["proposed"] == "Somewhere Within the Shadows"
    assert changes["cover_url"]["proposed"] == "https://example.test/1.jpg"
    assert changes["isbn"]["proposed"] == "9782205055559"
    assert len(traducteur) == 1


# ===== Le grain : ce qui ne sera pas écrit ne se traduit pas =====


def test_les_albums_que_kavita_ne_detient_pas_ne_sont_pas_traduits(traducteur):
    """Un run ComicVine rend cent numéros ; la bibliothèque en détient dix."""
    index = {str(n): {"summary": f"Issue {n} blurb"} for n in range(1, 101)}

    translate_plan_summaries(_plan(index, [_unite(1), _unite(2)]), CONFIG)

    assert _textes(traducteur) == ["Issue 1 blurb", "Issue 2 blurb"], (
        "seuls les tomes appariés comptent"
    )


def test_un_resume_deja_rempli_ne_se_traduit_pas(traducteur):
    """Le cœur du problème observé : une série déjà enrichie repayait la
    traduction de tous ses albums à chaque passe, un appel par seconde."""
    index = {"1": {"summary": "Meet John Blacksad."}}
    unites = [_unite(1, summary="Un résumé déjà écrit en français.")]

    out = translate_plan_summaries(_plan(index, unites), CONFIG)

    assert traducteur == []
    assert out["units"][0]["changes"]["summary"]["write"] is False


def test_un_resume_verrouille_ne_se_traduit_pas(traducteur):
    index = {"1": {"summary": "Meet John Blacksad."}}
    unites = [_unite(1, summaryLocked=True)]

    translate_plan_summaries(_plan(index, unites), CONFIG)

    assert traducteur == []


def test_une_serie_entierement_faite_ne_coute_aucun_appel(traducteur):
    """Le cas de la passe relancée : tout est rempli et verrouillé."""
    index = {str(n): {"summary": f"Blurb {n}"} for n in range(1, 41)}
    unites = [_unite(n, summary=f"Résumé {n}", summaryLocked=True) for n in range(1, 41)]

    translate_plan_summaries(_plan(index, unites), CONFIG)

    assert traducteur == []


def test_une_passe_forcee_traduit_de_nouveau(traducteur):
    """`VOLUME_FORCE_OVERWRITE` lève la politique de comblement : le résumé part,
    donc il doit être traduit."""
    index = {"1": {"summary": "Meet John Blacksad."}}
    unites = [_unite(1, summary="Ancien texte anglais.")]

    out = translate_plan_summaries(_plan(index, unites, force=True), CONFIG)

    assert len(traducteur) == 1
    assert out["units"][0]["changes"]["summary"]["proposed"].startswith("[FR] ")


def test_une_traduction_identique_a_l_existant_n_est_plus_annoncee(traducteur):
    """Sur une passe forcée, le plan compare le texte du **fournisseur** à celui
    de Kavita : deux textes différents, donc une écriture annoncée. Une fois
    traduit, le texte peut retomber exactement sur celui qui est déjà là."""
    index = {"1": {"summary": "Meet John Blacksad."}}
    unites = [_unite(1, summary="[FR] Meet John Blacksad.")]

    out = translate_plan_summaries(_plan(index, unites, force=True), CONFIG)
    change = out["units"][0]["changes"]["summary"]

    assert change["write"] is False
    assert change["reason"] == "filled"
    # Les compteurs sont ce sur quoi l'interface décide d'annoncer « rien à
    # écrire » : les laisser en arrière promettrait une écriture qui n'aura pas lieu.
    assert out["units"][0]["write_count"] == 0
    assert out["counts"]["writable"] == 0
    assert out["counts"]["fields"] == 0


# ===== Une série entière tient en une requête =====


def test_toute_une_serie_part_en_une_seule_requete(traducteur):
    """La mesure qui met la passe hors de portée d'un blocage.

    Le point d'entrée gratuit de Google accepte plusieurs textes par requête, et
    c'est la requête — non le texte — qui compte pour se faire bloquer. Quarante
    albums en quarante requêtes rapprochées, c'est le profil de trafic qui a fait
    bannir l'IP du développeur pendant cette campagne.
    """
    index = {str(n): {"summary": f"Blurb number {n}"} for n in range(1, 41)}
    unites = [_unite(n) for n in range(1, 41)]

    out = translate_plan_summaries(_plan(index, unites), CONFIG)

    assert len(traducteur) == 1, "une requête, pas quarante"
    assert len(_textes(traducteur)) == 40
    # Et chaque tome reçoit bien *son* résumé : un décalage dans la réponse
    # écrirait le texte d'un album sur un autre, verrouillé au passage.
    for unite in out["units"]:
        attendu = f"[FR] Blurb number {int(unite['matched_on'])}"
        assert unite["changes"]["summary"]["proposed"] == attendu


def test_une_reponse_de_taille_inattendue_est_ignoree(monkeypatch):
    """Plutôt la langue d'origine qu'un résumé posé sur le mauvais album."""

    def _decale(texts, target_lang="FR", quiet=False, config=None):
        return [f"[{target_lang}] {texts[0]}"]

    monkeypatch.setattr("translator.translate_texts", _decale)
    index = {"1": {"summary": "Premier"}, "2": {"summary": "Second"}}

    out = translate_plan_summaries(_plan(index, [_unite(1), _unite(2)]), CONFIG)

    proposes = sorted(u["changes"]["summary"]["proposed"] for u in out["units"])
    assert proposes == ["Premier", "Second"]


# ===== Mémoïsation =====


def test_l_apercu_puis_l_ecriture_ne_paient_qu_une_fois(traducteur):
    """L'écriture reconstruit le plan, sans repayer DeepL.

    L'utilisateur valide un texte dans l'aperçu ; s'il était retraduit à
    l'écriture, il pourrait écrire autre chose que ce qu'il a vu — les moteurs ne
    sont pas déterministes d'un appel à l'autre.
    """
    index = {"1": {"summary": "Meet John Blacksad."}}

    apercu = translate_plan_summaries(_plan(index), CONFIG)
    ecriture = translate_plan_summaries(_plan(index), CONFIG)

    assert (
        apercu["units"][0]["changes"]["summary"]["proposed"]
        == ecriture["units"][0]["changes"]["summary"]["proposed"]
    )
    assert len(traducteur) == 1, "le second passage doit sortir du cache"


def test_deux_tomes_au_meme_texte_ne_font_qu_un_appel(traducteur):
    """Ce que le grain de l'index protégeait — un album couvrant deux chapitres —
    reste couvert : la clé de la mémoïsation est le texte source."""
    index = {
        "1": {"summary": "Same blurb for the whole run."},
        "2": {"summary": "Same blurb for the whole run."},
    }

    out = translate_plan_summaries(_plan(index, [_unite(1), _unite(2)]), CONFIG)

    summaries = [u["changes"]["summary"]["proposed"] for u in out["units"]]
    assert summaries[0] == summaries[1]
    assert _textes(traducteur) == ["Same blurb for the whole run."], (
        "le texte ne doit partir qu'une fois, même en lot"
    )


def test_changer_de_langue_cible_retraduit(traducteur):
    index = {"1": {"summary": "Meet John Blacksad."}}

    translate_plan_summaries(_plan(index), {**CONFIG, "TARGET_LANG": "FR"})
    espagnol = translate_plan_summaries(_plan(index), {**CONFIG, "TARGET_LANG": "ES"})

    assert espagnol["units"][0]["changes"]["summary"]["proposed"].startswith("[ES] ")
    assert len(traducteur) == 2, "la langue fait partie de la clé de cache"


# ===== Pannes et entrées dégénérées =====


def test_traducteur_eteint_laisse_le_texte_d_origine(traducteur):
    """`TRANSLATION_PROVIDER = NONE` : on n'appelle même pas le traducteur.

    Il saurait se taire de lui-même, mais il journalise une ligne par appel :
    une ligne par album pour un travail nul.
    """
    index = {"1": {"summary": "Meet John Blacksad."}}

    out = translate_plan_summaries(
        _plan(index), {"TRANSLATION_PROVIDER": "NONE", "TARGET_LANG": "FR"}
    )

    assert out["units"][0]["changes"]["summary"]["proposed"] == "Meet John Blacksad."
    assert traducteur == []


def test_le_traducteur_ne_journalise_pas_un_album_a_la_fois(traducteur):
    """Le traducteur écrit une ligne INFO par requête. À raison d'une requête par
    album, ces lignes noyaient la progression de la passe : c'est la moitié de ce
    qui se lisait comme du spam dans le journal. Le module rend un décompte."""
    translate_plan_summaries(_plan({"1": {"summary": "Meet John Blacksad."}}), CONFIG)

    assert traducteur, "l'appel devrait avoir eu lieu"
    assert all(r["quiet"] is True for r in traducteur), "`quiet` doit être demandé"


def test_un_traducteur_en_panne_n_arrete_pas_la_passe(monkeypatch):
    """Écrire le texte d'origine vaut mieux que ne rien écrire du tout."""

    def _explose(texts, target_lang="FR", quiet=False, config=None):
        raise RuntimeError("quota épuisé")

    monkeypatch.setattr("translator.translate_texts", _explose)
    index = {"1": {"summary": "Meet John Blacksad."}}

    out = translate_plan_summaries(_plan(index), CONFIG)

    assert out["units"][0]["changes"]["summary"]["proposed"] == "Meet John Blacksad."
    assert out["units"][0]["changes"]["summary"]["write"] is True


def test_les_albums_sans_resume_traversent_sans_appel(traducteur):
    index = {
        "1": {"summary": ""},
        "2": {"title": "Arctic Nation"},
        "3": {"summary": "   "},
    }

    out = translate_plan_summaries(_plan(index, [_unite(n) for n in (1, 2, 3)]), CONFIG)
    titres = [
        (u.get("changes") or {}).get("title", {}).get("proposed")
        for u in out["units"]
    ]

    assert traducteur == []
    assert "Arctic Nation" in titres, f"aucun titre proposé parmi {titres}"


@pytest.mark.parametrize("vide", [None, {}, [], "texte", {"units": []}, {"units": "non"}])
def test_un_plan_inexploitable_est_rendu_tel_quel(vide, traducteur):
    assert translate_plan_summaries(vide, CONFIG) == vide
    assert traducteur == []
