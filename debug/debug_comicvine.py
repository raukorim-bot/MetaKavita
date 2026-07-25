import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import logging
import requests
from config_manager import load_config

# Activation des logs HTTP bruts
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

config = load_config()
api_key = config.get("COMICVINE_API_KEY", "").strip()

if not api_key:
    print("❌ ERREUR : Clé COMICVINE_API_KEY manquante dans data/config.json !")
    exit(1)

headers = {"User-Agent": "MetaKavita-Debug/1.5", "Accept": "application/json"}

TEST_QUERIES = ["Batman", "Y: The Last Man"]

def inspect_comicvine(query):
    print(f"\n=================================================================")
    print(f"🔍 INSPECTION DE L'API COMICVINE POUR : '{query}'")
    print(f"=================================================================\n")

    # --- TEST 1 : ENDPOINT /search/ ---
    print(f"📡 --- TEST ENDPOINT A : /search/ (query='{query}') ---")
    url_search = "https://comicvine.gamespot.com/api/search/"
    params_search = {
        "api_key": api_key,
        "format": "json",
        "resources": "volume",
        "query": query,
        "limit": 10,
        "field_list": "id,name,start_year,count_of_issues,publisher,deck,description,first_issue"
    }

    try:
        res_s = requests.get(url_search, params=params_search, headers=headers, timeout=12)
        print(f"HTTP Status : {res_s.status_code}")
        if res_s.status_code == 200:
            results_s = res_s.json().get("results", [])
            print(f"Nombre de résultats renvoyés : {len(results_s)}\n")
            for idx, item in enumerate(results_s):
                pub = item.get("publisher") or {}
                pub_name = pub.get("name") if isinstance(pub, dict) else "AUCUN"
                print(f"  [{idx+1}] ID: 4050-{item.get('id')} | Titre: '{item.get('name')}' ({item.get('start_year')})")
                print(f"      - Éditeur: {pub_name}")
                print(f"      - Nombre de numéros (count_of_issues): {item.get('count_of_issues')}")
                print(f"      - Présence de résumé (deck/desc): {bool(item.get('deck') or item.get('description'))}")
                print(f"      - First Issue ID: {item.get('first_issue', {}).get('id') if isinstance(item.get('first_issue'), dict) else None}")
                print()
    except Exception as e:
        print(f"💥 Erreur /search/ : {e}")

    print("-" * 65 + "\n")

    # --- TEST 2 : ENDPOINT /volumes/ (Filter Direct) ---
    print(f"📡 --- TEST ENDPOINT B : /volumes/ (filter=name:'{query}') ---")
    url_vol = "https://comicvine.gamespot.com/api/volumes/"
    params_vol = {
        "api_key": api_key,
        "format": "json",
        "filter": f"name:{query}",
        "limit": 10,
        "field_list": "id,name,start_year,count_of_issues,publisher,deck,description,first_issue"
    }

    try:
        res_v = requests.get(url_vol, params=params_vol, headers=headers, timeout=12)
        print(f"HTTP Status : {res_v.status_code}")
        if res_v.status_code == 200:
            results_v = res_v.json().get("results", [])
            print(f"Nombre de résultats renvoyés : {len(results_v)}\n")
            for idx, item in enumerate(results_v):
                pub = item.get("publisher") or {}
                pub_name = pub.get("name") if isinstance(pub, dict) else "AUCUN"
                print(f"  [{idx+1}] ID: 4050-{item.get('id')} | Titre: '{item.get('name')}' ({item.get('start_year')})")
                print(f"      - Éditeur: {pub_name}")
                print(f"      - Nombre de numéros (count_of_issues): {item.get('count_of_issues')}")
                print(f"      - Présence de résumé (deck/desc): {bool(item.get('deck') or item.get('description'))}")
                print(f"      - First Issue ID: {item.get('first_issue', {}).get('id') if isinstance(item.get('first_issue'), dict) else None}")
                print()
    except Exception as e:
        print(f"💥 Erreur /volumes/ : {e}")

if __name__ == "__main__":
    for q in TEST_QUERIES:
        inspect_comicvine(q)