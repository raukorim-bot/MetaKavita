"""
Socle commun des scripts de stress MetaKavita.

Ce module ne teste rien par lui-même : il fournit les doubles (API Kavita,
fournisseurs), la base SQLite jetable et les instruments de mesure (temps,
mémoire du process, handles, taille de base) utilisés par les scénarios
`s1_*.py` à `s6_*.py`.

Garanties de sûreté, à ne jamais lever :

* aucune écriture vers une instance Kavita réelle — `FakeKavitaAPI` est un
  double en mémoire, et aucun script n'instancie `kavita_api.KavitaAPI` ;
* aucun appel réseau vers un fournisseur — les scrapers sont des doubles, et
  `requests` n'est jamais utilisé ;
* aucune écriture dans `data/cache.db` — `temp_db()` détourne
  `db_manager.DATA_DIR` / `DB_FILE` vers un dossier temporaire local (hors du
  partage réseau Z:) supprimé à la sortie ;
* aucun fichier de l'application n'est modifié.

Relance : ces scripts s'exécutent depuis la racine du dépôt, par exemple
    python debug/stress/s1_volume_pass_scale.py
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# Sentinelles Kavita 0.8 (cf. services/volume_enrichment/matching.py).
SPECIAL_VOL = 100_000
LOOSE_VOL = -100_000


# --------------------------------------------------------------------------
# Instruments de mesure
# --------------------------------------------------------------------------
class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _win_api():
    """Prototypes explicites : sans `argtypes`, le pseudo-handle -1 rendu par
    `GetCurrentProcess` est tronqué à 32 bits et tous les appels échouent en
    silence (les mesures rendaient 0)."""
    if os.name != "nt":
        return None, None, None
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    memory_info = getattr(kernel32, "K32GetProcessMemoryInfo", None) or getattr(
        ctypes.windll.psapi, "GetProcessMemoryInfo"
    )
    memory_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        ctypes.c_ulong,
    ]
    memory_info.restype = ctypes.c_int
    handles = kernel32.GetProcessHandleCount
    handles.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    handles.restype = ctypes.c_int
    return kernel32.GetCurrentProcess(), memory_info, handles


_PROCESS, _MEMORY_INFO, _HANDLE_COUNT = _win_api()


def rss_mb() -> float:
    """Working set du process, en Mo."""
    if os.name != "nt":
        try:
            import resource  # noqa: PLC0415

            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            return 0.0
    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
    if not _MEMORY_INFO(_PROCESS, ctypes.byref(counters), counters.cb):
        return 0.0
    return counters.WorkingSetSize / (1024.0 * 1024.0)


def handle_count() -> int:
    """Handles ouverts par le process (fichiers, sockets, events...)."""
    if os.name != "nt":
        try:
            return len(os.listdir("/proc/self/fd"))
        except Exception:
            return 0
    count = ctypes.c_ulong(0)
    if not _HANDLE_COUNT(_PROCESS, ctypes.byref(count)):
        return 0
    return int(count.value)


def thread_count() -> int:
    return threading.active_count()


def db_size_mb(db_file: str) -> float:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(db_file + suffix)
        except OSError:
            # Le -wal / -shm apparaît et disparaît au gré des checkpoints.
            pass
    return total / (1024.0 * 1024.0)


def percentile(values, pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[position]


class Snapshot:
    """Photo avant/après d'un scénario."""

    def __init__(self, db_file=None):
        self.db_file = db_file
        self.t0 = time.perf_counter()
        self.rss0 = rss_mb()
        self.handles0 = handle_count()
        self.threads0 = thread_count()
        self.db0 = db_size_mb(db_file) if db_file else 0.0

    def close(self) -> dict:
        return {
            "duration_s": round(time.perf_counter() - self.t0, 3),
            "rss_start_mb": round(self.rss0, 1),
            "rss_end_mb": round(rss_mb(), 1),
            "rss_delta_mb": round(rss_mb() - self.rss0, 1),
            "handles_start": self.handles0,
            "handles_end": handle_count(),
            "threads_start": self.threads0,
            "threads_end": thread_count(),
            "db_start_mb": round(self.db0, 3),
            "db_end_mb": round(db_size_mb(self.db_file) if self.db_file else 0.0, 3),
        }


