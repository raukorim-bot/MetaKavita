import logging
import base64
import json
import time
import requests
from curl_cffi import requests as cffi_requests

from typing import Optional, Tuple

from config_manager import get_kavita_http_timeout, filter_enabled_libraries, is_library_enabled
from secure_logging import safe_exc_str

# RE-LOCK : 1 retry max, pause courte, timeout retry plafonné — ne pas doubler
# un KAVITA_HTTP_TIMEOUT de 60–120s sur le chemin chaud d'enrichissement.
_RELOCK_MAX_ATTEMPTS = 2
_RELOCK_RETRY_DELAY_S = 0.5
_RELOCK_RETRY_TIMEOUT_CAP_S = 20


class KavitaAPI:
    """
    Interface d'interaction avec l'API REST de Kavita (v0.8+).
    Gère l'authentification JWT, la normalisation des données, l'ingestion des métadonnées
    et le contournement des verrous internes (C# Lock Guard).
    """

    # Cache en mémoire des types de bibliothèque par série (série_id -> type)
    # Permet de limiter les requêtes HTTP lors du traitement par lots
    _series_lib_type_cache = {}

    def __init__(self, url: str, api_key: str, write_timeout: Optional[int] = None):
        """
        Initialise le client API avec l'URL du serveur et la clé API d'utilisateur.
        Nettoie l'URL pour éviter les doubles slashes.

        `write_timeout` : timeout HTTP (s) pour les POST d'écriture. Si None, lit
        `KAVITA_HTTP_TIMEOUT` via config_manager (défaut 60).
        """
        self.url = url.strip().rstrip('/') if url else ""
        self.api_key = api_key.strip() if api_key else ""
        self.token = None
        self.headers = {}
        self._write_timeout_override = write_timeout

    def _write_timeout(self) -> int:
        if self._write_timeout_override is not None:
            return int(self._write_timeout_override)
        return get_kavita_http_timeout()

    def _post_relock(
        self,
        url: str,
        payload: dict,
        *,
        label: str,
        write_timeout: int,
    ) -> Tuple[bool, str]:
        """POST de re-lock avec un seul retry léger (pas de re-write / re-scrape).

        Returns:
            (sealed, detail) — sealed=True si verrous posés ; False = soft-fail
            (données déjà écrites à l'étape 1, verrous éventuellement ouverts).
        """
        last_detail = "re-lock échoué"
        for attempt in range(1, _RELOCK_MAX_ATTEMPTS + 1):
            timeout = (
                write_timeout
                if attempt == 1
                else min(int(write_timeout), _RELOCK_RETRY_TIMEOUT_CAP_S)
            )
            if attempt > 1:
                logging.info(
                    "🔁 [AUDIT KAVITA] RE-LOCK retry %s/%s (%s, timeout=%ss)",
                    attempt,
                    _RELOCK_MAX_ATTEMPTS,
                    label,
                    timeout,
                )
                time.sleep(_RELOCK_RETRY_DELAY_S)
            try:
                res = requests.post(
                    url, json=payload, headers=self.headers, timeout=timeout
                )
                logging.info(
                    f"   📥 Réponse Kavita (Code {res.status_code}) : {res.text}"
                )
                if res.status_code == 200:
                    return True, "Succès"
                last_detail = f"HTTP {res.status_code}: {res.text}"
                logging.warning(
                    "⚠️ [AUDIT KAVITA] RE-LOCK %s tentative %s → %s",
                    label,
                    attempt,
                    last_detail,
                )
            except Exception as lock_err:
                last_detail = str(lock_err)
                logging.warning(
                    "⚠️ [AUDIT KAVITA] RE-LOCK %s tentative %s échouée (%s)",
                    label,
                    attempt,
                    lock_err,
                )

        logging.warning(
            "⚠️ [AUDIT KAVITA] Écriture %s OK, mais RE-LOCK a échoué après %s tentatives (%s) — "
            "données déjà persistées ; verrous éventuellement ouverts jusqu'au prochain sync "
            "(risque d'écrasement par un scan fichiers Kavita).",
            label,
            _RELOCK_MAX_ATTEMPTS,
            last_detail,
        )
        return False, last_detail

    def authenticate(self) -> bool:
        """
        S'authentifie auprès du serveur Kavita et récupère un jeton JWT Bearer.
        Configure les en-têtes HTTP par défaut pour les requêtes ultérieures.

        Pose ``self.last_auth_error`` (code stable) en cas d'échec pour l'UI :
        ``missing``, ``localhost``, ``http_401``, ``http_other``, ``timeout``,
        ``dns``, ``connection``, ``ssl``, ``unknown``.
        """
        self.last_auth_error = None
        logging.info("[DEBUG] Auth Kavita tentée avec URL: '%s' (clé API non loguée).", self.url)
        if not self.api_key or not self.url:
            self.last_auth_error = "missing"
            return False

        # Depuis un conteneur, localhost = MetaKavita, pas Kavita sur l'hôte.
        host_l = ""
        try:
            from urllib.parse import urlparse
            host_l = (urlparse(self.url).hostname or "").lower()
        except Exception:
            host_l = ""
        if host_l in ("localhost", "127.0.0.1", "::1"):
            logging.error(
                "[Erreur Auth] KAVITA_URL pointe vers localhost (%s) — "
                "injoignable depuis Docker. Utilisez host.docker.internal:<port> "
                "ou le nom de service sur le même réseau.",
                self.url,
            )
            self.last_auth_error = "localhost"
            return False

        try:
            full_url = f"{self.url}/api/Plugin/authenticate"
            params = {"apiKey": self.api_key, "pluginName": "KavitaFetcher"}

            res = requests.post(full_url, params=params, timeout=10)
            res.raise_for_status()

            # Extraction du jeton JWT Bearer
            self.token = res.json().get("token")
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            return True
        except requests.exceptions.HTTPError as e:
            # Sécurité : on masque la clé API en cas d'erreur de journalisation
            code = e.response.status_code if e.response is not None else "?"
            logging.error("[Erreur Auth] Le serveur Kavita a rejeté la requête (Code %s).", code)
            self.last_auth_error = "http_401" if code == 401 else "http_other"
            return False
        except requests.exceptions.Timeout:
            logging.error("[Erreur Auth] Timeout vers Kavita (hôte=%s).", self.url)
            self.last_auth_error = "timeout"
            return False
        except requests.exceptions.SSLError as e:
            logging.error("[Erreur Auth] SSL (%s) hôte=%s", safe_exc_str(e), self.url)
            self.last_auth_error = "ssl"
            return False
        except requests.exceptions.ConnectionError as e:
            msg = safe_exc_str(e).lower()
            logging.error("[Erreur Auth] %s (hôte=%s)", safe_exc_str(e), self.url)
            if "name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
                self.last_auth_error = "dns"
            else:
                self.last_auth_error = "connection"
            return False
        except Exception as e:
            # Ne jamais logger str(e) brut : urllib3 inclut souvent ?apiKey= dans le message
            logging.error("[Erreur Auth] %s (hôte=%s)", safe_exc_str(e), self.url)
            self.last_auth_error = "unknown"
            return False

    def get_libraries(self) -> list:
        """
        Récupère la liste globale de toutes les bibliothèques configurées dans Kavita.
        """
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
    def _normalize_library_type(raw_type) -> str:
        """
        Convertit un type de bibliothèque brut (ID numérique C# ou nom textuel)
        en l'un des 4 types internes MetaKavita : 'Manga', 'Comic', 'Book', ou 'ComicFlexible'.
        """
        if raw_type is None:
            return "Manga"

        val_str = str(raw_type).strip().lower()

        # Type Comic Flexible (ID Kavita : 5) — cascade hybride Comic puis Manga (C35)
        if val_str in ["5", "comic (flexible)", "comicflexible", "comic_flexible", "flexiblecomic"]:
            return "ComicFlexible"
        if "flexible" in val_str and "comic" in val_str:
            return "ComicFlexible"

        # Type Comic strict (ID Kavita : 1)
        if val_str in ["1", "comic", "comics"] or "comic" in val_str:
            return "Comic"

        # Type Livre / Roman (IDs Kavita : 2 et 3)
        if val_str in ["2", "3", "book", "books", "novel", "novels", "lightnovel", "lightnovels", "light novel", "light novels"] or "book" in val_str or "novel" in val_str:
            return "Book"

        # Type Manga / Webtoon / Image par défaut
        return "Manga"

    def get_all_series(self, library_id=None, respect_disabled_filter=True) -> list:
        """
        Récupère l'ensemble des séries d'une bibliothèque spécifique ou de l'instance complète.
        Purge le cache mémoire de type de bibliothèque avant l'exécution.

        respect_disabled_filter: si True (défaut), ignore les bibliothèques listées dans
        DISABLED_LIBRARIES — périmètre **sync** (batch / auto-sync / webhook).
        Passer False pour le dashboard UI ou un inventaire complet (purge cache).
        """
        if not self.token and not self.authenticate():
            return []
        try:
            # Purge du cache pour prendre en compte tout changement dans Kavita
            self.__class__._series_lib_type_cache.clear()

            all_libs = self.get_libraries()
            if respect_disabled_filter:
                all_libs = filter_enabled_libraries(all_libs)
                if library_id and not is_library_enabled(library_id):
                    return []
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
                            # Filtrage de sécurité sur la bibliothèque ciblée
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

    def get_library_type_for_series(self, series_id) -> str:
        """
        Détermine le type de bibliothèque ('Manga', 'Comic', 'Book', 'ComicFlexible')
        associé à une série donnée.
        Utilise un cache mémoire local pour éviter les requêtes HTTP répétitives.
        """
        if int(series_id) in self._series_lib_type_cache:
            return self._series_lib_type_cache[int(series_id)]

        if not self.token and not self.authenticate():
            return "Manga"

        try:
            all_libs = self.get_libraries()
            lib_id_to_type = {lib['id']: self._normalize_library_type(lib.get('type') or lib.get('libraryType') or 0) for lib in all_libs}

            res = requests.get(f"{self.url}/api/Series/{series_id}", headers=self.headers, timeout=10)
            if res.status_code == 200:
                lib_type = lib_id_to_type.get(res.json().get('libraryId'), "Manga")
                self._series_lib_type_cache[int(series_id)] = lib_type
                return lib_type
        except Exception as e:
            logging.error(f"[Erreur Library Type for Series] {e}")

        return "Manga"

    def get_series(self, series_id) -> dict:
        """
        Récupère l'objet SeriesDto principal depuis Kavita (Généralités, Titres, Format).
        Target: GET /api/Series/{series_id}
        """
        if not self.token and not self.authenticate():
            return None
        try:
            res = requests.get(f"{self.url}/api/Series/{series_id}", headers=self.headers, timeout=15)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logging.error(f"[Erreur get_series] {e}")
        return None

    def get_series_metadata(self, series_id) -> dict:
        """
        Récupère l'objet SeriesMetadataDto détaillé depuis Kavita (Auteurs, Tags, Éditeur, Résumé).
        Target: GET /api/Series/metadata?seriesId={series_id}
        """
        if not self.token and not self.authenticate():
            return None
        try:
            res = requests.get(f"{self.url}/api/Series/metadata?seriesId={series_id}", headers=self.headers, timeout=25)
            if res.status_code == 200:
                data = res.json()
                # Sécurité si Kavita retourne une liste [ { ... } ]
                return data[0] if isinstance(data, list) and len(data) > 0 else data
            return None
        except Exception as e:
            logging.error(f"[Erreur Metadata] {e}")
            return None

    def update_series_metadata(self, metadata: dict) -> tuple:
        """
        Met à jour les métadonnées approfondies d'une série (Auteurs, Genres, Tags, Éditeurs, Résumé, etc.).
        Target: POST /api/Series/metadata

        Mécanisme C# Lock Guard à 2 Passages :
        1. Passage 1 : force tous les clés `...Locked` à False pour autoriser l'écriture en base BDD.
        2. Passage 2 : ré-applique le dictionnaire d'origine avec les clés `...Locked` à True pour verrouiller la fiche.

        Returns:
            (ok, message, sealed) — sealed=False si écriture OK mais re-lock échoué.
        """
        if not self.token and not self.authenticate():
            return False, "Non authentifié", False

        try:
            # ASSAINISSEMENT (kavita_api.md §4.1) : le dict `metadata` provient généralement
            # d'un GET /api/Series/metadata et contient des propriétés calculées/système
            # (created, lastModified, totalCount, maxCount, pages, wordCount) qui ne doivent
            # JAMAIS être ré-envoyées en POST. Kavita répond 200 OK même si elles sont présentes,
            # mais leur écho peut déclencher des exceptions de concurrence d'état côté
            # Entity Framework Core ou corrompre silencieusement les compteurs de progression
            # de lecture. On nettoie ici, en amont, pour protéger TOUS les appelants.
            for system_key in ("created", "lastModified", "totalCount", "maxCount", "pages", "wordCount"):
                metadata.pop(system_key, None)

            # ÉTAPE 1 : Déverrouillage dynamique de toutes les clés se terminant par 'Locked'
            metadata_unlock = metadata.copy()
            for key, val in list(metadata_unlock.items()):
                if key.endswith("Locked") and isinstance(val, bool):
                    metadata_unlock[key] = False

            payload_unlock = {"seriesMetadata": metadata_unlock}

            logging.info("👉 [AUDIT KAVITA] Envoi METADATA (Étape 1 : UNLOCK & WRITE)")
            logging.info(f"   📦 Payload : {json.dumps(payload_unlock, ensure_ascii=False)}")

            write_timeout = self._write_timeout()
            res_unlock = requests.post(
                f"{self.url}/api/Series/metadata",
                json=payload_unlock,
                headers=self.headers,
                timeout=write_timeout,
            )
            logging.info(f"   📥 Réponse Kavita (Code {res_unlock.status_code}) : {res_unlock.text}")

            if res_unlock.status_code != 200:
                return False, f"Code {res_unlock.status_code} : {res_unlock.text}", False

            # ÉTAPE 2 : Verrouillage de sécurité pour protéger les métadonnées contre les scans de fichiers futurs
            payload_lock = {"seriesMetadata": metadata}
            logging.info("👉 [AUDIT KAVITA] Envoi METADATA (Étape 2 : RE-LOCK)")

            sealed, lock_detail = self._post_relock(
                f"{self.url}/api/Series/metadata",
                payload_lock,
                label="metadata",
                write_timeout=write_timeout,
            )
            if sealed:
                return True, "Succès", True
            # Soft-success : l'étape 1 a déjà persisté les valeurs (cf. issue SqueezedByte).
            return True, f"Succès (écriture OK ; re-lock échoué: {lock_detail})", False
        except Exception as e:
            logging.error(f"❌ [AUDIT KAVITA] Crash Metadata : {e}")
            return False, str(e), False

    def update_series_general(self, series_id: int, localized_name: str = None, format_val: int = None) -> tuple:
        """
        Met à jour les propriétés générales d'affichage d'une série (Titre alternatif & Sens de lecture/Format).
        Target: POST /api/Series/update

        ⚠️ PARTICULARITÉ KAVITA CRITIQUE (confirmée sur le code source de SeriesController.UpdateSeries) :
        Contrairement à `name`/`sortName` (protégés côté serveur C# par un garde `IsNullOrEmpty`),
        `localizedName` est écrasée par Kavita SANS AUCUNE protection dès que la clé JSON est
        absente du payload : .NET désérialise alors `LocalizedName` à `null`, le contrôleur le
        compare à la valeur normalisée existante en BDD, les juge différentes, et écrase
        silencieusement le titre alternatif à `null`. Pire : `NameLocked`/`SortNameLocked`/
        `LocalizedNameLocked` sont eux aussi réaffectés de façon INCONDITIONNELLE (aucun
        Lock Guard sur ces 3 flags précis), donc un simple appel "je ne veux changer que le
        format" les repasse tous à `false` s'ils sont absents du JSON.
        C'est ce mécanisme qui cassait silencieusement l'extension KOReader "Kamare" : celle-ci
        lit `localizedName` sans vérifier son type, et un JSON `null` (représenté en Lua comme
        une userdata, pas comme `nil`) provoque un crash `bad argument #1 to 'find'`.

        Pour ne plus jamais envoyer de payload partiel dangereux à cet endpoint, on récupère
        systématiquement l'état actuel complet de la série (GET /api/Series/{id}) et on
        réinjecte tel quel tout champ qu'on ne souhaite PAS modifier. Ceci a aussi pour effet
        de réparer automatiquement (au fil des prochains appels) les séries déjà touchées par
        l'ancien bug : dès qu'un `localized_name` valide est refourni par un scraper (passage
        normal du champ 'alt_titles' targeté), il est réécrit et re-verrouillé proprement ;
        et pour les autres, on ne fait plus que refléter l'état réel de Kavita au lieu de le
        détruire davantage.
        """
        if not self.token and not self.authenticate():
            return False, "Non authentifié", False

        # Sécurité / perf : ne rien faire (et surtout ne pas déclencher de GET inutile)
        # si aucune modification n'est demandée.
        if localized_name is None and format_val is None:
            return True, "Aucune mise à jour générale", True

        # Snapshot de l'état actuel AVANT toute écriture : c'est la seule façon de savoir
        # ce qu'il ne faut surtout pas nuller (voir avertissement ci-dessus).
        current = self.get_series(series_id)
        if not current:
            return False, "Impossible de récupérer l'état actuel de la série (GET /api/Series/{id} a échoué) — mise à jour annulée par sécurité pour éviter d'écraser localizedName/verrous existants.", False

        current_name = current.get('name')
        current_sort_name = current.get('sortName')
        current_localized_name = current.get('localizedName')
        current_name_locked = bool(current.get('nameLocked', False))
        current_sort_name_locked = bool(current.get('sortNameLocked', False))
        current_localized_name_locked = bool(current.get('localizedNameLocked', False))

        # Base commune : on réinjecte systématiquement l'état actuel de name/sortName et de
        # leurs verrous, pour empêcher Kavita de réinitialiser NameLocked/SortNameLocked à
        # false à chaque appel (effet de bord observé même quand on ne touche qu'au format).
        payload_unlock = {
            "id": int(series_id),
            "name": current_name,
            "sortName": current_sort_name,
            "nameLocked": current_name_locked,
            "sortNameLocked": current_sort_name_locked,
        }

        # Titre alternatif (localizedName)
        if localized_name is not None:
            # Écriture explicite demandée par un scraper : protocole Unlock -> Write -> Lock normal.
            payload_unlock["localizedName"] = localized_name
            payload_unlock["localizedNameLocked"] = False
            final_localized_name = localized_name
            final_localized_name_locked = True
        else:
            # RÉPARATION : on ne veut PAS modifier ce champ, donc on renvoie sa valeur/son
            # verrou ACTUELS tels quels plutôt que de les omettre. C'est ce qui annule
            # l'effet du bug historique (omission = null = destruction côté Kavita).
            payload_unlock["localizedName"] = current_localized_name
            payload_unlock["localizedNameLocked"] = current_localized_name_locked
            final_localized_name = current_localized_name
            final_localized_name_locked = current_localized_name_locked

        payload_lock = dict(payload_unlock)
        payload_lock["localizedName"] = final_localized_name
        payload_lock["localizedNameLocked"] = final_localized_name_locked

        # Sens de lecture / Format (format: 1=Manga, 2=Comic, 3=Novel, 4=Webtoon)
        if format_val is not None:
            payload_unlock["format"] = int(format_val)
            payload_unlock["formatLocked"] = False
            payload_lock["format"] = int(format_val)
            payload_lock["formatLocked"] = True

        try:
            url = f"{self.url}/api/Series/update"
            write_timeout = self._write_timeout()

            # Passage 1 : Écriture en mode déverrouillé
            logging.info("👉 [AUDIT KAVITA] Envoi GÉNÉRAL (Étape 1 : UNLOCK & WRITE)")
            logging.info(f"   📦 Payload : {json.dumps(payload_unlock, ensure_ascii=False)}")

            res_unlock = requests.post(url, json=payload_unlock, headers=self.headers, timeout=write_timeout)
            logging.info(f"   📥 Réponse Kavita (Code {res_unlock.status_code}) : {res_unlock.text}")

            if res_unlock.status_code != 200:
                return False, f"Code {res_unlock.status_code} : {res_unlock.text}", False

            # Passage 2 : Application du verrou de sécurité
            logging.info("👉 [AUDIT KAVITA] Envoi GÉNÉRAL (Étape 2 : RE-LOCK)")
            sealed, lock_detail = self._post_relock(
                url,
                payload_lock,
                label="général",
                write_timeout=write_timeout,
            )
            if sealed:
                return True, "Succès", True
            return True, f"Succès (écriture OK ; re-lock échoué: {lock_detail})", False
        except Exception as e:
            logging.error(f"❌ [AUDIT KAVITA] Crash General : {e}")
            return False, str(e), False

    def seal_series_locks(self, series_id) -> tuple:
        """
        Pose les verrous Kavita sans re-scraper : GET état actuel → POST *Locked=True.

        Utile après un soft-fail re-lock (statut NEEDS_RELOCK). Un seul passage
        (pas d'unlock) : les valeurs sont déjà en base, on scelle seulement.

        Returns:
            (ok, message)
        """
        if not self.token and not self.authenticate():
            return False, "Non authentifié"

        series_id = int(series_id)
        write_timeout = self._write_timeout()

        meta = self.get_series_metadata(series_id)
        if not meta:
            return False, "Impossible de lire les métadonnées Kavita"

        for system_key in ("created", "lastModified", "totalCount", "maxCount", "pages", "wordCount"):
            meta.pop(system_key, None)
        for key, val in list(meta.items()):
            if key.endswith("Locked") and isinstance(val, bool):
                meta[key] = True
        meta["seriesId"] = series_id

        try:
            res_meta = requests.post(
                f"{self.url}/api/Series/metadata",
                json={"seriesMetadata": meta},
                headers=self.headers,
                timeout=write_timeout,
            )
            if res_meta.status_code != 200:
                return False, f"Metadata seal HTTP {res_meta.status_code}: {res_meta.text}"
        except Exception as exc:
            return False, f"Metadata seal: {exc}"

        current = self.get_series(series_id)
        if not current:
            return False, "Metadata scellées ; GET série échoué pour sceller localizedName/format"

        general_payload = {
            "id": series_id,
            "name": current.get("name"),
            "sortName": current.get("sortName"),
            "localizedName": current.get("localizedName"),
            "nameLocked": bool(current.get("nameLocked", False)),
            "sortNameLocked": bool(current.get("sortNameLocked", False)),
            "localizedNameLocked": True,
        }
        if current.get("format") is not None:
            try:
                general_payload["format"] = int(current.get("format"))
                general_payload["formatLocked"] = True
            except (TypeError, ValueError):
                pass

        try:
            res_gen = requests.post(
                f"{self.url}/api/Series/update",
                json=general_payload,
                headers=self.headers,
                timeout=write_timeout,
            )
            if res_gen.status_code != 200:
                return False, f"General seal HTTP {res_gen.status_code}: {res_gen.text}"
        except Exception as exc:
            return False, f"General seal: {exc}"

        return True, "Verrous posés"

    def upload_series_cover(self, series_id, cover_url):
        if not self.token and not self.authenticate():
            return False, "Non authentifié"
        if not cover_url:
            return False, "URL de couverture invalide"

        try:
            from scrapers import ScraperRegistry
            from urllib.parse import urlparse
            from url_allowlist import validate_proxied_image_url, fetch_with_safe_redirects

            allowed_domains = ScraperRegistry.get_all_proxy_domains()
            ok, reason, domain = validate_proxied_image_url(cover_url, allowed_domains)
            if not ok:
                logging.warning("[Upload Cover] URL refusée (%s) : %s", reason, cover_url)
                return False, f"URL de couverture refusée ({reason})"

            parsed = urlparse(cover_url)
            # Détection propre de l'extension (.jpg, .png, .webp)
            ext = "jpg"
            if "." in parsed.path:
                possible_ext = parsed.path.split(".")[-1].lower()
                if possible_ext in ["jpg", "jpeg", "png", "webp"]:
                    ext = possible_ext

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            # Application du Referer si le domaine source exige un bypass hotlink
            for scraper in ScraperRegistry.get_all():
                if any(domain == d or domain.endswith('.' + d) for d in getattr(scraper, 'proxy_domains', [])):
                    if getattr(scraper, 'proxy_referer', None):
                        headers["Referer"] = scraper.proxy_referer
                    break

            # 1. Téléchargement — redirects suivis uniquement vers des hôtes re-validés
            def _cffi_get(u, **kw):
                return cffi_requests.get(u, impersonate="chrome110", **kw)

            img_res, fetch_reason, final_url = fetch_with_safe_redirects(
                _cffi_get,
                cover_url,
                allowed_domains,
                max_hops=3,
                headers=headers,
                timeout=15,
            )
            if img_res is None:
                if fetch_reason == "Client HTTP sans contrôle de redirect":
                    logging.warning("[Upload Cover] curl_cffi sans allow_redirects — fetch annulé par sécurité")
                    return False, "Téléchargement couverture indisponible (client HTTP trop ancien)"
                return False, f"Téléchargement couverture refusé ({fetch_reason})"

            if getattr(img_res, "status_code", None) != 200:
                return False, f"Impossible de télécharger l'image (Code {img_res.status_code})"

            # 2. Conversion en Base64 pur (sans préfixe Data URI)
            img_base64 = base64.b64encode(img_res.content).decode('utf-8')
            if img_base64.startswith("data:"):
                comma_idx = img_base64.find(',')
                if comma_idx >= 0:
                    img_base64 = img_base64[comma_idx + 1:]

            # 3. Payload base64 uniquement — Kavita 0.8+ interprète fileName comme un chemin
            # temporaire côté serveur (upload-by-url), pas comme le nom de sortie. L'envoyer
            # avec du base64 déclenche "Invalid Filename" dans CreateThumbnail().
            upload_url = f"{self.url}/api/Upload/series"
            payload = {
                "id": int(series_id),
                "url": img_base64,
                "lockCover": True
            }

            res = requests.post(upload_url, json=payload, headers=self.headers, timeout=self._write_timeout())

            if res.status_code != 200:
                logging.error("[DEBUG] Erreur Upload Cover Kavita : code %s", res.status_code)
                return False, f"Code {res.status_code}"

            return True, "Couverture mise à jour et verrouillée avec succès"

        except Exception as e:
            logging.error("[Erreur Upload Cover] %s", safe_exc_str(e))
            return False, "Erreur téléchargement couverture"

    def update_series_external_ids(self, series_id: int, anilist_id=None, mal_id=None, mangabaka_id=None) -> tuple:
        """
        Associe les identifiants uniques des plateformes externes (AniList, MyAnimeList, MangaBaka)
        à une série via POST /api/Series/update.

        ⚠️ Ne JAMAIS envoyer un payload partiel (id + IDs seuls) : Kavita nullifie
        `localizedName` et réinitialise les verrous name/sortName/localizedName si ces
        champs sont absents (même bug que celui corrigé dans `update_series_general`).
        On snapshot GET /api/Series/{id} et on réinjecte name / sortName / localizedName /
        verrous + IDs externes existants avant d'écraser uniquement les IDs fournis.
        """
        if not self.token and not self.authenticate():
            return False, "Non authentifié"

        def _coerce_ext_id(raw):
            if raw is None or raw is False:
                return None
            if isinstance(raw, bool):
                return None
            try:
                value = int(str(raw).strip())
            except (TypeError, ValueError):
                logging.warning("[Update IDs] Identifiant externe ignoré (non numérique) : %r", raw)
                return None
            return value if value > 0 else None

        new_anilist = _coerce_ext_id(anilist_id)
        new_mal = _coerce_ext_id(mal_id)
        new_mangabaka = _coerce_ext_id(mangabaka_id)

        if new_anilist is None and new_mal is None and new_mangabaka is None:
            return True, "Aucun ID à mettre à jour"

        current = self.get_series(series_id)
        if not current:
            return False, (
                "Impossible de récupérer l'état actuel de la série "
                "(GET /api/Series/{id} a échoué) — mise à jour des IDs externes annulée "
                "par sécurité pour éviter d'écraser localizedName/verrous existants."
            )

        payload = {
            "id": int(series_id),
            "name": current.get("name"),
            "sortName": current.get("sortName"),
            "localizedName": current.get("localizedName"),
            "nameLocked": bool(current.get("nameLocked", False)),
            "sortNameLocked": bool(current.get("sortNameLocked", False)),
            "localizedNameLocked": bool(current.get("localizedNameLocked", False)),
            "aniListId": current.get("aniListId"),
            "malId": current.get("malId"),
            "mangaBakaId": current.get("mangaBakaId"),
        }

        if new_anilist is not None:
            payload["aniListId"] = new_anilist
        if new_mal is not None:
            payload["malId"] = new_mal
        if new_mangabaka is not None:
            payload["mangaBakaId"] = new_mangabaka

        try:
            url = f"{self.url}/api/Series/update"
            res = requests.post(url, json=payload, headers=self.headers, timeout=self._write_timeout())
            return (True, "Succès") if res.status_code == 200 else (False, f"Code {res.status_code} : {res.text}")
        except Exception as e:
            logging.error(f"[Erreur Update IDs] {e}")
            return False, str(e)

    def get_series_isbn(self, series_id) -> str:
        """
        Analyse les volumes et chapitres d'une série pour extraire le premier ISBN valide disponible.
        Renoie une chaîne d'ISBN nettoyée (sans espaces ni tirets).
        """
        if not self.token and not self.authenticate():
            return None
        try:
            res = requests.get(f"{self.url}/api/Series/volumes?seriesId={series_id}", headers=self.headers, timeout=20)
            if res.status_code == 200:
                for vol in res.json():
                    if vol.get('isbn'):
                        return str(vol.get('isbn')).replace('-', '').replace(' ', '').strip()
                    for chap in vol.get('chapters', []):
                        if chap.get('isbn'):
                            return str(chap.get('isbn')).replace('-', '').replace(' ', '').strip()
        except Exception as e:
            logging.error(f"[Erreur ISBN] {e}")
        return None

    def get_series_deep_metadata(self, series_id) -> dict:
        """
        Récupère l'ensemble du contexte existant d'une série dans Kavita (ISBN, Auteurs, Éditeur, Année, Genres).
        Ce contexte est utilisé par la matrice de scoring de MetaKavita pour ancrer les recherches d'API externes.
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
            # Extraction des auteurs existants (writers)
            if meta.get('writers') and isinstance(meta.get('writers'), list):
                existing['authors'] = [w.get('name') for w in meta.get('writers', []) if isinstance(w, dict) and w.get('name')]

            # Extraction du premier éditeur de la liste 'publishers' (tableau au pluriel)
            if meta.get('publishers') and isinstance(meta.get('publishers'), list) and len(meta.get('publishers')) > 0:
                pub0 = meta['publishers'][0]
                existing['publisher'] = pub0.get('name') if isinstance(pub0, dict) else str(pub0)

            # Extraction de l'année de sortie
            if meta.get('releaseYear'):
                existing['year'] = meta.get('releaseYear')

            # Extraction des genres
            if meta.get('genres') and isinstance(meta.get('genres'), list):
                existing['genres'] = [g.get('title') for g in meta.get('genres', []) if isinstance(g, dict) and g.get('title')]

        # localizedName vit sur SeriesDto (GET /api/Series/{id}), PAS sur Series/metadata.
        series = self.get_series(series_id)
        if series and isinstance(series, dict) and series.get('localizedName'):
            existing['localized_name'] = series.get('localizedName')

        return existing