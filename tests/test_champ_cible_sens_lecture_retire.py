"""Champ ciblé « Sens lecture » (`format`) — retiré, et qui doit le rester.

La case promettait de choisir si MetaKavita écrivait le sens de lecture d'une
série. Elle n'a jamais rien piloté : `build_kavita_payload` n'a aucune branche
qui lise `"format"` dans le masque, parce que `UpdateSeriesDto` ne porte ni
`Format` ni `FormatLocked` (vérifié de la 0.4.2 à `develop`). Côté Kavita, le
sens de lecture est `AppUserPreferences.ReadingDirection`, une préférence par
utilisateur qu'aucun endpoint ne permet d'imposer série par série.

Trois garanties sont vérifiées ici :

1. la case ne réapparaît nulle part — liste de champs Python, liste JavaScript,
   gabarits, libellés ;
2. la **notion** de format survit : `resolve_kavita_format_enum` et l'aperçu de
   review manuelle affichent toujours le format renvoyé par un fournisseur —
   c'est de la lecture, jamais de l'écriture ;
3. les masques déjà enregistrés en base gardent exactement le sens qu'ils
   avaient. Le cas critique est le masque réduit à ce seul champ : il n'écrivait
   rien, il ne doit pas se mettre à tout écrire.
"""
import os

import pytest

from kavita_constants import resolve_kavita_format_enum
from services.enrichment_engine import ALL_TARGETED_FIELDS, resolve_active_fields
from services.kavita_payload import build_kavita_payload
from translations import translations

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Jetons de la case retirée. Le mot « format » seul serait inexploitable : les
# scrapers en émettent un, l'aperçu l'affiche, et `request.args.get("format")`
# désigne un format d'export. Seuls les identifiants propres à la case cochable
# sont interdits — et sous une forme qui ne peut pas attraper au passage les
# libellés d'affichage `mr_field_format` / `mr_meta_format`, qui eux restent.
_JETONS = (
    '"field_format"',         # clé de traduction du libellé
    "t.field_format",         # lecture de ce libellé dans un gabarit Jinja
    "batch-field-format",     # case du masque batch (sidebar)
    "field-format-__SID__",   # chip du panneau Options d'une série
    'data-field="format"',    # attribut de la même chip
)

_SUFFIXES_SCANNES = (".py", ".js", ".html")

# `tests/` porte les jetons dans ce fichier même ; `debug/` et `data/` ne sont
# pas du code livré ; CHANGELOG / ROADMAP en gardent la trace historique.
_DOSSIERS_IGNORES = frozenset({
    ".git", ".bf140_backup", ".pytest_cache", ".ruff_cache", "__pycache__",
    "data", "debug", "logs", "node_modules", "tests", "venv", ".venv",
})


def _sources_de_production():
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _DOSSIERS_IGNORES]
        for name in filenames:
            if name.endswith(_SUFFIXES_SCANNES):
                yield os.path.join(dirpath, name)


