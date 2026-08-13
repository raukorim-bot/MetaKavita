import contextvars
import logging
import re
import unicodedata
import difflib
from contextlib import contextmanager
from typing import Optional

ROMAN_MAP = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
    'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15, 'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20
}

STOP_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or", "no", 
    "de", "la", "le", "les", "du", "un", "une", "des", "et", "en", "tome", "vol", 
    "volume", "book", "part", "partie", "saison", "season", "chapitre", "chapter"
}

NOISE_KEYWORDS = {
    'guidebook', 'fanbook', 'artbook', 'databook', 'characterbook', 'official guide', 
    'illustration book', 'anthology', 'encyclopedia', 'encyclopedie'
}

# Seuil unique d'acceptation d'un candidat scoré par score_candidate() (0.0 à 1.0).
# Historiquement chaque scraper codait sa propre valeur en dur (0.50 pour Anilist/
# MangaBaka/GoogleBooks, 0.60 pour Hardcover/OpenLibrary) : 0.50 a été testé en usage
# réel et générait trop de faux positifs (homonymes, spin-offs). 0.60 est la valeur
# validée empiriquement et doit désormais être utilisée par TOUS les scrapers qui
# passent par score_candidate(), via cette constante partagée plutôt qu'un literal
# recopié dans chaque fichier.
MATCH_ACCEPT_THRESHOLD = 0.60
MATCH_THRESHOLD_MIN = 0.30
MATCH_THRESHOLD_MAX = 1.00

# Dedup (hygiène) — seuil plus strict que le match scraper (défaut 0.92).
# Les malus édition/spin-off sont désormais partagés avec `score_candidate()` :
# ils y sont indispensables, un spin-off étant précisément le faux positif qui
# passe le seuil de match sans être détectable autrement.
DUP_ACCEPT_THRESHOLD = 0.92
DUP_THRESHOLD_MIN = 0.70
DUP_THRESHOLD_MAX = 1.00

# Sous-chaînes normalisées (normalize_str) — spin-offs / éditions.
SPINOFF_MARKERS = (
    "gaiden",
    "spin off",
    "spinoff",
    "side story",
    "sidestory",
    "外伝",
    "番外",
    "novel",
    "light novel",
    "anthology",
)
EDITION_MARKERS = (
    "perfect edition",
    "deluxe edition",
    "ultimate edition",
    "kanzenban",
    "bunkoban",
    "collector edition",
    "collectors edition",
    "omnibus",
    "full color",
    "color edition",
    "edition deluxe",
    "edition collector",
)

# Clé interne (préfixée par "_" comme "_provider_used"/"_fusion_providers") sous laquelle
# chaque scraper attache le score de score_candidate() au dict qu'il retourne. Consommée
# par metadata_fetcher.py pour le "Smart Scoring" : comparer objectivement les candidats
# de plusieurs providers entre eux plutôt que de retenir aveuglément le premier de la
# liste de fallback qui dépasse MATCH_ACCEPT_THRESHOLD (voir CODE_REVIEW.md / DEVELOPER.md).
MATCH_SCORE_KEY = "_match_score"


def find_title_relation_markers(norm_title: str) -> dict:
    """Detect spin-off / edition marker substrings in an already-normalized title."""
    t = norm_title or ""
    spin = {m for m in SPINOFF_MARKERS if m in t}
    edition = {m for m in EDITION_MARKERS if m in t}
    return {"spinoff": spin, "edition": edition}


def relation_title_penalty(markers_a: dict, markers_b: dict) -> tuple:
    """
    Malus when titles differ by unilateral spin-off/edition markers.
    Returns (penalty 0..1, reasons[]). Utilisé par la détection de doublons ET
    par `score_candidate()` : « Berserk » et « Berserk Perfect Edition » sont
    deux séries distinctes dans les deux usages.
    """
    sa = set((markers_a or {}).get("spinoff") or ())
    sb = set((markers_b or {}).get("spinoff") or ())
    ea = set((markers_a or {}).get("edition") or ())
    eb = set((markers_b or {}).get("edition") or ())
    penalty = 0.0
    reasons = []
    if sa != sb and (sa or sb):
        # One has spin-off marker the other lacks (or different markers)
        if not (sa & sb) or sa.symmetric_difference(sb):
            penalty += 0.35
            reasons.append("spinoff_marker")
    if ea and eb and ea != eb and not (ea & eb):
        penalty += 0.40
        reasons.append("different_edition")
    elif (ea or eb) and ea != eb:
        # Unilateral edition marker (Berserk vs Berserk Perfect Edition)
        penalty += 0.40
        reasons.append("edition_marker")
    return min(1.0, penalty), reasons


