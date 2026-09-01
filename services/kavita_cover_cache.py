"""Cache disque des jaquettes déjà lues chez Kavita.

Le rail de l'atelier affiche une vignette par série. Sans fichier local, chaque
GET re-télécharge l'image chez Kavita (jeton, timeout, octets) — y compris pour
la même couverture vue dix fois. Les fichiers vivent sous `DATA_DIR/kavita_covers`,
clé `(kind, id, etag)` : l'etag est le `?v=` dérivé de `coverImage`, donc un
changement de jaquette manque le cache au lieu de servir l'ancienne.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Optional, Tuple

_DIR_NAME = "kavita_covers"
_ETAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_lock = threading.Lock()


def _root() -> str:
    from db_manager import DATA_DIR

    return os.path.join(DATA_DIR, _DIR_NAME)


def safe_etag(raw: str) -> str:
    text = str(raw or "").strip()
    return text if text and _ETAG_RE.fullmatch(text) else "0"


def _stem(kind: str, entity_id: int, etag: str) -> str:
    return f"{kind}_{int(entity_id)}_{safe_etag(etag)}"


def _paths(kind: str, entity_id: int, etag: str) -> Tuple[str, str]:
    stem = os.path.join(_root(), _stem(kind, entity_id, etag))
    return stem, stem + ".mime"


def read(kind: str, entity_id: int, etag: str) -> Optional[Tuple[bytes, str]]:
    blob_path, mime_path = _paths(kind, entity_id, etag)
    try:
        with open(blob_path, "rb") as fh:
            data = fh.read()
        if not data:
            return None
        ctype = "image/jpeg"
        if os.path.isfile(mime_path):
            with open(mime_path, "r", encoding="utf-8") as fh:
                ctype = (fh.read() or "").strip() or ctype
        return data, ctype
    except OSError:
        return None


def write(kind: str, entity_id: int, etag: str, data: bytes, content_type: str) -> None:
    if not data:
        return
    root = _root()
    os.makedirs(root, exist_ok=True)
    etag = safe_etag(etag)
    blob_path, mime_path = _paths(kind, entity_id, etag)
    tmp = blob_path + ".tmp"
    ctype = (content_type or "image/jpeg").split(";")[0].strip() or "image/jpeg"
    prefix = f"{kind}_{int(entity_id)}_"
    with _lock:
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, blob_path)
            with open(mime_path, "w", encoding="utf-8") as fh:
                fh.write(ctype)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
        keep = {os.path.basename(blob_path), os.path.basename(mime_path)}
        try:
            for name in os.listdir(root):
                if not name.startswith(prefix) or name in keep:
                    continue
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass
        except OSError:
            pass


def purge_series(series_id: int) -> int:
    """Supprime tous les fichiers de jaquettes associés à cette série dans le cache disque."""
    root = _root()
    if not os.path.isdir(root):
        return 0
    prefix = f"series_{int(series_id)}_"
    deleted = 0
    with _lock:
        try:
            for name in os.listdir(root):
                if name.startswith(prefix):
                    try:
                        os.remove(os.path.join(root, name))
                        deleted += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return deleted

