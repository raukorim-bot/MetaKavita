import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from metadata_fetcher import fetch_metadata
from scrapers import ScraperRegistry

# Activation des logs pour voir la cascade agir en direct
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

print("==================================================")
print("🧠 TEST DU MOTEUR CORE : CASCADE, FUSION & THREADS")
print("==================================================\n")

# --- TEST 1 : CASCADE & FUSION ---
print("--- 🧩 TEST 1 : CASCADE & FUSION INTELLIGENTE ---")
query = "Solo Leveling"
# On simule une cascade classique. MangaBaka est très rapide, mais Kitsu ou Anilist ont souvent plus de tags/données.
providers = ["MANGABAKA", "KITSU", "ANILIST"] 

print(f"🔍 Recherche de '{query}' avec la cascade : {' > '.join(providers)}")
print("⚙️  Option Smart Fusion : ACTIVÉE")

start_time = time.time()
result, used_providers = fetch_metadata(
    query=query,
    providers_list=providers,
    smart_fusion=True,
    library_type="Manga",
    existing_metadata={}
)
elapsed = time.time() - start_time

if result:
    print(f"\n✅ Terminé en {elapsed:.2f}s")
    print(f"🏆 Fournisseur de base  : {result.get('_provider_used')} (score: {result.get('_match_score', 'N/A')})")
    fusion = result.get('_fusion_providers', [])
    print(f"🧩 Fournisseurs fusion : {', '.join(fusion) if fusion else 'Aucun (Base complète à 100%)'}")
    print(f"📌 Sources sollicitées : {', '.join(used_providers)}")
    print(f"📚 Titre final         : {result.get('title')}")
    print(f"🏷️  Tags fusionnés       : {len(result.get('tags', []))} tags trouvés")
else:
    print("❌ Échec de la récupération.")

print("\n--------------------------------------------------\n")

# --- TEST 2 : MULTITHREADING COUVERTURES ---
print("--- ⚡ TEST 2 : MULTITHREADING COUVERTURES (Simulation app.py) ---")
query_cover = "Naruto"
# On prend 4 scrapers Manga au hasard pour le test
target_scrapers = ScraperRegistry.get_by_type("Manga")[:4] 
print(f"🖼️  Lancement de la recherche de couvertures en parallèle sur : {[s.id for s in target_scrapers]}")

def fetch_single_scraper(scraper):
    t0 = time.time()
    try:
        covers = scraper.fetch_covers(query_cover, library_type="Manga")
        t1 = time.time()
        return scraper.id, covers, t1 - t0
    except Exception as e:
        return scraper.id, [], 0

covers_found = []
start_time_threads = time.time()

# C'est ici que la magie du multithreading opère (exactement comme dans ton app.py)
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(fetch_single_scraper, s) for s in target_scrapers]
    for future in as_completed(futures):
        s_id, s_covers, duration = future.result()
        print(f"✔️  {s_id:<15} a répondu en {duration:.2f}s avec {len(s_covers)} images.")
        covers_found.extend(s_covers)

total_time = time.time() - start_time_threads

print(f"\n✅ Multithreading terminé en {total_time:.2f}s !")
print(f"💡 Remarque : Le temps total ({total_time:.2f}s) doit être proche du scraper le plus lent, et non de la somme des 4 (qui serait beaucoup plus longue).")
print(f"🖼️ Total des couvertures récupérées : {len(covers_found)}")
print("\n==================================================")