def get_dup_accept_threshold(config=None) -> float:
    """Seuil d'acceptation doublons (hygiène). Défaut 0.92 si custom off."""
    if config is None:
        try:
            from config_manager import load_config
            config = load_config()
        except Exception:
            return DUP_ACCEPT_THRESHOLD
    if not config.get("DUP_THRESHOLD_CUSTOM"):
        return DUP_ACCEPT_THRESHOLD
    try:
        value = float(config.get("DUP_ACCEPT_THRESHOLD", DUP_ACCEPT_THRESHOLD))
    except (TypeError, ValueError):
        return DUP_ACCEPT_THRESHOLD
    if value != value:  # NaN
        return DUP_ACCEPT_THRESHOLD
    return max(DUP_THRESHOLD_MIN, min(DUP_THRESHOLD_MAX, value))


# --- SEUIL ABAISSÉ À PORTÉE DE CONTEXTE (collecte de review manuelle) ---
# La Manual Review a besoin que les scrapers rendent AUSSI leurs correspondances
# faibles (l'utilisateur tranche ensuite dans la modale), donc d'un seuil à 0.0.
# Cet abaissement était historiquement fait en remplaçant l'attribut de module
# `get_match_accept_threshold` dans scrapers.utils / metadata_fetcher / tous les
# modules `scrapers*` chargés : un état de PROCESS. Un enrichissement automatique
# tournant en parallèle sur une autre série voyait donc 0.0 lui aussi et écrivait
# dans Kavita le premier candidat venu ; et deux collectes imbriquées laissaient
# le seuil à 0.0 jusqu'au redémarrage (la 2de capturait la fonction déjà patchée
# comme « original »). Un ContextVar rend l'abaissement local au contexte
# d'exécution (thread/greenlet) et son imbrication sûre : chaque `set()` rend un
# token restauré en LIFO à la sortie du `with`.
#
# ⚠️ `ThreadPoolExecutor.submit()` ne propage PAS le contexte : tout code qui
# déporte un appel de scraper dans un pool doit soumettre via
# `contextvars.copy_context().run(...)` (voir metadata_fetcher._submit_in_context),
# sinon les workers retombent sur le seuil réel et la collecte manuelle perd ses
# candidats faibles.
_match_accept_threshold_override: contextvars.ContextVar = contextvars.ContextVar(
    "metakavita_match_accept_threshold_override", default=None
)


@contextmanager
def match_accept_threshold_scope(value: float):
    """Abaisse `get_match_accept_threshold()` pour CE contexte d'exécution seulement."""
    token = _match_accept_threshold_override.set(float(value))
    try:
        yield
    finally:
        _match_accept_threshold_override.reset(token)


def get_match_accept_threshold(config=None) -> float:
    """Seuil d'acceptation effectif (Baromètre de fiabilité).

    - contexte de collecte manuelle actif (`match_accept_threshold_scope`) → sa valeur ;
    - `MATCH_THRESHOLD_CUSTOM` faux (défaut) → toujours 0.60 (valeur validée) ;
    - sinon → `MATCH_ACCEPT_THRESHOLD` clampé dans [0.30, 1.00].
    """
    override = _match_accept_threshold_override.get()
    if override is not None:
        return override
    if config is None:
        try:
            from config_manager import load_config
            config = load_config()
        except Exception:
            return MATCH_ACCEPT_THRESHOLD
    if not config.get("MATCH_THRESHOLD_CUSTOM"):
        return MATCH_ACCEPT_THRESHOLD
    try:
        value = float(config.get("MATCH_ACCEPT_THRESHOLD", MATCH_ACCEPT_THRESHOLD))
    except (TypeError, ValueError):
        return MATCH_ACCEPT_THRESHOLD
    if value != value:  # NaN
        return MATCH_ACCEPT_THRESHOLD
    return max(MATCH_THRESHOLD_MIN, min(MATCH_THRESHOLD_MAX, value))


