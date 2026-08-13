"""Sync core arbitré par la version, pas par le sha256 seul (BF143).

`data/scrapers/` est alimenté par deux sources concurrentes : le catalogue
communautaire (prioritaire, à jour entre deux releases) puis le package de
l'image. La seule comparaison disponible était une égalité de sha256, qui dit
si deux copies diffèrent mais pas laquelle est la plus récente. Conséquences :
un fichier posé par un catalogue en retard était déclaré « à jour » pour
toujours, et aucune mise à jour d'image ne pouvait plus livrer ses correctifs.

Ces tests fabriquent une image jetable et un `data/` jetable, pour ne dépendre
ni des scrapers réels ni du réseau.
"""
from __future__ import annotations

import hashlib
import textwrap

import pytest

import services.scraper_manager as sm
import services.scraper_store as store

CORE_FILE = "fakecore.py"


def _core_source(version: str, marker: str) -> str:
    return textwrap.dedent(f"""\
        from scrapers.base import BaseScraper


        class FakeCoreScraper(BaseScraper):
            id = "FAKECORE"
            is_core = True
            display_name = "Fake Core"
            supported_types = {{"Manga"}}
            version = {version!r}
            # {marker}

            def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
                return None
    """)


def _warned_downgrade(caplog) -> bool:
    return any("Downgrade core refusé" in record.getMessage() for record in caplog.records)


@pytest.fixture
def fake_core(tmp_path, monkeypatch):
    """Image jetable + `data/scrapers/` jetable, sans appel réseau."""
    import config_manager

    data_dir = tmp_path / "data"
    (data_dir / "scrapers").mkdir(parents=True)
    image_dir = tmp_path / "image"
    image_dir.mkdir()

    monkeypatch.setattr(config_manager, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(data_dir / "config.json"))
    (data_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sm, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(sm, "package_scrapers_dir", lambda: str(image_dir))
    monkeypatch.setattr(sm, "_try_sync_core_from_github", lambda **kwargs: None)
    monkeypatch.setattr(sm, "_core_filenames_cache", None, raising=False)
    sm.clear_pending_core_updates()

    yield {
        "image": image_dir,
        "data": data_dir / "scrapers",
        "installed": data_dir / "scrapers" / CORE_FILE,
        "shipped": image_dir / CORE_FILE,
    }

    sm._core_filenames_cache = None
    sm.clear_pending_core_updates()


def _wire_catalog(monkeypatch, *, body: bytes, version: str):
    """Branche un catalogue Magasin factice servant `body` pour le fichier core."""
    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [
            {
                "id": "FAKECORE",
                "file": CORE_FILE,
                "is_core": True,
                "version": version,
                "install": {
                    "path": CORE_FILE,
                    "url": f"{store.DEFAULT_RAW_BASE}/{CORE_FILE}",
                    "sha256": hashlib.sha256(body).hexdigest(),
                },
            }
        ],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda **kwargs: catalog)
    monkeypatch.setattr(store, "_download_catalog_python", lambda **kwargs: body)
    monkeypatch.setattr(
        sm,
        "_try_sync_core_from_github",
        lambda **kwargs: store.sync_core_from_catalog(
            auto_update=kwargs.get("auto_update", True), timeout=8.0
        ),
    )


def test_parse_version_tolere_les_versions_exotiques():
    assert sm.parse_version("1.2.3") == (1, 2, 3)
    assert sm.parse_version("2.0.0-rc1") == (2, 0, 0)
    assert sm.parse_version("") == (0,)
    assert sm.parse_version(None) == (0,)
    assert sm.parse_version("n'importe quoi") == (0,)


def test_version_is_newer_ignore_l_egalite_et_la_longueur():
    assert sm.version_is_newer("1.1.0", "1.0.0")
    assert sm.version_is_newer("1.0.1", "1.0")
    assert not sm.version_is_newer("1.0.0", "1.0.0")
    assert not sm.version_is_newer("1.0", "1.0.0")
    assert not sm.version_is_newer("1.0.0", "1.1.0")


def test_file_scraper_version_lit_l_attribut_de_classe(fake_core):
    fake_core["shipped"].write_text(_core_source("2.3.4", "image"), encoding="utf-8")
    assert sm.file_scraper_version(str(fake_core["shipped"])) == "2.3.4"
    assert sm.package_scraper_version(CORE_FILE) == "2.3.4"


def test_version_absente_vaut_le_defaut(fake_core):
    fake_core["shipped"].write_text(
        "class X:\n    id = 'X'\n    is_core = True\n", encoding="utf-8"
    )
    assert sm.file_scraper_version(str(fake_core["shipped"])) == sm.DEFAULT_SCRAPER_VERSION


