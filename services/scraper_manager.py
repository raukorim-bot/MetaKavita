"""
Gestion disque des scrapers sideloadés (`data/scrapers/`).

- Seed des scrapers core (package image → data/) si absents
- Origines (core / community / custom)
- Chemins sûrs (anti path-traversal)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from typing import Dict, Iterable, List, Optional, Set

from config_manager import DATA_DIR

CORE_SKIP_FILES = frozenset({
    "__init__.py",
    "base.py",
    "utils.py",
    "wikidata_map.py",
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


def list_core_filenames() -> List[str]:
    src = package_scrapers_dir()
    if not os.path.isdir(src):
        return []
    names = []
    for filename in sorted(os.listdir(src)):
        if not filename.endswith(".py"):
            continue
        if filename in CORE_SKIP_FILES or filename.startswith("__"):
            continue
        names.append(filename)
    return names


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
    origins = load_origins()
    origins[base] = origin
    save_origins(origins)


def resolve_origin(filename: str) -> str:
    base = os.path.basename(filename or "")
    if is_core_filename(base):
        return "core"
    marked = load_origins().get(base)
    if marked in ("community", "custom"):
        return marked
    return "custom"


def seed_core_scrapers() -> List[str]:
    """
    Copie les scrapers core vers data/scrapers/ s'ils sont absents.
    Ne jamais écraser un fichier déjà présent (hotfix utilisateur).
    Retourne la liste des fichiers nouvellement copiés.
    """
    dest_dir = data_scrapers_dir()
    src_dir = package_scrapers_dir()
    copied: List[str] = []
    origins = load_origins()
    dirty = False

    for filename in list_core_filenames():
        src = os.path.join(src_dir, filename)
        dest = os.path.join(dest_dir, filename)
        if not os.path.isfile(src):
            continue
        if not os.path.isfile(dest):
            try:
                shutil.copy2(src, dest)
                copied.append(filename)
                logging.info("[Scrapers] Core seedé : %s", filename)
            except OSError as e:
                logging.error("[Scrapers] Échec seed core %s : %s", filename, e)
                continue
        if origins.get(filename) != "core":
            origins[filename] = "core"
            dirty = True

    if dirty:
        save_origins(origins)
    return copied


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