def attach_match_score(candidate: Optional[dict], score: float) -> Optional[dict]:
    """
    Attache le score de correspondance (0.0 à 1.0) au candidat retourné par fetch(),
    sans changer le comportement existant du scraper pris isolément (la clé est ignorée
    par tout code qui ne la lit pas explicitement). À utiliser sur CHAQUE `return` d'un
    candidat accepté dans fetch(), y compris les correspondances par ID direct (is_id=True)
    qui n'appellent pas score_candidate() : dans ce cas on attache 1.0, car une recherche
    par identifiant explicite (URL/ID fourni par l'utilisateur ou déjà connu) ne comporte
    par nature aucune ambiguïté à scorer — elle doit toujours l'emporter face à un simple
    match par titre d'un autre provider.

    Le score est coercé en float et clampé dans [0.0, 1.0] : un scraper communautaire qui
    passerait une chaîne / un hors-bornes ne doit pas pouvoir injecter une valeur qui ferait
    planter le tri Smart Scoring dans `metadata_fetcher.py` (voir aussi `_safe_match_score`
    côté consommateur, filet de sécurité même si `attach_match_score` n'est pas utilisé).
    """
    if candidate is None:
        return None
    try:
        if isinstance(score, bool):
            raise TypeError("bool is not a valid match score")
        numeric = float(score)
        if numeric != numeric:  # NaN
            numeric = get_match_accept_threshold()
        else:
            numeric = max(0.0, min(1.0, numeric))
    except (TypeError, ValueError):
        numeric = get_match_accept_threshold()
    candidate[MATCH_SCORE_KEY] = numeric
    return candidate


# --- CAUSE RÉELLE D'UN « AUCUN RÉSULTAT » ---
# Une clé API révoquée, un jeton expiré ou un quota dépassé rendaient exactement
# la même chose qu'une série inconnue : `fetch()` -> None, sans un seul journal.
# L'utilisateur voyait « aucun résultat » sur tous ses fournisseurs et n'avait
# aucun moyen de savoir qu'il devait renouveler une clé. Les scrapers déposent
# donc ici la cause qu'ils connaissent, et l'appelant (metadata_fetcher) peut la
# distinguer d'une absence de correspondance.
#
# ContextVar et non variable de module : la cascade de providers tourne dans un
# ThreadPoolExecutor, et deux séries enrichies en parallèle ne doivent pas se
# voler leurs diagnostics.
_provider_errors: contextvars.ContextVar = contextvars.ContextVar(
    "metakavita_provider_errors", default=None
)

# Causes normalisées, pour que l'appelant puisse trier sans lire un message.
PROVIDER_ERROR_AUTH = "auth"          # 401 / 403 / jeton expiré / clé invalide
PROVIDER_ERROR_QUOTA = "quota"        # 429 / quota applicatif dépassé
PROVIDER_ERROR_HTTP = "http"          # tout autre non-200


@contextmanager
def provider_error_scope():
    """Collecte les causes signalées par les scrapers pendant CE contexte."""
    bucket: list = []
    token = _provider_errors.set(bucket)
    try:
        yield bucket
    finally:
        _provider_errors.reset(token)


def note_provider_error(provider_id, kind: str, detail: str = "") -> None:
    """Signale à l'appelant pourquoi ce fournisseur ne rendra rien.

    Hors d'un `provider_error_scope()` (scraper appelé isolément, diagnostic,
    test), l'appel ne fait rien : c'est un canal d'information, jamais une
    dépendance.
    """
    bucket = _provider_errors.get()
    if bucket is None:
        return
    bucket.append({"provider": str(provider_id or ""), "kind": kind, "detail": str(detail or "")})


def _retry_after(res) -> str:
    try:
        return str((res.headers or {}).get("Retry-After") or "")
    except Exception:
        return ""