def test_une_image_plus_recente_ecrase_la_copie_du_catalogue(fake_core, monkeypatch):
    """Le cœur de BF143 : le catalogue passe d'abord, l'image doit rattraper.

    Avant le correctif, `_sync_core_from_image` ne comblait que les fichiers
    absents après un sync catalogue réussi : la copie 1.0.0 restait en place et
    le correctif livré par l'image n'atteignait jamais le registre.
    """
    fake_core["shipped"].write_text(_core_source("1.1.0", "image corrigee"), encoding="utf-8")
    fake_core["installed"].write_text(_core_source("1.0.0", "vieille copie"), encoding="utf-8")
    _wire_catalog(monkeypatch, body=_core_source("1.0.0", "catalogue").encode(), version="1.0.0")

    result = sm.sync_core_scrapers(force=False, auto_update=True)

    assert CORE_FILE in result["updated"]
    assert "image corrigee" in fake_core["installed"].read_text(encoding="utf-8")
    assert sm.installed_scraper_version(CORE_FILE) == "1.1.0"


def test_installation_neuve_prend_l_image_quand_le_catalogue_est_en_retard(
    fake_core, monkeypatch, caplog
):
    """`data/scrapers/` vide : inutile de télécharger une version plus ancienne."""
    fake_core["shipped"].write_text(_core_source("1.1.0", "image corrigee"), encoding="utf-8")
    _wire_catalog(monkeypatch, body=_core_source("1.0.0", "catalogue").encode(), version="1.0.0")

    with caplog.at_level("WARNING"):
        result = sm.sync_core_scrapers(force=False, auto_update=True)

    assert CORE_FILE in result["seeded"]
    assert "image corrigee" in fake_core["installed"].read_text(encoding="utf-8")
    assert _warned_downgrade(caplog)


def test_un_catalogue_plus_recent_reste_prioritaire(fake_core, monkeypatch):
    """La priorité au catalogue est le comportement voulu — quand il est en avance."""
    fake_core["shipped"].write_text(_core_source("1.0.0", "image"), encoding="utf-8")
    fake_core["installed"].write_text(_core_source("1.0.0", "vieille copie"), encoding="utf-8")
    body = _core_source("1.2.0", "catalogue en avance").encode()
    _wire_catalog(monkeypatch, body=body, version="1.2.0")

    result = sm.sync_core_scrapers(force=False, auto_update=True)

    assert CORE_FILE in result["updated"]
    assert "catalogue en avance" in fake_core["installed"].read_text(encoding="utf-8")


def test_l_image_ne_fait_pas_regresser_une_copie_plus_recente(fake_core, caplog):
    """Catalogue injoignable : l'image ne doit pas écraser un core plus récent."""
    fake_core["shipped"].write_text(_core_source("1.0.0", "image ancienne"), encoding="utf-8")
    fake_core["installed"].write_text(_core_source("1.2.0", "copie recente"), encoding="utf-8")

    with caplog.at_level("WARNING"):
        result = sm.sync_core_scrapers(force=False, auto_update=True)

    assert CORE_FILE not in result["updated"]
    assert "copie recente" in fake_core["installed"].read_text(encoding="utf-8")
    assert _warned_downgrade(caplog)


def test_le_forcage_manuel_ne_downgrade_pas_non_plus(fake_core):
    """Le CTA « appliquer les mises à jour core » écrit toujours — sauf en arrière."""
    fake_core["shipped"].write_text(_core_source("1.0.0", "image ancienne"), encoding="utf-8")
    fake_core["installed"].write_text(_core_source("1.2.0", "copie recente"), encoding="utf-8")

    result = sm.apply_core_scraper_updates()

    assert CORE_FILE not in result["updated"]
    assert "copie recente" in fake_core["installed"].read_text(encoding="utf-8")


def test_a_version_egale_le_contenu_de_l_image_tranche_toujours(fake_core):
    """Sans réseau et à version égale, l'image reste la référence du core."""
    fake_core["shipped"].write_text(_core_source("1.0.0", "image"), encoding="utf-8")
    fake_core["installed"].write_text("# copie locale bricolée\n", encoding="utf-8")

    result = sm.sync_core_scrapers(force=False, auto_update=True)

    assert CORE_FILE in result["updated"]
    assert "# image" in fake_core["installed"].read_text(encoding="utf-8")


def test_une_montee_de_version_image_reste_signalee_quand_l_auto_update_est_coupe(
    fake_core, monkeypatch
):
    """AUTO_UPDATE_CORE_SCRAPERS=False : on ne touche à rien, mais on le dit."""
    fake_core["shipped"].write_text(_core_source("1.1.0", "image corrigee"), encoding="utf-8")
    fake_core["installed"].write_text(_core_source("1.0.0", "vieille copie"), encoding="utf-8")
    _wire_catalog(monkeypatch, body=_core_source("1.0.0", "catalogue").encode(), version="1.0.0")

    result = sm.sync_core_scrapers(force=False, auto_update=False)

    assert CORE_FILE not in result["updated"]
    assert CORE_FILE in result["pending"]
    assert "vieille copie" in fake_core["installed"].read_text(encoding="utf-8")
    assert any(p["file"] == CORE_FILE for p in sm.get_pending_core_updates())
