"""
Gestion disque des scrapers sideloadés (`data/scrapers/`).

- Discovery core via ``is_core = True`` dans le package image (`scrapers/`)
- Sync au boot : catalogue GitHub community (``is_core``) → data/, fallback image
  selon ``AUTO_UPDATE_CORE_SCRAPERS``
- Origines (core / community / custom) + chemins sûrs (anti path-traversal)
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import threading
from typing import Dict, List, Optional, Set, Tuple

from config_manager import DATA_DIR

# Serialise read-modify-write on .origins.json (install/delete/seed races).
_ORIGINS_LOCK = threading.RLock()
_PENDING_LOCK = threading.Lock()
_pending_core_updates: List[Dict[str, str]] = []
_core_filenames_cache: Optional[Tuple[str, Tuple[str, ...]]] = None

# Helpers / non-scraper modules in the package — never treated as installable core.
CORE_SKIP_FILES = frozenset({
    "__init__.py",
    "base.py",
    "utils.py",
    "wikidata_map.py",
})

# Former image-core scrapers now published via Magasin only.
# Their seeded copies used package-relative imports and break as custom_scrapers.*.
FORMER_CORE_FILES = frozenset({
    "wikidata.py",
})

ORIGINS_FILENAME = ".origins.json"
VALID_ORIGINS = frozenset({"core", "community", "custom"})


def package_scrapers_dir() -> str:
    """Répertoire des scrapers livrés dans l'image (`scrapers/`)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scrapers"))


def data_scrapers_dir() -> str:
    path = os.path.join(DATA_DIR, "scrapers")
    os.makedirs(path, exist_ok=True)
    return path


def _file_declares_is_core(path: str) -> bool:
    """True if a class body in ``path`` assigns ``is_core = True`` (AST, no exec)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
    except (OSError, SyntaxError, ValueError):
        return False

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            target_name = None
            value_node = None
            if isinstance(item, ast.Assign) and len(item.targets) == 1:
                t0 = item.targets[0]
                if isinstance(t0, ast.Name):
                    target_name = t0.id
                    value_node = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                target_name = item.target.id
                value_node = item.value
            if target_name != "is_core" or value_node is None:
                continue
            if isinstance(value_node, ast.Constant) and value_node.value is True:
                return True
    return False


DEFAULT_SCRAPER_VERSION = "1.0.0"


def parse_version(raw) -> Tuple[int, ...]:
    """`"1.2.3"` → `(1, 2, 3)`. Tolérant : tout segment illisible vaut 0.

    Volontairement plus simple que PEP 440 : les versions de scrapers sont des
    `major.minor.patch` produits par le générateur du catalogue, et une version
    exotique doit dégrader vers « pas plus récent » plutôt que lever.
    """
    text = str(raw or "").strip()
    if not text:
        return (0,)
    parts: List[int] = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def version_is_newer(candidate, reference) -> bool:
    """True si `candidate` est **strictement** plus récent que `reference`.

    À version égale on ne conclut rien : c'est ce qui laisse le contenu trancher
    comme avant (comparaison de sha256), et ce qui évite de réécrire en boucle
    deux copies identiques dont la version n'a pas bougé.
    """
    a, b = parse_version(candidate), parse_version(reference)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def file_scraper_version(path: str) -> str:
    """Version déclarée par la classe du scraper dans ``path`` (AST, sans exec).

    Absente → ``DEFAULT_SCRAPER_VERSION``, comme `BaseScraper.version` : un
    scraper core qui n'a jamais bougé se compare donc à égalité avec lui-même,
    quelle que soit la source dont vient la copie.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
    except (OSError, SyntaxError, ValueError):
        return DEFAULT_SCRAPER_VERSION

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            target_name = None
            value_node = None
            if isinstance(item, ast.Assign) and len(item.targets) == 1:
                t0 = item.targets[0]
                if isinstance(t0, ast.Name):
                    target_name = t0.id
                    value_node = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                target_name = item.target.id
                value_node = item.value
            if target_name != "version" or value_node is None:
                continue
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                declared = value_node.value.strip()
                if declared:
                    return declared
    return DEFAULT_SCRAPER_VERSION


def package_scraper_version(filename: str) -> str:
    """Version du scraper tel que livré dans l'image, ou le défaut s'il n'y est pas."""
    path = os.path.join(package_scrapers_dir(), os.path.basename(filename or ""))
    if not os.path.isfile(path):
        return DEFAULT_SCRAPER_VERSION
    return file_scraper_version(path)