def log_provider_http_error(provider, res, context: str = "") -> None:
    """Journalise un non-200 au niveau que sa cause mérite, et le signale.

    ERROR sur 401/403 : seule l'action de l'utilisateur (renouveler la clé) peut
    y remédier, il faut donc que ça se voie. WARNING sur 429 et sur le reste :
    c'est passager, mais un batch qui en collectionne indique un `rate_limit`
    trop court. Le silence était la pire des options : les bonnes pratiques
    existaient déjà dans `metron.py`, `openlibrary.py` et `babelio.py`, c'était
    une incohérence entre fichiers, pas un choix.
    """
    provider_id = getattr(provider, "id", None) or str(provider or "?")
    status = getattr(res, "status_code", None)
    where = f" ({context})" if context else ""
    if status in (401, 403):
        note_provider_error(provider_id, PROVIDER_ERROR_AUTH, f"HTTP {status}")
        logging.error(
            "🔑 [%s] HTTP %s%s — accès refusé : vérifiez la clé API / le jeton.",
            provider_id, status, where,
        )
        return
    if status == 429:
        retry = _retry_after(res)
        note_provider_error(provider_id, PROVIDER_ERROR_QUOTA, f"HTTP 429 Retry-After={retry or '?'}")
        logging.warning(
            "⏳ [%s] HTTP 429%s — quota atteint%s.",
            provider_id, where,
            f", Retry-After={retry}s" if retry else "",
        )
        return
    note_provider_error(provider_id, PROVIDER_ERROR_HTTP, f"HTTP {status}")
    logging.warning("⚠️ [%s] HTTP %s%s — réponse ignorée.", provider_id, status, where)


def response_is_ok(provider, res, context: str = "") -> bool:
    """True si la réponse est exploitable ; journalise et signale sinon."""
    if res is None:
        note_provider_error(
            getattr(provider, "id", None) or str(provider or "?"),
            PROVIDER_ERROR_HTTP,
            "aucune réponse",
        )
        logging.warning(
            "⚠️ [%s] aucune réponse%s.",
            getattr(provider, "id", None) or provider,
            f" ({context})" if context else "",
        )
        return False
    if getattr(res, "status_code", None) == 200:
        return True
    log_provider_http_error(provider, res, context=context)
    return False


def normalize_str(s):
    """Retire les accents, la ponctuation et met en minuscule pour la comparaison."""
    if not s: return ""
    # 1. Suppression des accents
    s = "".join(c for c in unicodedata.normalize('NFD', str(s).lower()) if unicodedata.category(c) != 'Mn')
    # 2. Remplacement de la ponctuation par un espace
    s = re.sub(r'[^\w\s]', ' ', s)
    # 3. Normalisation des espaces doubles
    return re.sub(r'\s+', ' ', s).strip()

def convert_roman_vol(text: str) -> str:
    """Convertit les chiffres romains de tomes en chiffres arabes (ex: Tome II -> Tome 2)."""
    if not text: return ""
    def replace_roman(match):
        prefix = match.group(1)
        roman = match.group(2).upper()
        if roman in ROMAN_MAP:
            return f"{prefix} {ROMAN_MAP[roman]}"
        return match.group(0)

    pattern = r'(?i)\b(tome|vol|volume|band|book|n[°º]?|#)\s+([IVXLCDM]+)\b'
    return re.sub(pattern, replace_roman, text)

def extract_distinctive_words(text: str) -> set:
    """Extrait les mots significatifs d'un titre en ignorant la ponctuation et les mots vides."""
    norm = normalize_str(text)
    words = re.findall(r'\b\w+\b', norm)
    return {w for w in words if w not in STOP_WORDS and len(w) > 1 and not w.isdigit()}

def extract_volume_number(text: str) -> Optional[int]:
    """Extrait le numéro de tome/volume s'il existe dans le titre (supporte chiffres arabes et romains)."""
    if not text: return None
    text_converted = convert_roman_vol(text)
    match = re.search(r'(?i)\b(?:tome|vol|volume|band|book|neo|n[°º]?|#)\s*(\d+)\b', text_converted)
    if match:
        return int(match.group(1))
    return None

def album_number_key(raw) -> Optional[str]:
    """Numéro d'album sous sa forme canonique, décimales comprises.

    Le format doit être **exactement** celui que produit
    `services.volume_enrichment.matching.number_key` sur le même nombre, sinon
    l'album ne s'apparie à aucun tome Kavita : entier sans décimale inutile
    (`3`), décimale conservée telle quelle (`1.5`), virgule ramenée au point.

    Les hors-série numérotés en 1.5 sont la raison d'être de cette fonction.
    Les deux parseurs BD tronquaient la décimale et rendaient `1` : un tome 1.5
    rencontré avant le tome 1 occupait sa clé, et le vrai tome 1 recevait le
    résumé et la couverture du hors-série, sans que rien ne le signale.
    """
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:g}"


