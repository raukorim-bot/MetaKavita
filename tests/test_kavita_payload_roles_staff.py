"""
Staff : les rôles composés doivent alimenter tous les métiers qu'ils annoncent.

La chaîne de `elif` testait des sous-chaînes dans un ordre qui se trompait sur
deux rôles qu'AniList émet réellement :

* « Story & Art » — le cas le plus courant d'un manga — tombait dans les
  scénaristes et n'alimentait jamais les dessinateurs : la moitié des mangas
  arrivaient dans Kavita sans dessinateur ;
* « Cover Illustration » et « Cover Art » étaient captés par `illustration` /
  `art` avant la branche `cover`, donc rangés en dessinateurs au lieu
  d'illustrateurs de couverture.
"""

from __future__ import annotations

import pytest

from services.kavita_payload import build_kavita_payload, staff_role_buckets


def _staff(*roles):
    return [{"role": r, "node": {"name": {"full": f"Auteur {i}"}}} for i, r in enumerate(roles)]


def _payload(*roles):
    built = build_kavita_payload(
        {"staff": _staff(*roles)}, {}, ["staff"], {}, {}, True, 1
    )
    return built["metadata"]


def _names(meta, key):
    return [p["name"] for p in meta.get(key) or []]


def test_story_and_art_alimente_scenario_et_dessin():
    meta = _payload("Story & Art")

    assert _names(meta, "writers") == ["Auteur 0"]
    assert _names(meta, "pencillers") == ["Auteur 0"], (
        "le mangaka auteur complet n'était compté que comme scénariste"
    )
    assert meta["pencillerLocked"] is True


def test_la_couverture_ne_devient_pas_du_dessin_interieur():
    meta = _payload("Cover Illustration", "Cover Art")

    assert _names(meta, "coverArtists") == ["Auteur 0", "Auteur 1"]
    assert not meta.get("pencillers"), (
        "l'illustrateur de couverture a été rangé avec les dessinateurs"
    )


@pytest.mark.parametrize(
    "role, attendus",
    [
        ("Story", {"writers"}),
        ("Art", {"pencillers"}),
        ("Original Story", {"writers"}),
        ("Story & Art", {"writers", "pencillers"}),
        ("Story, Art", {"writers", "pencillers"}),
        ("Art (Ch. 1-45)", {"pencillers"}),
        ("Cover Illustration", {"cover_artists"}),
        ("Cover Art", {"cover_artists"}),
        ("Colour Assistant", {"colorists"}),
        ("Translator", {"translators"}),
        ("Story & Colour", {"writers", "colorists"}),
        ("Lettering", {"letterers"}),
        ("Inking", {"inkers"}),
        ("Editing", {"editors"}),
        ("Assistant", set()),
    ],
)
def test_les_roles_composes_sont_ventiles(role, attendus):
    assert staff_role_buckets(role) == attendus


def test_un_role_ne_compte_quune_fois_par_metier():
    meta = _payload("Story & Art", "Art")

    assert _names(meta, "pencillers") == ["Auteur 0", "Auteur 1"]
    assert _names(meta, "writers") == ["Auteur 0"]
