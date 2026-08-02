"""
Constantes et mappings d'énumération partagés pour l'intégration Kavita.

Objectif (voir DEVELOPER.md section 11.D "Centraliser, ne pas dupliquer") :
regrouper en un seul endroit les tables de correspondance entre les valeurs
"métier" utilisées par MetaKavita (scrapers, moteur d'enrichissement) et les
enums numériques attendus par l'API Kavita (voir kavita_api.md section 3),
ainsi que les mappings de normalisation des statuts bruts renvoyés par les
fournisseurs externes (MangaBaka, etc.).

Avant ce module, ces dictionnaires étaient dupliqués/réimplémentés localement
dans app.py et dans certains scrapers, ce qui a directement causé un bug de
production (le statut brut "completed" de MangaBaka ne correspondait à aucune
clé du mapping local de app.py, qui attendait "FINISHED").
"""

from typing import Optional
import re

# --- STATUT DE PUBLICATION (Series/metadata -> publicationStatus) ---
# Voir kavita_api.md section 3.A
PUBLICATION_STATUS_MAP = {
    "RELEASING": 0,
    "HIATUS": 1,
    "FINISHED": 2,
    "CANCELLED": 3,
}

# --- CLASSIFICATION D'ÂGE (Series/metadata -> ageRating) ---
# Enum Kavita réel (AgeRating.cs / GET /api/metadata/age-ratings) — PAS les
# content ratings MangaDex. Vocabulaire interne neutre (BF81) :
#   safe / suggestive / mature / r18 / x18
# Aliases deprecated (MangaDex-shaped) : erotica→r18, pornographic→x18.
# Voir kavita_api.md §3.B et DEVELOPER.md (AGE_RATING_MAP / BF53 / BF80 / BF81).
AGE_RATING_MAP = {
    "safe": 3,            # Everyone
    "suggestive": 8,      # Teen
    "mature": 10,         # Mature 17+ (intense / themes, not explicit sexual)
    "r18": 12,            # R18+ (adult restricted — not necessarily porn)
    "x18": 14,            # X18+ (explicit sexual / hentai)
    # Deprecated aliases — still accepted from scrapers / community:
    "erotica": 12,        # → r18
    "pornographic": 14,   # → x18
}

# --- NORMALISATION DES STATUTS BRUTS FOURNISSEURS ---
# Convertit les valeurs brutes renvoyées par les API externes (souvent en
# minuscules, format libre) vers le contrat interne MetaKavita utilisé par
# PUBLICATION_STATUS_MAP ci-dessus ("RELEASING"/"HIATUS"/"FINISHED"/"CANCELLED").
# Utilisé notamment par scrapers/mangabaka.py.
RAW_STATUS_NORMALIZATION_MAP = {
    "completed": "FINISHED",
    "finished": "FINISHED",
    "releasing": "RELEASING",
    "ongoing": "RELEASING",
    "hiatus": "HIATUS",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
}


def normalize_provider_status(raw_status) -> Optional[str]:
    """
    Normalise un statut brut de fournisseur externe (ex: "completed", "Releasing")
    vers le contrat interne MetaKavita ("FINISHED", "RELEASING", ...).
    Retourne None si la valeur est inconnue (au lieu de planter ou de mapper au hasard).
    """
    if not raw_status:
        return None
    return RAW_STATUS_NORMALIZATION_MAP.get(str(raw_status).strip().lower())


# --- SENS DE LECTURE / FORMAT (Series/update -> format) ---
# Voir kavita_api.md section 3.C. Les scrapers émettent surtout des tokens
# courts ("manga"/"comic"/"webtoon"/"book") ; certains labels libres existent
# encore ("Manhwa (KR)", "Light Novel"). BF58 : plus de matching par sous-chaîne
# (ex. "BOOK" dans "COMIC BOOK" → Novel, "US" dans "MUST…" → Comic).

# Tokens exacts du contrat scraper (insensible à la casse).
_FORMAT_EXACT = {
    "manga": 1,
    "comic": 2,
    "bd": 2,
    "book": 3,
    "novel": 3,
    "webtoon": 4,
    "manhwa": 4,
}

# Table documentaire (priorité Comic avant Novel pour "COMIC BOOK").
FORMAT_KEYWORDS = (
    (4, ("WEBTOON", "MANHWA", "KR")),
    (2, ("COMIC", "BD", "US", "FR")),
    (3, ("NOVEL", "BOOK")),
    (1, ("MANGA", "JP")),
)

_FORMAT_TOKEN_RE = re.compile(r"[A-Z0-9]+")


def resolve_kavita_format_enum(raw_format) -> Optional[int]:
    """
    Détecte l'enum Kavita `format` (1=Manga, 2=Comic/BD, 3=Novel, 4=Webtoon)
    à partir d'une chaîne libre renvoyée par un scraper (ex: provider_data['format']).
    Retourne None si aucun mot-clé connu n'est détecté.

    BF58 : exact match d'abord, puis tokens (word-split), jamais `keyword in string`.
    """
    if not raw_format:
        return None
    text = str(raw_format).strip()
    if not text:
        return None

    exact = _FORMAT_EXACT.get(text.lower())
    if exact is not None:
        return exact

    tokens = set(_FORMAT_TOKEN_RE.findall(text.upper()))
    if not tokens:
        return None

    if tokens & {"WEBTOON", "MANHWA"} or "KR" in tokens:
        return 4
    # Comic avant Book — "COMIC BOOK" → Comic (2), pas Novel
    if tokens & {"COMIC", "BD"}:
        return 2
    if tokens & {"NOVEL", "BOOK"}:
        return 3
    if tokens & {"MANGA", "JP"}:
        return 1
    # Codes région seuls (évite "US" dans "MUST" grâce au split)
    if tokens & {"US", "FR"}:
        return 2
    return None
