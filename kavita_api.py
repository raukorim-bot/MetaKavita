import logging
import base64
import json
import time
import requests
from curl_cffi import requests as cffi_requests

from typing import Optional, Tuple

from config_manager import get_kavita_http_timeout
from kavita_constants import LIBRARY_TYPE_BY_ENUM
from secure_logging import safe_exc_str
from translations import get_ui_translations

# RE-LOCK : 1 retry max, pause courte, timeout retry plafonné — ne pas doubler
# un KAVITA_HTTP_TIMEOUT de 60–120s sur le chemin chaud d'enrichissement.
_RELOCK_MAX_ATTEMPTS = 2
_RELOCK_RETRY_DELAY_S = 0.5
_RELOCK_RETRY_TIMEOUT_CAP_S = 20

# Propriétés calculées d'un `SeriesMetadataDto` lu : jamais ré-envoyées en POST.
_SERIES_SYSTEM_KEYS = (
    "created",
    "lastModified",
    "totalCount",
    "maxCount",
    "pages",
    "wordCount",
)

# Verrou de `SeriesMetadataDto` -> champ qu'il protège.
#
# `SeriesService.UpdateSeriesMetadata` assigne ces booléens depuis le DTO SANS
# CONDITION : un verrou envoyé à `True` est fermé, point. Un verrou fermé sur un
# champ vide ne protège donc rien — il interdit seulement au scan de fichiers et
# à Kavita+ de le remplir plus tard. La table sert à ne sceller que ce qui a du
# contenu quand l'appelant ne dit pas quels verrous sa passe a réellement posés.
SERIES_METADATA_LOCK_SOURCES = {
    "summaryLocked": "summary",
    "releaseYearLocked": "releaseYear",
    "publicationStatusLocked": "publicationStatus",
    "languageLocked": "language",
    "genresLocked": "genres",
    "tagsLocked": "tags",
    "ageRatingLocked": "ageRating",
    "writerLocked": "writers",
    "coverArtistLocked": "coverArtists",
    "publisherLocked": "publishers",
    "characterLocked": "characters",
    "pencillerLocked": "pencillers",
    "inkerLocked": "inkers",
    "coloristLocked": "colorists",
    "lettererLocked": "letterers",
    "editorLocked": "editors",
    "translatorLocked": "translators",
    "imprintLocked": "imprints",
    "teamLocked": "teams",
    "locationLocked": "locations",
}

# `POST /api/Upload/series` et `POST /api/Upload/chapter` portent tous deux
# `[RequestSizeLimit(ControllerConstants.MaxUploadSizeBytes)]`, soit 30 Mio, et
# le base64 gonfle le corps de 4/3. Plafonner les octets bruts à 20 Mio laisse
# donc ~26,7 Mio de corps JSON, enveloppe comprise : au-delà, Kavita refuse la
# requête entière avant même de regarder l'image.
MAX_COVER_BYTES = 20 * 1024 * 1024

# Durée maximale du téléchargement d'une couverture, corps compris.
#
# Elle n'est tenue que parce que la requête n'est **pas** en mode flux : avec
# `stream=True`, `curl_cffi` n'applique pas ce délai au corps, qui est consommé
# après le retour de la requête (voir `_cover_http_session`). Mesuré :
# `timeout=5` sur un hôte muet en mode flux attendait toujours à 8 s ; sans le
# mode flux, curl rend « Operation timed out after 5007 ms ».
COVER_FETCH_TIMEOUT_SECONDS = 20


def _cover_http_session():
    """Session `curl_cffi` utilisable sous le worker eventlet.

    `curl_cffi` est libcurl, du C que le monkey-patch d'eventlet n'atteint pas.
    La bibliothèque le sait et prévoit `thread="eventlet"` : son chemin **non
    flux** passe alors `curl.perform()` par `eventlet.tpool`, donc par un vrai
    thread système, et le hub continue de tourner pendant le transfert.

    Son chemin **flux** (`stream=True`), lui, ignore ce réglage : il soumet
    `perform()` à un `ThreadPoolExecutor` et livre les morceaux par une file.
    Sous eventlet, l'attente d'un morceau ne se laisse alors borner par rien —
    le délai de curl ne s'y applique pas, et une échéance vérifiée entre deux
    morceaux n'est jamais atteinte puisque c'est l'attente elle-même qui ne rend
    pas la main. Ce mode laisse en plus derrière lui un exécuteur que
    `Session.close()` ne ferme pas, un par couverture.

    C'est le défaut qui a figé une passe par tome sur sa première unité :
    « 0 / 11 » pendant treize minutes, aucune ligne de journal, et l'application
    par ailleurs vivante — ce qui écartait un blocage du worker et désignait une
    attente que personne ne réveillerait. Reproduit par
    `debug/repro_cover_eventlet.py`.

    Hors eventlet (tests, scripts), une session ordinaire suffit : le délai de
    curl borne déjà le transfert, seule la vivacité du hub demandait le détour.
    """
    try:
        import eventlet.patcher

        if eventlet.patcher.is_monkey_patched("thread"):
            return cffi_requests.Session(thread="eventlet")
    except Exception:
        pass
    return cffi_requests.Session()

# Types que Kavita accepte pour une couverture (`AllowedCoverExtensions` de
# `UploadController`). SVG en est absent côté Kavita — c'est un porteur de
# script, pas une image — donc il ne doit pas non plus partir d'ici.
COVER_IMAGE_MIMES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
})


def _has_content(value) -> bool:
    """Un champ de métadonnées Kavita porte-t-il quelque chose à protéger ?

    Les enums de Kavita valent 0 quand rien n'est connu (`AgeRating.Unknown`,
    `PublicationStatus.OnGoing` que le scan pose par défaut) et un `releaseYear`
    à 0 signifie « pas d'année » : dans les trois cas, un verrou ne protégerait
    aucune donnée.
    """
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return bool(value)

# Identifiants de correspondance externe d'une série. La clé est la même dans
# `SeriesDto` (lecture) et `UpdateSeriesDto` (écriture).
#
# BF106 au carré : `SeriesController.UpdateSeries` appelle
# `ExternalMetadataIdHelper.SetExternalMetadataIds(series, updateSeries)` SANS
# CONDITION, et le helper écrit `entity.X = dto.X ?? 0`. Une clé absente du corps
# JSON arrive en `null` côté .NET, donc remet l'identifiant à zéro — Kavita répond
# 200 et la perte est silencieuse. TOUT payload envoyé à `POST /api/Series/update`
# doit donc porter les sept clés, y compris celui qui ne prétend toucher qu'au
# format ou qu'aux verrous.
SERIES_EXTERNAL_ID_KEYS = (
    "aniListId",
    "malId",
    "hardcoverId",
    "metronId",
    "comicVineId",
    "mangaBakaId",
    "cbrId",
)


def series_external_ids(current: dict) -> dict:
    """Les sept identifiants de correspondance externe d'un `SeriesDto` lu.

    Kavita rend `0` pour « pas d'identifiant » et `0 ?? 0` vaut `0` : la valeur
    lue se renvoie telle quelle, sans conversion ni repli.
    """
    current = current or {}
    return {key: current.get(key) for key in SERIES_EXTERNAL_ID_KEYS}


