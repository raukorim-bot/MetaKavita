"""
Tests seed / registry data-only / DISABLED_SCRAPERS / scopes / store install.
"""
import hashlib
import textwrap
from unittest.mock import MagicMock

import pytest

from scrapers import _ScraperRegistry
from scrapers.base import BaseScraper


class _SeriesScraper(BaseScraper):
    id = "FAKE_SERIES"
    display_name = "Fake Series"
    supported_types = {"Manga"}
    scopes = {"series"}

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        return None


class _VolumeScraper(BaseScraper):
    id = "FAKE_VOLUME"
    display_name = "Fake Volume"
    supported_types = {"Manga"}
    scopes = {"volume"}

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        return None


def _write_scraper(path, class_name, scraper_id, scopes=None):
    scopes = scopes or {"series"}
    scopes_repr = "{" + ", ".join(repr(s) for s in sorted(scopes)) + "}"
    path.write_text(textwrap.dedent(f"""\
        from scrapers.base import BaseScraper

        class {class_name}(BaseScraper):
            id = {scraper_id!r}
            display_name = {scraper_id!r}
            supported_types = {{"Manga"}}
            scopes = {scopes_repr}

            def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
                return None
    """), encoding="utf-8")


def _patch_install_load_ok(monkeypatch, store, scraper_id, scopes=None):
    """Install now requires loaded scraper after reload — stub both."""
    scopes = set(scopes or {"series"})

    class _Loaded:
        id = scraper_id

        def normalized_scopes(self):
            return scopes

    monkeypatch.setattr(store.ScraperRegistry, "reload", lambda: None)
    monkeypatch.setattr(
        store.ScraperRegistry,
        "get",
        lambda sid, include_disabled=False: _Loaded() if sid == scraper_id else None,
    )
    monkeypatch.setattr(store.ScraperRegistry, "get_proxy_cover_hosts", lambda: [])


@pytest.fixture
def isolated_scrapers(tmp_path, monkeypatch):
    """DATA_DIR jetable + registre frais (pas le singleton global)."""
    import config_manager
    import services.scraper_manager as sm

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    scrapers_dir = data_dir / "scrapers"
    scrapers_dir.mkdir()

    monkeypatch.setattr(config_manager, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(data_dir / "config.json"))
    monkeypatch.setattr(sm, "DATA_DIR", str(data_dir))
    # Tests image-path déterministes : pas d'appel réseau Magasin par défaut.
    monkeypatch.setattr(sm, "_try_sync_core_from_github", lambda **kwargs: None)
    sm.clear_pending_core_updates()
    sm._core_filenames_cache = None

    # Empty config
    (data_dir / "config.json").write_text("{}", encoding="utf-8")

    registry = _ScraperRegistry()
    return {
        "data_dir": data_dir,
        "scrapers_dir": scrapers_dir,
        "registry": registry,
        "sm": sm,
        "config_manager": config_manager,
    }


