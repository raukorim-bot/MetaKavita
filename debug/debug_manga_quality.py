"""⚠️ SCRIPT À USAGE MANUEL — INTERROGE POUR DE VRAI TOUS LES SCRAPERS MANGA.

Produit cas de test × fournisseurs : quelques centaines d'appels sortants.
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
    "debug_manga_quality.py",
    "tous les fournisseurs Manga installés",
    details="Produit cas de test × fournisseurs.",
)

import logging
import time
from scrapers import ScraperRegistry

# Log minimaliste
logging.basicConfig(level=logging.ERROR)

MANGA_TEST_CASES = [
    {
        "name": "1. Manhwa / Webtoon (Sens de lecture)",
        "query": "Solo Leveling",
        "expect_format": "webtoon",
        "desc": "Doit détecter le format Webtoon / Vertical."
    },
    {
        "name": "2. Titre chiffré (Nettoyeur Regex)",
        "query": "20th Century Boys",
        "expect_title": "20th Century Boys",
        "desc": "Ne doit PAS supprimer '20th' en croyant que c'est un numéro de dossier."
    },
    {
        "name": "3. Titre Japonais / Romaji",
        "query": "Shingeki no Kyojin",
        "desc": "Doit trouver la fiche même sous son titre Romaji."
    },
    {
        "name": "4. Éditeur VF & Contenu Français",
        "query": "Spy x Family",
        "expect_publisher": ["Kurokawa", "Shueisha"],
        "desc": "Test d'extraction de l'éditeur VF (Pika, Kurokawa...)."
    },
    {
        "name": "5. Caractères Spéciaux & Long Titre",
        "query": "Re:Zero -Starting Life in Another World-",
        "desc": "Gestion des deux-points et des tirets d'encadrement."
    },
    {
        "name": "6. Risque de Spin-off (Série Principale)",
        "query": "My Hero Academia",
        "reject_title": "Vigilantes",
        "desc": "Ne doit PAS renvoyer 'My Hero Academia: Vigilantes'."
    },
    {
        "name": "7. Classification d'Âge (Ecchi / Adulte)",
        "query": "Rosen Garten Saga",
        "expect_rating": ["suggestive", "pornographic", "erotica", "ecchi"],
        "desc": "Test de détection de la classification d'âge."
    },
    {
        "name": "8. Oneshot / Œuvre courte",
        "query": "Look Back",
        "desc": "Doit trouver le oneshot sans l'écarter comme une fausse série."
    }
]

def audit_mangas():
    manga_scrapers = ScraperRegistry.get_by_type("Manga")
    
    print("\n==========================================================================================")
    print(f"⛩️  AUDIT DE QUALITÉ & STRESS-TEST MANGAS ({len(manga_scrapers)} SCRAPERS)")
    print("==========================================================================================\n")

    for test in MANGA_TEST_CASES:
        print(f"📌 \033[1mTEST : {test['name']}\033[0m (Requête : '{test['query']}')")
        print(f"   💡 Objectif : {test['desc']}")
        print("-" * 90)
        print(f"{'SCRAPER':<20} | {'TITRE TROUVÉ':<25} | {'FORMAT':<8} | {'AUTEURS':<5} | {'TAGS':<5} | {'EDITEUR':<12} | {'IDs'}")
        print("-" * 90)

        for scraper in manga_scrapers:
            try:
                start = time.time()
                data = scraper.fetch(test['query'], library_type="Manga", is_id=False, existing_metadata={})
                elapsed = time.time() - start
                
                if not data:
                    print(f"{scraper.display_name[:20]:<20} | \033[91m❌ Aucun résultat\033[0m")
                    continue

                title = str(data.get('title', 'N/A'))[:24]
                summary_ok = "📖" if data.get('summary') and len(data.get('summary')) > 20 else "❌"
                cover_ok = "🖼️" if data.get('cover_url') else "❌"
                
                staff_count = len(data.get('staff', []))
                tags_count = len(data.get('tags', []) + data.get('genres', []))
                
                fmt = str(data.get('format', 'N/A')).upper()
                fmt_display = "\033[92mWEBTOON\033[0m" if "WEBTOON" in fmt or "KR" in fmt or "MANHWA" in fmt else ("MANGA" if "MANGA" in fmt or "JP" in fmt else fmt[:8])
                
                pub = str(data.get('publisher') or 'N/A')[:12]
                
                ids = []
                if data.get('anilist_id'): ids.append(f"AL:{data['anilist_id']}")
                if data.get('mal_id'): ids.append(f"MAL:{data['mal_id']}")
                if data.get('mangabaka_id'): ids.append(f"MB:{data['mangabaka_id']}")
                ids_str = " ".join(ids) if ids else "-"

                # Alerte visuelle si le titre contient le spin-off interdit
                title_display = title
                if test.get("reject_title") and test["reject_title"].lower() in title.lower():
                    title_display = f"\033[91m{title}\033[0m"

                print(f"{scraper.display_name[:20]:<20} | {title_display:<25} | {fmt_display:<8} | {staff_count:<5} | {tags_count:<5} | {pub:<12} | {ids_str}")

            except Exception as e:
                print(f"{scraper.display_name[:20]:<20} | \033[91m💥 CRASH : {str(e)[:30]}\033[0m")

            # Pause anti-ban rate limit
            time.sleep(scraper.rate_limit)

        print("-" * 90 + "\n")

if __name__ == "__main__":
    audit_mangas()