class Report:
    """Collecte les mesures et les écrit en JSON à côté du script."""

    def __init__(self, name: str):
        self.name = name
        self.rows = []
        self.findings = []
        self.started = time.time()

    def add(self, label: str, **metrics):
        row = {"scenario": label, **metrics}
        self.rows.append(row)
        printable = " ".join(f"{k}={v}" for k, v in metrics.items())
        print(f"  [{label}] {printable}", flush=True)
        return row

    def finding(self, severity: str, title: str, detail: str):
        self.findings.append({"severity": severity, "title": title, "detail": detail})
        print(f"  !! [{severity}] {title} — {detail}", flush=True)

    def save(self):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"{self.name}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "name": self.name,
                    "started": self.started,
                    "elapsed_s": round(time.time() - self.started, 2),
                    "rows": self.rows,
                    "findings": self.findings,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\n--> {path}", flush=True)
        return path


def banner(text: str):
    print("\n" + "=" * 78, flush=True)
    print(text, flush=True)
    print("=" * 78, flush=True)


# --------------------------------------------------------------------------
# Base SQLite jetable
# --------------------------------------------------------------------------
@contextmanager
def temp_db(prefix: str = "mkstress-"):
    """Détourne db_manager vers une base temporaire locale, puis nettoie.

    Le dossier temporaire est pris sur le disque local (`%TEMP%`) et non dans
    le dépôt : mesurer SQLite à travers un partage SMB ne dirait rien de la
    production (conteneur Linux, volume local).
    """
    import db_manager

    directory = tempfile.mkdtemp(prefix=prefix)
    old_dir, old_file = db_manager.DATA_DIR, db_manager.DB_FILE
    db_manager.DATA_DIR = directory
    db_manager.DB_FILE = os.path.join(directory, "cache.db")
    db_manager.init_db()
    try:
        yield db_manager, db_manager.DB_FILE
    finally:
        db_manager.DATA_DIR, db_manager.DB_FILE = old_dir, old_file
        shutil.rmtree(directory, ignore_errors=True)


class Patches:
    """Monkeypatch minimal, hors pytest, avec restauration garantie."""

    def __init__(self):
        self._undo = []

    def attr(self, obj, name, value):
        had = hasattr(obj, name)
        old = getattr(obj, name, None)
        setattr(obj, name, value)
        self._undo.append((obj, name, old, had))
        return value

    def dotted(self, path: str, value):
        module_name, _, attr = path.rpartition(".")
        module = __import__(module_name, fromlist=["_"])
        return self.attr(module, attr, value)

    def undo(self):
        while self._undo:
            obj, name, old, had = self._undo.pop()
            if had:
                setattr(obj, name, old)
            else:
                try:
                    delattr(obj, name)
                except AttributeError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.undo()
        return False


# --------------------------------------------------------------------------
# Double de l'API Kavita
# --------------------------------------------------------------------------
class FakeKavitaAPI:
    """Kavita en mémoire, avec état : ce qui est écrit est relu.

    L'état compte : `apply_entry` relit le chapitre avant d'écrire, et la
    politique « on ne comble que les vides » ne se vérifie que si le double
    reflète les écritures précédentes.
    """

    def __init__(self, series, volumes, *, write_delay=0.0, read_delay=0.0, fail_every=0):
        self.series = list(series)
        self._by_id = {int(s["id"]): s for s in self.series}
        self.volumes = volumes  # {series_id: [volume dicts]}
        self.write_delay = write_delay
        self.read_delay = read_delay
        self.fail_every = fail_every
        self.lock = threading.Lock()
        self.calls = {}
        self.writes = []  # (chapter_id, tuple(champs écrits))
        self.cover_uploads = []
        self._chapters = {}
        for sid, vols in volumes.items():
            for volume in vols:
                for chapter in volume.get("chapters", []):
                    self._chapters[int(chapter["id"])] = dict(chapter)

    def _count(self, name):
        with self.lock:
            self.calls[name] = self.calls.get(name, 0) + 1
            return self.calls[name]

    # --- lecture ---
    def get_all_series(self, library_id=None):
        self._count("get_all_series")
        return list(self.series)

    def get_series(self, sid):
        self._count("get_series")
        return self._by_id.get(int(sid))

    def get_library_type_for_series(self, sid):
        self._count("get_library_type_for_series")
        return "Comic"

    def get_series_metadata(self, sid):
        self._count("get_series_metadata")
        return {"summary": "", "genres": [], "tags": [], "webLinks": ""}

    def get_series_volumes(self, sid):
        self._count("get_series_volumes")
        if self.read_delay:
            time.sleep(self.read_delay)
        return self.volumes.get(int(sid), [])

    def get_chapter(self, chapter_id):
        self._count("get_chapter")
        if self.read_delay:
            time.sleep(self.read_delay)
        with self.lock:
            current = self._chapters.get(int(chapter_id))
            return dict(current) if current else None

    # --- écriture (jamais vers un vrai Kavita) ---
    def update_chapter_metadata(self, dto):
        n = self._count("update_chapter_metadata")
        if self.write_delay:
            time.sleep(self.write_delay)
        if self.fail_every and n % self.fail_every == 0:
            return False, "kavita-500"
        chapter_id = int(dto["id"])
        with self.lock:
            state = self._chapters.setdefault(chapter_id, {"id": chapter_id})
            for key, value in dto.items():
                if key != "_written_fields":
                    state[key] = value
            self.writes.append(chapter_id)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        self._count("upload_chapter_cover")
        with self.lock:
            self.cover_uploads.append(int(chapter_id))
            state = self._chapters.setdefault(int(chapter_id), {"id": int(chapter_id)})
            state["coverImageLocked"] = True
        return True, "ok"

    # --- introspection ---
    def write_count(self):
        with self.lock:
            return len(self.writes)

    def distinct_written_chapters(self):
        with self.lock:
            return set(self.writes)

    def duplicate_writes(self):
        with self.lock:
            seen, dupes = set(), []
            for chapter_id in self.writes:
                if chapter_id in seen:
                    dupes.append(chapter_id)
                seen.add(chapter_id)
            return dupes