def calculate_similarity(s1, s2):
    """Calcule le pourcentage de ressemblance entre deux titres (0.0 à 1.0)"""
    n1 = normalize_str(convert_roman_vol(s1))
    n2 = normalize_str(convert_roman_vol(s2))
    if not n1 or not n2: return 0.0
    
    ratio = difflib.SequenceMatcher(None, n1, n2).ratio()

    if len(n1) >= 5 and len(n2) >= 5:
        coverage = min(len(n1), len(n2)) / max(len(n1), len(n2))

        # Le plancher de 0.85 ne vaut que si les deux titres se recouvrent
        # largement : « Berserk » est un préfixe de « Berserk Perfect Edition »
        # comme « Monster » l'est de « Monster Musume no Iru Nichijou », et sans
        # condition de couverture le plancher accordait 0.85 aux deux. Après le
        # malus « mot-clé en trop » (-0.25) et l'ancrage tome 1 (+0.10), le score
        # retombait invariablement à 0.70 — au-dessus du seuil de 0.60, donc
        # écrit puis verrouillé dans Kavita sans passer par la revue manuelle. Le
        # seuil de couverture est celui qu'applique déjà la branche
        # « sous-chaîne » juste en dessous : un préfixe est un cas particulier de
        # sous-chaîne, il n'y a pas de raison qu'il soit plus permissif.
        if n2.startswith(n1) or n1.startswith(n2):
            if coverage >= 0.65:
                return max(0.85, ratio)
            return ratio

        if n1 in n2 or n2 in n1:
            if coverage >= 0.65:
                bonus_score = 0.70 + (0.20 * coverage)
                return max(bonus_score, ratio)

    return ratio

def library_type_for_scraper(scraper, detected_type: str) -> str:
    """
    Type à passer à fetch_covers / clean_title pour un scraper donné.
    ComicFlexible n'existe pas dans supported_types : on mappe vers Comic ou Manga.
    """
    if detected_type != "ComicFlexible":
        return detected_type
    st = getattr(scraper, "supported_types", set()) or set()
    if "Comic" in st:
        return "Comic"
    if "Manga" in st:
        return "Manga"
    return "Comic"


# Année de run façon Kavita Flexible / Comic Vine : "Batman (2025)", "Saga (2012-)",
# "Spawn (1992–)". Ne match pas une année hors parenthèses ("Blade Runner 2049").
_COMIC_YEAR_PAREN_RE = re.compile(
    r"\(\s*(?P<year>19\d{2}|20\d{2})\s*(?:[–\-—]\s*(?:\d{2,4})?)?\s*\)"
)


def extract_year_from_title(title: str) -> Optional[int]:
    """Extrait la première année de run entre parenthèses d'un nom de série Kavita."""
    if not title:
        return None
    m = _COMIC_YEAR_PAREN_RE.search(str(title))
    return int(m.group("year")) if m else None


def apply_title_year_hint(existing_metadata: Optional[dict], *titles) -> dict:
    """
    Si `existing_metadata` n'a pas encore d'`year`, la remplit depuis le premier
    titre qui porte un `(YYYY)` Kavita-style. Mutates and returns the dict.
    """
    meta = existing_metadata if isinstance(existing_metadata, dict) else {}
    if meta.get("year"):
        return meta
    for raw in titles:
        hint = extract_year_from_title(raw)
        if hint:
            meta["year"] = hint
            break
    return meta


def clean_title(title: str, library_type: str = "Manga") -> str:
    title = str(title)
    title = re.sub(r'(?i)\.(cbz|cbr|zip|rar|epub|pdf)$', '', title)
    
    if library_type in ("Comic", "ComicFlexible"):
        title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
        title = re.sub(r'\[.*?\]', '', title)
        # IDs / éditeurs hors année pure (ex: (168592), (Antarctic Press, 1992–)).
        title = re.sub(r'\((?!\d{4}\))[^\)]*?\)', '', title)
        # Runs Kavita Flexible : (2025), (2012-), (1992–) — hors du filtre name ComicVine ;
        # l'année est réinjectée via extract_year_from_title → existing_metadata.
        title = _COMIC_YEAR_PAREN_RE.sub('', title)
        title = re.sub(r'\s{2,}', ' ', title)
        title = re.sub(r'^\d{1,3}\s*[-_]\s+', '', title)
        title = re.sub(r'^0\d{1,2}\s+', '', title)
        title = re.sub(r'[-_]', ' ', title)
        title = re.sub(r'\s{2,}', ' ', title)
        
    elif library_type == "Book":
        if " - " in title: title = title.split(" - ")[0].strip()
        elif " _ " in title: title = title.split(" _ ")[0].strip()
        title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
        title = re.sub(r'\[.*?\]', '', title)
        title = re.sub(r'\(.*?\)', '', title)
        title = re.sub(r'[-_]', ' ', title)
        title = re.sub(r'\s{2,}', ' ', title)
        
    else:
        # Manga (Défaut)
        title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
        title = re.sub(r'\[.*?\]', '', title)
        title = re.sub(r'\(.*?\)', '', title)
        title = re.sub(r'^\d{1,3}\s*[-_]\s+', '', title)
        title = re.sub(r'^0\d{1,2}\s+', '', title)
        title = re.sub(r'(?i)\s*[-_]?\s*(perfect|deluxe|ultimate|kanzenban|bunkoban|star|full color|color)\s*(edition|édition)\b.*$', '', title)
        title = re.sub(r'(?i)\b(omnibus|intégrale|integrale|coffret|box set)\b.*$', '', title)
        title = re.sub(r'(?i)\b(tome|vol|volume|t|v|chapitre|chapter|ch|c|partie|part|saison|season)\s*[-_]?\s*\d+.*$', '', title)
        title = re.sub(r'[-_]', ' ', title)
        title = re.sub(r'\s{2,}', ' ', title)
        
    return title.strip()

