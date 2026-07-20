# debug_nautiljon.py

import sys
from curl_cffi import requests
from bs4 import BeautifulSoup

def run_test(impersonate_profile):
    print(f"\n[{impersonate_profile}] 🚀 Lancement du test avec l'empreinte : {impersonate_profile}")
    
    session = requests.Session(impersonate=impersonate_profile)
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.nautiljon.com/", 
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1"
    })
    
    url = "https://www.nautiljon.com/mangas/"
    print(f"[{impersonate_profile}] 🌐 Requête GET vers {url}...")
    
    try:
        res = session.get(url, timeout=15)
        print(f"[{impersonate_profile}] 📊 Statut HTTP : {res.status_code}")
        print(f"[{impersonate_profile}] 🛡️ Serveur : {res.headers.get('Server', 'Inconnu')}")
        
        soup = BeautifulSoup(res.text, 'html.parser')
        st_input = soup.find('input', {'name': 'st'})
        
        if st_input and st_input.get('value'):
            print(f"[{impersonate_profile}] ✅ SUCCÈS ! Jeton 'st' trouvé : {st_input['value']}")
            return True
        else:
            print(f"[{impersonate_profile}] ❌ ÉCHEC ! Jeton 'st' introuvable.")
            
            # Recherche d'indices Cloudflare
            title = soup.title.string.strip() if soup.title else "Pas de titre"
            print(f"[{impersonate_profile}] 📄 Titre de la page reçue : '{title}'")
            
            if "cloudflare" in res.text.lower() or "just a moment" in res.text.lower():
                print(f"[{impersonate_profile}] 🚨 ALERTE : La page ressemble à une protection Cloudflare / Captcha.")
            
            # Sauvegarde du HTML pour inspection humaine
            filename = f"nautiljon_dump_{impersonate_profile}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(res.text)
            print(f"[{impersonate_profile}] 💾 Code HTML sauvegardé dans '{filename}' pour analyse.")
            return False
            
    except Exception as e:
        print(f"[{impersonate_profile}] 💥 Erreur critique réseau : {e}")
        return False

if __name__ == "__main__":
    print("="*60)
    print("🕵️ MetaKavita - SCRIPT DE DEBUG NAUTILJON")
    print("="*60)
    
    # Test 1: L'empreinte actuelle en production (qui a planté chez toi)
    success_safari = run_test("safari15_5")
    
    # Test 2: L'empreinte plus récente proposée pour le correctif
    success_chrome = run_test("chrome110")
    
    print("\n" + "="*60)
    print("💡 DIAGNOSTIC & CONCLUSION :")
    if not success_safari and not success_chrome:
        print("❌ Les deux profils échouent.")
        print("   -> Soit Nautiljon a modifié son code source (le jeton ne s'appelle plus 'st').")
        print("   -> Soit ton IP est lourdement flagguée par Cloudflare en ce moment (Captcha obligatoire).")
        print("👉 Ouvre les fichiers 'nautiljon_dump_xxx.html' générés dans ton navigateur pour voir ce qui bloque.")
    elif not success_safari and success_chrome:
        print("✅ Le profil 'chrome110' fonctionne mais 'safari15_5' échoue !")
        print("👉 C'était bien l'empreinte Safari obsolète qui se faisait recaler par Cloudflare.")
        print("👉 Applique le fix du profil Chrome dans le code principal de MetaKavita.")
    elif success_safari:
        print("✅ L'empreinte actuelle 'safari15_5' fonctionne finalement très bien !")
        print("👉 L'erreur que tu as eue plus tôt était juste un blocage temporaire (rate-limit ou test de routine de Cloudflare).")
    print("="*60)