# --------------------------------------------------------------------------
# Générateur de bibliothèque synthétique
# --------------------------------------------------------------------------
def _chapter(chapter_id, number, **extra):
    chapter = {
        "id": chapter_id,
        "minNumber": number,
        "titleName": "",
        "summary": "",
        "isbn": "",
        "releaseDate": "0001-01-01T00:00:00",
        "sortOrder": number if isinstance(number, (int, float)) else 0,
        "genres": [],
        "tags": [],
        "writers": [],
    }
    chapter.update(extra)
    return chapter


def make_series(series_id, shape="normal", volume_count=3):
    """Une série synthétique et ses tomes, selon la forme demandée.

    Formes : `normal` (n tomes d'un fichier), `long` (300 tomes),
    `multi` (un tome, n chapitres — le cas comics), `sentinel` (feuilles
    volantes -100000 et spéciaux 100000), `decimal` (1, 1.5, 2), `empty`.
    """
    name = f"{shape.capitalize()} Series {series_id}"
    base_chapter = series_id * 10_000
    base_volume = series_id * 10_000 + 500_000
    volumes = []

    if shape == "empty":
        volumes = []
    elif shape == "multi":
        chapters = [
            _chapter(base_chapter + n, float(n)) for n in range(1, volume_count + 1)
        ]
        volumes = [{"id": base_volume, "minNumber": 1.0, "chapters": chapters}]
    elif shape == "sentinel":
        volumes = [
            {
                "id": base_volume,
                "minNumber": LOOSE_VOL,
                "chapters": [_chapter(base_chapter + 1, 1.0)],
            },
            {
                "id": base_volume + 1,
                "minNumber": SPECIAL_VOL,
                "isSpecial": True,
                "chapters": [_chapter(base_chapter + 2, SPECIAL_VOL, isSpecial=True)],
            },
            {
                "id": base_volume + 2,
                "minNumber": SPECIAL_VOL,
                "chapters": [_chapter(base_chapter + 3, 2.0)],
            },
            {
                "id": base_volume + 3,
                "minNumber": 1.0,
                "chapters": [_chapter(base_chapter + 4, 1.0)],
            },
        ]
    elif shape == "decimal":
        numbers = [1.0, 1.5, 2.0, 2.5, 3.0]
        volumes = [
            {
                "id": base_volume + i,
                "minNumber": number,
                "chapters": [_chapter(base_chapter + i, number)],
            }
            for i, number in enumerate(numbers, start=1)
        ]
    else:  # normal / long
        volumes = [
            {
                "id": base_volume + n,
                "minNumber": float(n),
                "chapters": [_chapter(base_chapter + n, float(n))],
            }
            for n in range(1, volume_count + 1)
        ]

    series = {"id": series_id, "name": name, "libraryType": "Comic", "libraryId": 1}
    return series, volumes


def make_library(spec):
    """`spec` : liste de (forme, nombre de séries, tomes par série)."""
    series_list, volumes = [], {}
    next_id = 1
    for shape, count, size in spec:
        for _ in range(count):
            series, vols = make_series(next_id, shape=shape, volume_count=size)
            series_list.append(series)
            volumes[next_id] = vols
            next_id += 1
    return series_list, volumes