def calculate_author_similarity(ex_authors: list, cand_staff: list) -> float:
    """Calcule le taux de correspondance entre auteurs de manière sécurisée."""
    if not ex_authors or not cand_staff:
        return 0.0

    cand_authors = []
    for s in cand_staff:
        if isinstance(s, dict):
            node = s.get('node')
            if isinstance(node, dict):
                name_obj = node.get('name')
                if isinstance(name_obj, dict):
                    full_name = name_obj.get('full')
                    if full_name: cand_authors.append(full_name)
                elif isinstance(name_obj, str):
                    cand_authors.append(name_obj)
            elif isinstance(node, str):
                cand_authors.append(node)

    if not cand_authors:
        return 0.0

    best_author_sim = 0.0
    for ea in ex_authors:
        if not ea or not isinstance(ea, str): continue
        norm_ea = normalize_str(ea)
        
        for ca in cand_authors:
            if not ca or not isinstance(ca, str): continue
            norm_ca = normalize_str(ca)
            
            sim = calculate_similarity(norm_ea, norm_ca)
            
            ea_words = [w for w in norm_ea.split() if len(w) > 2]
            ca_words = [w for w in norm_ca.split() if len(w) > 2]
            if ea_words and ca_words:
                if ea_words[-1] == ca_words[-1]:
                    sim = max(sim, 0.85)

            if sim > best_author_sim:
                best_author_sim = sim

    return best_author_sim