def test_list_core_filenames_requires_is_core_flag(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    core_files = sm.list_core_filenames()
    assert "mangabaka.py" in core_files
    assert "anilist.py" in core_files
    assert "base.py" not in core_files
    assert "utils.py" not in core_files
    assert "wikidata_map.py" not in core_files


def test_seed_updates_stale_core_when_auto_on(isolated_scrapers, monkeypatch):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    config_manager = isolated_scrapers["config_manager"]

    monkeypatch.setattr(
        config_manager,
        "load_config",
        lambda: {"AUTO_UPDATE_CORE_SCRAPERS": True},
    )

    marker = scrapers_dir / "mangabaka.py"
    marker.write_text("# stale local copy\n", encoding="utf-8")

    result = sm.sync_core_scrapers(force=False, auto_update=True)
    assert "mangabaka.py" in result["updated"]
    assert marker.read_text(encoding="utf-8") != "# stale local copy\n"
    assert "is_core = True" in marker.read_text(encoding="utf-8")
    assert sm.get_pending_core_updates() == []


def _wire_github_catalog(
    monkeypatch, sm, *, body: bytes, auto_via_try: bool = True, version: str = "9.9.9"
):
    """Branche un catalogue Magasin mocké sur le chemin sync core GitHub.

    La version par défaut dépasse celle de tous les scrapers de l'image : sans
    elle, l'entrée serait lue comme un miroir en retard et refusée avant même le
    téléchargement. Ces tests portent sur la priorité du catalogue, pas sur le
    refus de régression — celui-ci est couvert par test_core_scraper_versioning.
    """
    import hashlib
    import services.scraper_store as store

    sha = hashlib.sha256(body).hexdigest()
    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [
            {
                "id": "MANGABAKA",
                "file": "mangabaka.py",
                "is_core": True,
                "version": version,
                "install": {
                    "path": "scrapers/mangabaka.py",
                    "url": f"{store.DEFAULT_RAW_BASE}/scrapers/mangabaka.py",
                    "sha256": sha,
                },
            }
        ],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda **kwargs: catalog)
    monkeypatch.setattr(store, "_download_catalog_python", lambda **kwargs: body)
    if auto_via_try:
        monkeypatch.setattr(
            sm,
            "_try_sync_core_from_github",
            lambda **kwargs: store.sync_core_from_catalog(
                auto_update=kwargs.get("auto_update", True), timeout=8.0
            ),
        )
    return store


def test_github_core_sync_updates_before_image(isolated_scrapers, monkeypatch):
    """Catalogue GitHub prioritaire : contenu community écrit quand il apporte du neuf."""
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    body = b"# github core hotfix\nis_core = True\n\n\nclass Hotfix:\n    version = \"9.9.9\"\n"
    _wire_github_catalog(monkeypatch, sm, body=body)

    marker = scrapers_dir / "mangabaka.py"
    marker.write_text("# stale local copy\n", encoding="utf-8")

    result = sm.sync_core_scrapers(force=False, auto_update=True)
    assert "mangabaka.py" in result["updated"]
    assert marker.read_bytes() == body
    assert sm.resolve_origin("mangabaka.py") == "core"


def test_github_unreachable_falls_back_to_image(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]

    # Fixture mocks github → None ; fall-through image
    marker = scrapers_dir / "mangabaka.py"
    marker.write_text("# stale\n", encoding="utf-8")
    result = sm.sync_core_scrapers(force=False, auto_update=True)
    assert "mangabaka.py" in result["updated"]
    assert "is_core = True" in marker.read_text(encoding="utf-8")


def test_github_pending_when_auto_off(isolated_scrapers, monkeypatch):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    body = b"# newer from github\n"
    _wire_github_catalog(monkeypatch, sm, body=body)

    marker = scrapers_dir / "mangabaka.py"
    marker.write_text("# local kept\n", encoding="utf-8")

    result = sm.sync_core_scrapers(force=False, auto_update=False)
    assert "mangabaka.py" not in result["updated"]
    assert "mangabaka.py" in result["pending"]
    assert marker.read_text(encoding="utf-8") == "# local kept\n"


def test_github_seed_missing_on_fresh_install(isolated_scrapers, monkeypatch):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    body = b"# fresh github seed\nis_core = True\n\n\nclass Seed:\n    version = \"9.9.9\"\n"
    _wire_github_catalog(monkeypatch, sm, body=body)

    marker = scrapers_dir / "mangabaka.py"
    assert not marker.is_file()

    result = sm.sync_core_scrapers(force=False, auto_update=True)
    assert "mangabaka.py" in result["seeded"]
    assert marker.read_bytes() == body


def test_seed_keeps_stale_when_auto_off(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]

    marker = scrapers_dir / "mangabaka.py"
    marker.write_text("# stale local copy\n", encoding="utf-8")

    result = sm.sync_core_scrapers(force=False, auto_update=False)
    assert "mangabaka.py" not in result["updated"]
    assert "mangabaka.py" in result["pending"]
    assert marker.read_text(encoding="utf-8") == "# stale local copy\n"
    pending = sm.get_pending_core_updates()
    assert any(p["file"] == "mangabaka.py" for p in pending)


