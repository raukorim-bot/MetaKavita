"""⚠️ SCRIPT À USAGE MANUEL — SE CONNECTE AU VRAI KAVITA PUIS AUX FOURNISSEURS.

Tout s'exécute au chargement du module : lancer le fichier suffit à partir.
"""
import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _live_network_guard import confirm_live_network

confirm_live_network(
    "debug_deep.py",
    "le serveur Kavita configuré, puis les fournisseurs de la cascade",
)

import logging
from config_manager import load_config
from kavita_api import KavitaAPI
from metadata_fetcher import fetch_metadata

# Activation des logs dans la console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

config = load_config()
kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

print("🔌 Connexion à Kavita...")
if not kavita.authenticate():
    print("❌ Échec d'authentification Kavita. Vérifie ton config.json")
    exit(1)

print("✅ Authentification réussie !")

# Récupération de la première série disponible
all_series = kavita.get_all_series()
if not all_series:
    print("⚠️ Aucune série trouvée dans Kavita.")
    exit(0)

test_series = all_series[0]
series_id = test_series['id']
series_name = test_series['name']

print(f"\n🧪 Test sur la série : '{series_name}' (ID: {series_id})")

# 1. Test d'extraction des métadonnées profondes
deep_meta = kavita.get_series_deep_metadata(series_id)
print(f"📊 Deep Metadata extraites de Kavita : {deep_meta}")

# 2. Test du scraping
lib_type = kavita.get_library_type_for_series(series_id)
providers = ["GOOGLEBOOKS", "OPENLIBRARY", "HARDCOVER"] if lib_type in ["Book", "Comic"] else ["MANGABAKA", "ANILIST"]

print(f"🔍 Lancement du scraping (Type: {lib_type}) avec providers: {providers}")
result, used = fetch_metadata(
    query=series_name,
    providers_list=providers,
    library_type=lib_type,
    existing_metadata=deep_meta
)

if result:
    print(f"\n✅ Succès ! Source utilisée : {used}")
    print(f"   Titre trouvé : {result.get('title')}")
    print(f"   Résumé : {result.get('summary', '')[:120]}...")
else:
    print("\n⚠️ Aucun résultat renvoyé par les scrapers.")