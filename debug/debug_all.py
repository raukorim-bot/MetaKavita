import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import time
from config_manager import load_config
from scrapers import ScraperRegistry

# On réduit les logs de base pour ne pas polluer l'affichage du rapport
logging.basicConfig(level=logging.ERROR, format='%(levelname)s - %(message)s')

# Définition des tests selon le type de bibliothèque supporté par le scraper
TEST_CASES = {
    "Manga": {
        "query": "Berserk", 
        "context": {"authors": ["Kentaro Miura"], "isbn": None, "year": 1989}
    },
    "Comic": {
        "query": "Lanfeust de Troy", 
        "context": {"authors": ["Arleston"], "isbn": None, "year": 1994}
    },
    "Book": {
        "query": "Dune", 
        "context": {"authors": ["Frank Herbert"], "isbn": None, "year": 1965}
    }
}

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def run_diagnostics():
    config = load_config()
    scrapers = ScraperRegistry.get_all()
    
    print(f"\n{Colors.BOLD}================================================================={Colors.RESET}")
    print(f"{Colors.BOLD}🚀 DIAGNOSTIC GLOBAL META-KAVITA V1.5.6 ({len(scrapers)} SCRAPERS){Colors.RESET}")
    print(f"{Colors.BOLD}================================================================={Colors.RESET}\n")

    report = []
    
    for scraper in scrapers:
        print(f"⏳ Test en cours sur : {Colors.CYAN}{scraper.display_name}{Colors.RESET}...", end="", flush=True)
        
        # 1. Vérification des Clés API
        if getattr(scraper, 'needs_api_key', False):
            key_name = f"{scraper.id}_API_KEY"
            if not config.get(key_name):
                print(f"\r⚠️  {Colors.YELLOW}[IGNORÉ]{Colors.RESET} {scraper.display_name:<30} (Clé API manquante)")
                report.append((scraper.display_name, f"{Colors.YELLOW}IGNORÉ{Colors.RESET}", "Clé API non configurée"))
                continue
                
        # 2. Détermination du type de test approprié
        lib_type = "Manga"
        if "Manga" in scraper.supported_types: lib_type = "Manga"
        elif "Comic" in scraper.supported_types: lib_type = "Comic"
        elif "Book" in scraper.supported_types: lib_type = "Book"
        
        test_case = TEST_CASES[lib_type]
        
        # 3. Exécution du Fetch
        start_time = time.time()
        try:
            res = scraper.fetch(
                query=test_case["query"], 
                library_type=lib_type, 
                is_id=False, 
                existing_metadata=test_case["context"]
            )
            elapsed = time.time() - start_time
            
            if res is None:
                print(f"\r❌ {Colors.RED}[ÉCHEC]{Colors.RESET}  {scraper.display_name:<30} (Renvoie None)")
                report.append((scraper.display_name, f"{Colors.RED}ÉCHEC{Colors.RESET}", f"Aucun match pour '{test_case['query']}'"))
            elif isinstance(res, list):
                print(f"\r❌ {Colors.RED}[CRASH]{Colors.RESET}  {scraper.display_name:<30} (Renvoie une LISTE !)")
                report.append((scraper.display_name, f"{Colors.RED}CRASH API{Colors.RESET}", "Renvoie list au lieu de dict (Bug de signature)"))
            elif isinstance(res, dict):
                title = res.get('title', 'Titre Inconnu')
                summary = res.get('summary', '')[:20].replace('\n', ' ') + "..."
                print(f"\r✅ {Colors.GREEN}[SUCCÈS]{Colors.RESET} {scraper.display_name:<30} ({elapsed:.1f}s)")
                report.append((scraper.display_name, f"{Colors.GREEN}SUCCÈS{Colors.RESET}", f"Trouvé: {title} | Résumé: {summary}"))
            else:
                print(f"\r❌ {Colors.RED}[ERREUR]{Colors.RESET} {scraper.display_name:<30} (Type inattendu)")
                report.append((scraper.display_name, f"{Colors.RED}ERREUR TYP.{Colors.RESET}", f"Type retourné : {type(res)}"))
                
        except Exception as e:
            print(f"\r💥 {Colors.RED}[CRASH]{Colors.RESET}  {scraper.display_name:<30} (Exception Python)")
            report.append((scraper.display_name, f"{Colors.RED}EXCEPTION{Colors.RESET}", str(e)[:50]))
            
        time.sleep(1) # Pause de courtoisie pour ne pas se faire ban IP
        
    # --- GÉNÉRATION DU RAPPORT FINAL ---
    print(f"\n\n{Colors.BOLD}📋 RAPPORT RÉCAPITULATIF : {Colors.RESET}")
    print("-" * 90)
    print(f"{'FOURNISSEUR':<35} | {'STATUT':<18} | {'DÉTAIL / RÉSULTAT'}")
    print("-" * 90)
    
    success_count = 0
    fail_count = 0
    for name, status, detail in report:
        if "SUCCÈS" in status: success_count += 1
        elif "IGNORÉ" not in status: fail_count += 1
        print(f"{name:<35} | {status:<18} | {detail}")
        
    print("-" * 90)
    print(f"📊 Bilan : {Colors.GREEN}{success_count} Fonctionnels{Colors.RESET} | {Colors.RED}{fail_count} En Échec{Colors.RESET}")
    print("=================================================================\n")

if __name__ == "__main__":
    run_diagnostics()