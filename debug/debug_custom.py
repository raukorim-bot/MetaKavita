import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from metadata_fetcher import fetch_metadata

# Logs activés dans la console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION DU TEST ---
TEST_QUERY = "Berserk"
LIBRARY_TYPE = "Manga"
PROVIDERS = ["MANGABAKA", "KITSU", "ANILIST"]

# Simulation de métadonnées Kavita si tu en connais (ex: l'auteur)
MOCK_EXISTING = {
    'isbn': None,
    'authors': ['Frank Borsch'],  # Un des auteurs principaux de Perry Rhodan Neo
    'publisher': None,
    'year': None,
    'genres': [],
    'localized_name': None
}

print(f"🧪 Test de debug autonome sur la requête : '{TEST_QUERY}'")
print(f"📚 Type de bibliothèque : {LIBRARY_TYPE}\n")

# Appel direct du fetcher sans passer par Kavita
result, used = fetch_metadata(
    query=TEST_QUERY,
    providers_list=PROVIDERS,
    library_type=LIBRARY_TYPE,
    existing_metadata=MOCK_EXISTING
)

if result:
    print(f"\n✅ MATCH REUSSI via {used} !")
    print(f"   Titre retenu : {result.get('title')}")
    print(f"   Auteurs : {[s['node']['name']['full'] for s in result.get('staff', [])]}")
    print(f"   Année : {result.get('year')}")
    print(f"   Résumé : {result.get('summary', '')[:150]}...")
else:
    print("\n❌ ÉCHEC : Aucun résultat n'a franchi le seuil de 60%.")