def test_seed_skips_identical_core(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    sm.seed_core_scrapers()
    target = scrapers_dir / "mangabaka.py"
    before = target.read_bytes()
    mtime = target.stat().st_mtime

    result = sm.sync_core_scrapers(force=True)
    assert "mangabaka.py" not in result["seeded"]
    assert "mangabaka.py" not in result["updated"]
    assert target.read_bytes() == before
    assert target.stat().st_mtime == mtime


def test_apply_core_scraper_updates_force(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    marker = scrapers_dir / "mangabaka.py"
    marker.write_text("# stale\n", encoding="utf-8")
    sm.sync_core_scrapers(force=False, auto_update=False)
    assert sm.get_pending_core_updates()

    result = sm.apply_core_scraper_updates()
    assert "mangabaka.py" in result["updated"]
    assert sm.get_pending_core_updates() == []
    assert "is_core = True" in marker.read_text(encoding="utf-8")


def test_seed_reseeds_deleted_core(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    sm.seed_core_scrapers()
    target = scrapers_dir / "mangabaka.py"
    assert target.is_file()
    target.unlink()
    copied = sm.seed_core_scrapers()
    assert "mangabaka.py" in copied
    assert target.is_file()


def test_purge_demoted_legacy_wikidata_seed(isolated_scrapers):
    """Former core wikidata.py with relative imports must be removed on upgrade."""
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    assert "wikidata.py" not in sm.list_core_filenames()

    legacy = scrapers_dir / "wikidata.py"
    legacy.write_text(
        "from .base import BaseScraper\nfrom .wikidata_map import normalize_qid\n",
        encoding="utf-8",
    )
    sm.set_origin("wikidata.py", "core")

    removed = sm.purge_demoted_core_scrapers()
    assert "wikidata.py" in removed
    assert not legacy.is_file()
    assert "wikidata.py" not in sm.load_origins()


def test_purge_keeps_community_wikidata_install(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    community = scrapers_dir / "wikidata.py"
    community.write_text(
        "from scrapers.base import BaseScraper\nfrom scrapers.wikidata_map import normalize_qid\n",
        encoding="utf-8",
    )
    sm.set_origin("wikidata.py", "community")

    removed = sm.purge_demoted_core_scrapers()
    assert "wikidata.py" not in removed
    assert community.is_file()
    assert sm.load_origins().get("wikidata.py") == "community"


def test_registry_loads_only_data_scrapers(isolated_scrapers):
    registry = isolated_scrapers["registry"]
    scrapers_dir = isolated_scrapers["scrapers_dir"]

    # Only seed a tiny fake set — avoid loading full core for speed
    _write_scraper(scrapers_dir / "fake_series.py", "FakeSeries", "FAKE_SERIES")
    import services.scraper_manager as sm_mod
    from unittest.mock import patch

    with patch.object(sm_mod, "list_core_filenames", return_value=[]):
        registry.load_all()

    assert registry.get("FAKE_SERIES") is not None
    assert registry.get("MANGABAKA") is None  # not seeded in this test


def test_disabled_scrapers_filtered(isolated_scrapers, monkeypatch):
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    registry = isolated_scrapers["registry"]
    cm = isolated_scrapers["config_manager"]
    _write_scraper(scrapers_dir / "fake_series.py", "FakeSeries", "FAKE_SERIES")

    import services.scraper_manager as sm_mod
    from unittest.mock import patch

    with patch.object(sm_mod, "list_core_filenames", return_value=[]):
        registry.load_all()

    assert registry.get("FAKE_SERIES") is not None
    monkeypatch.setattr(cm, "get_disabled_scraper_ids", lambda config=None: {"FAKE_SERIES"})
    # Registry reads get_disabled via import inside method — patch config_manager symbol used
    monkeypatch.setattr("config_manager.get_disabled_scraper_ids", lambda config=None: {"FAKE_SERIES"})

    assert registry.get("FAKE_SERIES") is None
    assert registry.get("FAKE_SERIES", include_disabled=True) is not None
    assert registry.get_by_type("Manga") == []
    assert len(registry.get_all(include_disabled=True)) == 1


def test_volume_scope_excluded_from_series_providers(isolated_scrapers):
    scrapers_dir = isolated_scrapers["scrapers_dir"]
    registry = isolated_scrapers["registry"]
    _write_scraper(scrapers_dir / "fake_series.py", "FakeSeries", "FAKE_SERIES", {"series"})
    _write_scraper(scrapers_dir / "fake_volume.py", "FakeVolume", "FAKE_VOLUME", {"volume"})

    import services.scraper_manager as sm_mod
    from unittest.mock import patch

    with patch.object(sm_mod, "list_core_filenames", return_value=[]):
        registry.load_all()

    series = registry.get_by_type("Manga", scope="series")
    assert [s.id for s in series] == ["FAKE_SERIES"]
    volumes = registry.get_by_scope("volume")
    assert [s.id for s in volumes] == ["FAKE_VOLUME"]


def test_delete_core_forbidden(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    sm.seed_core_scrapers()
    with pytest.raises(PermissionError):
        sm.delete_scraper_file("mangabaka.py")


def test_safe_scraper_path_rejects_traversal(isolated_scrapers):
    sm = isolated_scrapers["sm"]
    assert sm.safe_scraper_path("../evil.py") is None
    assert sm.safe_scraper_path("subdir/x.py") is None
    assert sm.safe_scraper_path("ok_scraper.py") is not None


def test_install_from_catalog_sha256(isolated_scrapers, monkeypatch):
    from services import scraper_store as store

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    content = b"# community scraper\nfrom scrapers.base import BaseScraper\n\nclass W(BaseScraper):\n    id='WEBTOON_SHA_TEST'\n    display_name='Webtoon'\n    supported_types={'Manga'}\n    def fetch(self, query, library_type='Manga', is_id=False, existing_metadata=None):\n        return None\n"
    digest = hashlib.sha256(content).hexdigest()
    file_name = "webtoon_sha_test.py"
    url = f"{store.DEFAULT_RAW_BASE}/{file_name}"

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "WEBTOON_SHA_TEST",
            "file": file_name,
            "display_name": "Webtoon",
            "scopes": ["series"],
            "install": {
                "path": file_name,
                "url": url,
                "sha256": digest,
                "bytes": len(content),
            },
        }],
    }

    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    _patch_install_load_ok(monkeypatch, store, "WEBTOON_SHA_TEST")

    fake = MagicMock()
    fake.content = content
    fake.headers = {"Content-Type": "text/plain; charset=utf-8"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)

    # Avoid writing into real registry; just check file write + sha
    result = store.install_from_catalog("WEBTOON_SHA_TEST")
    assert result["id"] == "WEBTOON_SHA_TEST"
    assert result["loaded"] is True
    written = scrapers_dir / file_name
    assert written.is_file()
    assert written.read_bytes() == content


def test_install_sha_mismatch_writes_nothing(isolated_scrapers, monkeypatch):
    from services import scraper_store as store

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    content = b"hello"
    file_name = "bad.py"
    url = f"{store.DEFAULT_RAW_BASE}/{file_name}"
    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "BAD",
            "file": file_name,
            "install": {"path": file_name, "url": url, "sha256": "0" * 64},
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)

    fake = MagicMock()
    fake.content = content
    fake.headers = {"Content-Type": "text/plain"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)

    with pytest.raises(store.StoreError) as ei:
        store.install_from_catalog("BAD")
    assert "sha256" in ei.value.message
    assert not (scrapers_dir / file_name).exists()


def test_install_rejects_url_outside_raw_base(isolated_scrapers, monkeypatch):
    from services import scraper_store as store

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "EVIL",
            "file": "evil.py",
            "install": {
                "path": "evil.py",
                "url": "https://evil.example/evil.py",
                "sha256": "a" * 64,
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    with pytest.raises(store.StoreError):
        store.install_from_catalog("EVIL")


def test_install_core_forbidden(isolated_scrapers, monkeypatch):
    from services import scraper_store as store

    sm = isolated_scrapers["sm"]
    sm.seed_core_scrapers()
    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "MANGABAKA",
            "file": "mangabaka.py",
            "install": {
                "path": "mangabaka.py",
                "url": f"{store.DEFAULT_RAW_BASE}/mangabaka.py",
                "sha256": "b" * 64,
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    with pytest.raises(store.StoreError) as ei:
        store.install_from_catalog("MANGABAKA")
    assert ei.value.status_code == 403


def test_api_delete_core_403(isolated_scrapers):
    """Deleting a core scraper file is refused (PermissionError / route 403)."""
    sm = isolated_scrapers["sm"]
    sm.seed_core_scrapers()
    assert sm.is_core_filename("mangabaka.py")
    with pytest.raises(PermissionError):
        sm.delete_scraper_file("mangabaka.py")


def test_normalized_scopes_default_series():
    s = _SeriesScraper()
    assert s.normalized_scopes() == {"series"}
    v = _VolumeScraper()
    assert v.normalized_scopes() == {"volume"}
    assert v.fetch_volume("x") is None


def test_sha256_matches_tolerates_crlf_vs_lf():
    """Catalogue Windows (CRLF) vs raw GitHub (LF) — même fichier logique."""
    from services.scraper_manager import sha256_matches, sha256_hex

    lf = b"print('hello')\nprint('world')\n"
    crlf = b"print('hello')\r\nprint('world')\r\n"
    assert sha256_hex(lf) != sha256_hex(crlf)
    assert sha256_matches(lf, sha256_hex(crlf))
    assert sha256_matches(crlf, sha256_hex(lf))
    assert sha256_matches(lf, sha256_hex(lf))
    assert not sha256_matches(lf, "0" * 64)


def test_install_accepts_catalog_crlf_hash_for_lf_download(isolated_scrapers, monkeypatch):
    from services import scraper_store as store
    from services.scraper_manager import sha256_hex

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    lf_content = b"# community\nfrom scrapers.base import BaseScraper\n\nclass W(BaseScraper):\n    id='WEBTOON_EOL_TEST'\n    display_name='Webtoon'\n    supported_types={'Manga'}\n    def fetch(self, query, library_type='Manga', is_id=False, existing_metadata=None):\n        return None\n"
    crlf_content = lf_content.replace(b"\n", b"\r\n")
    catalog_sha = sha256_hex(crlf_content)  # as if built on Windows
    file_name = "webtoon_eol_test.py"
    url = f"{store.DEFAULT_RAW_BASE}/{file_name}"

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "WEBTOON_EOL_TEST",
            "file": file_name,
            "display_name": "Webtoon",
            "scopes": ["series"],
            "install": {
                "path": file_name,
                "url": url,
                "sha256": catalog_sha,
                "bytes": len(crlf_content),
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    _patch_install_load_ok(monkeypatch, store, "WEBTOON_EOL_TEST")

    fake = MagicMock()
    fake.content = lf_content  # GitHub raw serves LF
    fake.headers = {"Content-Type": "text/plain; charset=utf-8"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)

    result = store.install_from_catalog("WEBTOON_EOL_TEST")
    assert result["id"] == "WEBTOON_EOL_TEST"
    assert (scrapers_dir / file_name).read_bytes() == lf_content


def test_update_detection_ignores_eol_only_diff(isolated_scrapers, monkeypatch):
    from services import scraper_store as store
    from services.scraper_manager import sha256_hex, write_scraper_bytes

    lf = b"print(1)\n"
    crlf_sha = sha256_hex(b"print(1)\r\n")
    file_name = "eol_check.py"
    write_scraper_bytes(file_name, lf, origin="community")

    # Fake registry entry pointing at that file
    class _S(_SeriesScraper):
        id = "EOLCHECK"

    registry = isolated_scrapers["registry"]
    registry._scrapers["EOLCHECK"] = _S()
    registry._sources["EOLCHECK"] = file_name
    monkeypatch.setattr(store, "ScraperRegistry", registry)

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "EOLCHECK",
            "file": file_name,
            "display_name": "EOL",
            "install": {
                "path": file_name,
                "url": f"{store.DEFAULT_RAW_BASE}/{file_name}",
                "sha256": crlf_sha,
            },
        }],
    }
    enriched = store.enrich_catalog_for_ui(catalog, lang="en")
    row = enriched["scrapers"][0]
    assert row["state"] == "installed"
    assert row["update_available"] is False


def test_content_mismatch_marks_update_and_force_replaces(isolated_scrapers, monkeypatch):
    """sha discordant → state=update ; install force remplace data/scrapers/<file>."""
    from services import scraper_store as store
    from services.scraper_manager import sha256_hex, write_scraper_bytes

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    file_name = "outdated_scraper.py"
    old = b"# old version\nprint(1)\n"
    new = b"# new version\nprint(2)\n"
    write_scraper_bytes(file_name, old, origin="community")

    class _S(_SeriesScraper):
        id = "OUTDATED"

    registry = isolated_scrapers["registry"]
    registry._scrapers["OUTDATED"] = _S()
    registry._sources["OUTDATED"] = file_name
    monkeypatch.setattr(store, "ScraperRegistry", registry)

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "OUTDATED",
            "file": file_name,
            "display_name": "Outdated",
            "install": {
                "path": file_name,
                "url": f"{store.DEFAULT_RAW_BASE}/{file_name}",
                "sha256": sha256_hex(new),
                "bytes": len(new),
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)

    enriched = store.enrich_catalog_for_ui(catalog, lang="en")
    row = enriched["scrapers"][0]
    assert row["state"] == "update"
    assert row["update_available"] is True

    fake = MagicMock()
    fake.content = new
    fake.headers = {"Content-Type": "text/plain; charset=utf-8"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)
    _patch_install_load_ok(monkeypatch, store, "OUTDATED")

    result = store.install_from_catalog("OUTDATED", force=True)
    assert result["action"] == "updated"
    assert result["updated"] is True
    assert (scrapers_dir / file_name).read_bytes() == new


def test_retired_status_blocks_install_and_marks_ui(isolated_scrapers, monkeypatch):
    from services import scraper_store as store
    from services.scraper_manager import sha256_hex

    body = b"# retired scraper\n"
    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "DEADSRC",
            "file": "dead_src.py",
            "display_name": "Dead",
            "status": "retired",
            "install": {
                "path": "dead_src.py",
                "url": f"{store.DEFAULT_RAW_BASE}/dead_src.py",
                "sha256": sha256_hex(body),
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    enriched = store.enrich_catalog_for_ui(catalog, lang="en")
    row = enriched["scrapers"][0]
    assert row["retired"] is True
    assert row["status"] == "retired"

    try:
        store.install_from_catalog("DEADSRC", force=False)
        assert False, "expected StoreError"
    except store.StoreError as e:
        assert e.status_code == 403
        assert "retired" in e.message.lower()


def test_retired_via_tag(isolated_scrapers):
    from services.scraper_store import is_entry_retired

    assert is_entry_retired({"status": "stable", "tags": ["retired"]}) is True
    assert is_entry_retired({"status": "stable", "tags": ["html"]}) is False
    assert is_entry_retired({"retired": True}) is True


def test_manage_flags_off_store_and_removed(isolated_scrapers, monkeypatch):
    from routes.scrapers_manage import list_installed_payload
    from services import scraper_store as store
    from services.scraper_manager import write_scraper_bytes

    write_scraper_bytes("manual_drop.py", b"# custom\n", origin="custom")
    write_scraper_bytes("gone_store.py", b"# was store\n", origin="community")

    class _Manual(_SeriesScraper):
        id = "MANUALDROP"

    class _Gone(_SeriesScraper):
        id = "GONESTORE"

    registry = isolated_scrapers["registry"]
    registry._scrapers = {"MANUALDROP": _Manual(), "GONESTORE": _Gone()}
    registry._sources = {"MANUALDROP": "manual_drop.py", "GONESTORE": "gone_store.py"}
    monkeypatch.setattr("routes.scrapers_manage.ScraperRegistry", registry)
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: {
        "schema_version": 1,
        "scrapers": [{"id": "STILLTHERE", "file": "still.py"}],
    })

    payload = list_installed_payload(config={"DISABLED_SCRAPERS": ""})
    by_id = {r["id"]: r for r in payload["scrapers"]}
    assert by_id["MANUALDROP"]["off_store"] is True
    assert by_id["MANUALDROP"]["from_store"] is False
    assert by_id["GONESTORE"]["from_store"] is True
    assert by_id["GONESTORE"]["removed_from_store"] is True


def test_proxy_cover_hosts_from_requires_proxy(isolated_scrapers, monkeypatch):
    """Manual Review lit window.PROXY_COVER_HOSTS depuis requires_proxy scrapers."""
    registry = isolated_scrapers["registry"]

    class _NeedsProxy(_SeriesScraper):
        id = "NEEDSPROXY"
        requires_proxy = True
        proxy_domains = ["cdn.example-hotlink.test", "www.example-hotlink.test"]

    class _NoProxy(_SeriesScraper):
        id = "NOPROXY"
        requires_proxy = False
        proxy_domains = ["open.example.test"]

    registry._scrapers = {"NEEDSPROXY": _NeedsProxy(), "NOPROXY": _NoProxy()}
    hosts = registry.get_proxy_cover_hosts()
    assert "cdn.example-hotlink.test" in hosts
    assert "www.example-hotlink.test" in hosts
    assert "open.example.test" not in hosts


def test_install_unloadable_rolls_back(isolated_scrapers, monkeypatch):
    from services import scraper_store as store

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    content = b"# broken - no BaseScraper class\nprint('nope')\n"
    digest = hashlib.sha256(content).hexdigest()
    file_name = "broken_unloadable.py"
    url = f"{store.DEFAULT_RAW_BASE}/{file_name}"
    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "BROKEN_UNLOAD",
            "file": file_name,
            "display_name": "Broken",
            "scopes": ["series"],
            "install": {
                "path": file_name,
                "url": url,
                "sha256": digest,
                "bytes": len(content),
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    registry = isolated_scrapers["registry"]
    monkeypatch.setattr(store, "ScraperRegistry", registry)

    fake = MagicMock()
    fake.content = content
    fake.headers = {"Content-Type": "text/plain"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)
    monkeypatch.setattr(registry, "reload", lambda: None)
    monkeypatch.setattr(registry, "get", lambda sid, include_disabled=False: None)
    monkeypatch.setattr(registry, "get_proxy_cover_hosts", lambda: [])

    deleted = []

    def _del(name):
        deleted.append(name)
        p = scrapers_dir / name
        if p.is_file():
            p.unlink()

    monkeypatch.setattr(store, "delete_scraper_file", _del)

    with pytest.raises(store.StoreError) as ei:
        store.install_from_catalog("BROKEN_UNLOAD")
    assert "failed to load" in ei.value.message.lower()
    assert file_name in deleted


def test_install_rejects_core_id_shadow(isolated_scrapers, monkeypatch):
    from services import scraper_store as store

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "ANILIST",
            "file": "anilist_shadow.py",
            "install": {
                "path": "anilist_shadow.py",
                "url": f"{store.DEFAULT_RAW_BASE}/anilist_shadow.py",
                "sha256": "c" * 64,
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    monkeypatch.setattr(store, "_core_ids_from_registry", lambda: {"ANILIST", "MANGABAKA"})

    with pytest.raises(store.StoreError) as ei:
        store.install_from_catalog("ANILIST")
    assert "already core" in ei.value.message.lower()


def test_registry_reload_restores_on_empty(monkeypatch, isolated_scrapers):
    registry = isolated_scrapers["registry"]

    class _Keep:
        id = "KEEP"

    registry._scrapers["KEEP"] = _Keep()
    registry._sources["KEEP"] = "keep.py"
    backup_ids = set(registry._scrapers)
    rebound = []

    monkeypatch.setattr(registry, "load_all", lambda: None)
    monkeypatch.setattr(registry, "_drop_provider_modules", lambda: None)
    monkeypatch.setattr(
        registry,
        "_rebind_modules_from_sources",
        lambda sources: rebound.append(dict(sources)),
    )

    with pytest.raises(RuntimeError):
        registry.reload()
    assert "KEEP" in registry._scrapers
    assert set(registry._scrapers) == backup_ids
    assert rebound and rebound[0].get("KEEP") == "keep.py"


def test_install_update_unloadable_restores_previous_bytes(isolated_scrapers, monkeypatch):
    """Failed update must restore prior file contents (not delete)."""
    from services import scraper_store as store
    from services.scraper_manager import sha256_hex, write_scraper_bytes

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    file_name = "restore_me.py"
    good = b"# good\nfrom scrapers.base import BaseScraper\n\nclass G(BaseScraper):\n    id='RESTOREME'\n    display_name='R'\n    supported_types={'Manga'}\n    def fetch(self, query, library_type='Manga', is_id=False, existing_metadata=None):\n        return None\n"
    bad = b"# bad - no scraper class\nprint(1)\n"
    write_scraper_bytes(file_name, good, origin="community")

    class _S(_SeriesScraper):
        id = "RESTOREME"

    registry = isolated_scrapers["registry"]
    registry._scrapers["RESTOREME"] = _S()
    registry._sources["RESTOREME"] = file_name
    monkeypatch.setattr(store, "ScraperRegistry", registry)

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "RESTOREME",
            "file": file_name,
            "display_name": "R",
            "scopes": ["series"],
            "install": {
                "path": file_name,
                "url": f"{store.DEFAULT_RAW_BASE}/{file_name}",
                "sha256": sha256_hex(bad),
                "bytes": len(bad),
            },
        }],
    }
    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)

    fake = MagicMock()
    fake.content = bad
    fake.headers = {"Content-Type": "text/plain"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)

    # reload succeeds but get never finds the id (unloadable)
    monkeypatch.setattr(registry, "reload", lambda: None)
    monkeypatch.setattr(registry, "get", lambda sid, include_disabled=False: None)
    monkeypatch.setattr(registry, "get_proxy_cover_hosts", lambda: [])

    with pytest.raises(store.StoreError) as ei:
        store.install_from_catalog("RESTOREME", force=True)
    assert "failed to load" in ei.value.message.lower()
    assert (scrapers_dir / file_name).is_file()
    assert (scrapers_dir / file_name).read_bytes() == good


