import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
from curl_cffi import requests

# --- CONFIGURATION ---
# Colle ton jeton ici (avec ou sans le "Bearer ", le script gère)
API_TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJIYXJkY292ZXIiLCJ2ZXJzaW9uIjoiOCIsImp0aSI6IjdjNDY1NzhhLWI0NjUtNDA5YS1hOTk5LTJiY2I2MDEzZjM1MiIsImFwcGxpY2F0aW9uSWQiOjIsInN1YiI6IjEzNDE4NiIsImF1ZCI6IjEiLCJpZCI6IjEzNDE4NiIsImxvZ2dlZEluIjp0cnVlLCJpYXQiOjE3ODQ4MDE2NzEsImV4cCI6MTgxNjMzNzY3MSwiaHR0cHM6Ly9oYXN1cmEuaW8vand0L2NsYWltcyI6eyJ4LWhhc3VyYS1hbGxvd2VkLXJvbGVzIjpbInVzZXIiXSwieC1oYXN1cmEtZGVmYXVsdC1yb2xlIjoidXNlciIsIngtaGFzdXJhLXJvbGUiOiJ1c2VyIiwiWC1oYXN1cmEtdXNlci1pZCI6IjEzNDE4NiJ9LCJ1c2VyIjp7ImlkIjoxMzQxODZ9fQ.JCWyUflSp9oc9sno9jBE3OLV4jJWFNK7jXVwsDQunIQ" 

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
    if API_TOKEN == "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJI...":
        print("⚠️ N'oublie pas de remplacer la variable API_TOKEN par ton vrai jeton dans le script !")
    else:
        run_test()