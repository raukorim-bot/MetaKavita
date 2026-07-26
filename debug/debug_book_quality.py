import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import time
from scrapers import ScraperRegistry

# Log minimaliste
logging.basicConfig(level=logging.ERROR)

BOOK_TEST_CASES = [
    {
        "name": "1. Sci-Fi Classique Mondial",
        "query": "Dune",
        "desc": "Chef-d'œuvre de Frank Herbert."
    },
    {
        "name": "2. Saga / Série Fleuve de Fantasy",
        "query": "Le Seigneur des Anneaux",
        "desc": "Ancrage sur la saga complète (J.R.R. Tolkien)."
    },
    {
        "name": "3. Littérature Classique Française",
        "query": "Le Comte de Monte-Cristo",
        "desc": "Classique du domaine public (Alexandre Dumas)."
    },
    {
        "name": "4. Bestseller Français Contemporain",
        "query": "L'Anomalie",
        "desc": "Prix Goncourt (Hervé Le Tellier)."
    },
    {
        "name": "5. Light Novel Japonais (Format Ebook Kavita)",
        "query": "Sword Art Online",
        "desc": "Light Novel japonais (Reki Kawahara)."
    },
    {
        "name": "6. Nom de Fichier EPUB ('Titre - Auteur')",
        "query": "Sapiens - Yuval Noah Harari",
        "desc": "Nettoyage du séparateur ' - Auteur' typique des EPUBs."
    },
    {
        "name": "7. Titre Ultra-Court (2 Lettres)",
        "query": "It",
        "desc": "Roman de Stephen King ('Ça')."
    },
    {
        "name": "8. SF Contemporaine Traduite",
        "query": "Le Problème à trois corps",
        "desc": "Roman chinois de Cixin Liu traduit en français."
    }
]

def audit_books():
    book_scrapers = ScraperRegistry.get_by_type("Book")
    
    print("\n==========================================================================================")
    print(f"📖 AUDIT DE QUALITÉ & STRESS-TEST BOOKS & LITTÉRATURE ({len(book_scrapers)} SCRAPERS)")
    print("==========================================================================================\n")

    for test in BOOK_TEST_CASES:
        print(f"📌 \033[1mTEST : {test['name']}\033[0m (Requête : '{test['query']}')")
        print(f"   💡 Objectif : {test['desc']}")
        print("-" * 95)
        print(f"{'SCRAPER':<20} | {'TITRE TROUVÉ':<26} | {'RÉSUMÉ':<8} | {'STAFF':<5} | {'ISBN':<14} | {'ÉDITEUR'}")
        print("-" * 95)

        for scraper in book_scrapers:
            try:
                start = time.time()
                data = scraper.fetch(test['query'], library_type="Book", is_id=False, existing_metadata={})
                elapsed = time.time() - start
                
                if not data:
                    print(f"{scraper.display_name[:20]:<20} | \033[91m❌ Aucun résultat\033[0m")
                    continue

                title = str(data.get('title', 'N/A'))[:25]
                summary_raw = str(data.get('summary', '') or '').strip()
                summary_len = len(summary_raw)
                
                if summary_len > 30:
                    summary_display = f"\033[92m{summary_len}car\033[0m"
                elif summary_len > 0:
                    summary_display = f"\033[93m{summary_len}car\033[0m"
                else:
                    summary_display = f"\033[91m0car (VIDE)\033[0m"
                
                staff_count = len(data.get('staff', []))
                isbn = str(data.get('isbn') or 'N/A')[:14]
                pub = str(data.get('publisher') or 'N/A')[:12]

                print(f"{scraper.display_name[:20]:<20} | {title:<26} | {summary_display:<17} | {staff_count:<5} | {isbn:<14} | {pub}")

            except Exception as e:
                print(f"{scraper.display_name[:20]:<20} | \033[91m💥 CRASH : {str(e)[:30]}\033[0m")

            time.sleep(getattr(scraper, 'rate_limit', 1.0))

        print("-" * 95 + "\n")

if __name__ == "__main__":
    audit_books()