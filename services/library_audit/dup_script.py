"""Script bash à relire, pour jeter les dossiers des doublons.

MetaKavita n'exécute rien : le navigateur copie ou télécharge le texte, et
c'est l'utilisateur qui le colle dans un terminal Linux. Le delete Kavita
sans toucher aux fichiers faisait revenir la fiche au scan suivant.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

SCRIPT_MODES = ("trash", "delete")
SCRIPT_FORMATS = ("sh", "ps1")

_POSIX_UNSAFE = re.compile(r"[^\w@%+=:,./-]", re.ASCII)


def _posix_sh_quote(value: str) -> str:
    """Quote POSIX, indépendant de `os.name` (les tests tournent aussi sous Windows)."""
    s = str(value)
    if not s:
        return "''"
    if _POSIX_UNSAFE.search(s) is None:
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _powershell_quote(value: str) -> str:
    """Quote PowerShell littéral (guillemets simples avec doublement)."""
    s = str(value or "").strip()
    if not s:
        return "''"
    return "'" + s.replace("'", "''") + "'"


_WIN_DRIVE_RE = re.compile(r"^[a-zA-Z]:/")


def _is_absolute_path(s: str) -> bool:
    """Vérifie qu'un chemin (déjà normalisé ``\\`` → ``/``) est absolu.

    Accepte :
    - Chemins POSIX : ``/mnt/media/...``
    - Chemins UNC : ``//serveur/partage/...`` (commence aussi par ``/``)
    - Chemins Windows avec lettre de lecteur : ``C:/Comics/...``, ``D:/Manga/...``
    """
    return s.startswith("/") or bool(_WIN_DRIVE_RE.match(s))


def normalize_inventory_folder_trash(raw: Any) -> str:
    """Dossier corbeille côté NAS ou hôte (chemin absolu POSIX ou Windows, hors `..`)."""
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        return ""
    if any(c in s for c in ("\n", "\r", "\0")):
        return ""
    if not _is_absolute_path(s):
        return ""
    if "://" in s:
        # Rejette les URI (http://..., ftp://...) mais autorise les lettres de
        # lecteur Windows : le ``://`` d'un URI se trouve toujours AVANT le
        # troisième caractère pour un chemin ``C:/...`` (index 1), alors qu'un
        # URI a ``://`` à index >= 3 (``ftp://``).  On rejette uniquement quand
        # le ``://`` est situé après le deuxième caractère.
        idx = s.index("://")
        if idx > 1:
            return ""
    if ".." in s.split("/"):
        return ""
    trimmed = s.rstrip("/")
    # Un chemin Windows comme « C: » sans slash final est accepté tel quel.
    return trimmed if trimmed else ""


def normalize_inventory_folder_path_prefix(raw: Any) -> str:
    """Préfixe POSIX collé devant le `folderPath` Kavita dans le script.

    Kavita peut rendre `/comics/X` alors que le disque est `/mnt/media/comics/X`.
    Un `http://` est refusé : ce n'est pas un lien navigateur.
    """
    return normalize_inventory_folder_trash(raw)


def posix_folder_path(raw: Any) -> str:
    """Chemin de série utilisable dans un script shell (POSIX ou Windows)."""
    return normalize_inventory_folder_trash(raw)


def inventory_folder_path_prefix_from_config(cfg: Any) -> str:
    """`PATH_PREFIX` d'abord ; l'ancienne clé HTTP n'est reprise que si c'est un chemin."""
    data = cfg if isinstance(cfg, dict) else {}
    path = normalize_inventory_folder_path_prefix(data.get("INVENTORY_FOLDER_PATH_PREFIX"))
    if path:
        return path
    return normalize_inventory_folder_path_prefix(data.get("INVENTORY_FOLDER_URL_PREFIX"))


def resolve_script_folder_path(folder_path: Any, prefix: Any = "") -> str:
    """`prefix` + `folderPath` → chemin que le script `mv` / `rm` utilisera."""
    path = posix_folder_path(folder_path)
    base = normalize_inventory_folder_path_prefix(prefix)
    if not path:
        return ""
    if not base:
        return path
    if path == base or path.startswith(base + "/"):
        return path
    # Un chemin Windows absolu (C:/…) n'a pas besoin de préfixe, il est déjà
    # complet. On ne préfixe que les chemins POSIX relatifs à la racine.
    if _is_absolute_path(path) and not path.startswith("/"):
        return path
    return base + path if path.startswith("/") else base + "/" + path


def build_duplicate_folder_script(
    groups: Sequence[dict],
    drop_ids: Iterable[Any],
    *,
    mode: str = "trash",
    script_format: str = "sh",
    trash_dir: str = "",
    path_prefix: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Rend le script et un résumé (combien de `mv`/`rm`, groupes vidés)."""
    mode = (mode or "trash").strip().lower()
    if mode not in SCRIPT_MODES:
        raise ValueError("invalid script mode")

    script_format = (script_format or "sh").strip().lower()
    if script_format not in SCRIPT_FORMATS:
        raise ValueError("invalid script format")

    wanted: Set[int] = set()
    for raw in drop_ids or []:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    if not wanted:
        raise ValueError("no series to drop")

    trash = posix_folder_path(trash_dir)
    prefix = normalize_inventory_folder_path_prefix(path_prefix)

    is_ps1 = script_format == "ps1"

    if is_ps1:
        lines = [
            "# Generated by MetaKavita — review before running.",
            "# MetaKavita does not execute this script.",
            f"# MODE={mode} FORMAT=ps1",
            '$ErrorActionPreference = "Stop"',
            "",
        ]
        if mode == "trash":
            if trash:
                lines.append(f"$TRASH = {_powershell_quote(trash)}")
            else:
                lines.append('$TRASH = $env:TRASH')
            lines += [
                'if (-not $TRASH) {',
                '    Write-Error "Set `$TRASH to a folder outside your Kavita libraries."',
                '    exit 1',
                '}',
                'if (-not (Test-Path -LiteralPath $TRASH)) {',
                '    New-Item -ItemType Directory -LiteralPath $TRASH -Force | Out-Null',
                '}',
                "",
            ]
    else:
        lines = [
            "#!/bin/sh",
            "# Generated by MetaKavita — review before running.",
            "# MetaKavita does not execute this script.",
            f"# MODE={mode}",
            "set -eu",
            "",
        ]
        if mode == "trash":
            if trash:
                lines.append(f"TRASH={_posix_sh_quote(trash)}")
            else:
                lines.append('TRASH="${TRASH:-}"')
            lines += [
                'if [ -z "$TRASH" ]; then',
                '  echo "Set TRASH to a folder outside your Kavita libraries." >&2',
                "  exit 1",
                "fi",
                'mkdir -p "$TRASH"',
                "",
            ]

    by_id: Dict[int, Tuple[str, str]] = {}
    dropped = 0
    skipped_no_path = 0
    groups_all_dropped: List[str] = []
    seen: Set[int] = set()

    for group in groups or []:
        if not isinstance(group, dict):
            continue
        ids: List[int] = []
        for raw in group.get("series_ids") or []:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        names = list(group.get("names") or [])
        paths = list(group.get("folder_paths") or [])
        for index, sid in enumerate(ids):
            name = names[index] if index < len(names) else ""
            path = resolve_script_folder_path(
                paths[index] if index < len(paths) else "",
                prefix,
            )
            by_id[sid] = (path, name)

    unknown = [sid for sid in sorted(wanted) if sid not in by_id]

    for group in groups or []:
        if not isinstance(group, dict):
            continue
        ids: List[int] = []
        for raw in group.get("series_ids") or []:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        drop_here = [sid for sid in ids if sid in wanted]
        if not drop_here:
            continue
        keep_here = [sid for sid in ids if sid not in wanted]
        gid = group.get("group_id") or ""
        score = group.get("score")
        reasons = " ".join(group.get("reasons") or [])
        if ids and not keep_here:
            groups_all_dropped.append(str(gid))
        lines.append(f"# --- {gid}  score {score}  {reasons} ---")
        names = list(group.get("names") or [])
        paths = list(group.get("folder_paths") or [])
        for index, sid in enumerate(ids):
            if sid in wanted:
                continue
            name = names[index] if index < len(names) else ""
            path = resolve_script_folder_path(
                paths[index] if index < len(paths) else "",
                prefix,
            )
            label = path or f"series {sid}"
            lines.append(f"# KEEP  {label}  ({name} #{sid})")
        for sid in drop_here:
            if sid in seen:
                continue
            seen.add(sid)
            path, name = by_id.get(sid, ("", ""))
            if not path:
                lines.append(
                    f"# SKIP  no folder path  ({name} #{sid}) — re-run Analyze"
                )
                skipped_no_path += 1
                continue
            if is_ps1:
                quoted = _powershell_quote(path)
                if mode == "trash":
                    lines.append(f"Move-Item -LiteralPath {quoted} -Destination $TRASH -Force")
                else:
                    lines.append(f"Remove-Item -LiteralPath {quoted} -Recurse -Force")
            else:
                quoted = _posix_sh_quote(path)
                if mode == "trash":
                    lines.append(f"mv -n -- {quoted} \"$TRASH/\"")
                else:
                    lines.append(f"rm -rf -- {quoted}")
            dropped += 1
        lines.append("")

    if unknown:
        lines.append("# Not in the current duplicate groups:")
        for sid in unknown:
            lines.append(f"# SKIP  unknown series #{sid}")
        lines.append("")

    script = "\n".join(lines).rstrip() + "\n"
    return script, {
        "mode": mode,
        "format": script_format,
        "dropped": dropped,
        "skipped_no_path": skipped_no_path,
        "skipped_unknown": len(unknown),
        "groups_all_dropped": groups_all_dropped,
        "empty": dropped == 0,
    }
