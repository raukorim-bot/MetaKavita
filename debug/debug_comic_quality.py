"""⚠️ SCRIPT À USAGE MANUEL — LE PLUS LOURD DU DOSSIER EN TRAFIC RÉEL.

Chaque cas de test est joué sur CHAQUE scraper Comic, Bédéthèque et Planète BD
en tête : c'est un produit cas × fournisseurs, soit des milliers de pages HTML
chez deux sites sans API qui bannissent l'IP.
"""
import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _live_network_guard import confirm_live_network

# Avant `from scrapers import ...`, qui synchronise déjà le catalogue core
# depuis GitHub : rien ne sort tant que personne n'a confirmé.
confirm_live_network(
    "debug_comic_quality.py",
    "tous les fournisseurs Comic, dont Bédéthèque et Planète BD",
    details="Produit cas de test × fournisseurs, chaque cas coûtant plusieurs pages HTML.",
)

import logging
import time
from scrapers import ScraperRegistry

# Log minimaliste
logging.basicConfig(level=logging.ERROR)

COMIC_TEST_CASES = [
    {
        "name": "1. US Series Majeure (Ongoing Run)",
        "query": "Saga",
        "desc": "Recherche d'une série Image Comics majeure sans sous-titre."
    },
    {
        "name": "2. Graphic Novel / Arc Spécifique",
        "query": "Watchmen",
        "desc": "Mini-série culte / Roman graphique complet."
    },
    {
        "name": "3. Franco-Belge Classique (Série)",
        "query": "Astérix",
        "desc": "Série BD européenne culte."
    },
    {
        "name": "4. Franco-Belge Album Spécifique",
        "query": "Astérix et Cléopâtre",
        "desc": "Album unique au sein d'une saga."
    },
    {
        "name": "5. Series avec Homonymes Multiples (US)",
        "query": "Batman",
        "desc": "Doit trouver une série Batman majeure (DC Comics)."
    },
    {
        "name": "6. BD Franco-Belge avec Sous-titre Long",
        "query": "Blacksad : Quelque part entre les ombres",
        "desc": "Recherche par titre d'album Franco-Belge."
    },
    {
        "name": "7. Titre court / Symboles",
        "query": "Y: The Last Man",
        "desc": "Gestion des deux-points et du nom court 'Y'."
    },
    {
        "name": "8. Mini-série / Marvel",
        "query": "Civil War",
        "desc": "Événement Marvel / Crossover."
    }
]

def audit_comics():
    comic_scrapers = ScraperRegistry.get_by_type("Comic")
    
    print("\n==========================================================================================")
    print(f"🦸 AUDIT DE QUALITÉ & STRESS-TEST COMICS & BDs ({len(comic_scrapers)} SCRAPERS)")
    print("==========================================================================================\n")

    for test in COMIC_TEST_CASES:
        print(f"📌 \033[1mTEST : {test['name']}\033[0m (Requête : '{test['query']}')")
        print(f"   💡 Objectif : {test['desc']}")
        print("-" * 95)
        print(f"{'SCRAPER':<20} | {'TITRE TROUVÉ':<28} | {'RÉSUMÉ':<8} | {'STAFF':<5} | {'ÉDITEUR':<14} | {'ANNÉE'}")
        print("-" * 95)

        for scraper in comic_scrapers:
            try:
                start = time.time()
                data = scraper.fetch(test['query'], library_type="Comic", is_id=False, existing_metadata={})
                elapsed = time.time() - start
                
                if not data:
                    print(f"{scraper.display_name[:20]:<20} | \033[91m❌ Aucun résultat\033[0m")
                    continue

                title = str(data.get('title', 'N/A'))[:27]
                summary_raw = str(data.get('summary', '') or '').strip()
                summary_len = len(summary_raw)
                
                if summary_len > 30:
                    summary_display = f"\033[92m{summary_len}car\033[0m"
                elif summary_len > 0:
                    summary_display = f"\033[93m{summary_len}car\033[0m"
                else:
                    summary_display = f"\033[91m0car (VIDE)\033[0m"
                
                staff_count = len(data.get('staff', []))
                pub = str(data.get('publisher') or 'N/A')[:14]
                year = str(data.get('year') or 'N/A')

                print(f"{scraper.display_name[:20]:<20} | {title:<28} | {summary_display:<17} | {staff_count:<5} | {pub:<14} | {year}")

            except Exception as e:
                print(f"{scraper.display_name[:20]:<20} | \033[91m💥 CRASH : {str(e)[:30]}\033[0m")

            # Pause anti-ban / rate limit
            time.sleep(getattr(scraper, 'rate_limit', 1.0))

        print("-" * 95 + "\n")

if __name__ == "__main__":
    audit_comics()