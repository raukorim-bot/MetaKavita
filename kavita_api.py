from curl_cffi import requests as cffi_requests
import requests
import base64

class KavitaAPI:
    def __init__(self, url, api_key):
        self.url = url.strip().rstrip('/') if url else ""
        self.api_key = api_key.strip() if api_key else ""
        self.token = None
        self.headers = {}

    def authenticate(self):
        print(f"[DEBUG] Auth tentée avec URL: '{self.url}' et Key: '{self.api_key[:5]}...'")
        if not self.api_key or not self.url:
            return False
            
        try:
            full_url = f"{self.url}/api/Plugin/authenticate"
            params = {"apiKey": self.api_key, "pluginName": "KavitaFetcher"}
            
            res = requests.post(full_url, params=params, timeout=10)
            res.raise_for_status()
            
            self.token = res.json().get("token")
            self.headers = {
                "Authorization": f"Bearer {self.token}", 
                "Content-Type": "application/json"
            }
            return True
        except Exception as e:
            print(f"[Erreur Auth] {e}")
            return False

    def get_libraries(self):
        if not self.token and not self.authenticate():
            return []
        try:
            res = requests.get(f"{self.url}/api/Library/libraries", headers=self.headers, timeout=10)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"[Erreur Libraries] {e}")
            return []

    def get_all_series(self, library_id=None):
        if not self.token and not self.authenticate():
            return []
            
        try:
            all_libs = self.get_libraries()
            if library_id:
                # On isole uniquement la bibliothèque demandée
                libraries_to_scan = [lib for lib in all_libs if str(lib['id']) == str(library_id)]
            else:
                libraries_to_scan = all_libs

            unique_series = {}
            
            for lib in libraries_to_scan:
                try:
                    series_url = f"{self.url}/api/Series/all-v2"
                    series_res = requests.post(series_url, json={"libraryId": lib["id"]}, headers=self.headers, timeout=10)
                    
                    if series_res.status_code == 200:
                        for s in series_res.json():
                            # LA SÉCURITÉ ABSOLUE : on filtre nous-mêmes !
                            # Si la série n'a pas le bon libraryId, elle dégage.
                            if str(s.get('libraryId', lib['id'])) == str(lib['id']):
                                unique_series[s['id']] = s
                                
                except Exception as inner_e:
                    print(f"[Erreur] Bibliothèque {lib.get('id')} : {inner_e}")
                    
            all_series = list(unique_series.values())
            all_series.sort(key=lambda x: x.get('name', '').lower())
            return all_series
            
        except Exception as e:
            print(f"[Erreur globale] {e}")
            return []

    def get_series_metadata(self, series_id):
        if not self.token and not self.authenticate(): 
            return None
        try:
            res = requests.get(f"{self.url}/api/Series/metadata?seriesId={series_id}", headers=self.headers, timeout=10)
            return res.json() if res.status_code == 200 else None
        except Exception as e:
            print(f"[Erreur Metadata] {e}")
            return None

    def update_series_metadata(self, metadata):
        if not self.token and not self.authenticate(): 
            return False, "Non authentifié"
        try:
            # On encapsule les métadonnées dans la clé 'seriesMetadata' comme exigé par la doc
            payload = {"seriesMetadata": metadata}
            
            print(f"[DEBUG] Envoi encapsulé vers /api/Series/metadata : {payload}")
            
            res = requests.post(
                f"{self.url}/api/Series/metadata", 
                json=payload, 
                headers=self.headers, 
                timeout=10
            )
            
            if res.status_code != 200:
                print(f"[DEBUG] Erreur Kavita : {res.text}")
                return False, f"Code {res.status_code} : {res.text}"
                
            return True, "Succès"
        except Exception as e:
            print(f"[Erreur Update] {e}")
            return False, str(e)
            
    def update_series_summary(self, series_id, summary_text):
        # On cible l'endpoint /api/Series/update comme indiqué dans ta doc
        url = f"{self.url}/api/Series/update"
        
        # Le payload minimaliste. 
        # Kavita n'a besoin que de l'ID pour identifier la série
        # et des champs que tu veux modifier (summary et summaryLocked)
        payload = {
            "id": int(series_id),
            "summary": summary_text,
            "summaryLocked": True
        }
        
        try:
            print(f"[DEBUG] Envoi minimaliste vers /api/Series/update : {payload}")
            res = requests.post(url, json=payload, headers=self.headers, timeout=10)
            res.raise_for_status()
            return True, "Succès"
        except Exception as e:
            print(f"[Erreur Update Summary] {e}")
            return False, str(e)

    # --- NOUVELLE FONCTION POUR UPLOADER L'IMAGE ---
    def upload_series_cover(self, series_id, cover_url):
        if not self.token and not self.authenticate(): 
            return False, "Non authentifié"
            
        if not cover_url:
            return False, "URL de couverture invalide"
            
        try:
            # 1. On télécharge l'image depuis le web (AVEC BYPASS CLOUDFLARE/HOTLINK)
            print(f"[DEBUG] Téléchargement de la couverture depuis : {cover_url}")
            headers = {
                "Referer": "https://www.nautiljon.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            img_res = cffi_requests.get(cover_url, headers=headers, impersonate="safari15_5", timeout=15)
            
            if img_res.status_code != 200:
                return False, f"Impossible de télécharger l'image (Code {img_res.status_code})"
            
            # 2. On convertit l'image en base64 pur
            img_base64 = base64.b64encode(img_res.content).decode('utf-8')
            
            # 3. On envoie à Kavita via l'API Upload (en HTTP standard)
            upload_url = f"{self.url}/api/Upload/series"
            payload = {
                "id": int(series_id),
                "url": img_base64
            }
            
            res = requests.post(upload_url, json=payload, headers=self.headers, timeout=15)
            
            if res.status_code != 200:
                print(f"[DEBUG] Erreur Upload Cover Kavita : {res.text}")
                return False, f"Code {res.status_code} : {res.text}"
                
            return True, "Couverture mise à jour avec succès"
            
        except Exception as e:
            print(f"[Erreur Upload Cover] {e}")
            return False, str(e)