def installed_scraper_version(filename: str) -> str:
    """Version de la copie présente sous `data/scrapers/`, ou le défaut si absente."""
    path = os.path.join(data_scrapers_dir(), os.path.basename(filename or ""))
    if not os.path.isfile(path):
        return DEFAULT_SCRAPER_VERSION
    return file_scraper_version(path)


def list_core_filenames() -> List[str]:
    """Basenames des scrapers officiels : ``is_core = True`` dans le package image."""
    global _core_filenames_cache
    src = package_scrapers_dir()
    try:
        mtime = os.path.getmtime(src) if os.path.isdir(src) else -1.0
    except OSError:
        mtime = -1.0
    cache_key = f"{src}:{mtime}"
    if _core_filenames_cache and _core_filenames_cache[0] == cache_key:
        return list(_core_filenames_cache[1])

    names: List[str] = []
    if os.path.isdir(src):
        for filename in sorted(os.listdir(src)):
            if not filename.endswith(".py"):
                continue
            if filename in CORE_SKIP_FILES or filename.startswith("__"):
                continue
            path = os.path.join(src, filename)
            if _file_declares_is_core(path):
                names.append(filename)
    _core_filenames_cache = (cache_key, tuple(names))
    return list(names)


def is_core_filename(filename: str) -> bool:
    base = os.path.basename(filename or "")
    return base in set(list_core_filenames())


def origins_path() -> str:
    return os.path.join(data_scrapers_dir(), ORIGINS_FILENAME)


