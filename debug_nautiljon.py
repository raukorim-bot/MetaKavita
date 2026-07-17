from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import sys

def run_debug(query):
    base_url = "https://www.nautiljon.com/mangas/"
    print("="*60)
    print(f"🔍 DEBUG NAUTILJON (Contournement du Jeton ST) : '{query}'")
    print("="*60)
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.nautiljon.com/", 
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1"
    }

    # On utilise une Session pour conserver les cookies entre les deux requêtes
    session = requests.Session(impersonate="safari15_5")
    session.headers.update(headers)

    try:
        # ---------------------------------------------------------
        # ETAPE 1 : Récupérer le jeton de recherche (Token 'st')
        # ---------------------------------------------------------
        print("[1] Chargement de la page de base pour extraire le jeton 'st'...")
        res_init = session.get(base_url, timeout=15)
        
        soup_init = BeautifulSoup(res_init.text, 'html.parser')
        st_input = soup_init.find('input', {'name': 'st'})
        
        if not st_input or not st_input.get('value'):
            print("  ❌ ÉCHEC : Impossible de trouver le jeton 'st' sur la page d'accueil.")
            return
            
        search_token = st_input['value']
        print(f"  ✅ SUCCÈS : Jeton extrait -> {search_token}")

        # ---------------------------------------------------------
        # ETAPE 2 : Lancer la vraie recherche avec le jeton
        # ---------------------------------------------------------
        print(f"\n[2] Lancement de la recherche avec le paramètre q='{query}' & st='{search_token}'...")
        params = {
            "q": query,
            "st": search_token
        }
        
        res_search = session.get(base_url, params=params, timeout=15)
        print(f"  -> STATUS HTTP : {res_search.status_code}")
        
        soup_search = BeautifulSoup(res_search.text, 'html.parser')
        
        # Vérification des erreurs
        error_div = soup_search.find('div', id='errors')
        if error_div:
            print(f"  🚨 ERREUR NAUTILJON DÉTECTÉE : {error_div.get_text(strip=True)}")
            return

        # Recherche du fameux tableau
        search_table = soup_search.find('table', class_='search')
        
        if search_table:
            print("  ✅ SUCCÈS : Le tableau HTML '.search' a bien été trouvé avec les résultats !")
            a_tag = search_table.find('a', href=re.compile(r'^/mangas/.*\.html$'))
            if a_tag:
                print(f"  🔗 LIEN TROUVÉ : https://www.nautiljon.com{a_tag['href']}")
            else:
                print("  ❌ Aucun lien de manga valide à l'intérieur du tableau.")
        else:
            print("  ❌ ÉCHEC : Le tableau '.search' est introuvable. Redirection ou changement de code HTML ?")

    except Exception as e:
        print(f"\n[!] CRASH RÉSEAU : Erreur : {e}")

if __name__ == "__main__":
    test_query = "jujutsu kaisen"
    if len(sys.argv) > 1:
        test_query = " ".join(sys.argv[1:])
    
    run_debug(test_query)