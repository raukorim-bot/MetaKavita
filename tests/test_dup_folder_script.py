"""C85 — chemins dossier, préfixe POSIX, script bash (Meta n'exécute rien)."""

from __future__ import annotations

from flask import Flask

from services.library_audit.dup_script import (
    build_duplicate_folder_script,
    inventory_folder_path_prefix_from_config,
    normalize_inventory_folder_path_prefix,
    normalize_inventory_folder_trash,
    resolve_script_folder_path,
)
from services.library_audit.duplicates import cluster_duplicate_series
from services.library_audit.series_identity import merge_series_identity, series_folder_path


def test_folder_path_prefers_folder_path_then_lowest():
    assert series_folder_path({"folderPath": "/mnt/media/library/X"}) == "/mnt/media/library/X"
    assert series_folder_path({"lowestFolderPath": "/mnt/media/library/Y"}) == "/mnt/media/library/Y"
    assert series_folder_path(
        {"folderPath": "/keep", "lowestFolderPath": "/other"}
    ) == "/keep"
    assert series_folder_path({"id": 1}) == ""


def test_identity_forwards_kavita_folder_path():
    ident = merge_series_identity(
        {"id": 4, "name": "X", "folderPath": "/mnt/media/library/X"},
        {},
    )
    assert ident["folder_path"] == "/mnt/media/library/X"


def test_cluster_keeps_folder_paths_aligned_with_ids():
    groups = cluster_duplicate_series(
        [
            {
                "id": 1,
                "name": "Attack on Titan",
                "libraryId": 5,
                "aniListId": 53390,
                "folderPath": "/mnt/media/library/AoT",
            },
            {
                "id": 2,
                "name": "Attack on Titan",
                "libraryId": 5,
                "aniListId": 53390,
                "folderPath": "/mnt/media/library/AoT - Digital",
            },
        ],
        library_id=5,
    )
    assert len(groups) == 1
    assert groups[0]["series_ids"] == [1, 2] or set(groups[0]["series_ids"]) == {1, 2}
    by_id = dict(zip(groups[0]["series_ids"], groups[0]["folder_paths"]))
    assert by_id[1] == "/mnt/media/library/AoT"
    assert by_id[2] == "/mnt/media/library/AoT - Digital"


def test_path_prefix_is_posix_not_http():
    assert normalize_inventory_folder_path_prefix("/mnt/media/") == "/mnt/media"
    assert normalize_inventory_folder_path_prefix("http://files.example.xx") == ""
    assert normalize_inventory_folder_path_prefix("files.example.xx") == ""
    assert normalize_inventory_folder_path_prefix("javascript:alert(1)") == ""
    assert resolve_script_folder_path("/comics/Example Series", "/mnt/media") == (
        "/mnt/media/comics/Example Series"
    )
    assert resolve_script_folder_path("/mnt/media/comics/X", "/mnt/media") == (
        "/mnt/media/comics/X"
    )
    assert resolve_script_folder_path("/comics/X", "") == "/comics/X"
    assert inventory_folder_path_prefix_from_config(
        {"INVENTORY_FOLDER_URL_PREFIX": "http://files.example.xx"}
    ) == ""
    assert inventory_folder_path_prefix_from_config(
        {"INVENTORY_FOLDER_URL_PREFIX": "/mnt/media"}
    ) == "/mnt/media"


def test_trash_path_rejects_relative_and_dotdot():
    assert normalize_inventory_folder_trash("/mnt/media/corbeille-doublons") == (
        "/mnt/media/corbeille-doublons"
    )
    assert normalize_inventory_folder_trash("corbeille") == ""
    assert normalize_inventory_folder_trash("/mnt/media/../etc") == ""
    assert normalize_inventory_folder_trash("") == ""


def _group():
    return {
        "group_id": "dup-1",
        "score": 1.0,
        "reasons": ["same_anilist_id"],
        "series_ids": [1, 2],
        "names": ["One Piece", "One Piece - Digital"],
        "folder_paths": [
            "/comics/One Piece",
            "/comics/One Piece - Digital",
        ],
    }