def lock_keys_from_payload(*payloads) -> list:
    """Les verrous qu'un payload a réellement fermés, pour `seal_series_locks`.

    Sceller à l'aveugle referme des champs que l'utilisateur avait laissés
    ouverts. Le seul endroit qui sait ce qu'une passe a écrit est le payload
    qu'elle a construit : cette fonction en extrait les verrous à `True` pour que
    le rescellement, automatique ou manuel, s'y limite. Accepte plusieurs
    payloads (métadonnées et champs généraux partent séparément).
    """
    keys = []
    for payload in payloads:
        for key, value in (payload or {}).items():
            if key.endswith("Locked") and value is True and key not in keys:
                keys.append(key)
    return keys


class KavitaAPI:
    """
    Interface d'interaction avec l'API REST de Kavita (v0.8+).
    Gère l'authentification JWT, la normalisation des données, l'ingestion des métadonnées
    et le contournement des verrous internes (C# Lock Guard).
    """

    # Cache en mémoire des types de bibliothèque par série (série_id -> type)
    # Permet de limiter les requêtes HTTP lors du traitement par lots
    _series_lib_type_cache = {}
    # Cache en mémoire du libraryId brut par série (série_id -> id), rempli par
    # le même appel HTTP que _series_lib_type_cache (voir get_library_type_for_series).
    _series_library_id_cache = {}

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
        self.t = get_ui_translations()
        # Vrai uniquement après un get_all_series() sans filtre qui a lu toutes
        # les bibliothèques sans erreur. Seul feu vert acceptable pour purger le
        # cache : un inventaire tronqué ferait passer des séries vivantes pour
        # des orphelines (voir db_manager.clean_orphaned_cache).
        self.last_inventory_complete = False

    def _write_timeout(self) -> int:
        if self._write_timeout_override is not None:
            return int(self._write_timeout_override)
        return get_kavita_http_timeout()

    def _send(self, method: str, url: str, **kwargs):
        """Requête portant le jeton, rejouée une fois après ré-auth sur 401.

        Kavita signe un jeton valable trois jours (`TokenService`), et une clé
        d'API peut être révoquée en cours de route. Or une instance de `KavitaAPI`
        vit le temps d'une passe de bibliothèque, qui peut durer des jours : sans
        ce rejeu, la première 401 était définitive pour l'instance — toutes les
        lectures rendaient `None`, toutes les écritures échouaient, et les séries
        traversées étaient malgré tout marquées traitées, donc écartées des passes
        suivantes.

        Rend `None` uniquement quand l'authentification est impossible. Les
        exceptions réseau remontent telles quelles : les appelants les traitent
        déjà, et les confondre avec une absence d'authentification masquerait la
        cause réelle.
        """
        send = getattr(requests, method)
        if not self.token and not self.authenticate():
            return None

        res = send(url, headers=self.headers, **kwargs)
        if getattr(res, "status_code", None) != 401:
            return res

        # 401 sur un appel authentifié = jeton expiré ou clé révoquée. Une seule
        # reprise : si la ré-auth échoue, on rend la 401 telle quelle pour que
        # l'appelant la traite comme un échec plutôt que de boucler.
        logging.info("🔑 [Kavita] 401 sur %s — ré-authentification puis nouvelle tentative", url)
        self.token = None
        if not self.authenticate():
            return res
        return send(url, headers=self.headers, **kwargs)

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
        last_detail = self.t.get("msg_relock_failed", "re-lock échoué")
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
                res = self._send("post", url, json=payload, timeout=timeout)
                if res is None:
                    last_detail = self.t.get("msg_not_authenticated", "Non authentifié")
                    continue
                logging.info(self.t.get("log_kavita_response", "   📥 Réponse Kavita (Code {0}) : {1}").format(res.status_code, res.text))
                if res.status_code == 200:
                    return True, self.t.get("msg_success", "Succès")
                last_detail = f"HTTP {res.status_code}: {res.text}"
                logging.warning(self.t.get("log_kavita_relock_attempt", "⚠️ [AUDIT KAVITA] RE-LOCK {0} tentative {1} → {2}").format(label, attempt, last_detail))
            except Exception as lock_err:
                last_detail = str(lock_err)
                logging.warning(self.t.get("log_kavita_relock_attempt_fail", "⚠️ [AUDIT KAVITA] RE-LOCK {0} tentative {1} échouée ({2})").format(label, attempt, lock_err))

        logging.warning(self.t.get("log_kavita_relock_exhausted", "⚠️ [AUDIT KAVITA] Écriture {0} OK, mais RE-LOCK a échoué après {1} tentatives ({2}) — données déjà persistées ; verrous éventuellement ouverts jusqu'au prochain sync (risque d'écrasement par un scan fichiers Kavita).").format(label, _RELOCK_MAX_ATTEMPTS, last_detail))
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
        # Diagnostic verbeux uniquement en niveau DEBUG (évite le spam INFO à chaque
        # auth : dashboard, préflight /diagnostics, enrichissement, etc.).
        logging.debug(self.t.get("log_kavita_auth_attempt", "Auth Kavita tentée avec URL: {0} (clé API non loguée)").format(self.url))
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
            logging.error(self.t.get("log_kavita_auth_localhost", "[Erreur Auth] KAVITA_URL pointe vers localhost ({0}) — injoignable depuis Docker. Utilisez host.docker.internal:<port> ou le nom de service sur le même réseau.").format(self.url))
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
            logging.error(self.t.get("log_kavita_auth_rejected", "[Erreur Auth] Le serveur Kavita a rejeté la requête (Code {0}).").format(code))
            self.last_auth_error = "http_401" if code == 401 else "http_other"
            return False
        except requests.exceptions.Timeout:
            logging.error(self.t.get("log_kavita_auth_timeout", "[Erreur Auth] Timeout vers Kavita (hôte={0}).").format(self.url))
            self.last_auth_error = "timeout"
            return False
        except requests.exceptions.SSLError as e:
            logging.error(self.t.get("log_kavita_auth_ssl", "[Erreur Auth] SSL ({0}) hôte={1}").format(safe_exc_str(e), self.url))
            self.last_auth_error = "ssl"
            return False
        except requests.exceptions.ConnectionError as e:
            msg = safe_exc_str(e).lower()
            logging.error(self.t.get("log_kavita_auth_host", "[Erreur Auth] {0} (hôte={1})").format(safe_exc_str(e), self.url))
            if "name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
                self.last_auth_error = "dns"
            else:
                self.last_auth_error = "connection"
            return False
        except Exception as e:
            # Ne jamais logger str(e) brut : urllib3 inclut souvent ?apiKey= dans le message
            logging.error(self.t.get("log_kavita_auth_host", "[Erreur Auth] {0} (hôte={1})").format(safe_exc_str(e), self.url))
            self.last_auth_error = "unknown"
            return False

    def get_libraries(self) -> list:
        """
        Récupère la liste globale de toutes les bibliothèques configurées dans Kavita.
        """
        try:
            res = self._send("get", f"{self.url}/api/Library/libraries", timeout=20)
            if res is None:
                return []
            res.raise_for_status()
            return res.json()
        except Exception as e:
            logging.error(self.t.get("log_kavita_lib_err", "[Erreur Libraries] {0}").format(e))
            return []

    @staticmethod
    def _normalize_library_type(raw_type) -> str:
        """
        Convertit un type de bibliothèque brut (ID numérique C# ou nom textuel)
        en l'un des 4 types internes MetaKavita : 'Manga', 'Comic', 'Book', ou 'ComicFlexible'.

        L'identifiant numérique fait foi (voir `LIBRARY_TYPE_BY_ENUM`, calqué sur
        `LibraryType.cs`). Le rattrapage textuel qui suit n'existe que pour les
        `LibraryDto` sérialisés avec le nom du membre plutôt qu'avec sa valeur, et
        il doit distinguer la description « Comic (Flexible) » — qui est `Comic = 1`
        — de la description « Comic » — qui est `ComicVine = 5`.
        """
        if raw_type is None:
            return "Manga"

        val_str = str(raw_type).strip().lower()

        try:
            return LIBRARY_TYPE_BY_ENUM[int(val_str)]
        except (KeyError, TypeError, ValueError):
            pass

        # « Comic (Flexible) » = Comic = 1 : à tester avant « comic » tout court.
        if "flexible" in val_str and "comic" in val_str:
            return "ComicFlexible"
        if val_str in ("comicflexible", "comic_flexible", "flexiblecomic"):
            return "ComicFlexible"

        # « Comic » nu = ComicVine = 5, le parsing strict façon Comic Vine.
        if val_str in ("comic", "comics", "comicvine", "comic vine", "comic_vine"):
            return "Comic"

        # Livres et light novels (Book = 2, LightNovel = 4).
        if "novel" in val_str or "book" in val_str:
            return "Book"

        # Reste : Manga (0), Image (3) et tout ce qui n'est pas reconnu. Les
        # bibliothèques d'images et de webtoons se traitent comme du manga, pas
        # comme un catalogue de livres.
        if "comic" in val_str:
            return "Comic"
        return "Manga"

    def get_all_series(self, library_id=None) -> list:
        """
        Récupère l'ensemble des séries d'une bibliothèque spécifique ou de l'instance complète.
        Purge le cache mémoire de type de bibliothèque avant l'exécution.

        Renvoie toujours l'inventaire complet : DISABLED_LIBRARIES n'est pas lu ici.
        Le filtrage appartient au seul appelant concerné (polling auto-sync, voir
        `services.background_tasks.select_auto_sync_candidates`).

        Pose `self.last_inventory_complete` : les appelants qui purgent le cache
        doivent le tester, une liste tronquée n'étant pas distinguable d'une
        bibliothèque réellement vidée.

        ⚠️ `SeriesFilterV2Dto` ne porte PAS de `libraryId` — il n'a que `Id`,
        `Name`, `Statements`, `Combination`, `SortOptions` et `LimitTo`. Le
        `{"libraryId": …}` qu'on postait était donc ignoré par System.Text.Json,
        et `POST /api/Series/all-v2` rendait tout le catalogue visible, une fois
        par bibliothèque : cinq bibliothèques de 3 000 séries transféraient
        15 000 objets pour en garder 3 000. Un seul appel sans filtre rend
        exactement le même inventaire — `UserParams` est lié en `[FromQuery]` et
        vaut `int.MaxValue` sans paramètre, donc rien n'est tronqué — et la
        répartition se fait localement sur `SeriesDto.libraryId`.
        """
        self.last_inventory_complete = False
        try:
            # Purge du cache pour prendre en compte tout changement dans Kavita
            self.__class__._series_lib_type_cache.clear()

            all_libs = self.get_libraries()
            if library_id:
                libraries_to_scan = [lib for lib in all_libs if str(lib['id']) == str(library_id)]
            else:
                libraries_to_scan = all_libs
            if not libraries_to_scan:
                return []

            types_by_library = {}
            for lib in libraries_to_scan:
                raw_type = lib.get('type') or lib.get('libraryType') or lib.get('LibraryType') or lib.get('Type') or 0
                types_by_library[str(lib['id'])] = (lib['id'], self._normalize_library_type(raw_type))

            series_res = self._send(
                "post", f"{self.url}/api/Series/all-v2", json={}, timeout=10
            )
            if series_res is None:
                return []
            if series_res.status_code != 200:
                logging.warning(
                    self.t.get(
                        "log_kavita_inventory_http_err",
                        "[Kavita] Inventaire des séries indisponible (code {0})",
                    ).format(series_res.status_code)
                )
                return []

            payload = series_res.json()
            if not isinstance(payload, list):
                logging.warning(
                    self.t.get(
                        "log_kavita_inventory_shape",
                        "[Kavita] Inventaire des séries inattendu (pas une liste)",
                    )
                )
                return []

            unique_series = {}
            unattributed = 0
            for s in payload:
                if not isinstance(s, dict) or s.get('id') is None:
                    continue
                known = types_by_library.get(str(s.get('libraryId')))
                if known is None:
                    # Série d'une bibliothèque hors périmètre (filtre explicite) ou
                    # inconnue de /api/Library/libraries : on ne sait pas la typer.
                    unattributed += 1
                    continue
                lib_id, lib_type = known
                s['libraryType'] = lib_type
                s.setdefault('libraryId', lib_id)
                unique_series[s['id']] = s

            if unattributed and not unique_series:
                # Aucune série rattachable : mieux vaut un inventaire vide et non
                # complet qu'une liste que `clean_orphaned_cache` prendrait pour la
                # vérité.
                logging.warning(
                    self.t.get(
                        "log_kavita_inventory_unattributed",
                        "[Kavita] Inventaire non rattachable à une bibliothèque ({0} séries)",
                    ).format(unattributed)
                )
                return []

            all_series = list(unique_series.values())
            all_series.sort(key=lambda x: x.get('name', '').lower())
            # Complet = aucun filtre + inventaire lu sans erreur.
            self.last_inventory_complete = not library_id
            return all_series
        except Exception as e:
            logging.error(self.t.get("log_kavita_global_err", "[Erreur globale] {0}").format(e))
            return []

    def get_library_type_for_series(self, series_id) -> str:
        """
        Détermine le type de bibliothèque ('Manga', 'Comic', 'Book', 'ComicFlexible')
        associé à une série donnée.
        Utilise un cache mémoire local pour éviter les requêtes HTTP répétitives.
        """
        if int(series_id) in self._series_lib_type_cache:
            return self._series_lib_type_cache[int(series_id)]

        try:
            all_libs = self.get_libraries()
            lib_id_to_type = {lib['id']: self._normalize_library_type(lib.get('type') or lib.get('libraryType') or 0) for lib in all_libs}

            res = self._send("get", f"{self.url}/api/Series/{series_id}", timeout=10)
            if res is not None and res.status_code == 200:
                data = res.json()
                lib_type = lib_id_to_type.get(data.get('libraryId'), "Manga")
                self._series_lib_type_cache[int(series_id)] = lib_type
                # Piggybacke le libraryId brut (lien de vérification Kavita en review
                # manuelle, voir get_cached_library_id) : même appel HTTP, pas de coût
                # supplémentaire.
                if data.get('libraryId') is not None:
                    self._series_library_id_cache[int(series_id)] = data.get('libraryId')
                return lib_type
        except Exception as e:
            logging.error(self.t.get("log_kavita_library_type_err", "[Erreur Library Type for Series] {0}").format(e))

        return "Manga"

    def get_cached_library_id(self, series_id):
        """ID de bibliothèque Kavita mis en cache par un appel préalable à
        `get_library_type_for_series` — ne déclenche AUCUN appel réseau. Retourne
        `None` si cette série n'a jamais été résolue dans ce process."""
        return self._series_library_id_cache.get(int(series_id))

    def fetch_series(self, series_id, timeout: float = 15):
        """
        Like get_series but distinguishes failures.

        Returns (series_dict|None, error_code|None) where error_code is one of:
          kavita_auth | kavita_unreachable | series_not_found
        """
        try:
            res = self._send(
                "get", f"{self.url}/api/Series/{series_id}", timeout=timeout
            )
            if res is None:
                return None, "kavita_auth"
            if res.status_code == 200:
                return res.json(), None
            if res.status_code == 404:
                return None, "series_not_found"
            return None, "kavita_unreachable"
        except Exception as e:
            logging.error(self.t.get("log_kavita_get_series_err", "[Erreur get_series] {0}").format(e))
            return None, "kavita_unreachable"

    def get_series(self, series_id) -> dict:
        """
        Récupère l'objet SeriesDto principal depuis Kavita (Généralités, Titres, Format).
        Target: GET /api/Series/{series_id}
        """
        data, _err = self.fetch_series(series_id)
        return data

    def get_series_metadata(self, series_id) -> dict:
        """
        Récupère l'objet SeriesMetadataDto détaillé depuis Kavita (Auteurs, Tags, Éditeur, Résumé).
        Target: GET /api/Series/metadata?seriesId={series_id}
        """
        try:
            res = self._send(
                "get", f"{self.url}/api/Series/metadata?seriesId={series_id}", timeout=25
            )
            if res is None:
                return None
            if res.status_code == 200:
                data = res.json()
                # Sécurité si Kavita retourne une liste [ { ... } ]
                return data[0] if isinstance(data, list) and len(data) > 0 else data
            return None
        except Exception as e:
            logging.error(self.t.get("log_kavita_metadata_err", "[Erreur Metadata] {0}").format(e))
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
            return False, self.t.get("msg_not_authenticated", "Non authentifié"), False

        try:
            # ASSAINISSEMENT (kavita_api.md §4.1) : le dict `metadata` provient généralement
            # d'un GET /api/Series/metadata et contient des propriétés calculées/système
            # (created, lastModified, totalCount, maxCount, pages, wordCount) qui ne doivent
            # JAMAIS être ré-envoyées en POST. Kavita répond 200 OK même si elles sont présentes,
            # mais leur écho peut déclencher des exceptions de concurrence d'état côté
            # Entity Framework Core ou corrompre silencieusement les compteurs de progression
            # de lecture. On nettoie ici, en amont, pour protéger TOUS les appelants.
            #
            # L'assainissement travaille sur une copie : purger le dictionnaire de
            # l'appelant lui retirerait des clés qu'il n'a pas demandé à perdre.
            metadata = {k: v for k, v in metadata.items() if k not in _SERIES_SYSTEM_KEYS}

            # ÉTAPE 1 : Déverrouillage dynamique de toutes les clés se terminant par 'Locked'
            metadata_unlock = metadata.copy()
            for key, val in list(metadata_unlock.items()):
                if key.endswith("Locked") and isinstance(val, bool):
                    metadata_unlock[key] = False

            payload_unlock = {"seriesMetadata": metadata_unlock}

            logging.info(self.t.get("log_kavita_audit_meta_unlock", "👉 [AUDIT KAVITA] Envoi METADATA (Étape 1 : UNLOCK & WRITE)"))
            logging.info(f"   📦 Payload : {json.dumps(payload_unlock, ensure_ascii=False)}")

            write_timeout = self._write_timeout()
            res_unlock = self._send(
                "post",
                f"{self.url}/api/Series/metadata",
                json=payload_unlock,
                timeout=write_timeout,
            )
            if res_unlock is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié"), False
            logging.info(self.t.get("log_kavita_response", "   📥 Réponse Kavita (Code {0}) : {1}").format(res_unlock.status_code, res_unlock.text))

            if res_unlock.status_code != 200:
                return False, f"Code {res_unlock.status_code} : {res_unlock.text}", False

            # ÉTAPE 2 : Verrouillage de sécurité pour protéger les métadonnées contre les scans de fichiers futurs
            payload_lock = {"seriesMetadata": metadata}
            logging.info(self.t.get("log_kavita_audit_meta_relock", "👉 [AUDIT KAVITA] Envoi METADATA (Étape 2 : RE-LOCK)"))

            sealed, lock_detail = self._post_relock(
                f"{self.url}/api/Series/metadata",
                payload_lock,
                label="metadata",
                write_timeout=write_timeout,
            )
            if sealed:
                return True, self.t.get("msg_success", "Succès"), True
            # Soft-success : l'étape 1 a déjà persisté les valeurs (cf. issue SqueezedByte).
            return True, self.t.get("msg_success_relock_fail", "Succès (écriture OK ; re-lock échoué: {0})").format(lock_detail), False
        except Exception as e:
            logging.error(self.t.get("log_kavita_audit_crash_meta", "❌ [AUDIT KAVITA] Crash Metadata : {0}").format(e))
            return False, str(e), False

    def update_series_general(self, series_id: int, localized_name: str = None, format_val: int = None) -> tuple:
        """
        Met à jour le titre alternatif d'une série (`localizedName`).
        Target: POST /api/Series/update

        ⚠️ `format_val` EST IGNORÉ, et ce n'est pas un oubli. `UpdateSeriesDto` ne
        porte ni `Format` ni `FormatLocked` — vérifié sur les sources Kavita de la
        0.5.0 à la 0.9.0.20, le champ n'y a jamais existé. System.Text.Json ignorait
        donc silencieusement les deux clés : Kavita répondait 200 et rien n'était
        écrit. Le sens de lecture est une préférence de lecteur
        (`AppUserPreferences.ReadingDirection`), pas une propriété de série, et
        aucun endpoint ne permet de l'imposer série par série. Le paramètre reste
        accepté pour ne pas casser les appelants ; il ne déclenche plus aucun appel.

        ⚠️ PARTICULARITÉ KAVITA CRITIQUE (confirmée sur le code source de SeriesController.UpdateSeries) :
        Contrairement à `name`/`sortName` (protégés côté serveur C# par un garde `IsNullOrEmpty`),
        `localizedName` est écrasée par Kavita SANS AUCUNE protection dès que la clé JSON est
        absente du payload : .NET désérialise alors `LocalizedName` à `null`, le contrôleur le
        compare à la valeur normalisée existante en BDD, les juge différentes, et écrase
        silencieusement le titre alternatif à `null`. Pire : `NameLocked`/`SortNameLocked`/
        `LocalizedNameLocked` sont eux aussi réaffectés de façon INCONDITIONNELLE (aucun
        Lock Guard sur ces 3 flags précis), donc un simple appel "je ne veux changer que le
        format" les repasse tous à `false` s'ils sont absents du JSON. `CoverImageLocked`
        (BF106) est encore plus destructeur : le passage true -> false vide `CoverImage` et
        replanifie une génération de couverture depuis les fichiers.
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
            return False, self.t.get("msg_not_authenticated", "Non authentifié"), False

        if format_val is not None:
            logging.debug(
                "[Kavita] Sens de lecture %s ignoré : UpdateSeriesDto ne porte pas de format.",
                format_val,
            )

        # Sécurité / perf : ne rien faire (et surtout ne pas déclencher de GET inutile)
        # si aucune modification n'est demandée. Un appel qui ne portait qu'un format
        # est désormais dans ce cas : il n'aurait rien écrit et coûtait un GET plus
        # deux POST par série.
        if localized_name is None:
            return True, self.t.get("msg_no_general_update", "Aucune mise à jour générale"), True

        # Snapshot de l'état actuel AVANT toute écriture : c'est la seule façon de savoir
        # ce qu'il ne faut surtout pas nuller (voir avertissement ci-dessus).
        current = self.get_series(series_id)
        if not current:
            return False, self.t.get("msg_current_series_failed", "Impossible de récupérer l'état actuel de la série (GET /api/Series/{id} a échoué) — mise à jour annulée par sécurité pour éviter d'écraser localizedName/verrous existants."), False

        current_name = current.get('name')
        current_sort_name = current.get('sortName')
        current_localized_name = current.get('localizedName')
        current_name_locked = bool(current.get('nameLocked', False))
        current_sort_name_locked = bool(current.get('sortNameLocked', False))
        current_localized_name_locked = bool(current.get('localizedNameLocked', False))
        # BF106 — `coverImageLocked` appartient à la même famille de flags sans Lock
        # Guard que les trois ci-dessus, mais avec une conséquence bien plus violente :
        # quand Kavita voit un verrou passer de true à false, il ne se contente pas de
        # déverrouiller, il EFFACE `CoverImage` et replanifie une génération depuis les
        # fichiers. Omettre la clé (donc envoyer false par défaut .NET) après un choix
        # manuel de couverture — qui, lui, upload avec `lockCover: True` — détruisait
        # donc la couverture choisie au sync suivant, sans rien remettre à la place :
        # la couverture étant marquée comme choix manuel (voir `cover_manual`),
        # MetaKavita l'épargne et ne réuploade pas.
        current_cover_locked = bool(current.get('coverImageLocked', False))

        # Base commune : on réinjecte systématiquement l'état actuel de name/sortName et de
        # leurs verrous, pour empêcher Kavita de réinitialiser NameLocked/SortNameLocked à
        # false à chaque appel.
        #
        # `dontMatch` n'y figure pas : la propriété n'est pas sur `UpdateSeriesDto`.
        # Kavita l'expose par `POST /api/Series/dont-match?seriesId=&dontMatch=`, et
        # la clé qu'on glissait ici était purement décorative — ni lue, ni écrite.
        payload_unlock = {
            "id": int(series_id),
            "name": current_name,
            "sortName": current_sort_name,
            "nameLocked": current_name_locked,
            "sortNameLocked": current_sort_name_locked,
            "coverImageLocked": current_cover_locked,
            # Même leçon que `localizedName` / `coverImageLocked`, appliquée aux
            # sept identifiants de correspondance externe : les omettre les remet
            # à zéro. Cet appel part APRÈS `update_series_external_ids()` dans
            # `apply_kavita_payload()`, si bien que l'écriture d'un simple titre
            # alternatif annulait les identifiants tout juste posés.
            **series_external_ids(current),
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

        try:
            url = f"{self.url}/api/Series/update"
            write_timeout = self._write_timeout()

            # Passage 1 : Écriture en mode déverrouillé
            logging.info(self.t.get("log_kavita_audit_general_unlock", "👉 [AUDIT KAVITA] Envoi GÉNÉRAL (Étape 1 : UNLOCK & WRITE)"))
            logging.info(f"   📦 Payload : {json.dumps(payload_unlock, ensure_ascii=False)}")

            res_unlock = self._send("post", url, json=payload_unlock, timeout=write_timeout)
            if res_unlock is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié"), False
            logging.info(self.t.get("log_kavita_response", "   📥 Réponse Kavita (Code {0}) : {1}").format(res_unlock.status_code, res_unlock.text))

            if res_unlock.status_code != 200:
                return False, f"Code {res_unlock.status_code} : {res_unlock.text}", False

            # Passage 2 : Application du verrou de sécurité
            logging.info(self.t.get("log_kavita_audit_general_relock", "👉 [AUDIT KAVITA] Envoi GÉNÉRAL (Étape 2 : RE-LOCK)"))
            sealed, lock_detail = self._post_relock(
                url,
                payload_lock,
                label=self.t.get("label_general", "général"),
                write_timeout=write_timeout,
            )
            if sealed:
                return True, self.t.get("msg_success", "Succès"), True
            return True, self.t.get("msg_success_relock_fail", "Succès (écriture OK ; re-lock échoué: {0})").format(lock_detail), False
        except Exception as e:
            logging.error(self.t.get("log_kavita_audit_crash_general", "❌ [AUDIT KAVITA] Crash General : {0}").format(e))
            return False, str(e), False

    def seal_series_locks(self, series_id, *, lock_keys=None) -> tuple:
        """
        Pose les verrous Kavita sans re-scraper : GET état actuel → POST *Locked.

        Utile après un soft-fail re-lock (statut NEEDS_RELOCK). Un seul passage
        (pas d'unlock) : les valeurs sont déjà en base, on scelle seulement.

        `lock_keys` est la liste des verrous que la passe a effectivement posés,
        c'est-à-dire les clés `...Locked` à `True` du payload d'origine. Elle est
        nécessaire parce que `SeriesService` assigne ces booléens depuis le DTO
        SANS CONDITION : un verrou envoyé à `True` est fermé, y compris sur un
        champ que l'utilisateur avait laissé ouvert exprès pour que le scan de
        fichiers le rafraîchisse. Fermer tous les verrous, comme on le faisait,
        figeait donc des champs que MetaKavita n'avait jamais écrits, sans que
        rien ne le signale.

        Sans cette liste, on se replie sur les verrous dont le champ porte
        réellement quelque chose : un verrou sur un champ vide ne protège aucune
        donnée, il interdit seulement de le remplir plus tard. Un verrou déjà
        fermé n'est jamais rouvert.

        Returns:
            (ok, message)
        """
        if not self.token and not self.authenticate():
            return False, self.t.get("msg_not_authenticated", "Non authentifié")

        series_id = int(series_id)
        write_timeout = self._write_timeout()
        wanted = None if lock_keys is None else {str(k) for k in lock_keys}

        meta = self.get_series_metadata(series_id)
        if not meta:
            return False, self.t.get("msg_metadata_read_failed", "Impossible de lire les métadonnées Kavita")

        meta = {k: v for k, v in meta.items() if k not in _SERIES_SYSTEM_KEYS}
        for key, val in list(meta.items()):
            if not key.endswith("Locked") or not isinstance(val, bool):
                continue
            meta[key] = self._should_seal(key, meta, wanted)
        meta["seriesId"] = series_id

        try:
            res_meta = self._send(
                "post",
                f"{self.url}/api/Series/metadata",
                json={"seriesMetadata": meta},
                timeout=write_timeout,
            )
            if res_meta is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié")
            if res_meta.status_code != 200:
                return False, f"Metadata seal HTTP {res_meta.status_code}: {res_meta.text}"
        except Exception as exc:
            return False, f"Metadata seal: {exc}"

        current = self.get_series(series_id)
        if not current:
            return False, self.t.get("msg_metadata_sealed_general_failed", "Metadata scellées ; GET série échoué pour sceller localizedName")

        # Un titre alternatif absent ne se verrouille pas : le fermer empêcherait
        # Kavita de le renseigner sans rien protéger en échange.
        if wanted is not None:
            seal_localized = "localizedNameLocked" in wanted
        else:
            seal_localized = _has_content(current.get("localizedName"))

        general_payload = {
            "id": series_id,
            "name": current.get("name"),
            "sortName": current.get("sortName"),
            "localizedName": current.get("localizedName"),
            "nameLocked": bool(current.get("nameLocked", False)),
            "sortNameLocked": bool(current.get("sortNameLocked", False)),
            "localizedNameLocked": bool(current.get("localizedNameLocked", False)) or seal_localized,
            # BF106 : omettre le flag revient à demander un déverrouillage, que Kavita
            # traduit par « efface la couverture et régénère-la depuis les fichiers ».
            "coverImageLocked": bool(current.get("coverImageLocked", False)),
            # Sceller des verrous ne doit rien détruire au passage : sans ces sept
            # clés, le bouton 🔒 remettait à zéro les correspondances Hardcover /
            # Metron / ComicVine / CBR / AniList / MAL / MangaBaka de la série.
            **series_external_ids(current),
        }

        try:
            res_gen = self._send(
                "post",
                f"{self.url}/api/Series/update",
                json=general_payload,
                timeout=write_timeout,
            )
            if res_gen is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié")
            if res_gen.status_code != 200:
                return False, f"General seal HTTP {res_gen.status_code}: {res_gen.text}"
        except Exception as exc:
            return False, f"General seal: {exc}"

        return True, self.t.get("msg_locks_set", "Verrous posés")

    @staticmethod
    def _should_seal(lock_key: str, meta: dict, wanted) -> bool:
        """Faut-il fermer ce verrou de métadonnées ? Jamais le rouvrir."""
        if bool(meta.get(lock_key)):
            return True
        if wanted is not None:
            return lock_key in wanted
        source = SERIES_METADATA_LOCK_SOURCES.get(lock_key)
        if source is None:
            # Verrou que MetaKavita ne connaît pas : on reflète l'état lu plutôt
            # que de décider à la place de l'utilisateur.
            return False
        return _has_content(meta.get(source))

    def _download_cover_base64(self, cover_url) -> Tuple[Optional[str], str]:
        """Télécharge une couverture et la rend en base64 pur.

        Partagé par l'upload série et l'upload chapitre : l'allowlist de
        domaines, le bypass hotlink et le contrôle des redirections doivent
        valoir pour les deux, sans quoi le chemin tome deviendrait la porte
        dérobée du chemin série.

        Le corps est refusé s'il n'annonce pas un type image, et plafonné à
        `MAX_COVER_BYTES` : `POST /api/Upload/{series,chapter}` refusent la
        requête entière au-delà de 30 Mio et le base64 gonfle de 4/3, si bien
        qu'une image un peu lourde partait pour rien. Le contrôle de type, lui,
        évite le cas concret d'un hôte autorisé qui rend une page d'erreur HTML
        en 200 : sans lui, la page était encodée et envoyée comme couverture.
        C'est la même règle que le proxy d'images (`routes/misc.py`), qui la
        pratique déjà.
        """
        from scrapers import ScraperRegistry
        from url_allowlist import validate_proxied_image_url, fetch_with_safe_redirects

        allowed_domains = ScraperRegistry.get_all_proxy_domains()
        ok, reason, domain = validate_proxied_image_url(cover_url, allowed_domains)
        if not ok:
            logging.warning(self.t.get("log_cover_url_refused_log", "[Upload Cover] URL refusée ({0}) : {1}").format(reason, cover_url))
            return None, self.t.get("msg_cover_url_refused", "URL de couverture refusée ({0})").format(reason)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        for scraper in ScraperRegistry.get_all(include_disabled=True):
            if any(domain == d or domain.endswith('.' + d) for d in getattr(scraper, 'proxy_domains', []) or []):
                if getattr(scraper, 'proxy_referer', None):
                    headers["Referer"] = scraper.proxy_referer
                break

        # Pas de `stream=True` : sous eventlet, l'attente d'un morceau n'y est
        # bornée par rien (voir `_cover_http_session`). Le corps est donc lu par
        # curl lui-même, sous son délai, et le plafond de taille s'applique sur
        # la réponse complète. La session est fermée dans tous les cas, comme la
        # réponse : sous le worker eventlet unique, une connexion abandonnée est
        # un greenthread perdu.
        session = _cover_http_session()

        def _cffi_get(u, **kw):
            return session.get(u, impersonate="chrome110", **kw)

        try:
            try:
                img_res, fetch_reason, final_url = fetch_with_safe_redirects(
                    _cffi_get,
                    cover_url,
                    allowed_domains,
                    max_hops=3,
                    headers=headers,
                    timeout=COVER_FETCH_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                # Un hôte muet rend maintenant une erreur de curl au bout du
                # délai, là où le mode flux attendait sans fin. Elle est nommée
                # ici plutôt que remontée : une couverture est un extra, et la
                # passe doit continuer sans elle.
                logging.warning(
                    self.t.get(
                        "log_cover_fetch_failed",
                        "[Upload Cover] Téléchargement abandonné ({0}) : {1}",
                    ).format(safe_exc_str(exc), cover_url)
                )
                return None, self.t.get(
                    "msg_cover_fetch_failed",
                    "Téléchargement de la couverture impossible (délai de {0} s dépassé ou hôte injoignable)",
                ).format(COVER_FETCH_TIMEOUT_SECONDS)
            if img_res is None:
                if fetch_reason == "Client HTTP sans contrôle de redirect":
                    logging.warning(self.t.get("log_cover_curl_no_redirect", "[Upload Cover] curl_cffi sans allow_redirects — fetch annulé par sécurité"))
                    return None, self.t.get("msg_cover_client_old", "Téléchargement couverture indisponible (client HTTP trop ancien)")
                return None, self.t.get("msg_cover_download_refused", "Téléchargement couverture refusé ({0})").format(fetch_reason)

            try:
                if getattr(img_res, "status_code", None) != 200:
                    return None, self.t.get("msg_cover_download_http", "Impossible de télécharger l'image (Code {0})").format(img_res.status_code)

                res_headers = getattr(img_res, "headers", None) or {}
                # Content-Type absent : on laisse passer, certains CDN n'en
                # envoient pas et Kavita valide le contenu de son côté.
                declared_type = (res_headers.get("Content-Type") or "image/jpeg").split(";")[0].strip().lower()
                if declared_type not in COVER_IMAGE_MIMES and not declared_type.startswith("image/"):
                    logging.warning(self.t.get("log_cover_ctype_refused", "[Upload Cover] Content-Type non image refusé ({0}) : {1}").format(declared_type, final_url))
                    return None, self.t.get("msg_cover_not_an_image", "La réponse n'est pas une image ({0})").format(declared_type)

                # `Content-Length` n'est qu'une indication — un hôte peut l'omettre,
                # mentir, ou répondre en chunked où elle n'existe pas. On la lit
                # pour renoncer avant même de regarder le corps ; le contrôle
                # ci-dessous est ce qui applique réellement le plafond.
                declared_length = res_headers.get("Content-Length")
                if declared_length is not None:
                    try:
                        if int(declared_length) > MAX_COVER_BYTES:
                            logging.warning(self.t.get("log_cover_too_large", "[Upload Cover] Image trop volumineuse ({0} octets) : {1}").format(declared_length, final_url))
                            return None, self.t.get("msg_cover_too_large", "Image trop volumineuse pour Kavita (plafond {0} octets)").format(MAX_COVER_BYTES)
                    except (TypeError, ValueError):
                        pass

                # Le corps est déjà là : curl l'a lu sous son propre délai. Le
                # plafond se vérifie donc après coup, sur ce qui est arrivé, et
                # non morceau par morceau — ce que le mode flux permettait au
                # prix d'une attente que rien ne bornait.
                chunks = getattr(img_res, "content", None) or b""
                if len(chunks) > MAX_COVER_BYTES:
                    logging.warning(self.t.get("log_cover_too_large", "[Upload Cover] Image trop volumineuse ({0} octets) : {1}").format(len(chunks), final_url))
                    return None, self.t.get("msg_cover_too_large", "Image trop volumineuse pour Kavita (plafond {0} octets)").format(MAX_COVER_BYTES)

                if not chunks:
                    return None, self.t.get("msg_cover_empty", "Image vide")

                return base64.b64encode(bytes(chunks)).decode('utf-8'), ""
            finally:
                closer = getattr(img_res, "close", None)
                if callable(closer):
                    closer()
        finally:
            session.close()

    def get_chapter(self, chapter_id) -> Optional[dict]:
        """`ChapterDto` complet (`GET /api/Chapter?chapterId=`), None si échec.

        C'est la seule base acceptable pour une écriture : `UpdateChapterDto`
        remplace tout, donc écrire sans avoir lu revient à effacer.
        """
        try:
            res = self._send(
                "get", f"{self.url}/api/Chapter?chapterId={int(chapter_id)}", timeout=20
            )
            if res is None:
                return None
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, dict) else None
            logging.warning(
                self.t.get("log_chapter_get_http", "[Chapitre] GET {0} : code {1}").format(chapter_id, res.status_code)
            )
        except Exception as e:
            logging.error(self.t.get("log_chapter_get_err", "[Chapitre] Lecture {0} impossible : {1}").format(chapter_id, safe_exc_str(e)))
        return None

    def update_chapter_metadata(self, dto: dict) -> Tuple[bool, str]:
        """`POST /api/Chapter/update` avec un payload complet.

        Le payload doit venir de `services.kavita_chapter_payload
        .build_update_chapter_dto`, qui recopie l'état lu avant d'appliquer les
        changements. N'appelez jamais cette méthode avec un dict partiel.
        """
        if not self.token and not self.authenticate():
            return False, self.t.get("msg_not_authenticated", "Non authentifié")
        if not isinstance(dto, dict) or not dto.get("id"):
            return False, self.t.get("msg_chapter_payload_invalid", "Payload chapitre invalide (id manquant)")
        try:
            res = self._send(
                "post",
                f"{self.url}/api/Chapter/update",
                json=dto,
                timeout=self._write_timeout(),
            )
            if res is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié")
            if res.status_code == 200:
                return True, self.t.get("msg_success", "Succès")
            return False, f"Code {res.status_code} : {res.text}"
        except Exception as e:
            logging.error(self.t.get("log_chapter_update_err", "[Chapitre] Écriture {0} impossible : {1}").format(dto.get("id"), safe_exc_str(e)))
            return False, str(e)

    def upload_chapter_cover(self, chapter_id, cover_url, lock: bool = True) -> Tuple[bool, str]:
        """`POST /api/Upload/chapter` — pose aussi la couverture du tome parent.

        Kavita recopie l'image et le verrou sur le volume qui contient le
        chapitre : c'est ce qui fait apparaître la couverture sur la tuile du
        tome, et pas seulement à l'intérieur.
        """
        if not self.token and not self.authenticate():
            return False, self.t.get("msg_not_authenticated", "Non authentifié")
        if not cover_url:
            return False, self.t.get("msg_cover_invalid", "URL de couverture invalide")

        try:
            # Deux durées, séparées : le téléchargement chez le fournisseur et
            # l'envoi à Kavita, qui reçoit du base64 (un tiers plus lourd que
            # l'image) puis génère sa vignette. C'est le poste le plus coûteux de
            # l'enrichissement par tome, et les journaux ne disaient pas lequel
            # des deux traînait.
            started = time.monotonic()
            img_base64, err = self._download_cover_base64(cover_url)
            downloaded = time.monotonic()
            if not img_base64:
                return False, err

            res = self._send(
                "post",
                f"{self.url}/api/Upload/chapter",
                json={"id": int(chapter_id), "url": img_base64, "lockCover": bool(lock)},
                timeout=self._write_timeout(),
            )
            logging.debug(
                "[Upload Cover] chapitre %s : téléchargement=%.2fs envoi=%.2fs",
                chapter_id,
                downloaded - started,
                time.monotonic() - downloaded,
            )
            if res is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié")
            if res.status_code != 200:
                logging.error(self.t.get("log_cover_upload_http_err", "[Upload Cover] Erreur Kavita : code {0}").format(res.status_code))
                return False, f"Code {res.status_code}"
            return True, self.t.get("msg_cover_updated", "Couverture mise à jour et verrouillée avec succès")
        except Exception as e:
            logging.error(self.t.get("log_cover_upload_err", "[Erreur Upload Cover] {0}").format(safe_exc_str(e)))
            return False, self.t.get("msg_cover_download_error", "Erreur téléchargement couverture")

    def upload_series_cover(self, series_id, cover_url):
        if not self.token and not self.authenticate():
            return False, self.t.get("msg_not_authenticated", "Non authentifié")
        if not cover_url:
            return False, self.t.get("msg_cover_invalid", "URL de couverture invalide")

        try:
            img_base64, err = self._download_cover_base64(cover_url)
            if not img_base64:
                return False, err

            # Payload base64 uniquement — Kavita 0.8+ interprète fileName comme un chemin
            # temporaire côté serveur (upload-by-url), pas comme le nom de sortie. L'envoyer
            # avec du base64 déclenche "Invalid Filename" dans CreateThumbnail().
            upload_url = f"{self.url}/api/Upload/series"
            payload = {
                "id": int(series_id),
                "url": img_base64,
                "lockCover": True
            }

            res = self._send("post", upload_url, json=payload, timeout=self._write_timeout())
            if res is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié")

            if res.status_code != 200:
                logging.error(self.t.get("log_cover_upload_http_err", "[Upload Cover] Erreur Kavita : code {0}").format(res.status_code))
                return False, f"Code {res.status_code}"

            return True, self.t.get("msg_cover_updated", "Couverture mise à jour et verrouillée avec succès")

        except Exception as e:
            logging.error(self.t.get("log_cover_upload_err", "[Erreur Upload Cover] {0}").format(safe_exc_str(e)))
            return False, self.t.get("msg_cover_download_error", "Erreur téléchargement couverture")

    def update_series_external_ids(self, series_id: int, anilist_id=None, mal_id=None, mangabaka_id=None) -> tuple:
        """
        Associe les identifiants uniques des plateformes externes (AniList, MyAnimeList, MangaBaka)
        à une série via POST /api/Series/update.

        ⚠️ Ne JAMAIS envoyer un payload partiel (id + IDs seuls) : Kavita nullifie
        `localizedName` et réinitialise les verrous name/sortName/localizedName si ces
        champs sont absents (même bug que celui corrigé dans `update_series_general`).
        On snapshot GET /api/Series/{id} et on réinjecte name / sortName / localizedName /
        verrous + IDs externes existants avant d'écraser uniquement les IDs fournis.

        BF122 — `coverImageLocked` appartient à la même famille et doit être
        réinjecté ici EXACTEMENT comme dans `update_series_general`
        (voir le commentaire BF106 là-bas) : un verrou de couverture qui passe de
        `true` à `false` fait effacer `CoverImage` à Kavita et replanifier une
        génération depuis les fichiers. Cet appel part en premier dans
        `apply_kavita_payload()`, avant l'étape couverture — elle-même sautée quand
        la couverture est un choix manuel — donc l'oubli détruisait la couverture
        choisie à la main sans rien remettre à la place.

        BF140 — même mécanisme pour les sept identifiants de correspondance externe
        (`SERIES_EXTERNAL_ID_KEYS`) : n'en envoyer que trois remettait les quatre
        autres à zéro. Ils sont désormais tous relus depuis l'état courant avant
        d'écraser uniquement ceux qui sont fournis.
        """
        if not self.token and not self.authenticate():
            return False, self.t.get("msg_not_authenticated", "Non authentifié")

        def _coerce_ext_id(raw):
            if raw is None or raw is False:
                return None
            if isinstance(raw, bool):
                return None
            try:
                value = int(str(raw).strip())
            except (TypeError, ValueError):
                logging.warning(self.t.get("log_ext_id_ignored", "[Update IDs] Identifiant externe ignoré (non numérique) : {0!r}").format(raw))
                return None
            return value if value > 0 else None

        new_anilist = _coerce_ext_id(anilist_id)
        new_mal = _coerce_ext_id(mal_id)
        new_mangabaka = _coerce_ext_id(mangabaka_id)

        if new_anilist is None and new_mal is None and new_mangabaka is None:
            return True, self.t.get("msg_no_ids_update", "Aucun ID à mettre à jour")

        current = self.get_series(series_id)
        if not current:
            return False, self.t.get("msg_current_series_ids_failed", "Impossible de récupérer l'état actuel de la série (GET /api/Series/{id} a échoué) — mise à jour des IDs externes annulée par sécurité pour éviter d'écraser localizedName/verrous existants.")

        payload = {
            "id": int(series_id),
            "name": current.get("name"),
            "sortName": current.get("sortName"),
            "localizedName": current.get("localizedName"),
            "nameLocked": bool(current.get("nameLocked", False)),
            "sortNameLocked": bool(current.get("sortNameLocked", False)),
            "localizedNameLocked": bool(current.get("localizedNameLocked", False)),
            "coverImageLocked": bool(current.get("coverImageLocked", False)),
            # `dontMatch` n'est pas sur `UpdateSeriesDto` : Kavita ne l'expose que
            # par `POST /api/Series/dont-match?seriesId=&dontMatch=`.
            # Les sept identifiants, pas seulement les trois qu'on sait écrire :
            # n'envoyer qu'AniList / MAL / MangaBaka effaçait Hardcover, Metron,
            # ComicVine et CBR, que l'utilisateur a pu associer à la main dans
            # Kavita et que MetaKavita n'a aucune raison de toucher.
            **series_external_ids(current),
        }

        if new_anilist is not None:
            payload["aniListId"] = new_anilist
        if new_mal is not None:
            payload["malId"] = new_mal
        if new_mangabaka is not None:
            payload["mangaBakaId"] = new_mangabaka

        try:
            url = f"{self.url}/api/Series/update"
            res = self._send("post", url, json=payload, timeout=self._write_timeout())
            if res is None:
                return False, self.t.get("msg_not_authenticated", "Non authentifié")
            return (True, self.t.get("msg_success", "Succès")) if res.status_code == 200 else (False, f"Code {res.status_code} : {res.text}")
        except Exception as e:
            logging.error(self.t.get("log_update_ids_err", "[Erreur Update IDs] {0}").format(e))
            return False, str(e)

    def fetch_series_volumes(self, series_id) -> Tuple[Optional[list], Optional[str]]:
        """Volumes Kavita (`GET /api/Series/volumes`), en distinguant les échecs.

        Rend `(volumes, None)` — la liste pouvant être vide, une série sans tome
        étant un état parfaitement normal — ou `(None, code)` avec `kavita_auth`,
        `series_not_found` ou `kavita_unreachable`.

        La distinction existe parce que confondre les deux fait marquer une série
        comme traitée pendant une indisponibilité de Kavita, ce qui l'écarte
        définitivement des passes suivantes. Même contrat que `fetch_series`.
        """
        try:
            res = self._send(
                "get", f"{self.url}/api/Series/volumes?seriesId={series_id}", timeout=20
            )
            if res is None:
                return None, "kavita_auth"
            if res.status_code == 200:
                data = res.json()
                return (data, None) if isinstance(data, list) else (None, "kavita_unreachable")
            if res.status_code == 404:
                return None, "series_not_found"
            return None, "kavita_unreachable"
        except Exception as e:
            logging.error(self.t.get("log_volumes_err", "[Erreur Volumes] {0}").format(safe_exc_str(e)))
            return None, "kavita_unreachable"

    def get_series_volumes(self, series_id) -> list:
        """Liste brute des volumes Kavita. [] si erreur / auth.

        Conservé pour les appelants qui n'ont pas besoin de la nuance ; quand
        « série sans tome » et « Kavita muet » ne se traitent pas pareil, c'est
        `fetch_series_volumes` qu'il faut appeler.
        """
        volumes, _err = self.fetch_series_volumes(series_id)
        return volumes or []

    def get_series_isbn(self, series_id) -> str:
        """
        Premier ISBN trouvé dans les chapitres d'une série, nettoyé (sans espaces ni tirets).

        L'ISBN vit sur le chapitre : `VolumeDto` ne porte pas d'`Isbn`, seul
        `ChapterDto` en a un (renseigné par le lecteur ComicInfo). Interroger le
        tome ne rendait donc jamais rien.
        """
        try:
            for vol in self.get_series_volumes(series_id):
                if not isinstance(vol, dict):
                    continue
                for chap in vol.get('chapters') or []:
                    if isinstance(chap, dict) and chap.get('isbn'):
                        return str(chap.get('isbn')).replace('-', '').replace(' ', '').strip()
        except Exception as e:
            logging.error(self.t.get("log_isbn_err", "[Erreur ISBN] {0}").format(e))
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