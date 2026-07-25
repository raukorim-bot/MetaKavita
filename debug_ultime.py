import json
import sys
import requests
import time

sys.path.append('.')
from config_manager import load_config
from kavita_api import KavitaAPI

def test_kavita_payloads(series_id):
    print("\n" + "="*80)
    print(f"📡 DÉBOGAGE API KAVITA (Série ID: {series_id})")
    print("="*80)
    
    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), '5ICZyZBqCPAMyMfFc9CB')
    
    if not kavita.authenticate():
        print("❌ Échec de l'authentification Kavita. Vérifiez l'URL et l'API Key.")
        return

    print("✅ Authentification réussie.\n")
    
    # 1. Récupération des métadonnées existantes
    meta = kavita.get_series_metadata(series_id)
    if not meta:
        print(f"❌ Impossible de trouver la série ID {series_id} dans Kavita.")
        return
        
    print("📥 MÉTADONNÉES EXISTANTES (Champ 'publisher' actuel) :")
    print(json.dumps(meta.get('publisher'), indent=2, ensure_ascii=False))

    # 2. Les 5 formats à tester (Car Kavita est très capricieux sur les schémas C#)
    tests = [
        ("Format 1 (Objet avec ID 0)", {"id": 0, "name": "TEST_FORMAT_1"}),
        ("Format 2 (Objet complet avec SortName)", {"id": 0, "name": "TEST_FORMAT_2", "sortName": "TEST_FORMAT_2"}),
        ("Format 3 (Dans une Liste / Array)", [{"id": 0, "name": "TEST_FORMAT_3"}]),
        ("Format 4 (String simple)", "TEST_FORMAT_4"),
        ("Format 5 (Objet vide avec Name uniquement)", {"name": "TEST_FORMAT_5"})
    ]

    for format_name, pub_payload in tests:
        print("\n" + "-"*70)
        print(f"🧪 TEST : {format_name}")
        print("-" * 70)
        
        # Préparation du payload exact tel que MetaKavita le fait
        meta_test = meta.copy()
        meta_test['seriesId'] = int(series_id)
        meta_test['publisher'] = pub_payload
        meta_test['publisherLocked'] = True
        
        # Nettoyage des champs bloquants (comme le fait app.py)
        meta_test.pop('created', None)
        meta_test.pop('lastModified', None)

        payload = {"seriesMetadata": meta_test}
        
        print(f"📦 Envoi du champ publisher : {json.dumps(pub_payload, ensure_ascii=False)}")
        
        # Envoi HTTP
        url = f"{kavita.url}/api/Series/metadata"
        try:
            res = requests.post(url, json=payload, headers=kavita.headers, timeout=15)
            print(f"📤 Réponse HTTP de Kavita : {res.status_code}")
            
            if res.status_code != 200:
                print(f"❌ Erreur Kavita : {res.text}")
            else:
                # Pause pour laisser le temps à Kavita d'écrire en DB
                time.sleep(1)
                
                # Vérification : A-t-il vraiment sauvegardé ?
                meta_verify = kavita.get_series_metadata(series_id)
                pub_verify = meta_verify.get('publisher')
                print(f"🔍 Ce que Kavita a réelement sauvegardé : {json.dumps(pub_verify, ensure_ascii=False)}")
                
                # Analyse du résultat
                success = False
                if pub_verify and isinstance(pub_verify, dict) and "TEST_FORMAT" in str(pub_verify.get('name', '')):
                    success = True
                elif pub_verify and isinstance(pub_verify, list) and len(pub_verify) > 0 and "TEST_FORMAT" in str(pub_verify[0]):
                    success = True
                elif pub_verify and isinstance(pub_verify, str) and "TEST_FORMAT" in pub_verify:
                    success = True
                    
                if success:
                    print(f"🎉 SUCCÈS TOTAL ! Kavita accepte le {format_name} !")
                else:
                    print(f"⚠️ ÉCHEC SILENCIEUX ! Kavita a dit 200 OK mais a jeté la donnée à la poubelle.")
                    
        except Exception as e:
            print(f"💥 Crash HTTP : {e}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        test_kavita_payloads(sys.argv[1])
    else:
        s_id = input("👉 Entrez l'ID d'une série Kavita pour faire le test (ex: 24) : ")
        test_kavita_payloads(s_id)