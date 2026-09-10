"""Script bash à relire, pour jeter les dossiers des doublons.

MetaKavita n'exécute rien : le navigateur copie ou télécharge le texte, et
c'est l'utilisateur qui le colle dans un terminal Linux. Le delete Kavita
sans toucher aux fichiers faisait revenir la fiche au scan suivant.

Deux règles tiennent ce module : **aucun secret n'entre dans le texte rendu**
(le script lit `KAVITA_API_KEY` dans son environnement, voir BF200) et **aucune
donnée venue de Kavita n'y entre sans passer par un échappement** — les chemins
par `_posix_sh_quote` / `_powershell_quote`, les libellés par `_comment`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

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


_COMMENT_UNSAFE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _comment(text: Any) -> str:
    """Rend un libellé inoffensif dans un commentaire de script.

    Les chemins sont quotés, mais les commentaires ne l'étaient pas : un nom de
    série contenant un saut de ligne (légal sur ext4, et saisissable via l'API
    Kavita) refermait le commentaire et injectait une ligne exécutable dans un
    texte destiné à être collé dans un terminal. Tout ce qui pourrait rompre la
    ligne est donc réduit à une espace — seule porte d'écriture des libellés.
    """
    return _COMMENT_UNSAFE.sub(" ", str(text if text is not None else "")).strip()


class ScriptRequestError(ValueError):
    """Demande de script irrecevable, avec le motif exact.

    Un `ValueError` nu faisait répondre « Cochez au moins une série à jeter » à
    un format invalide comme à une sélection vide : l'utilisateur lisait un
    conseil sans rapport avec son problème.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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


