import requests
import sys

# On utilise les infos de tes précédentes captures d'écran
URL = "http://192.168.1.116:5001"
API_KEY = "E83kE2mmRMS4L1NIGulnLeM41"

print(f"--- TEST DE CONNEXION KAVITA ---")
print(f"URL cible : {URL}")
print(f"Clé API   : {API_KEY}\n")

try:
    print("1. Tentative d'authentification...")
    res = requests.post(
        f"{URL}/api/Plugin/authenticate",
        json={"apiKey": API_KEY, "pluginName": "KavitaFetcher"},
        timeout=10
    )
    
    print(f"Code HTTP retourné : {res.status_code}")
    print(f"Réponse brute      : {res.text}\n")

    if res.status_code == 200:
        token = res.json().get("token")
        print(f"[SUCCÈS] Token d'accès généré (début) : {token[:15]}...")
        
        print("\n2. Tentative de lecture des bibliothèques...")
        lib_res = requests.get(
            f"{URL}/api/Library",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10
        )
        print(f"Code HTTP retourné : {lib_res.status_code}")
        print(f"Contenu brut       : {lib_res.text}")
    else:
        print("[ÉCHEC] Kavita a refusé l'accès.")

except Exception as e:
    print(f"\n[CRASH RESEAU] Impossible d'atteindre Kavita : {e}")