def test_disk_orphan_allows_install_without_force(isolated_scrapers, monkeypatch):
    from services import scraper_store as store
    from services.scraper_manager import sha256_hex

    scrapers_dir = isolated_scrapers["scrapers_dir"]
    registry = isolated_scrapers["registry"]
    monkeypatch.setattr(store, "ScraperRegistry", registry)

    file_name = "orphan_scraper.py"
    body = b"# orphan\nfrom scrapers.base import BaseScraper\n\nclass O(BaseScraper):\n    id='ORPHAN1'\n    display_name='O'\n    supported_types={'Manga'}\n    def fetch(self, query, library_type='Manga', is_id=False, existing_metadata=None):\n        return None\n"
    (scrapers_dir / file_name).write_bytes(body)

    catalog = {
        "schema_version": 1,
        "raw_base": store.DEFAULT_RAW_BASE,
        "scrapers": [{
            "id": "ORPHAN1",
            "file": file_name,
            "display_name": "O",
            "scopes": ["series"],
            "install": {
                "path": file_name,
                "url": f"{store.DEFAULT_RAW_BASE}/{file_name}",
                "sha256": sha256_hex(body),
                "bytes": len(body),
            },
        }],
    }
    enriched = store.enrich_catalog_for_ui(catalog, lang="en")
    row = enriched["scrapers"][0]
    assert row["state"] == "orphan"
    assert row["orphan"] is True

    monkeypatch.setattr(store, "fetch_catalog", lambda force=False: catalog)
    _patch_install_load_ok(monkeypatch, store, "ORPHAN1")
    fake = MagicMock()
    fake.content = body
    fake.headers = {"Content-Type": "text/plain"}
    fake.raise_for_status = lambda: None
    monkeypatch.setattr(store.requests, "get", lambda *a, **k: fake)

    # No force — orphan path must not 409.
    result = store.install_from_catalog("ORPHAN1", force=False)
    assert result["loaded"] is True
