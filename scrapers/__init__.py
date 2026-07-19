import re

def clean_title(title):
    title = str(title)
    
    # 1. Enlever les extensions de fichiers (.cbz, .zip)
    title = re.sub(r'(?i)\.(cbz|cbr|zip|rar|epub|pdf)$', '', title)
    
    # 2. Remplacer les points par des espaces, SAUF s'ils sont entre deux chiffres (ex: "2.5")
    # Ça sauve la vie de "2.5 Dimensional Seduction" !
    title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
    
    # 3. Enlever les balises de Scantrad [Team] ou (Edition)
    title = re.sub(r'\[.*?\]', '', title)
    title = re.sub(r'\(.*?\)', '', title)
    
    # 4. Enlever les préfixes de numérotation (Les dossiers de chapitres)
    # Cas A : "12 - Naruto" -> On exige un tiret/underscore SUIVI d'un espace.
    # Protège "07-Ghost" (pas d'espace après le tiret) et "17 ans" (pas de tiret).
    title = re.sub(r'^\d{1,3}\s*[-_]\s+', '', title)
    
    # Cas B : "01 Premières gaffes" -> Numérotation qui commence par un ZÉRO sans tiret.
    # Protège "6 Game" ou "17 ans" car ils ne commencent pas par un zéro.
    title = re.sub(r'^0\d{1,2}\s+', '', title)
    
    # 5. Enlever les mentions d'éditions spéciales (ex: "- Perfect Edition")
    title = re.sub(r'(?i)\s*[-_]?\s*(perfect|deluxe|ultimate|kanzenban|bunkoban|star|full color|color)\s*(edition|édition)\b.*$', '', title)
    title = re.sub(r'(?i)\b(omnibus|intégrale|integrale|coffret|box set)\b.*$', '', title)
    
    # 6. Enlever les suffixes de Tomes / Saisons
    title = re.sub(r'(?i)\b(tome|vol|volume|t|v|chapitre|chapter|ch|c|partie|part|saison|season)\s*[-_]?\s*\d+.*$', '', title)
    
    # 7. Nettoyage final : tirets/underscores résiduels et espaces multiples
    title = re.sub(r'[-_]', ' ', title)
    title = re.sub(r'\s{2,}', ' ', title)
    
    return title.strip()