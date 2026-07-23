import re
import unicodedata
import difflib
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

def calculate_similarity(s1, s2):
    """Calcule le pourcentage de ressemblance entre deux titres (0.0 à 1.0)"""
    n1 = normalize_str(convert_roman_vol(s1))
    n2 = normalize_str(convert_roman_vol(s2))
    if not n1 or not n2: return 0.0
    
    ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    
    if len(n1) >= 5 and len(n2) >= 5:
        if n2.startswith(n1) or n1.startswith(n2):
            return max(0.85, ratio)

        if n1 in n2 or n2 in n1:
            shorter_len = min(len(n1), len(n2))
            longer_len = max(len(n1), len(n2))
            coverage = shorter_len / longer_len
            if coverage >= 0.65:
                bonus_score = 0.70 + (0.20 * coverage)
                return max(bonus_score, ratio)
            
    return ratio

def clean_title(title: str, library_type: str = "Manga") -> str:
    title = str(title)
    title = re.sub(r'(?i)\.(cbz|cbr|zip|rar|epub|pdf)$', '', title)
    
    if library_type == "Comic":
        title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
        title = re.sub(r'\[.*?\]', '', title)
        title = re.sub(r'\((?!\d{4}\))[^\)]*?\)', '', title)
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