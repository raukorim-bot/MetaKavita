import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
from curl_cffi import requests
from config_manager import load_config

# --- CONFIGURATION ---
# ⚠️ Ne JAMAIS coller de jeton en dur ici (voir CODE_REVIEW.md section 0 : un
# ancien jeton personnel Hardcover a fui dans ce fichier puis a été révoqué).
# Le jeton est lu depuis data/config.json (clé déjà utilisée par
# scrapers/hardcover.py) ou, à défaut, depuis la variable d'environnement
# HARDCOVER_API_KEY.
API_TOKEN = load_config().get("HARDCOVER_API_KEY", "").strip() or os.getenv("HARDCOVER_API_KEY", "").strip()

# Le titre du livre que tu cherches
SEARCH_QUERY = "Choses dites"

def run_test():
    print(f"🔍 Lancement de la recherche Hardcover pour : '{SEARCH_QUERY}'\n")

    auth_token = f"Bearer {API_TOKEN}" if not API_TOKEN.startswith("Bearer") else API_TOKEN

    headers = {
        "Authorization": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://hardcover.app",
        "Referer": "https://hardcover.app/"
    }

    graphql_url = "https://api.hardcover.app/v1/graphql"
    session = requests.Session(impersonate="chrome110")

    # Requête de recherche Typesense (identique à la documentation officielle)
    gql_search = """
    query searchBooks($title: String!) {
      search(
          query: $title, 
          query_type: "Book", 
          per_page: 5, 
          page: 1
      ) {
          results
      }
    }
    """

    payload = {
        "query": gql_search,
        "variables": {"title": SEARCH_QUERY}
    }

    try:
        print("⏳ Envoi de la requête POST vers l'API GraphQL...")
        res = session.post(graphql_url, json=payload, headers=headers, timeout=15)
        
        print(f"📊 Statut HTTP : {res.status_code}")
        
        if res.status_code != 200:
            print("\n❌ ERREUR HTTP:")
            print(res.text)
            return

        data = res.json()
        
        print("\n✅ RÉPONSE BRUTE (JSON) :")
        print("-" * 50)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("-" * 50)

    except Exception as e:
        print(f"\n💥 CRASH EXCEPTION : {e}")

if __name__ == "__main__":
    if not API_TOKEN:
        print("❌ ERREUR : Clé HARDCOVER_API_KEY manquante. Configurez-la dans data/config.json")
        print("   (via l'UI MetaKavita) ou exportez-la en variable d'environnement HARDCOVER_API_KEY.")
    else:
        run_test()