def score_candidate(candidate: dict, search_query: str, existing_metadata: dict) -> float:
    """
    Calcule le score global d'un candidat (0.0 à 1.0) avec matrice de décision avancée.
    """
    if not candidate or not isinstance(candidate, dict):
        return 0.0

    # 1. RÈGLE D'OR : ISBN Exact Match
    ex_isbn = existing_metadata.get('isbn') if existing_metadata else None
    cand_isbn = candidate.get('isbn')
    if ex_isbn and cand_isbn:
        clean_ex = re.sub(r'[\s\-]', '', str(ex_isbn))
        clean_cand = re.sub(r'[\s\-]', '', str(cand_isbn))
        if clean_ex and clean_cand and clean_ex == clean_cand:
            return 1.0

    # 2. Score de Titre
    cand_titles = [candidate.get('title')] + (candidate.get('alternative_titles') or [])
    query_titles = [search_query]
    if existing_metadata and existing_metadata.get('localized_name'):
        query_titles.append(existing_metadata['localized_name'])

    best_title_sim = 0.0
    for q_t in query_titles:
        if not q_t: continue
        for c_t in cand_titles:
            if not c_t: continue
            sim = calculate_similarity(q_t, c_t)
            if sim > best_title_sim:
                best_title_sim = sim

    ex_authors = existing_metadata.get('authors', []) if existing_metadata else []
    cand_staff = candidate.get('staff', [])

    # 3. Calcul du score de base (Titre + Auteur)
    author_sim = 0.0
    has_author_comparison = False
    
    if ex_authors and cand_staff:
        author_sim = calculate_author_similarity(ex_authors, cand_staff)
        base_score = (best_title_sim * 0.60) + (author_sim * 0.40)
        has_author_comparison = True
    else:
        base_score = best_title_sim

    bonus = 0.0

    # --- A. PÉNALITÉ ANTI-HOMONYME (Auteurs incompatibles) ---
    if has_author_comparison and author_sim < 0.35:
        bonus -= 0.50

    # --- B. ANCRAGE NUMÉRIQUE (Extraire les tomes avant la vérification des mots) ---
    query_vol = extract_volume_number(search_query)
    cand_title_str = candidate.get('title', '')
    cand_vol = extract_volume_number(cand_title_str)

    # --- C. PÉNALITÉ SPIN-OFF (Mots clés distinctifs manquants) ---
    query_distinct = extract_distinctive_words(search_query)
    cand_distinct = extract_distinctive_words(cand_title_str)

    if query_distinct and cand_distinct:
        missing_from_cand = query_distinct - cand_distinct
        extra_in_cand = cand_distinct - query_distinct
        
        # Si le candidat ne contient pas un mot clé majeur du titre recherché (ex: "Troy" vs "Étoiles")
        if missing_from_cand and len(missing_from_cand) >= 1:
            bonus -= 0.35
        # Si le candidat ajoute un mot clé majeur non demandé (ex: "Monster" vs "Monster Musume")
        elif extra_in_cand and len(query_distinct) <= 2:
            # Exemption : On ne pénalise pas un sous-titre d'album si le numéro de tome correspond !
            if not (query_vol and cand_vol and query_vol == cand_vol):
                bonus -= 0.25

    # --- D. PÉNALITÉ GUIDEBOOK / FANBOOK ---
    cand_norm_title = normalize_str(cand_title_str)
    query_norm = normalize_str(search_query)
    
    cand_has_noise = any(kw in cand_norm_title for kw in NOISE_KEYWORDS)
    query_has_noise = any(kw in query_norm for kw in NOISE_KEYWORDS)
    
    if cand_has_noise and not query_has_noise:
        bonus -= 0.50

    # --- D-bis. PÉNALITÉ ÉDITION / SPIN-OFF ---
    # Les marqueurs existaient mais ne servaient qu'à la détection de doublons :
    # rien n'empêchait « Berserk » de recevoir les métadonnées de « Berserk
    # Perfect Edition » ni « Naruto » celles de « Naruto Gaiden », `age_rating`
    # compris. Un marqueur d'édition ou de spin-off présent d'un seul côté ne
    # décrit pas une variante de titre mais une autre œuvre : c'est le seul
    # signal disponible quand les deux titres sont par ailleurs presque égaux
    # (« Berserk Deluxe » vs « Berserk Perfect Edition »), où la similarité seule
    # conclurait au contraire.
    relation_penalty, _relation_reasons = relation_title_penalty(
        find_title_relation_markers(query_norm),
        find_title_relation_markers(cand_norm_title),
    )
    bonus -= relation_penalty

    # --- E. ANCRAGE TOME 1 & PÉNALITÉ DE TOME INTERMÉDIAIRE ---
    if query_vol is None:
        if cand_vol == 1 or cand_vol is None:
            bonus += 0.10
        elif cand_vol and cand_vol > 1:
            bonus -= 0.45
    elif query_vol and cand_vol:
        if query_vol == cand_vol:
            bonus += 0.15
        else:
            bonus -= 0.45

    # --- F. BONUS SECONDAIRES (Éditeur / Année / Genres) ---
    ex_pub = existing_metadata.get('publisher') if existing_metadata else None
    cand_pub = candidate.get('publisher')
    if ex_pub and cand_pub and (normalize_str(ex_pub) in normalize_str(cand_pub) or normalize_str(cand_pub) in normalize_str(ex_pub)):
        bonus += 0.04

    ex_year = existing_metadata.get('year') if existing_metadata else None
    cand_year = candidate.get('year')
    if ex_year and cand_year:
        try:
            if abs(int(ex_year) - int(cand_year)) <= 1:
                bonus += 0.03
        except (ValueError, TypeError):
            pass

    ex_genres = set(normalize_str(g) for g in (existing_metadata.get('genres', []) if existing_metadata else []))
    cand_genres = set(normalize_str(g) for g in (candidate.get('genres', []) + candidate.get('tags', [])))
    if ex_genres and cand_genres and ex_genres.intersection(cand_genres):
        bonus += 0.03

    return min(1.0, max(0.0, round(base_score + bonus, 2)))