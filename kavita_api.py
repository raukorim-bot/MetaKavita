from curl_cffi import requests as cffi_requests
import requests
import base64

class KavitaAPI:
    # Cache mémoire au niveau de la CLASSE (partagé et conservé pour tout le batch)
    _series_lib_type_cache = {}

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
        except requests.exceptions.HTTPError as e:
            # On masque l'URL contenant la clé API dans le message d'erreur
            print(f"[Erreur Auth] Le serveur Kavita a rejeté la requête (Code {e.response.status_code}).")
            return False
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
                            # Filtrage de sécurité
                            if str(s.get('libraryId', lib['id'])) == str(lib['id']):
                                # Récupération et conversion du type de bibliothèque
                                raw_type = lib.get('type') or lib.get('libraryType') or lib.get('LibraryType') or lib.get('Type') or 0
                                if raw_type in [0, "0", "Manga", "manga"]:
                                    lib_type_str = "Manga"
                                elif raw_type in [1, "1", "Comic", "comic", "Comics", "comics"]:
                                    lib_type_str = "Comic"
                                elif raw_type in [2, "2", "Book", "book", "Books", "books"]:
                                    lib_type_str = "Book"
                                elif raw_type in [3, "3", "Novel", "novel", "LightNovel", "lightnovel", "Light Novels", "light novels"]:
                                    lib_type_str = "Book"
                                elif raw_type in [4, "4", "Image", "image", "Images", "images"]:
                                    lib_type_str = "Manga"
                                else:
                                    lib_type_str = "Manga"
                                    
                                s['libraryType'] = lib_type_str
                                unique_series[s['id']] = s
                                
                except Exception as inner_e:
                    print(f"[Erreur] Bibliothèque {lib.get('id')} : {inner_e}")
                    
            all_series = list(unique_series.values())
            all_series.sort(key=lambda x: x.get('name', '').lower())
            return all_series
            
        except Exception as e:
            print(f"[Erreur globale] {e}")
            return []

    def get_library_type_for_series(self, series_id):
        """
        Récupère le type de bibliothèque exact (Manga, Comic, Book) pour une série donnée.
        Utilise un cache mémoire interne pour optimiser les performances.
        """
        if int(series_id) in self._series_lib_type_cache:
            return self._series_lib_type_cache[int(series_id)]
            
        if not self.token and not self.authenticate():
            return "Manga"
            
        try:
            all_libs = self.get_libraries()
            lib_id_to_type = {}
            for lib in all_libs:
                raw_type = lib.get('type') or lib.get('libraryType') or lib.get('LibraryType') or lib.get('Type') or 0
                if raw_type in [0, "0", "Manga", "manga"]:
                    lib_type_str = "Manga"
                elif raw_type in [1, "1", "Comic", "comic", "Comics", "comics"]:
                    lib_type_str = "Comic"
                elif raw_type in [2, "2", "Book", "book", "Books", "books"]:
                    lib_type_str = "Book"
                elif raw_type in [3, "3", "Novel", "novel", "LightNovel", "lightnovel", "Light Novels", "light novels"]:
                    lib_type_str = "Book"
                elif raw_type in [4, "4", "Image", "image", "Images", "images"]:
                    lib_type_str = "Manga"
                else:
                    lib_type_str = "Manga"
                lib_id_to_type[lib['id']] = lib_type_str
                
            all_series = self.get_all_series()
            for s in all_series:
                s_id = s['id']
                l_id = s.get('libraryId')
                self._series_lib_type_cache[int(s_id)] = lib_id_to_type.get(l_id, "Manga")
                
            return self._series_lib_type_cache.get(int(series_id), "Manga")
        except Exception as e:
            print(f"[Erreur Library Type for Series] {e}")
            return "Manga"

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
        url = f"{self.url}/api/Series/update"
        
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

    def upload_series_cover(self, series_id, cover_url):
        if not self.token and not self.authenticate(): 
            return False, "Non authentifié"
            
        if not cover_url:
            return False, "URL de couverture invalide"
            
        try:
            print(f"[DEBUG] Téléchargement de la couverture depuis : {cover_url}")
            
            referer = "https://kitsu.io/"
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            if "comicvine" in cover_url or "gamespot" in cover_url:
                referer = "https://comicvine.gamespot.com/"
                # CORRECTION : Utiliser un agent navigateur pour éviter le 403 sur le CDN
                user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                
            headers = {
                "Referer": referer,
                "User-Agent": user_agent
            }
            
            img_res = cffi_requests.get(cover_url, headers=headers, impersonate="safari15_5", timeout=15)
            
            if img_res.status_code != 200:
                return False, f"Impossible de télécharger l'image (Code {img_res.status_code})"
            
            # Convertit l'image en base64
            img_base64 = base64.b64encode(img_res.content).decode('utf-8')
            
            # Envoi de la couverture à l'API Kavita
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
            
    def update_series_external_ids(self, series_id, anilist_id=None, mal_id=None, mangabaka_id=None):
        if not self.token and not self.authenticate(): 
            return False, "Non authentifié"
            
        payload = { "id": int(series_id) }
        
        if anilist_id: payload["aniListId"] = int(anilist_id)
        if mal_id: payload["malId"] = int(mal_id)
        if mangabaka_id: payload["mangaBakaId"] = int(mangabaka_id)
        
        if len(payload) == 1:
            return True, "Aucun ID à mettre à jour"
            
        try:
            url = f"{self.url}/api/Series/update"
            print(f"[DEBUG] Envoi des IDs externes vers {url} : {payload}")
            res = requests.post(url, json=payload, headers=self.headers, timeout=10)
            
            if res.status_code == 200:
                return True, "Succès"
            else:
                print(f"[DEBUG] Erreur Update IDs : {res.text}")
                return False, f"Code {res.status_code} : {res.text}"
        except Exception as e:
            print(f"[Erreur Update IDs] {e}")
            return False, str(e)