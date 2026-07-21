# debug_comicvine.py

import json
import os
import sys
import requests
import re
from bs4 import BeautifulSoup

def main():
    print("=" * 60)
    print("🕵️ MetaKavita - SCRIPT DE DEBUG COMICVINE")
    print("=" * 60)

    # 1. Lecture de la configuration existante
    config_path = "data/config.json"
    if not os.path.exists(config_path):
        print(f"❌ Erreur : Fichier de configuration '{config_path}' introuvable.")
        print("Veuillez lancer MetaKavita au moins une fois pour générer la configuration.")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ Erreur lors de la lecture de la config : {e}")
        sys.exit(1)

    api_key = config.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        print("❌ Erreur : Clé API 'COMICVINE_API_KEY' manquante dans data/config.json.")
        print("Veuillez la configurer dans l'interface Web ou dans le fichier de config.")
        sys.exit(1)

    print(f"✅ Clé API chargée : {api_key[:6]}...{api_key[-6:] if len(api_key) > 12 else ''}")

    # 2. Définition des requêtes de test
    queries_to_test = [
        "01 Premières gaffes",  # Requête brute problématique
        "Premières gaffes",     # Titre d'album seul
        "Gaston",               # Titre de la série Dupuis (Exact)
        "Gaston Lagaffe"        # Titre complet alternatif
    ]

    headers = {
        "User-Agent": "MetaKavita-Debug-Script/1.0 (contact@metakavita.com)",
        "Accept": "application/json"
    }

    for query in queries_to_test:
        print("\n" + "-" * 50)
        print(f"🔍 Test de recherche pour la requête : '{query}'")
        print("-" * 50)

        url = "https://comicvine.gamespot.com/api/search/"
        params = {
            "api_key": api_key,
            "format": "json",
            "resources": "volume",
            "query": query,
            "limit": 5
        }

        try:
            res = requests.get(url, params=params, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"❌ Erreur HTTP {res.status_code} lors de la requête.")
                if res.status_code in [401, 403]:
                    print("👉 Votre clé d'API ComicVine semble invalide ou rejetée par le serveur.")
                continue

            data = res.json()
            if data.get("status_code") == 100:
                print(f"❌ Erreur interne ComicVine : {data.get('error')}")
                continue

            results = data.get("results", [])
            print(f"📊 Résultats trouvés dans la catégorie 'Volume' (Séries) : {len(results)}")

            if not results:
                print("⚠️ Aucun volume trouvé. Pourquoi ?")
                print("💡 Explication : ComicVine indexe la BD francophone sous son titre de SÉRIE globale (ex: 'Gaston').")
                print("   Les titres d'albums (ex: 'Premières gaffes') sont indexés comme des 'Issues' (tomes)")
                print("   à l'intérieur du Volume principal, et non comme des fiches de séries à part entière.")
                continue

            for idx, vol in enumerate(results):
                print(f"\n[Résultat #{idx + 1}]")
                print(f"  - ID ComicVine : 4050-{vol.get('id')}")
                print(f"  - Titre du Volume : {vol.get('name')}")
                print(f"  - Année de début : {vol.get('start_year')}")
                print(f"  - Éditeur : {vol.get('publisher', {}).get('name') if vol.get('publisher') else 'Aucun'}")
                print(f"  - Nombre d'issues : {vol.get('count_of_issues', 'Inconnu')}")
                
                deck = vol.get("deck") or ""
                print(f"  - Longueur du résumé court (Search API) : {len(deck)} caractères.")
                
                # Test d'appel de l'étape 2 (Détail exhaustif du Volume)
                vol_id = vol.get("id")
                detail_url = f"https://comicvine.gamespot.com/api/volume/4050-{vol_id}/"
                detail_params = {"api_key": api_key, "format": "json"}
                
                print(f"  ⚡ Étape 2 : Requête de détails du Volume (ID: 4050-{vol_id})...")
                det_res = requests.get(detail_url, params=detail_params, headers=headers, timeout=10)
                if det_res.status_code == 200:
                    det_data = det_res.json().get("results", {})
                    full_desc = det_data.get("description") or ""
                    print(f"    ✅ Détail récupéré ! Longueur description riche : {len(full_desc)} caractères.")
                    
                    if full_desc:
                        soup = BeautifulSoup(full_desc, "html.parser")
                        text_clean = soup.get_text().strip()
                        print(f"    📖 Extrait nettoyé : {text_clean[:130]}...")
                    else:
                        print("    ⚠️ Ce volume n'a pas de description rédigée sur le wiki ComicVine.")
                        
                    # Test d'accessibilité de la couverture
                    img_dict = det_data.get("image") or {}
                    cover_url = img_dict.get("original_url")
                    print(f"    🖼️ URL Image d'origine : {cover_url}")
                    
                    if cover_url:
                        img_res = requests.get(cover_url, headers=headers, timeout=10)
                        print(f"    🔌 Test de connexion CDN image : HTTP {img_res.status_code} ({'OK' if img_res.status_code == 200 else 'BLOQUÉ'})")
                else:
                    print(f"    ❌ Échec de l'étape 2 (HTTP {det_res.status_code})")

        except Exception as e:
            print(f"💥 Erreur inattendue durant le processus : {e}")

    print("\n" + "=" * 60)
    print("💡 ANALYSE ET SOLUTIONS PRATIQUES :")
    print("=" * 60)
    print("1. SI VOTRE SÉRIE S'APPELLE ENCORE '01 Premières gaffes' :")
    print("   La recherche échouera systématiquement car 'Premières gaffes' est un tome et non un titre de série.")
    print("\n2. COMMENT LE RÉSOUDRE DE MANIÈRE TRANSPARENTE ?")
    print("   👉 Solution A (Recommandée) : Organisez vos fichiers dans un dossier parent au nom de la série.")
    print("      Ex: '/mangas/Gaston Lagaffe/01 - Premières gaffes.cbz'. Kavita créera alors la série 'Gaston Lagaffe'.")
    print("   👉 Solution B : Utilisez le champ 'Titre Alternatif' (Override) dans l'interface MetaKavita.")
    print("      Saisissez 'Gaston' dans le champ de titre alternatif de l'œuvre, cliquez sur Sauver (💾) puis relancez la synchronisation.")
    print("      Le scraper ComicVine recherchera alors 'Gaston', trouvera le volume Dupuis, et récupérera l'ensemble de la fiche.")
    print("=" * 60)

if __name__ == "__main__":
    main()