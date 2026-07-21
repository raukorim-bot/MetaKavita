import time
import re
from bs4 import BeautifulSoup
from curl_cffi import requests

SERIE_A_TESTER = "Les Schtroumpfs"

def generate_search_queries(title: str) -> list:
    queries = [title]
    pattern = r'^(le\s+|la\s+|les\s+|l[\'’]\s*|the\s+|a\s+|an\s+|un\s+|une\s+|des\s+)(.*)$'
    match = re.match(pattern, title, flags=re.IGNORECASE)
    
    if match:
        article = match.group(1).strip()
        rest = match.group(2).strip()
        if rest:
            var2 = f"{rest} ({article})"
            if var2 not in queries:
                queries.append(var2)
            if rest not in queries:
                queries.append(rest)
    return queries

def _extract_staff_and_publisher(soup):
    staff = []
    publisher = None
    
    for label_tag in soup.find_all(['label', 'span']):
        if label_tag.name == 'span' and 'type' not in label_tag.get('class', []):
            continue
        
        label_text = label_tag.get_text(strip=True).lower()
        
        is_writer = "scénario" in label_text or "scénariste" in label_text
        is_penciller = "dessin" in label_text
        is_colorist = "couleur" in label_text
        is_publisher = "editeur" in label_text or "éditeur" in label_text
        
        if not any([is_writer, is_penciller, is_colorist, is_publisher]):
            continue
        
        parent = label_tag.parent
        if not parent:
            continue
            
        a_tags = parent.find_all('a')
        authors = []
        if a_tags:
            for a in a_tags:
                authors.append(a.get_text(strip=True))
        else:
            text_content = parent.get_text(strip=True).replace(label_tag.get_text(strip=True), '')
            for auth in re.split(r'[·&,;]', text_content):
                if auth.strip():
                    authors.append(auth.strip())
                    
        for name_raw in authors:
            name = name_raw.strip()
            if not name or "<indéterminé>" in name.lower() or name.lower() == "indéterminé":
                continue
                
            if ',' in name:
                parts = name.split(',', 1)
                name = f"{parts[1].strip()} {parts[0].strip()}"
                
            if is_writer:
                staff.append(f"Scénario: {name}")
            elif is_penciller:
                staff.append(f"Dessin: {name}")
            elif is_colorist:
                staff.append(f"Couleur: {name}")
            elif is_publisher and not publisher:
                publisher = name
                
    return staff, publisher


def debug_bedetheque(query):
    print(f"🔍 Début du débuggage pour : '{query}'...")
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.bedetheque.com/search/albums"
    }

    session = requests.Session(impersonate="chrome110")

    print("▶️ Récupération du jeton de sécurité (CSRF)...")
    res_init = session.get("https://www.bedetheque.com/search/albums", headers=headers, timeout=10)
    soup_init = BeautifulSoup(res_init.text, 'html.parser')
    csrf_tag = soup_init.find('input', {'name': 'csrf_token_bel'})
    csrf_token = csrf_tag['value'] if csrf_tag else ""

    queries_to_try = generate_search_queries(query)
    album_url = None

    print(f"▶️ Requêtes générées à tester : {queries_to_try}")

    for q in queries_to_try:
        print(f"   Recherche avec '{q}'...")
        params = {"RechSerie": q, "csrf_token_bel": csrf_token}
        res_search = session.get("https://www.bedetheque.com/search/albums", params=params, headers=headers, timeout=15)
        
        soup_search = BeautifulSoup(res_search.text, 'html.parser')
        results_ul = soup_search.find('ul', class_='search-list')
        
        if not results_ul:
            print("   ❌ Aucun résultat UL.")
            continue

        first_li = results_ul.find('li')
        if not first_li:
            print("   ❌ La liste est vide.")
            continue

        a_tag = first_li.find('a', class_='image-tooltip') or first_li.find('a')
        
        if not a_tag or not a_tag.get('href'):
            print("   ❌ Impossible de trouver le lien de l'album.")
            continue
            
        album_url = a_tag['href']
        break
        
    if not album_url:
        print("❌ Impossible de trouver un album avec ces recherches. Fin.")
        return

    if not album_url.startswith('http'):
        album_url = f"https://www.bedetheque.com{album_url}"
        
    print(f"\n✅ Album trouvé : {album_url}")

    print("▶️ Téléchargement de la page de l'album...")
    res_album = session.get(album_url, headers=headers)
    soup_album = BeautifulSoup(res_album.text, 'html.parser')
    
    with open("debug_album.html", "w", encoding="utf-8") as f:
        f.write(soup_album.prettify())
    print("💾 Fichier 'debug_album.html' sauvegardé !")

    print("\n--- 🔎 RÉSULTAT EXTRACTION STAFF (ALBUM) ---")
    staff, pub = _extract_staff_and_publisher(soup_album)
    for s in staff:
        print(s)
    print(f"Éditeur: {pub}")

    # Trouver la page de la série
    serie_url = None
    h1_serie = soup_album.find('h1')
    if h1_serie and h1_serie.find('a'):
        serie_url = h1_serie.find('a').get('href')
    
    if not serie_url:
        serie_links = soup_album.find_all('a', href=lambda h: h and '/serie-' in h and '.html' in h)
        if serie_links:
            serie_url = serie_links[0]['href']

    if serie_url:
        if not serie_url.startswith('http'):
            serie_url = f"https://www.bedetheque.com{serie_url}"
            
        print(f"\n✅ Série trouvée : {serie_url}")
        print("▶️ Téléchargement de la page de la série...")
        res_serie = session.get(serie_url, headers=headers)
        soup_serie = BeautifulSoup(res_serie.text, 'html.parser')
        
        with open("debug_serie.html", "w", encoding="utf-8") as f:
            f.write(soup_serie.prettify())
        print("💾 Fichier 'debug_serie.html' sauvegardé !")
        
        print("\n--- 🔎 RÉSULTAT EXTRACTION STAFF (SÉRIE) ---")
        staff_s, pub_s = _extract_staff_and_publisher(soup_serie)
        for s in staff_s:
            print(s)
        print(f"Éditeur: {pub_s}")
    else:
        print("❌ Impossible de trouver l'URL de la série.")

if __name__ == "__main__":
    debug_bedetheque(SERIE_A_TESTER)