import logging
import base64
import sys
from urllib.parse import urlparse
import requests
from curl_cffi import requests as cffi_requests

from config_manager import load_config
from kavita_api import KavitaAPI
from scrapers import ScraperRegistry

# Configuration stricte des logs pour tout voir
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.DEBUG,
    handlers=[logging.StreamHandler(sys.stdout)]
)

def debug_manual_cover_upload(series_id, cover_url):
    config = load_config()
    kavita_url = config.get("KAVITA_URL")
    kavita_api_key = config.get("KAVITA_API_KEY")

    if not kavita_url or not kavita_api_key:
        logging.error("❌ Kavita URL ou API Key introuvable dans la configuration.")
        return

    logging.info("=" * 60)
    logging.info("🚀 DEBOGAGE DE LA CHAÎNE D'UPLOAD DE COUVERTURE")
    logging.info(f"📌 Série cible (ID) : {series_id}")
    logging.info(f"🖼️  Image cible (URL) : {cover_url}")
    logging.info("=" * 60)

    # ---------------------------------------------------------
    # ÉTAPE 1 : AUTHENTIFICATION KAVITA
    # ---------------------------------------------------------
    logging.info("\n🔑 [ÉTAPE 1] Authentification auprès de Kavita...")
    kavita = KavitaAPI(kavita_url, kavita_api_key)
    if not kavita.authenticate():
        logging.error("❌ Échec de l'authentification Kavita. Jeton refusé.")
        return
    logging.info(f"✅ Authentification réussie. Jeton: {kavita.token[:15]}...***")

    # ---------------------------------------------------------
    # ÉTAPE 2 : PRÉPARATION DU TÉLÉCHARGEMENT DE L'IMAGE
    # ---------------------------------------------------------
    logging.info("\n🌐 [ÉTAPE 2] Préparation de la requête de téléchargement de l'image...")
    parsed = urlparse(cover_url)
    domain = parsed.netloc.lower().split(':')[0]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # Recherche d'un referer proxy potentiel comme dans le script d'origine
    for scraper in ScraperRegistry.get_all():
        if any(domain == d or domain.endswith('.' + d) for d in getattr(scraper, 'proxy_domains', [])):
            referer = getattr(scraper, 'proxy_referer', None)
            if referer:
                headers["Referer"] = referer
                logging.info(f"🛡️ Protection Proxy trouvée ! Injection du Referer : {referer}")
            break

    # ---------------------------------------------------------
    # ÉTAPE 3 : TÉLÉCHARGEMENT (CURL_CFFI)
    # ---------------------------------------------------------
    logging.info(f"📥 [ÉTAPE 3] Téléchargement de l'image depuis le serveur source...")
    try:
        img_res = cffi_requests.get(cover_url, headers=headers, impersonate="chrome110", timeout=15)
        logging.info(f"   -> Code HTTP de réponse : {img_res.status_code}")
        
        if img_res.status_code != 200:
            logging.error(f"❌ Le serveur distant a refusé l'accès à l'image. (Code {img_res.status_code})")
            return
            
        img_size_kb = len(img_res.content) / 1024
        logging.info(f"✅ Image téléchargée avec succès. Taille : {img_size_kb:.2f} KB")
        logging.info(f"   -> Content-Type reçu : {img_res.headers.get('Content-Type', 'Inconnu')}")

    except Exception as e:
        logging.error(f"❌ Crash lors du téléchargement de l'image : {e}")
        return

    # ---------------------------------------------------------
    # ÉTAPE 4 : ENCODAGE BASE64
    # ---------------------------------------------------------
    logging.info("\n⚙️ [ÉTAPE 4] Conversion de l'image en Base64 pur...")
    try:
        img_base64 = base64.b64encode(img_res.content).decode('utf-8')
        logging.info(f"   -> Longueur de la chaîne Base64 : {len(img_base64)} caractères")
        logging.info(f"   -> Début de la chaîne : {img_base64[:40]}...")
    except Exception as e:
        logging.error(f"❌ Crash lors de l'encodage de l'image : {e}")
        return

    # ---------------------------------------------------------
    # ÉTAPE 5 : ENVOI DU PAYLOAD À KAVITA
    # ---------------------------------------------------------
    logging.info("\n⬆️ [ÉTAPE 5] Envoi de l'image à l'API de Kavita...")
    upload_url = f"{kavita_url}/api/Upload/series"
    payload = {
        "id": int(series_id),
        "url": img_base64
    }
    
    logging.info(f"   -> URL d'envoi : {upload_url}")
    logging.info(f"   -> Payload JSON contient les clés : {list(payload.keys())}")

    try:
        res_kavita = requests.post(upload_url, json=payload, headers=kavita.headers, timeout=35)
        logging.info(f"   -> Code HTTP de Kavita : {res_kavita.status_code}")
        
        if res_kavita.status_code == 200:
            logging.info("🎉 SUCCÈS TOTAL : Kavita a accepté et traité l'image !")
        else:
            logging.error(f"❌ ÉCHEC : Kavita a refusé l'image.")
            logging.error(f"   -> Réponse brute de Kavita : {res_kavita.text}")
    except Exception as e:
        logging.error(f"❌ Crash lors de la communication avec Kavita : {e}")

if __name__ == "__main__":
    print("========================================")
    print("  DEBUGGEUR INTERACTIF DE COUVERTURES   ")
    print("========================================")
    s_id = input("👉 Entrez l'ID de la série Kavita (ex: 24) : ").strip()
    c_url = input("👉 Entrez l'URL de l'image (ex: https://...) : ").strip()
    
    if s_id.isdigit() and c_url.startswith("http"):
        debug_manual_cover_upload(int(s_id), c_url)
    else:
        print("❌ Saisie invalide. L'ID doit être un nombre et l'URL doit commencer par http(s).")