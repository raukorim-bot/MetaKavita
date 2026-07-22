import re
import unicodedata
import difflib

def normalize_str(s):
    """Retire les accents, met en minuscule et nettoie la chaîne pour la comparaison."""
    if not s: return ""
    return "".join(c for c in unicodedata.normalize('NFD', str(s).lower()) if unicodedata.category(c) != 'Mn').strip()

def calculate_similarity(s1, s2):
    """Calcule le pourcentage de ressemblance entre deux titres (0.0 à 1.0)"""
    n1 = normalize_str(s1)
    n2 = normalize_str(s2)
    if not n1 or not n2: return 0.0
    
    # On calcule le ratio mathématique exact
    ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    
    # Bonus absolu : si l'un est inclus dans l'autre (ex: "Naruto" dans "Naruto Shippuden")
    # On garde le meilleur score entre le ratio réel et le bonus de 0.85
    if len(n1) > 4 and len(n2) > 4:
        if n1 in n2 or n2 in n1:
            return max(0.85, ratio)
            
    return ratio

def clean_title(title: str, library_type: str = "Manga") -> str:
    title = str(title)
    # 1. Enlever les extensions de fichiers
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