def _scan_library_id(library_id: Any) -> Optional[int]:
    """Identifiant de bibliothèque du bloc de scan — `None` pour « toutes ».

    Un identifiant ni numérique ni « all » n'a pas d'endpoint Kavita : le
    signaler ici évite qu'un `int()` lève au milieu du rendu et se fasse passer
    pour une sélection vide.
    """
    raw = str(library_id if library_id is not None else "").strip().lower()
    if raw in ("", "all", "0", "none", "*"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ScriptRequestError("invalid_library") from None


def _trash_helper_lines(is_ps1: bool) -> List[str]:
    """Fonction de mise à la corbeille, définie une fois en tête de script.

    Les deux formats se comportaient différemment sur la collision la plus
    courante — deux doublons dont le dossier porte le même nom : `mv -n` renonçait
    en silence et rendait 0 (l'utilisateur croyait le dossier déplacé) là où
    `Move-Item -Force` écrasait. Les deux annoncent désormais le saut et ne
    détruisent jamais ce qui se trouve déjà dans la corbeille.
    """
    if is_ps1:
        return [
            "function Move-ToTrash([string]$Path) {",
            "    $dest = Join-Path $TRASH (Split-Path -Leaf $Path)",
            "    if (Test-Path -LiteralPath $dest) {",
            '        Write-Warning "SKIP  $Path - already present in the trash folder"',
            "        return",
            "    }",
            "    Move-Item -LiteralPath $Path -Destination $TRASH",
            "}",
            "",
        ]
    return [
        "mk_trash() {",
        '  _mk_dest="$TRASH/$(basename -- "$1")"',
        '  if [ -e "$_mk_dest" ]; then',
        '    echo "SKIP  $1 - already present in the trash folder" >&2',
        "    return 0",
        "  fi",
        '  mv -- "$1" "$TRASH/"',
        "}",
        "",
    ]


def build_duplicate_folder_script(
    groups: Sequence[dict],
    drop_ids: Iterable[Any],
    *,
    mode: str = "trash",
    script_format: str = "sh",
    trash_dir: str = "",
    path_prefix: str = "",
    trigger_scan: bool = False,
    kavita_url: str = "",
    library_id: Any = None,
) -> Tuple[str, Dict[str, Any]]:
    """Rend le script et un résumé (combien de `mv`/`rm`, groupes vidés).

    Aucune clé API n'est acceptée ni rendue : le bloc de scan lit
    `KAVITA_API_KEY` dans l'environnement du terminal (BF200).
    """
    mode = (mode or "trash").strip().lower()
    if mode not in SCRIPT_MODES:
        raise ScriptRequestError("invalid_mode")

    script_format = (script_format or "sh").strip().lower()
    if script_format not in SCRIPT_FORMATS:
        raise ScriptRequestError("invalid_format")

    scan_library_id = _scan_library_id(library_id) if trigger_scan else None

    wanted: Set[int] = set()
    for raw in drop_ids or []:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    if not wanted:
        raise ScriptRequestError("no_selection")

    trash = posix_folder_path(trash_dir)
    prefix = normalize_inventory_folder_path_prefix(path_prefix)

    is_ps1 = script_format == "ps1"

    if is_ps1:
        lines = [
            "# Generated by MetaKavita — review before running.",
            "# MetaKavita does not execute this script.",
            "# Run in PowerShell: .\\metakavita-duplicates.ps1 or paste into terminal.",
            f"# MODE={mode} FORMAT=ps1",
            '$ErrorActionPreference = "Continue"',
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
            lines += _trash_helper_lines(True)
    else:
        lines = [
            "#!/bin/sh",
            "# Generated by MetaKavita — review before running.",
            "# MetaKavita does not execute this script.",
            "# Run in Linux / macOS / NAS terminal: sh metakavita-duplicates.sh or paste directly.",
            f"# MODE={mode}",
            "set -u",
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
            lines += _trash_helper_lines(False)

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
        lines.append(_comment(f"# --- {gid}  score {score}  {reasons} ---"))
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
            lines.append(_comment(f"# KEEP  {label}  ({name} #{sid})"))
        for sid in drop_here:
            if sid in seen:
                continue
            seen.add(sid)
            path, name = by_id.get(sid, ("", ""))
            if not path:
                lines.append(
                    _comment(f"# SKIP  no folder path  ({name} #{sid}) — re-run Analyze")
                )
                skipped_no_path += 1
                continue
            if is_ps1:
                quoted = _powershell_quote(path)
                if mode == "trash":
                    lines.append(f"Move-ToTrash {quoted}")
                else:
                    lines.append(f"Remove-Item -LiteralPath {quoted} -Recurse -Force")
            else:
                quoted = _posix_sh_quote(path)
                if mode == "trash":
                    lines.append(f"mk_trash {quoted}")
                else:
                    lines.append(f"rm -rf -- {quoted}")
            dropped += 1
        lines.append("")

    if unknown:
        lines.append("# Not in the current duplicate groups:")
        for sid in unknown:
            lines.append(f"# SKIP  unknown series #{sid}")
        lines.append("")

    if trigger_scan:
        scan_endpoint = (
            "scan-all" if scan_library_id is None else f"scan?libraryId={scan_library_id}"
        )
        lines.append("# --- Trigger Kavita Library Scan ---")
        # La clé API ne descend jamais ici : elle transiterait par le navigateur,
        # le presse-papier, le fichier téléchargé puis l'historique du shell. Le
        # script la lit dans l'environnement du terminal, où elle reste (BF200).
        lines.append("# Export KAVITA_API_KEY in your terminal before running this block.")
        if is_ps1:
            k_url = str(kavita_url or "").rstrip("/")
            url_expr = _powershell_quote(k_url) if k_url else "$env:KAVITA_URL"
            lines += [
                f"$kavitaUrl = {url_expr}",
                "$kavitaApiKey = $env:KAVITA_API_KEY",
                'if ($kavitaUrl -and $kavitaApiKey) {',
                '    try {',
                '        $authUri = "$($kavitaUrl.TrimEnd(\'/\'))/api/Plugin/authenticate?apiKey=$kavitaApiKey&pluginName=KavitaFetcher"',
                '        $auth = Invoke-RestMethod -Method Post -Uri $authUri',
                f'        $scanUri = "$($kavitaUrl.TrimEnd(\'/\'))/api/Library/{scan_endpoint}"',
                '        Invoke-RestMethod -Method Post -Uri $scanUri -Headers @{ Authorization = "Bearer $($auth.token)" } | Out-Null',
                '        Write-Host "Kavita scan triggered successfully."',
                '    } catch {',
                '        Write-Warning "Could not trigger Kavita scan: $_"',
                '    }',
                '} else {',
                '    Write-Warning "KAVITA_URL or KAVITA_API_KEY not configured — skipping library scan trigger."',
                '}',
                "",
            ]
        else:
            k_url = str(kavita_url or "").rstrip("/")
            url_line = f'KAVITA_URL={_posix_sh_quote(k_url)}' if k_url else 'KAVITA_URL="${KAVITA_URL:-}"'
            lines += [
                url_line,
                'KAVITA_API_KEY="${KAVITA_API_KEY:-}"',
                'if [ -n "$KAVITA_URL" ] && [ -n "$KAVITA_API_KEY" ]; then',
                '  _K_BASE="${KAVITA_URL%/}"',
                '  _K_AUTH=$(curl -s -X POST "$_K_BASE/api/Plugin/authenticate?apiKey=$KAVITA_API_KEY&pluginName=KavitaFetcher")',
                '  _K_TOKEN=$(echo "$_K_AUTH" | grep -o \'"token":"[^"]*\' | cut -d\'"\' -f4)',
                '  if [ -n "$_K_TOKEN" ]; then',
                f'    curl -s -X POST "$_K_BASE/api/Library/{scan_endpoint}" -H "Authorization: Bearer $_K_TOKEN"',
                '    echo "Kavita scan triggered successfully."',
                '  else',
                '    echo "Failed to authenticate with Kavita to trigger scan." >&2',
                '  fi',
                'else',
                '  echo "KAVITA_URL or KAVITA_API_KEY not set — skipping library scan trigger." >&2',
                'fi',
                "",
            ]

    script = "\n".join(lines).rstrip() + "\n"
    return script, {
        "mode": mode,
        "format": script_format,
        "dropped": dropped,
        "skipped_no_path": skipped_no_path,
        "skipped_unknown": len(unknown),
        "groups_all_dropped": groups_all_dropped,
        "empty": dropped == 0,
        "trigger_scan": bool(trigger_scan),
    }
