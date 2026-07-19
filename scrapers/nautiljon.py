import re
from bs4 import BeautifulSoup
from curl_cffi import requests
from scrapers import clean_title

BASE_URL = "https://www.nautiljon.com"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.nautiljon.com/", 
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1"
}

def fetch_nautiljon(title_or_slug):
    slug = None
    
    session = requests.Session(impersonate="safari15_5")
    session.headers.update(HEADERS)
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', str(title_or_slug)) or " " in str(title_or_slug) or str(title_or_slug).isdigit():
        clean = clean_title(title_or_slug)
        print(f"[Nautiljon] Recherche par titre : '{clean}'")
        try:
            res_init = session.get(f"{BASE_URL}/mangas/", timeout=15)
            soup_init = BeautifulSoup(res_init.text, 'html.parser')
            st_input = soup_init.find('input', {'name': 'st'})
            
            if not st_input or not st_input.get('value'):
                print("[Nautiljon] Échec : Impossible de trouver le jeton 'st'.")
                return None
                
            search_token = st_input['value']
            
            params = {"q": clean, "st": search_token}
            res = session.get(f"{BASE_URL}/mangas/", params=params, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            search_table = soup.find('table', class_='search')
            if not search_table:
                return None
                
            a_tag = search_table.find('a', href=re.compile(r'^/mangas/.*\.html$'))
            if not a_tag:
                return None
                
            slug = a_tag['href'].replace('/mangas/', '').replace('.html', '')
        except Exception as e:
            print(f"[Erreur Recherche Nautiljon] {e}")
            return None
    else:
        slug = title_or_slug
        print(f"[Nautiljon] Requête directe par slug : {slug}")

    try:
        url = f"{BASE_URL}/mangas/{slug}.html"
        res = session.get(url, timeout=15)
        if res.status_code != 200:
            return None
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # --- Récupération de l'image de couverture ---
        cover_url = None
        img_tag = soup.find('img', itemprop='image')
        if img_tag and img_tag.has_attr('src'):
            if img_tag['src'].startswith('/'):
                cover_url = f"{BASE_URL}{img_tag['src']}"
            else:
                cover_url = img_tag['src']

        desc_div = soup.find(class_='description')
        summary = ""
        if desc_div:
            for br in desc_div.find_all(['br']):
                br.replace_with('\n')
            
            summary = desc_div.get_text(separator=' ', strip=True)
            summary = re.sub(r' +', ' ', summary)
            summary = re.sub(r' \n ', '\n', summary)
            summary = re.sub(r'\n ', '\n', summary)
            summary = re.sub(r' \n', '\n', summary)
            summary = re.sub(r' ,', ',', summary)
            summary = re.sub(r' \.', '.', summary)
            
        if summary == "N/C": summary = ""
        
        genres, tags, staff, alternative_titles = [], [], [], []
        year, status = None, None
        # CORRECTION : On initialise les variables à None pour éviter un crash si non trouvées
        publisher, format_type, age_rating = None, None, None
        
        infos = soup.find(class_='infosFicheTop')
        if infos:
            li_elements = infos.find(class_='liste_infos').find_all('li') if infos.find(class_='liste_infos') else []
            for li in li_elements:
                text = li.get_text(separator=' ', strip=True)
                span = li.find('span')
                if not span: continue
                label = span.text.strip()
                
                if "Genre" in label:
                    genres = [a.text.strip() for a in li.find_all('a')]
                elif "Thème" in label:
                    tags = [a.text.strip() for a in li.find_all('a')]
                elif "Origine" in label:
                    year_tag = li.find(itemprop='datePublished')
                    if year_tag and year_tag.has_attr('content'):
                        try: year = int(year_tag['content'])
                        except: pass
                elif "Auteur" in label or "Scénariste" in label:
                    for a in li.find_all('a'):
                        staff.append({"role": "Story", "node": {"name": {"full": a.text.strip()}}})
                elif "Dessinateur" in label:
                    for a in li.find_all('a'):
                        staff.append({"role": "Art", "node": {"name": {"full": a.text.strip()}}})
                elif "Nb volumes VO" in label:
                    if "(Terminé)" in text: status = "FINISHED"
                    elif "(En cours)" in text: status = "RELEASING"
                    elif "(En attente)" in text: status = "HIATUS"
                    elif "(Abandonné)" in text: status = "CANCELLED"
                elif "Éditeur VF" in label:
                    a_tags = li.find_all('a')
                    if a_tags: publisher = a_tags[0].text.strip()
                elif "Type" in label:
                    a_tags = li.find_all('a')
                    if a_tags: format_type = a_tags[0].text.strip()
                elif "Âge conseillé" in label:
                    age_text = text.replace(label, "").strip()
                    if "18" in age_text or "averti" in age_text: age_rating = "pornographic"
                    elif "16" in age_text or "14" in age_text: age_rating = "suggestive"
                    else: age_rating = "safe"
                elif "Titre alternatif" in label or "Titre original" in label:
                    alt_text = text.replace(label, "").strip()
                    parts = [p.strip() for p in alt_text.split('/') if p.strip()]
                    for p in parts:
                        if p and p not in alternative_titles:
                            alternative_titles.append(p)
        
        return {
            'summary': summary,
            'cover_url': cover_url,
            'genres': genres,
            'tags': tags[:15] if tags else [],
            'year': year,
            'status': status,
            'staff': staff,
            'characters': [],
            'alternative_titles': alternative_titles,
            'publisher': publisher,
            'format': format_type,
            'age_rating': age_rating,
            'url': url
        }

    except Exception as e:
        print(f"[Erreur Parsing Nautiljon] {e}")
        return None