def load_origins() -> Dict[str, str]:
    path = origins_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        out = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v in VALID_ORIGINS:
                out[os.path.basename(k)] = v
        return out
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_origins(origins: Dict[str, str]) -> None:
    path = origins_path()
    cleaned = {
        os.path.basename(k): v
        for k, v in origins.items()
        if isinstance(k, str) and v in VALID_ORIGINS
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def set_origin(filename: str, origin: str) -> None:
    if origin not in VALID_ORIGINS:
        raise ValueError(f"invalid origin: {origin}")
    base = os.path.basename(filename)
    with _ORIGINS_LOCK:
        origins = load_origins()
        origins[base] = origin
        save_origins(origins)


def resolve_origin(filename: str) -> str:
    base = os.path.basename(filename or "")
    if is_core_filename(base):
        return "core"
    marked = load_origins().get(base)
    if marked in VALID_ORIGINS:
        return marked
    return "custom"


def is_core_data_file(filename: str) -> bool:
    """True si le fichier data doit charger comme ``scrapers.<stem>`` (image ou origin=core)."""
    base = os.path.basename(filename or "")
    if not base:
        return False
    if is_core_filename(base):
        return True
    return load_origins().get(base) == "core"


def _contents_equivalent(a: bytes, b: bytes) -> bool:
    """True if raw bytes match or only differ by EOL (LF ↔ CRLF)."""
    if a == b:
        return True
    return normalize_newlines_lf(a) == normalize_newlines_lf(b)


def _write_bytes_atomic(path: str, content: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(content)
    os.replace(tmp, path)


def get_pending_core_updates() -> List[Dict[str, str]]:
    with _PENDING_LOCK:
        return [dict(x) for x in _pending_core_updates]


def set_pending_core_updates(items: List[Dict[str, str]]) -> None:
    with _PENDING_LOCK:
        _pending_core_updates.clear()
        _pending_core_updates.extend(dict(x) for x in items)


def clear_pending_core_updates() -> None:
    set_pending_core_updates([])


def diff_core_scrapers() -> List[Dict[str, str]]:
    """Compare package core files to data/scrapers/. Each item: file + status."""
    src_dir = package_scrapers_dir()
    dest_dir = data_scrapers_dir()
    out: List[Dict[str, str]] = []
    for filename in list_core_filenames():
        src = os.path.join(src_dir, filename)
        dest = os.path.join(dest_dir, filename)
        if not os.path.isfile(src):
            continue
        if not os.path.isfile(dest):
            out.append({"file": filename, "status": "missing"})
            continue
        src_bytes = read_file_bytes(src)
        dest_bytes = read_file_bytes(dest)
        if src_bytes is None or dest_bytes is None:
            out.append({"file": filename, "status": "stale"})
            continue
        if not _contents_equivalent(src_bytes, dest_bytes):
            out.append({"file": filename, "status": "stale"})
    return out


def write_core_scraper_bytes(filename: str, content: bytes) -> str:
    """Écrit un scraper core sous data/scrapers/ (bypass Magasin). Retourne le chemin."""
    path = safe_scraper_path(filename)
    if path is None:
        raise ValueError("invalid scraper filename")
    base = os.path.basename(path)
    if base in CORE_SKIP_FILES or not base.endswith(".py") or base.startswith("."):
        raise ValueError("invalid scraper filename")
    _write_bytes_atomic(path, content)
    set_origin(base, "core")
    return path


def _resolve_auto_update(*, force: bool, auto_update: Optional[bool]) -> bool:
    if force:
        return True
    if auto_update is not None:
        return bool(auto_update)
    try:
        from config_manager import load_config
        return bool(load_config().get("AUTO_UPDATE_CORE_SCRAPERS", True))
    except Exception:
        return True


def _sync_core_from_image(
    *,
    auto_update: bool,
    missing_only: bool = False,
) -> Dict[str, List[str]]:
    """
    Aligne data/scrapers/ sur le package image pour les fichiers ``is_core``.

    ``missing_only=True`` : ne remplit que les absents — **plus** les fichiers
    dont l'image porte une version strictement plus récente. C'est la seule
    manière pour une mise à jour d'image de livrer ses scrapers core corrigés :
    le catalogue GitHub passe avant elle et, une fois un fichier écrit, la
    comparaison de sha256 le déclarait « à jour » à jamais, quelle que soit son
    ancienneté (bug BF143 — l'enrichissement par tome n'avait plus aucun
    fournisseur, l'image seule portant `fetch_volume_index`).

    Dans les deux modes, une copie locale **plus récente** que l'image n'est
    jamais écrasée : elle vient d'un catalogue en avance sur l'image, et la
    régresser réintroduirait des bugs déjà corrigés. Le refus est journalisé.
    """
    src_dir = package_scrapers_dir()
    dest_dir = data_scrapers_dir()
    seeded: List[str] = []
    updated: List[str] = []
    pending: List[Dict[str, str]] = []

    with _ORIGINS_LOCK:
        origins = load_origins()
        dirty = False

        for filename in list_core_filenames():
            src = os.path.join(src_dir, filename)
            dest = os.path.join(dest_dir, filename)
            if not os.path.isfile(src):
                continue
            src_bytes = read_file_bytes(src)
            if src_bytes is None:
                continue

            if not os.path.isfile(dest):
                try:
                    _write_bytes_atomic(dest, src_bytes)
                    seeded.append(filename)
                    logging.info("[Scrapers] Core seedé (image) : %s", filename)
                except OSError as e:
                    logging.error("[Scrapers] Échec seed core %s : %s", filename, e)
                    continue
            else:
                src_version = file_scraper_version(src)
                dest_version = file_scraper_version(dest)
                if version_is_newer(dest_version, src_version):
                    logging.warning(
                        "[Scrapers] Downgrade core refusé : %s installé en %s, "
                        "image en %s — copie locale conservée.",
                        filename,
                        dest_version,
                        src_version,
                    )
                elif missing_only:
                    # Après un sync GitHub réussi : on ne rattrape que ce que
                    # l'image livre en version plus récente que la copie posée.
                    if version_is_newer(src_version, dest_version):
                        if auto_update:
                            try:
                                _write_bytes_atomic(dest, src_bytes)
                                updated.append(filename)
                                logging.info(
                                    "[Scrapers] Core mis à jour (image %s → %s) : %s",
                                    dest_version,
                                    src_version,
                                    filename,
                                )
                            except OSError as e:
                                logging.error("[Scrapers] Échec update core %s : %s", filename, e)
                                pending.append({"file": filename, "status": "stale"})
                        else:
                            pending.append({"file": filename, "status": "stale"})
                else:
                    dest_bytes = read_file_bytes(dest) or b""
                    if not _contents_equivalent(src_bytes, dest_bytes):
                        if auto_update:
                            try:
                                _write_bytes_atomic(dest, src_bytes)
                                updated.append(filename)
                                logging.info("[Scrapers] Core mis à jour (image) : %s", filename)
                            except OSError as e:
                                logging.error("[Scrapers] Échec update core %s : %s", filename, e)
                                pending.append({"file": filename, "status": "stale"})
                                continue
                        else:
                            pending.append({"file": filename, "status": "stale"})

            if origins.get(filename) != "core":
                origins[filename] = "core"
                dirty = True

        if dirty:
            save_origins(origins)

    return {"seeded": seeded, "updated": updated, "pending": [p["file"] for p in pending]}


def _try_sync_core_from_github(*, auto_update: bool) -> Optional[Dict[str, List[str]]]:
    """
    Sync core depuis le catalogue community. Retourne None si catalogue injoignable.
    N'appelle pas ``ScraperRegistry.reload`` (le boot charge ensuite).
    """
    try:
        from services.scraper_store import sync_core_from_catalog
    except Exception as e:
        logging.warning("[Scrapers] Import Magasin pour sync core : %s", e)
        return None
    try:
        return sync_core_from_catalog(auto_update=auto_update, timeout=8.0)
    except Exception as e:
        logging.warning("[Scrapers] Sync core GitHub abandonné : %s", e)
        return None


def sync_core_scrapers(*, force: bool = False, auto_update: Optional[bool] = None) -> Dict[str, List[str]]:
    """
    Aligne data/scrapers/ pour les scrapers ``is_core``.

    1. Catalogue GitHub community (source à jour entre releases image)
    2. Fallback / complétion depuis le package image si réseau KO ou fichier manquant

    - ``force=True`` : écrit toujours (endpoint manuel).
    - sinon lit ``AUTO_UPDATE_CORE_SCRAPERS`` (défaut True) ; si False, ne fait que
      le seed des fichiers *absents* et remplit ``pending`` pour les stale.
    """
    auto = _resolve_auto_update(force=force, auto_update=auto_update)

    gh = _try_sync_core_from_github(auto_update=auto)
    if gh is not None:
        # Combler les absents, et rattraper ce que l'image livre en version plus
        # récente que le catalogue : un catalogue en retard ne doit pas priver
        # l'installation d'un correctif déjà présent dans l'image.
        img = _sync_core_from_image(auto_update=auto, missing_only=True)
        seeded = list(gh.get("seeded") or []) + [f for f in (img.get("seeded") or []) if f not in gh.get("seeded", [])]
        updated = list(gh.get("updated") or []) + [
            f for f in (img.get("updated") or []) if f not in (gh.get("updated") or [])
        ]
        pending_files = list(gh.get("pending") or []) + [
            f for f in (img.get("pending") or []) if f not in (gh.get("pending") or [])
        ]
        # Origins for image-only cores still missing from github catalog
        set_pending_core_updates([{"file": f, "status": "stale"} for f in pending_files])
        logging.info(
            "[Scrapers] Sync core GitHub OK (seeded=%s updated=%s pending=%s ; "
            "image gaps=%s, image plus récente=%s)",
            len(gh.get("seeded") or []),
            len(gh.get("updated") or []),
            len(pending_files),
            len(img.get("seeded") or []),
            len(img.get("updated") or []),
        )
        return {"seeded": seeded, "updated": updated, "pending": pending_files}

    logging.info("[Scrapers] Sync core via image (catalogue GitHub indisponible)")
    result = _sync_core_from_image(auto_update=auto, missing_only=False)
    set_pending_core_updates([{"file": f, "status": "stale"} for f in result.get("pending") or []])
    return result


def seed_core_scrapers() -> List[str]:
    """
    Sync core au boot (respecte AUTO_UPDATE_CORE_SCRAPERS).
    Retourne les basenames nouvellement écrits (seed + update).
    """
    result = sync_core_scrapers(force=False)
    return list(result.get("seeded") or []) + list(result.get("updated") or [])


def apply_core_scraper_updates() -> Dict[str, List[str]]:
    """Force sync of all core files (manual CTA) then clear pending."""
    result = sync_core_scrapers(force=True)
    clear_pending_core_updates()
    return result


def _has_package_relative_imports(path: str) -> bool:
    """True si le fichier ressemble à un ancien scraper core (imports relatifs)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(6000)
    except OSError:
        return False
    return "from .base import" in head or "from .utils import" in head or "from .wikidata_map import" in head


def purge_demoted_core_scrapers() -> List[str]:
    """
    Retire les copies data/scrapers/ qui ne sont plus core.

    Les modules seedés avec des imports relatifs cassent une fois chargés sous
    ``custom_scrapers.*``. On les purge pour laisser le Magasin installer la
    version community. Retourne les basenames supprimés.
    """
    removed: List[str] = []
    dest_dir = data_scrapers_dir()
    core_set = set(list_core_filenames())

    with _ORIGINS_LOCK:
        origins = load_origins()
        dirty = False
        for filename in list(list_data_scraper_files()):
            if filename in core_set:
                continue
            path = os.path.join(dest_dir, filename)
            stale_core_mark = origins.get(filename) == "core"
            former_legacy = (
                filename in FORMER_CORE_FILES and _has_package_relative_imports(path)
            )
            if not (stale_core_mark or former_legacy):
                continue
            try:
                os.remove(path)
                removed.append(filename)
                logging.info(
                    "[Scrapers] Ancien core retiré (réinstaller via Magasin) : %s",
                    filename,
                )
            except OSError as e:
                logging.error("[Scrapers] Échec purge demoted %s : %s", filename, e)
                continue
            if filename in origins:
                origins.pop(filename, None)
                dirty = True
        if dirty:
            save_origins(origins)
    return removed


def list_data_scraper_files() -> List[str]:
    dest_dir = data_scrapers_dir()
    names = []
    for filename in sorted(os.listdir(dest_dir)):
        if filename.endswith(".py") and not filename.startswith("__") and not filename.startswith("."):
            names.append(filename)
    return names


def safe_scraper_path(filename: str) -> Optional[str]:
    """
    Résout un chemin sous data/scrapers/. Retourne None si traversal / invalide.
    """
    if not filename or not isinstance(filename, str):
        return None
    base = os.path.basename(filename.strip())
    if base != filename.strip() or not base.endswith(".py") or base.startswith("."):
        return None
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    dest_dir = os.path.realpath(data_scrapers_dir())
    candidate = os.path.realpath(os.path.join(dest_dir, base))
    if not candidate.startswith(dest_dir + os.sep) and candidate != dest_dir:
        return None
    return candidate


def file_sha256(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def read_file_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def normalize_newlines_lf(content: bytes) -> bytes:
    """Normalise CRLF/CR → LF (équivalent git sur checkout Unix / raw GitHub)."""
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_matches(content: bytes, expected: str) -> bool:
    """True si ``expected`` correspond au contenu brut ou après normalisation EOL.

    Le catalogue community est souvent généré sous Windows (hash CRLF) alors que
    ``raw.githubusercontent.com`` sert des fichiers en LF. Sans cette tolérance,
    chaque install échoue en ``sha256 mismatch``.
    """
    expected = (expected or "").strip().lower()
    if not expected or len(expected) != 64:
        return False
    if sha256_hex(content) == expected:
        return True
    lf = normalize_newlines_lf(content)
    if sha256_hex(lf) == expected:
        return True
    crlf = lf.replace(b"\n", b"\r\n")
    if sha256_hex(crlf) == expected:
        return True
    return False


def write_scraper_bytes(filename: str, content: bytes, *, origin: str = "community") -> str:
    """Écrit un .py sous data/scrapers/ et enregistre l'origine. Retourne le chemin."""
    path = safe_scraper_path(filename)
    if path is None:
        raise ValueError("invalid scraper filename")
    if is_core_filename(os.path.basename(path)):
        raise PermissionError("core scrapers cannot be overwritten")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(content)
    os.replace(tmp, path)
    set_origin(os.path.basename(path), origin)
    return path


def delete_scraper_file(filename: str) -> None:
    path = safe_scraper_path(filename)
    if path is None:
        raise ValueError("invalid scraper filename")
    base = os.path.basename(path)
    if is_core_filename(base):
        raise PermissionError("core scrapers cannot be deleted")
    if os.path.isfile(path):
        os.remove(path)
    with _ORIGINS_LOCK:
        origins = load_origins()
        if base in origins:
            origins.pop(base, None)
            save_origins(origins)


def normalize_scopes(raw) -> Set[str]:
    allowed = {"series", "volume"}
    if raw is None:
        return {"series"}
    if isinstance(raw, str):
        raw = [raw]
    out = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if key in allowed:
            out.add(key)
    return out or {"series"}
