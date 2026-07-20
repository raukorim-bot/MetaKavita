import re

def clean_title(title, library_type="Manga"):
    title = str(title)
    
    # 1. Enlever les extensions de fichiers (.cbz, .zip, etc.) pour tous les types
    title = re.sub(r'(?i)\.(cbz|cbr|zip|rar|epub|pdf)$', '', title)
    
    if library_type == "Comic":
        # Remplacer les points par des espaces, sauf s'ils sont entre deux chiffres (ex: issue 2.5)
        title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
        
        # Enlever uniquement les balises de Scantrad [Team]
        title = re.sub(r'\[.*?\]', '', title)
        
        # Enlever les parenthèses SAUF si elles contiennent une année de publication (ex: Batman (2011) #12)
        title = re.sub(r'\((?!\d{4}\))[^\)]*?\)', '', title)
        
        # Compression immédiate des espaces multiples générés par le retrait des points
        title = re.sub(r'\s{2,}', ' ', title)
        
        # Enlever les préfixes de numérotation d'albums de manière sécurisée
        # Ex: "04 Le bureau..." -> "Le bureau..."
        # Ex: "04 - Le bureau..." -> "Le bureau..."
        title = re.sub(r'^\d{1,3}\s*[-_]\s+', '', title)
        title = re.sub(r'^0\d{1,2}\s+', '', title)
        
        # Nettoyage final sans suppression agressive de la numérotation interne
        title = re.sub(r'[-_]', ' ', title)
        title = re.sub(r'\s{2,}', ' ', title)
        
    elif library_type == "Book":
        if " - " in title:
            title = title.split(" - ")[0].strip()
        elif " _ " in title:
            title = title.split(" _ ")[0].strip()
            
        title = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', title)
        
        title = re.sub(r'\[.*?\]', '', title)
        title = re.sub(r'\(.*?\)', '', title)
        
        title = re.sub(r'[-_]', ' ', title)
        title = re.sub(r'\s{2,}', ' ', title)
        
    else:
        # Manga (Logique Regex classique par défaut)
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