import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from config_manager import load_config
from scrapers.bedetheque import BedethequeScraper
from scrapers.comicvine import ComicVineScraper

# Activation des logs pour voir ce qui se passe
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(message)s')

print("==================================================")
print("🧪 TEST DE DEBUG AUTONOME : SCRAPERS COMICS (v1.5.6)")
print("==================================================\n")

# Simulation du nouveau contexte Kavita (Deep Extraction v1.5.5)
mock_existing = {
    'isbn': None,
    'authors': ['Arleston'], 
    'publisher': None,
    'year': None,
    'genres': [],
    'localized_name': None
}

# 1. TEST BÉDÉTHÈQUE
print("--- 🦸 TEST BÉDÉTHÈQUE ---")
bd_scraper = BedethequeScraper()
try:
    print(f"Lancement de fetch() sur '{bd_scraper.display_name}'...")
    res_bd = bd_scraper.fetch("Lanfeust de Troy", library_type="Comic", is_id=False, existing_metadata=mock_existing)
    
    print(f"Type de retour obtenu : {type(res_bd)}")
    
    if isinstance(res_bd, list):
        print("🚨 BINGO ! Le fetch() a retourné une LISTE (les couvertures) au lieu d'un DICTIONNAIRE !")
    elif isinstance(res_bd, dict):
        print(f"✅ Succès ! Résumé : {res_bd.get('summary', 'Aucun')[:50]}...")
    else:
        print(f"⚠️ Retour inattendu : {res_bd}")

except Exception as e:
    logging.exception(f"💥 Crash direct sur Bédéthèque : {e}")

print("\n--------------------------------------------------\n")

# 2. TEST COMICVINE
print("--- 🦇 TEST COMICVINE ---")
cv_scraper = ComicVineScraper()
config = load_config()

if not config.get("COMICVINE_API_KEY"):
    print("⚠️ Clé API ComicVine manquante dans config.json. Le test risque d'échouer proprement.")

try:
    print(f"Lancement de fetch() sur '{cv_scraper.display_name}'...")
    res_cv = cv_scraper.fetch("Batman Hush", library_type="Comic", is_id=False, existing_metadata=mock_existing)
    
    print(f"Type de retour obtenu : {type(res_cv)}")
    
    if isinstance(res_cv, dict):
        print(f"✅ Succès ! Résumé : {res_cv.get('summary', 'Aucun')[:50]}...")
    else:
        print(f"⚠️ Retour inattendu : {res_cv}")

except Exception as e:
    logging.exception(f"💥 Crash direct sur ComicVine : {e}")