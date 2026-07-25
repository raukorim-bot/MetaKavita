import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from metadata_fetcher import fetch_metadata

# Activation des logs dans la console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION DU TEST ---
TEST_QUERY = "Perry Rhodan Neo"
LIBRARY_TYPE = "Book"
PROVIDERS = ["OPENLIBRARY", "HARDCOVER", "GOOGLEBOOKS"]
SMART_FUSION = True  # Activé pour tester la fusion croisée

# Métadonnées simulées
MOCK_EXISTING = {
    'isbn': None,
    'authors': ['Frank Borsch'],
    'publisher': None,
    'year': None,
    'genres': [],
    'localized_name': None
}

print("==================================================")
print(f"🧪 TEST DE FUSION INTELLIGENTE SUR : '{TEST_QUERY}'")
print(f"⚙️  Smart Fusion : {SMART_FUSION}")
print(f"🔍 Cascade activée : {' > '.join(PROVIDERS)}")
print("==================================================\n")

# Lancement de l'extraction avec fusion
master_data, used_providers = fetch_metadata(
    query=TEST_QUERY,
    providers_list=PROVIDERS,
    smart_fusion=SMART_FUSION,
    library_type=LIBRARY_TYPE,
    existing_metadata=MOCK_EXISTING
)

if master_data:
    base_provider = master_data.get('_provider_used', 'Inconnu')
    fusion_providers = master_data.get('_fusion_providers', [])

    print("\n" + "="*55)
    print("📊 RÉSULTAT FINAL DE LA FUSION (MASTER DATA)")
    print("="*55)
    print(f"🏆 Provider de Base       : {base_provider}")
    print(f"🧩 Providers de Fusion    : {', '.join(fusion_providers) if fusion_providers else 'Aucune fusion (Base 100% complète)'}")
    print(f"📌 Sources sollicitées    : {', '.join(used_providers)}")
    print("-" * 55)
    print(f"📖 Titre Principal        : {master_data.get('title')}")
    print(f"📚 Titres Alternatifs     : {master_data.get('alternative_titles')}")
    
    # Formatage propre des auteurs
    staff_list = master_data.get('staff', [])
    authors = [f"{s.get('node', {}).get('name', {}).get('full')} [{s.get('role')}]" for s in staff_list if isinstance(s, dict)]
    print(f"✍️  Auteurs / Staff        : {', '.join(authors) if authors else '❌ Aucun (Vide)'}")
    
    print(f"📅 Année de sortie        : {master_data.get('year') or '❌ Inconnue'}")
    print(f"🏢 Éditeur                : {master_data.get('publisher') or '❌ Inconnu'}")
    print(f"🏷️  ISBN                   : {master_data.get('isbn') or '❌ Aucun'}")
    print(f"🎭 Genres                 : {master_data.get('genres')}")
    print(f"🏷️  Tags / Thèmes          : {master_data.get('tags')}")
    print(f"🖼️  URL Couverture         : {master_data.get('cover_url') or '❌ Aucune'}")
    print(f"🌐 Liens Web accumulés    : {master_data.get('accumulated_links')}")
    print("-" * 55)
    print("📝 RÉSUMÉ FUSIONNÉ :")
    summary = master_data.get('summary', '')
    if summary:
        print(summary)
    else:
        print("❌ Aucun résumé trouvé.")
    print("="*55)
else:
    print("\n❌ Aucun résultat renvoyé par les scrapers.")