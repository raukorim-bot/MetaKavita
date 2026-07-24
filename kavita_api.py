from curl_cffi import requests as cffi_requests
import requests
import base64
import logging

class KavitaAPI:
    # Le cache sera purgé dynamiquement lors des appels batch/dashboard !
    _series_lib_type_cache = {}
    
    def __init__(self, url, api_key):
        self.url = url.strip().rstrip('/') if url else ""
        self.api_key = api_key.strip() if api_key else ""
        self.token = None
        self.headers = {}

    def authenticate(self):
        logging.info(f"[DEBUG] Auth tentée avec URL: '{self.url}' et Key: '{self.api_key[:5]}...'")
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
            logging.error(f"[Erreur Auth] Le serveur Kavita a rejeté la requête (Code {e.response.status_code}).")
            return False
        except Exception as e:
            logging.error(f"[Erreur Auth] {e}")
            return False

    def get_libraries(self):
        if not self.token and not self.authenticate():
            return []
        try:
            res = requests.get(f"{self.url}/api/Library/libraries", headers=self.headers, timeout=20)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            logging.error(f"[Erreur Libraries] {e}")
            return []

    @staticmethod
    def _normalize_library_type(raw_type):
        """Convertit n'importe quel type de bibliothèque Kavita (ID ou String) en type standard MetaKavita."""
        if raw_type is None:
            return "Manga"
            
        val_str = str(raw_type).strip().lower()
        
        # 1. Détection des Comics / BD / Comic (Flexible) [IDs Kavita 1 et 5]
        if val_str in ["1", "5", "comic", "comics", "comic (flexible)", "comicflexible", "comic_flexible", "flexiblecomic"] or "comic" in val_str:
            return "Comic"
            
        # 2. Détection des Livres / Romans / Light Novels [IDs Kavita 2 et 3]
        if val_str in ["2", "3", "book", "books", "novel", "novels", "lightnovel", "lightnovels", "light novel", "light novels"] or "book" in val_str or "novel" in val_str:
            return "Book"
            
        # 3. Détection des Mangas / Images / Webtoons [IDs Kavita 0, 4 et 6]
        if val_str in ["0", "4", "6", "manga", "image", "images", "webtoon"] or "manga" in val_str or "image" in val_str or "webtoon" in val_str:
            return "Manga"
            
        return "Manga"

    def get_all_series(self, library_id=None):
        if not self.token and not self.authenticate():
            return []
            
        try:
            # 🎯 PURGE DU CACHE ! (À chaque ouverture du dashboard ou début de batch)
            self.__class__._series_lib_type_cache.clear()
            
            all_libs = self.get_libraries()
            if library_id:
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
                            if str(s.get('libraryId', lib['id'])) == str(lib['id']):
                                raw_type = lib.get('type') or lib.get('libraryType') or lib.get('LibraryType') or lib.get('Type') or 0
                                s['libraryType'] = self._normalize_library_type(raw_type)
                                unique_series[s['id']] = s
                                
                except Exception as inner_e:
                    logging.error(f"[Erreur] Bibliothèque {lib.get('id')} : {inner_e}")
                    
            all_series = list(unique_series.values())
            all_series.sort(key=lambda x: x.get('name', '').lower())
            return all_series
            
        except Exception as e:
            logging.error(f"[Erreur globale] {e}")
            return []

    # 🎯 CORRECTION : Récupération ciblée ultra-rapide
    def get_library_type_for_series(self, series_id):
        if int(series_id) in self._series_lib_type_cache:
            return self._series_lib_type_cache[int(series_id)]
            
        if not self.token and not self.authenticate():
            return "Manga"
            
        try:
            # 1. On récupère la map des bibliothèques (Rapide)
            all_libs = self.get_libraries()
            lib_id_to_type = {}
            for lib in all_libs:
                raw_type = lib.get('type') or lib.get('libraryType') or lib.get('LibraryType') or lib.get('Type') or 0
                lib_id_to_type[lib['id']] = self._normalize_library_type(raw_type)
                
            # 2. On interroge Kavita uniquement sur cette série pour connaître son libraryId (Rapide)
            res = requests.get(f"{self.url}/api/Series/{series_id}", headers=self.headers, timeout=10)
            if res.status_code == 200:
                s_data = res.json()
                l_id = s_data.get('libraryId')
                lib_type = lib_id_to_type.get(l_id, "Manga")
                
                # Sauvegarde temporaire pour ce traitement (sera purgé au prochain batch global)
                self._series_lib_type_cache[int(series_id)] = lib_type
                return lib_type
                
        except Exception as e:
            logging.error(f"[Erreur Library Type for Series] {e}")
            
        return "Manga"

    def get_series_metadata(self, series_id):
        if not self.token and not self.authenticate(): 
            return None
        try:
            res = requests.get(f"{self.url}/api/Series/metadata?seriesId={series_id}", headers=self.headers, timeout=25)
            if res.status_code == 200:
                data = res.json()
                # Sécurité : Si Kavita renvoie une liste [{...}], on extrait le dictionnaire principal !
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                elif isinstance(data, dict):
                    return data
            return None
        except Exception as e:
            logging.error(f"[Erreur Metadata] {e}")
            return None
            
    def update_series_metadata(self, metadata):
        if not self.token and not self.authenticate(): 
            return False, "Non authentifié"
        try:
            payload = {"seriesMetadata": metadata}
            logging.debug(f"[DEBUG] Envoi encapsulé vers /api/Series/metadata : {payload}")
            
            res = requests.post(
                f"{self.url}/api/Series/metadata", 
                json=payload, 
                headers=self.headers, 
                timeout=35
            )
            
            if res.status_code != 200:
                logging.error(f"[DEBUG] Erreur Kavita : {res.text}")
                return False, f"Code {res.status_code} : {res.text}"
                
            return True, "Succès"
        except Exception as e:
            logging.error(f"[Erreur Update] {e}")
            return False, str(e)

    def update_series_summary(self, series_id, summary_text):
        url = f"{self.url}/api/Series/update"
        payload = {
            "id": int(series_id),
            "summary": summary_text,
            "summaryLocked": True
        }
        try:
            logging.info(f"[DEBUG] Envoi minimaliste vers /api/Series/update : {payload}")
            res = requests.post(url, json=payload, headers=self.headers, timeout=30)
            res.raise_for_status()
            return True, "Succès"
        except Exception as e:
            logging.error(f"[Erreur Update Summary] {e}")
            return False, str(e)

    def upload_series_cover(self, series_id, cover_url):
        if not self.token and not self.authenticate(): 
            return False, "Non authentifié"
            
        if not cover_url:
            return False, "URL de couverture invalide"
            
        try:
            logging.debug(f"[DEBUG] Téléchargement de la couverture depuis : {cover_url}")
            
            from scrapers import ScraperRegistry
            from urllib.parse import urlparse
            
            parsed = urlparse(cover_url)
            domain = parsed.netloc.lower().split(':')[0]
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            for scraper in ScraperRegistry.get_all():
                if any(domain == d or domain.endswith('.' + d) for d in scraper.proxy_domains):
                    if getattr(scraper, 'proxy_referer', None):
                        headers["Referer"] = scraper.proxy_referer
                    break
            
            # Téléchargement de l'image depuis la source
            img_res = cffi_requests.get(cover_url, headers=headers, impersonate="chrome110", timeout=15)
            
            if img_res.status_code != 200:
                return False, f"Impossible de télécharger l'image (Code {img_res.status_code})"
            
            # 🎯 VRAI CORRECTIF : Encodage en Base64 PUR (SANS aucun préfixe)
            img_base64 = base64.b64encode(img_res.content).decode('utf-8')
            
            upload_url = f"{self.url}/api/Upload/series"
            payload = {
                "id": int(series_id),
                "url": img_base64  # <-- Seulement la chaîne pure, Kavita s'occupe du reste !
            }
            
            res = requests.post(upload_url, json=payload, headers=self.headers, timeout=35)
            
            if res.status_code != 200:
                logging.error(f"[DEBUG] Erreur Upload Cover Kavita : {res.text}")
                return False, f"Code {res.status_code} : {res.text}"
                
            return True, "Couverture mise à jour avec succès"
            
        except Exception as e:
            logging.error(f"[Erreur Upload Cover] {e}")
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
            logging.info(f"[DEBUG] Envoi des IDs externes vers {url} : {payload}")
            res = requests.post(url, json=payload, headers=self.headers, timeout=30)
            
            if res.status_code == 200:
                return True, "Succès"
            else:
                logging.error(f"[DEBUG] Erreur Update IDs : {res.text}")
                return False, f"Code {res.status_code} : {res.text}"
        except Exception as e:
            logging.error(f"[Erreur Update IDs] {e}")
            return False, str(e)

    def get_series_isbn(self, series_id):
        """Récupère le premier ISBN disponible parmi les volumes/chapitres de la série."""
        if not self.token and not self.authenticate(): 
            return None
        try:
            res = requests.get(f"{self.url}/api/Series/volumes?seriesId={series_id}", headers=self.headers, timeout=20)
            if res.status_code == 200:
                volumes = res.json()
                for vol in volumes:
                    raw_isbn = vol.get('isbn')
                    if raw_isbn:
                        return str(raw_isbn).replace('-', '').replace(' ', '').strip()
                        
                    for chap in vol.get('chapters', []):
                        raw_chap_isbn = chap.get('isbn')
                        if raw_chap_isbn:
                            return str(raw_chap_isbn).replace('-', '').replace(' ', '').strip()
        except Exception as e:
            logging.error(f"[Erreur ISBN] {e}")
        return None

    def get_series_deep_metadata(self, series_id):
        """
        Récupère l'ensemble des métadonnées existantes dans Kavita 
        (ISBN, auteurs existants, etc.) de manière sécurisée contre les listes.
        """
        existing = {
            'isbn': self.get_series_isbn(series_id),
            'authors': [],
            'publisher': None,
            'year': None,
            'genres': [],
            'localized_name': None
        }
        
        meta = self.get_series_metadata(series_id)
        if isinstance(meta, list) and len(meta) > 0:
            meta = meta[0]

        if meta and isinstance(meta, dict):
            if meta.get('writers') and isinstance(meta.get('writers'), list):
                existing['authors'] = [w.get('name') for w in meta.get('writers', []) if isinstance(w, dict) and w.get('name')]
                
            if meta.get('publisher'):
                pub = meta.get('publisher')
                if isinstance(pub, dict):
                    existing['publisher'] = pub.get('name')
                elif isinstance(pub, list) and len(pub) > 0 and isinstance(pub[0], dict):
                    existing['publisher'] = pub[0].get('name')
                elif isinstance(pub, str):
                    existing['publisher'] = pub
                    
            if meta.get('releaseYear'):
                existing['year'] = meta.get('releaseYear')
                
            if meta.get('genres') and isinstance(meta.get('genres'), list):
                existing['genres'] = [g.get('title') for g in meta.get('genres', []) if isinstance(g, dict) and g.get('title')]
                
            if meta.get('localizedName'):
                existing['localized_name'] = meta.get('localizedName')
                
        return existing