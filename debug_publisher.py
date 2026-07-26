import sys
import json
import requests

sys.path.append('.') 
from scrapers.mangaupdates import MangaUpdatesScraper
from scrapers.mangabaka import MangaBakaScraper

HEADERS = {
    "User-Agent": "MetaKavita-Fetcher/1.5",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def dump_api_mangaupdates(series_id="33"): 
    print("\n" + "="*60)
    print(f"📡 DUMP BRUT : API MANGAUPDATES (ID: {series_id})")
    print("="*60)
    url = f"https://api.mangaupdates.com/v1/series/{series_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        data = res.json()
        pubs = data.get("publishers", [])
        print("📥 Contenu exact du tableau 'publishers' renvoyé par l'API :")
        print(json.dumps(pubs, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Erreur HTTP: {e}")

def dump_api_mangabaka(query="Naruto"):
    print("\n" + "="*60)
    print(f"📡 DUMP BRUT : API MANGABAKA (Recherche: {query})")
    print("="*60)
    url = "https://api.mangabaka.org/v2/series/search"
    try:
        res = requests.get(url, params={"q": query}, headers=HEADERS, timeout=10)
        data = res.json()
        results = data.get('data') if 'data' in data else data
        if isinstance(results, list) and len(results) > 0:
            best = results[0]
            pubs = best.get("publishers", [])
            titre = best.get('title') or best.get('name')
            print(f"📌 Titre analysé : {titre}")
            print("📥 Contenu exact du tableau 'publishers' renvoyé par l'API :")
            print(json.dumps(pubs, indent=2, ensure_ascii=False))
        else:
            print("Aucun résultat.")
    except Exception as e:
        print(f"Erreur HTTP: {e}")

def test_scraper(ScraperClass, query, is_id=False):
    scraper = ScraperClass()
    print("\n" + "-"*60)
    print(f"⚙️  MOTEUR D'EXTRACTION : {scraper.id}")
    print("-"*60)
    
    # Simulation de la Préférence LOCALIZED (VF/VA)
    meta_loc = {"publisher_pref": "LOCALIZED"}
    res_loc = scraper.fetch(query, is_id=is_id, existing_metadata=meta_loc)
    
    if not res_loc:
        print(f"❌ Le scraper n'a rien trouvé pour '{query}'.")
        return

    print(f"✅ Œuvre formatée : {res_loc.get('title')}")
    print(f"   -> 🏢 Éditeur extrait (Test LOCALIZED) : {res_loc.get('publisher')}")
    print(f"   -> 📦 Objet qui sera envoyé à Kavita   : {json.dumps({'id': 0, 'name': res_loc.get('publisher')}, ensure_ascii=False)}")
    
    # Simulation de la Préférence ORIGINAL (VO)
    meta_orig = {"publisher_pref": "ORIGINAL"}
    res_orig = scraper.fetch(query, is_id=is_id, existing_metadata=meta_orig)
    print(f"   -> 🎌 Éditeur extrait (Test ORIGINAL)  : {res_orig.get('publisher')}")

if __name__ == '__main__':
    print("\n🚀 LANCEMENT DE L'AUDIT DES ÉDITEURS V2...")
    
    dump_api_mangaupdates("33")
    test_scraper(MangaUpdatesScraper, "33", is_id=True)
    
    dump_api_mangabaka("Naruto")
    test_scraper(MangaBakaScraper, "Naruto", is_id=False)
    
    print("\n" + "="*60 + "\n")