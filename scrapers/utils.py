import re

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