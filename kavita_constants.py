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

# --- STATUT DE PUBLICATION (Series/metadata -> publicationStatus) ---
# Voir kavita_api.md section 3.A
PUBLICATION_STATUS_MAP = {
    "RELEASING": 0,
    "HIATUS": 1,
    "FINISHED": 2,
    "CANCELLED": 3,
}

# --- CLASSIFICATION D'ÂGE (Series/metadata -> ageRating) ---
# Voir kavita_api.md section 3.B
AGE_RATING_MAP = {
    "safe": 1,
    "suggestive": 2,
    "erotica": 3,
    "pornographic": 4,
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
# Voir kavita_api.md section 3.C. Détection par mots-clés car les fournisseurs
# renvoient des libellés libres ("Manga", "Manhwa (KR)", "Light Novel", ...).
FORMAT_KEYWORDS = (
    (4, ("WEBTOON", "MANHWA", "KR")),
    (3, ("NOVEL", "LIGHT", "BOOK")),
    (2, ("COMIC", "BD", "US", "FR")),
    (1, ("MANGA", "JP")),
)


def resolve_kavita_format_enum(raw_format) -> Optional[int]:
    """
    Détecte l'enum Kavita `format` (1=Manga, 2=Comic/BD, 3=Novel, 4=Webtoon)
    à partir d'une chaîne libre renvoyée par un scraper (ex: provider_data['format']).
    Retourne None si aucun mot-clé connu n'est détecté.
    """
    if not raw_format:
        return None
    fmt = str(raw_format).upper()
    for enum_value, keywords in FORMAT_KEYWORDS:
        if any(keyword in fmt for keyword in keywords):
            return enum_value
    return None