def test_script_trashes_only_marked_ids_and_quotes_spaces():
    script, meta = build_duplicate_folder_script(
        [_group()],
        [2],
        mode="trash",
        trash_dir="/mnt/media/corbeille-doublons",
    )
    assert meta["dropped"] == 1
    assert meta["empty"] is False
    assert meta["groups_all_dropped"] == []
    assert "# KEEP  /comics/One Piece" in script
    assert "mv -n -- '/comics/One Piece - Digital' \"$TRASH/\"" in script
    assert "rm -rf" not in script
    assert "TRASH=/mnt/media/corbeille-doublons" in script


def test_script_applies_path_prefix():
    script, meta = build_duplicate_folder_script(
        [_group()],
        [2],
        mode="trash",
        trash_dir="/mnt/media/corbeille-doublons",
        path_prefix="/mnt/media",
    )
    assert meta["dropped"] == 1
    assert "mv -n -- '/mnt/media/comics/One Piece - Digital' \"$TRASH/\"" in script
    assert "# KEEP  /mnt/media/comics/One Piece" in script


def test_script_delete_mode_uses_rm():
    script, meta = build_duplicate_folder_script([_group()], [2], mode="delete")
    assert meta["dropped"] == 1
    assert "rm -rf -- '/comics/One Piece - Digital'" in script
    assert "mv -n" not in script


def test_script_skips_missing_path_and_flags_empty_group():
    group = _group()
    group["folder_paths"] = ["/comics/One Piece", ""]
    script, meta = build_duplicate_folder_script(
        [group], [1, 2], mode="trash", trash_dir="/mnt/media/corbeille"
    )
    assert meta["groups_all_dropped"] == ["dup-1"]
    assert meta["skipped_no_path"] == 1
    assert meta["dropped"] == 1
    assert "SKIP  no folder path" in script


