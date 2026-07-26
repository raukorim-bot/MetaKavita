import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import time
from metadata_fetcher import fetch_metadata

# Activation des logs pour voir la cascade agir
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

print("==================================================")
print("📚 TEST DES CASCADES : COMICS & BOOKS")
print("==================================================\n")

# --- TEST 1 : COMICS (BD / Comics) ---
print("--- 🦸 TEST 1 : CASCADE COMICS ---")
query_comic = "Blacksad"
# Cascade hybride : Franco-belge -> US -> Généraliste
providers_comic = ["BEDETHEQUE", "COMICVINE", "GOOGLEBOOKS"] 

print(f"🔍 Recherche de '{query_comic}' avec la cascade : {' > '.join(providers_comic)}")
print("⚙️  Option Smart Fusion : ACTIVÉE")

start_time = time.time()
res_comic, used_comic = fetch_metadata(
    query=query_comic,
    providers_list=providers_comic,
    smart_fusion=True,
    library_type="Comic",
    existing_metadata={}
)
elapsed_comic = time.time() - start_time

if res_comic:
    print(f"\n✅ Comic terminé en {elapsed_comic:.2f}s")
    print(f"🏆 Fournisseur de base  : {res_comic.get('_provider_used')}")
    fusion_c = res_comic.get('_fusion_providers', [])
    print(f"🧩 Fournisseurs fusion : {', '.join(fusion_c) if fusion_c else 'Aucun (Base 100% complète)'}")
    print(f"📌 Sources sollicitées : {', '.join(used_comic)}")
    print(f"📚 Titre final         : {res_comic.get('title')}")
    print(f"👥 Auteurs/Staff       : {len(res_comic.get('staff', []))} trouvés")
else:
    print("❌ Échec de la récupération Comic.")

print("\n--------------------------------------------------\n")

# --- TEST 2 : BOOKS (Romans / Livres) ---
print("--- 📖 TEST 2 : CASCADE BOOKS ---")
query_book = "Le Seigneur des Anneaux"
# Cascade littérature : OpenLibrary -> GoogleBooks -> Hardcover
providers_book = ["OPENLIBRARY", "GOOGLEBOOKS", "HARDCOVER"]

print(f"🔍 Recherche de '{query_book}' avec la cascade : {' > '.join(providers_book)}")
print("⚙️  Option Smart Fusion : ACTIVÉE")

start_time = time.time()
res_book, used_book = fetch_metadata(
    query=query_book,
    providers_list=providers_book,
    smart_fusion=True,
    library_type="Book",
    existing_metadata={}
)
elapsed_book = time.time() - start_time

if res_book:
    print(f"\n✅ Book terminé en {elapsed_book:.2f}s")
    print(f"🏆 Fournisseur de base  : {res_book.get('_provider_used')}")
    fusion_b = res_book.get('_fusion_providers', [])
    print(f"🧩 Fournisseurs fusion : {', '.join(fusion_b) if fusion_b else 'Aucun (Base 100% complète)'}")
    print(f"📌 Sources sollicitées : {', '.join(used_book)}")
    print(f"📚 Titre final         : {res_book.get('title')}")
    print(f"🏷️  ISBN trouvé          : {res_book.get('isbn') or 'Non'}")
else:
    print("❌ Échec de la récupération Book.")

print("\n==================================================")