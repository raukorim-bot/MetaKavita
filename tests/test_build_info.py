"""Le commit de build, et la chaîne qui l'amène jusqu'à `/healthz`.

Ce correctif existe à cause d'un incident précis : une production a répondu
« 1.7.2 » pendant une semaine en servant du code antérieur d'une semaine. La
version vient du premier titre de `CHANGELOG.md`, écrit au *début* d'un cycle —
elle annonce donc ce qui se prépare, pas ce qui tourne. Rien dans la réponse ne
permettait de s'en apercevoir.

Le contrat de `/healthz` lui-même vit dans `test_healthz.py`, qui possède cet
endpoint. Ici : le module, et la chaîne qui alimente sa valeur.

Cette valeur ne sert à rien seule : elle dépend de trois maillons —
le workflow passe `--build-arg`, le Dockerfile le transforme en variable
d'environnement, l'application la lit. Retirer n'importe lequel des trois rend
`commit` vide *sans rien casser* : les tests passeraient, l'endpoint
répondrait 200, et l'aveuglement reviendrait sans bruit. D'où les garde-fous
sur le Dockerfile et le workflow, qui ne testent pas du code mais la tuyauterie
qui le nourrit.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.build_info import SHORT_LEN, build_commit, build_commit_short

ROOT = Path(__file__).resolve().parents[1]


# ===== La lecture de la valeur =====


def test_sans_conteneur_le_commit_est_vide_et_pas_un_placeholder(monkeypatch):
    """`""` est la vérité d'un build local. « unknown » obligerait chaque
    appelant à connaître un mot magique pour tester l'absence."""
    monkeypatch.delenv("METAKAVITA_COMMIT", raising=False)

    assert build_commit() == ""
    assert build_commit_short() == ""


def test_le_commit_court_tient_en_sept_caracteres(monkeypatch):
    monkeypatch.setenv("METAKAVITA_COMMIT", "b02b65ead0c5f1e2a3b4c5d6e7f8a9b0c1d2e3f4")

    assert build_commit_short() == "b02b65e"
    assert len(build_commit_short()) == SHORT_LEN


def test_les_espaces_autour_de_la_valeur_ne_comptent_pas(monkeypatch):
    """Un `--build-arg` mal collé ou une variable d'environnement recopiée à la
    main arrivent avec un retour à la ligne : la valeur reste utilisable."""
    monkeypatch.setenv("METAKAVITA_COMMIT", "  b02b65ead0c5\n")

    assert build_commit() == "b02b65ead0c5"
    assert build_commit_short() == "b02b65e"


# ===== La chaîne qui amène la valeur jusqu'au conteneur =====


def test_le_dockerfile_grave_le_commit_dans_l_image():
    """Sans ces deux lignes, la valeur n'entre jamais dans le conteneur."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r'^ARG GIT_SHA=""', dockerfile, flags=re.M), "l'ARG doit avoir un défaut vide pour qu'un build local reste possible"
    assert re.search(r"^ENV METAKAVITA_COMMIT=\$GIT_SHA", dockerfile, flags=re.M)


def test_l_arg_est_declare_apres_l_installation_des_dependances():
    """Sa valeur change à chaque build. Déclaré avant `pip install`, il
    invaliderait ce cache à chaque fois — des minutes de CI par commit."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.index("pip install") < dockerfile.index("ARG GIT_SHA")


def test_la_ci_alimente_le_build_arg():
    """Le Dockerfile seul ne suffit pas : sans cette ligne, toutes les images
    publiées porteraient un commit vide."""
    workflow = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(encoding="utf-8")

    assert "build-args:" in workflow
    assert "GIT_SHA=${{ github.sha }}" in workflow


@pytest.mark.parametrize("cle", ["about_commit_hint"])
def test_l_info_bulle_existe_dans_les_deux_langues(cle):
    from translations import translations

    assert translations["fr"][cle].strip()
    assert translations["en"][cle].strip()
    assert translations["fr"][cle] != translations["en"][cle]