def _lire(chemin_relatif):
    with open(os.path.join(_ROOT, chemin_relatif), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. La case ne revient pas
# ---------------------------------------------------------------------------

def test_le_champ_ne_figure_plus_dans_la_liste_des_champs_ecrivables():
    assert "format" not in ALL_TARGETED_FIELDS, (
        "« format » ne correspond à aucune écriture Kavita : le remettre dans la "
        "liste, c'est réafficher une case qui ne pilote rien."
    )


def test_la_liste_javascript_reste_le_miroir_de_la_liste_python():
    """Une case affichée sans champ correspondant côté serveur (ou l'inverse)
    produit un masque que le moteur d'enrichissement ne sait pas honorer."""
    js = _lire(os.path.join("static", "js", "overrides.js"))
    debut = js.index("const TARGETED_FIELD_KEYS")
    bloc = js[debut: js.index("];", debut)]
    cles_js = [
        morceau.strip().strip("',\"")
        for morceau in bloc[bloc.index("[") + 1:].split(",")
        if morceau.strip()
    ]
    assert cles_js == list(ALL_TARGETED_FIELDS)


def test_aucune_source_de_production_ne_remet_la_case():
    coupables = []
    scannes = 0
    for chemin in _sources_de_production():
        scannes += 1
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            contenu = fh.read()
        for jeton in _JETONS:
            if jeton in contenu:
                coupables.append(f"{os.path.relpath(chemin, _ROOT)} ({jeton})")

    # Un parcours qui ne lirait plus rien serait vert sans rien garantir.
    assert scannes > 100, f"seulement {scannes} fichiers parcourus : le parcours est cassé"

    assert coupables == [], (
        "La case « Sens lecture » est réapparue : "
        + ", ".join(sorted(coupables))
        + ". Kavita n'accepte aucun sens de lecture par série ; cocher ou "
        "décocher cette case ne changeait rien à ce qui était envoyé."
    )


@pytest.mark.parametrize("langue", ("fr", "en"))
def test_le_libelle_de_la_case_ne_survit_dans_aucune_langue(langue):
    assert "field_format" not in translations[langue]


def test_les_deux_dictionnaires_restent_a_parite():
    assert set(translations["fr"]) == set(translations["en"])


# ---------------------------------------------------------------------------
# 2. La notion de format, elle, reste — en lecture seule
# ---------------------------------------------------------------------------

def test_le_format_renvoye_par_un_fournisseur_reste_affiche_dans_l_apercu():
    """L'aperçu de review manuelle montre le format du fournisseur pour aider à
    trancher entre deux candidats. Il ne dépend d'aucun champ ciblé, et n'a
    jamais rien écrit."""
    resultat = build_kavita_payload(
        provider_data={"title": "X", "format": "manga"},
        metadata={"seriesId": 1},
        active_fields=[],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert resultat["preview_fields"]["format"] == "manga"


@pytest.mark.parametrize("langue", ("fr", "en"))
def test_les_libelles_d_affichage_du_format_restent(langue):
    assert translations[langue]["mr_field_format"]
    assert translations[langue]["mr_meta_format"]


def test_la_table_de_formats_reste_utilisable():
    assert resolve_kavita_format_enum("manga") == 1
    assert resolve_kavita_format_enum("webtoon") == 4


# ---------------------------------------------------------------------------
# 3. Les masques déjà enregistrés gardent leur sens
# ---------------------------------------------------------------------------

_DONNEES_FOURNISSEUR = {
    "title": "Berserk",
    "summary": "Un résumé.",
    "year": 1989,
    "status": "RELEASING",
    "genres": ["Action"],
    "tags": ["Sombre"],
    "publisher": "Hakusensha",
    "age_rating": "mature",
    "format": "manga",
    "staff": [{"role": "Story & Art", "node": {"name": {"full": "Kentaro Miura"}}}],
    "anilist_id": 30002,
    "url": "https://anilist.co/manga/30002",
    "cover_url": "https://example.test/cover.jpg",
}


def _payload_pour(masque):
    return build_kavita_payload(
        provider_data=dict(_DONNEES_FOURNISSEUR),
        metadata={"seriesId": 1},
        active_fields=resolve_active_fields(masque),
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )


def test_un_masque_herite_reduit_au_champ_retire_n_ecrit_toujours_rien():
    """Le vrai risque du retrait. Un utilisateur dont la série ne ciblait que
    « Sens lecture » n'écrivait rien ; son prochain batch ne doit pas se mettre
    à tout écrire sous prétexte que le jeton n'est plus reconnu."""
    actifs = resolve_active_fields("format")
    assert actifs == ["format"], (
        "le jeton hérité doit traverser la résolution tel quel : le réduire à "
        "une liste vide le ferait confondre avec « ALL »"
    )
    assert actifs != list(ALL_TARGETED_FIELDS)

    resultat = _payload_pour("format")
    assert resultat["metadata"] == {"seriesId": 1}
    assert resultat["localized_name"] is None
    assert resultat["external_ids"] == {"anilist": None, "mal": None, "mangabaka": None}


def test_un_masque_herite_mixte_garde_ses_autres_champs():
    """Le jeton résiduel est inerte, mais il ne doit rien emporter avec lui."""
    metadata = _payload_pour("summary,format")["metadata"]
    assert metadata["summary"] == "Un résumé."
    assert metadata["summaryLocked"] is True
    assert "publicationStatus" not in metadata
    assert "genres" not in metadata
    assert "publishers" not in metadata


def test_un_masque_herite_est_relu_sans_la_case_mais_sans_changer_de_sens(
    client, isolated_db
):
    """Bout en bout : le panneau d'une série dont le masque enregistré ne
    contenait que le champ retiré s'ouvre entièrement décoché. Le ré-enregistrer
    stocke « NONE » — pas une chaîne vide, que le moteur relirait comme « tous
    les champs »."""
    from models import SeriesOverride

    isolated_db.save_series_override(
        SeriesOverride(series_id=4242, targeted_fields="format")
    )
    stocke = isolated_db.get_all_cached_data()[4242]["targeted_fields"]
    assert stocke == "format", "aucune migration : la valeur reste sur le disque"
    assert resolve_active_fields(stocke) == ["format"]

    reponse = client.post(
        "/save-override",
        data={
            "series_id": "4242",
            "forced_id": "",
            "alternative_title": "",
            "forced_provider": "AUTO",
            "targeted_fields": "",
        },
    )
    assert reponse.status_code == 200

    relu = isolated_db.get_all_cached_data()[4242]["targeted_fields"]
    assert relu == "NONE"
    assert resolve_active_fields(relu) == []


def test_un_enregistrement_sans_masque_vise_toujours_tous_les_champs(
    client, isolated_db
):
    """Contre-épreuve : le paramètre absent (appelants qui ne gèrent pas le
    granulaire) doit continuer de valoir « ALL »."""
    reponse = client.post(
        "/save-override",
        data={"series_id": "4243", "forced_id": "", "alternative_title": ""},
    )
    assert reponse.status_code == 200
    assert isolated_db.get_all_cached_data()[4243]["targeted_fields"] == "ALL"