def unit_total(volumes):
    return sum(len(v.get("chapters", [])) for vols in volumes.values() for v in vols)


def make_index(size=320):
    """Index fournisseur couvrant les numéros 1..size, plus les décimaux usuels."""
    index = {str(n): {"summary": f"Résumé du tome {n}", "title": f"Tome {n}"}
             for n in range(1, size + 1)}
    for half in ("1.5", "2.5"):
        index[half] = {"summary": f"Résumé du tome {half}", "title": f"Tome {half}"}
    return index


# --------------------------------------------------------------------------
# Doubles de fournisseurs
# --------------------------------------------------------------------------
class FakeScraper:
    """Fournisseur de tomes, avec panne programmable.

    Passe par le vrai `fetch_index` (donc par `throttle_provider`) : c'est la
    cadence réelle de MetaKavita qui est mesurée, pas une imitation.
    """

    supported_types = {"Comic", "Manga", "Book"}

    def __init__(self, scraper_id, *, rate_limit=0.0, index=None, latency=0.0,
                 mode="ok", index_size=320):
        self.id = scraper_id
        self.rate_limit = rate_limit
        self.latency = latency
        self.mode = mode
        self.index = index if index is not None else make_index(index_size)
        self.calls = 0
        self.call_times = []
        self.lock = threading.Lock()

    def fetch_volume_index(self, query, library_type="Comic", series_id=None,
                           existing_metadata=None):
        with self.lock:
            self.calls += 1
            self.call_times.append(time.perf_counter())
        if self.latency:
            time.sleep(self.latency)
        if self.mode == "timeout":
            raise TimeoutError("read timeout")
        if self.mode == "http429":
            raise RuntimeError("429 Too Many Requests")
        if self.mode == "http500":
            raise RuntimeError("500 Internal Server Error")
        if self.mode == "badjson":
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        if self.mode == "truncated":
            return {"1": {"summary": "<div class=\"al"}}  # HTML coupé net
        if self.mode == "empty":
            return None
        if self.mode == "giant":
            # Chaînes réellement distinctes : `"x" * 4000` serait replié en une
            # seule constante par le compilateur, et les 20 000 entrées
            # partageraient le même objet — l'index paraîtrait gratuit.
            return {
                str(n): {"summary": f"Résumé {n} " + "y" * 3990, "title": f"T{n}"}
                for n in range(1, 20_001)
            }
        if self.mode == "junk":
            return "pas un dict"
        return self.index

    def fetch_volume_credits(self, provider_ref):
        with self.lock:
            self.calls += 1
            self.call_times.append(time.perf_counter())
        return {"writers": ["Auteur"], "coverArtists": ["Dessinateur"]}

    def max_gap_violations(self):
        """Nombre d'appels partis avant l'expiration du rate_limit."""
        with self.lock:
            times = sorted(self.call_times)
        return sum(
            1
            for a, b in zip(times, times[1:])
            if (b - a) < self.rate_limit - 0.02
        )


def wire_volume_pass(patches, api, scrapers, *, config=None, isbn_index=None,
                     emit_counter=None):
    """Branche la passe par tome sur les doubles. Rend le dict de config utilisé."""
    from services.volume_enrichment import job, providers

    cfg = {"KAVITA_URL": "http://double", "KAVITA_API_KEY": "double"}
    cfg.update(config or {})

    patches.attr(job, "load_config", lambda: cfg)
    patches.attr(job, "KavitaAPI", lambda url, key: api)
    patches.attr(job, "get_all_cached_data", lambda: {})
    patches.attr(providers, "volume_providers", lambda lib_type, config=None: list(scrapers))
    patches.attr(providers, "fetch_by_isbn", lambda units, **kw: dict(isbn_index or {}))

    def _emit(event, payload):
        if emit_counter is not None:
            emit_counter[event] = emit_counter.get(event, 0) + 1

    patches.attr(job, "_emit", _emit)
    return cfg


def wait_idle(timeout=600.0, poll=0.02):
    """Attend la fin de la passe. Rend (fini, secondes attendues)."""
    from services.volume_enrichment import job

    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if not job.get_volume_enrich_state()["running"]:
            return True, time.perf_counter() - start
        time.sleep(poll)
    return False, time.perf_counter() - start


def reset_job_state():
    from services.volume_enrichment import job

    with job._lock:
        job._state.update(
            {"running": False, "cancelled": False, "done": 0, "total": 0,
             "counts": {}, "skipped": 0, "error": None}
        )
