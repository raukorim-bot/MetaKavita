"""
Garde-fou sur la chaîne de publication.

`docker-publish.yml` et `tests.yml` partageaient les mêmes déclencheurs et
tournaient côte à côte : un `pytest` rouge n'empêchait pas l'image de partir sur
GHCR, et un tag de release (`v*`) ne déclenchait même pas les tests. La
publication passe désormais par un appel au workflow de tests. Vérifié en texte
brut plutôt qu'en YAML pour ne pas ajouter de dépendance à la suite.
"""
import os

_WORKFLOWS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".github", "workflows")
)


def _read(name):
    with open(os.path.join(_WORKFLOWS, name), encoding="utf-8") as fh:
        return fh.read()


def test_docker_publish_depends_on_the_test_workflow():
    publish = _read("docker-publish.yml")

    assert "uses: ./.github/workflows/tests.yml" in publish, \
        "la publication doit appeler le workflow de tests"
    assert "needs: tests" in publish, \
        "le job de build doit dépendre du job de tests"


def test_the_test_workflow_is_callable_and_lints():
    tests_wf = _read("tests.yml")

    assert "workflow_call:" in tests_wf, \
        "sans workflow_call, docker-publish.yml ne peut pas appeler ce workflow"
    assert "ruff check ." in tests_wf, "le lint doit tourner en CI"
    assert "pytest" in tests_wf


def test_the_companion_is_checked_before_publishing():
    """L'extension est livrée en zip depuis le dépôt : ni ruff ni pytest ne la
    regardent. Sans ce job, trois clés de traduction non déclarées ont pu partir
    en production et s'afficher brutes aux utilisateurs."""
    tests_wf = _read("tests.yml")

    assert "companion:" in tests_wf, "il faut un job dédié à l'extension"
    for script in (
        "selfcheck-url-match.mjs",
        "selfcheck-i18n.mjs",
        "verify-dist.mjs",
    ):
        assert script in tests_wf, f"{script} doit tourner en CI"
    assert "node --check" in tests_wf, \
        "un fichier de l'extension qui ne parse pas casserait l'extension entière"


def test_ruff_is_pinned_in_dev_requirements():
    """Une version flottante ferait apparaître de nouvelles règles sans préavis,
    faisant échouer la CI — et donc la publication — sur un commit sans rapport."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "requirements-dev.txt"), encoding="utf-8") as fh:
        content = fh.read()

    assert "ruff==" in content