def test_script_refuses_empty_selection():
    try:
        build_duplicate_folder_script([_group()], [], mode="trash")
    except ValueError as exc:
        assert "no series" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_script_route_returns_text_and_delete_route_is_gone(isolated_db, monkeypatch):
    from db_manager import save_duplicate_groups_cache
    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {
            "UI_LANG": "en",
            "LIBRARY_INVENTORY_ENABLED": True,
            "INVENTORY_FOLDER_TRASH": "/mnt/media/corbeille-doublons",
            "INVENTORY_FOLDER_PATH_PREFIX": "/mnt/media",
        },
    )
    save_duplicate_groups_cache(2, [_group()])
    client = app.test_client()

    gone = client.post("/api/series/2/kavita-delete", json={"confirm": True})
    assert gone.status_code == 404

    empty = client.post(
        "/api/libraries/2/duplicates/script",
        json={"series_ids": [], "mode": "trash"},
    )
    assert empty.status_code == 400

    res = client.post(
        "/api/libraries/2/duplicates/script",
        json={"series_ids": [2], "mode": "trash"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["dropped"] == 1
    assert "mv -n --" in data["script"]
    assert "/mnt/media/comics/One Piece - Digital" in data["script"]


def test_js_no_longer_calls_kavita_delete():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    src = (root / "static" / "js" / "library_audit.js").read_text(encoding="utf-8")
    modal = (root / "templates" / "partials" / "_library_audit_modal.html").read_text(
        encoding="utf-8"
    )
    sidebar = (root / "templates" / "partials" / "_sidebar.html").read_text(encoding="utf-8")
    assert "kavita-delete" not in src
    assert "duplicates/script" in src
    assert "audit-dup-drop-cb" in src
    assert "_enforceDupKeepOne" in src
    assert "_dupDropMarked" in src
    assert "keepBody" in src


    assert "dupFolderPathPrefix" in src
    assert 'id="dupFolderPathPrefix"' in modal
    assert 'id="dupFolderTrash"' in modal
    assert "_resolvedFolderPath" in src
    assert "_folderHttpUrl" not in src
    assert "sidebar_inventory_folder_url_prefix" not in sidebar
    assert "sidebar_inventory_folder_trash" not in sidebar
    assert "192.168.1.116" not in modal
    assert "DATA4TO" not in modal
    assert "192.168.1.116" not in src
    assert "DATA4TO" not in src
    assert "http://files.example.xx" not in modal
    assert 'placeholder="/mnt/media"' in modal
    assert "/mnt/media/corbeille-doublons" in modal


def test_powershell_script_generation():
    from services.library_audit.dup_script import build_duplicate_folder_script

    groups = [
        {
            "group_id": "dup-1",
            "series_ids": [10, 20],
            "names": ["Naruto", "Naruto Digital"],
            "folder_paths": ["/data/Naruto", "/data/Naruto Digital's Copy"],
            "score": 1.0,
            "reasons": ["same_external_id"],
        }
    ]

    # Test mode trash ps1
    script_trash, meta_trash = build_duplicate_folder_script(
        groups,
        [20],
        mode="trash",
        script_format="ps1",
        trash_dir="/data/trash",
    )
    assert meta_trash["format"] == "ps1"
    assert meta_trash["dropped"] == 1
    assert "$TRASH = '/data/trash'" in script_trash
    assert "Move-Item -LiteralPath '/data/Naruto Digital''s Copy' -Destination $TRASH -Force" in script_trash

    # Test mode delete ps1
    script_del, meta_del = build_duplicate_folder_script(
        groups,
        [20],
        mode="delete",
        script_format="ps1",
    )
    assert meta_del["format"] == "ps1"
    assert "Remove-Item -LiteralPath '/data/Naruto Digital''s Copy' -Recurse -Force" in script_del


def test_windows_paths_normalization():
    """Vérifie que normalize_inventory_folder_trash accepte les lettres de lecteur Windows."""
    assert normalize_inventory_folder_trash("C:/Media/Trash") == "C:/Media/Trash"
    assert normalize_inventory_folder_trash("D:\\Manga\\Trash") == "D:/Manga/Trash"
    assert normalize_inventory_folder_trash("E:\\") == "E:"
    # Rejette toujours les chemins relatifs et les traversées
    assert normalize_inventory_folder_trash("relative\\path") == ""
    assert normalize_inventory_folder_trash("C:/Media/../Secret") == ""
    assert normalize_inventory_folder_trash("http://example.com/trash") == ""


def test_resolve_script_folder_path_windows():
    """Un chemin Windows absolu n'est pas préfixé de force."""
    assert resolve_script_folder_path("C:/Manga/One Piece", "") == "C:/Manga/One Piece"
    assert resolve_script_folder_path("C:\\Manga\\One Piece", "D:/Prefix") == "C:/Manga/One Piece"


def test_build_duplicate_folder_script_windows_ps1():
    """Génération de script PowerShell valide avec chemins Windows."""
    groups = [
        {
            "group_id": "dup-win",
            "series_ids": [10, 20],
            "names": ["Batman", "Batman (2016)"],
            "folder_paths": ["C:\\Comics\\Batman", "C:\\Comics\\Batman 2016"],
            "library_ids": [2, 2],
            "score": 1.0,
            "reasons": ["same_comicvine_id"],
        }
    ]
    script, meta = build_duplicate_folder_script(
        groups,
        [20],
        mode="trash",
        script_format="ps1",
        trash_dir="C:\\Corbeille",
    )
    assert meta["empty"] is False
    assert meta["dropped"] == 1
    assert "$TRASH = 'C:/Corbeille'" in script
    assert "Move-Item -LiteralPath 'C:/Comics/Batman 2016' -Destination $TRASH -Force" in script


def test_cluster_duplicate_series_propagates_library_ids():
    """Vérifie que cluster_duplicate_series inclut library_ids dans chaque groupe."""
    groups = cluster_duplicate_series(
        [
            {
                "id": 101,
                "name": "One Piece",
                "libraryId": 1,
                "folderPath": "/comics/op1",
                "aniListId": 30013,
            },
            {
                "id": 102,
                "name": "One Piece",
                "libraryId": 2,
                "folderPath": "/comics/op2",
                "aniListId": 30013,
            },
        ],
        library_id=None,
    )
    assert len(groups) == 1
    assert "library_ids" in groups[0]
    by_sid = dict(zip(groups[0]["series_ids"], groups[0]["library_ids"]))
    assert by_sid[101] == 1
    assert by_sid[102] == 2

