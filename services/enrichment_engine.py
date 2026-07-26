"""
Moteur d'enrichissement : orchestre le scraping, le mapping et l'envoi vers
Kavita pour UNE série donnée.

Extrait de l'ancien `app.py::process_series_logic()` (voir DEVELOPER.md
section 11 pour l'historique des bugs Kavita spécifiques gérés ici). Toutes
les dépendances (config, traductions, client Kavita, registre de scrapers)
sont importées directement par ce module : il n'a AUCUNE dépendance vers
`app.py` ni vers `routes/`, afin de rester appelable aussi bien depuis les
routes HTTP (`routes/sync.py::force_sync`) que depuis les workers de fond
(`services/background_tasks.py`).
"""

import logging
import threading

from config_manager import load_config, get_max_tags, get_max_genres
from db_manager import get_all_cached_data, update_status
from translations import translations
from translator import translate_text
from kavita_api import KavitaAPI
from scrapers import ScraperRegistry
from scrapers.utils import MATCH_SCORE_KEY
from kavita_constants import PUBLICATION_STATUS_MAP, AGE_RATING_MAP, resolve_kavita_format_enum

# --- GARDE ANTI-CONCURRENCE PAR SÉRIE ---
# `enrich_series()` a deux points d'entrée indépendants qui peuvent s'exécuter
# EN PARALLÈLE : `routes/sync.py::force_sync()` (bouton "Sync" d'une ligne,
# appel HTTP synchrone, hors file) et `services/background_tasks.py::_worker()`
# (consommateur de `sync_queue`, alimentée par le batch et le webhook). Rien
# n'empêchait un clic sur "Sync" pendant qu'un webhook pour LA MÊME série
# venait d'être dépilé par le worker : les deux threads liraient l'état Kavita
# en parallèle, appliqueraient leurs changements indépendamment et l'un
# écraserait silencieusement le travail de l'autre (perte de mise à jour), avec
# le même risque pour la couverture que le bug de course historique (voir
# CODE_REVIEW.md / DEVELOPER.md section 11). Ce verrou en mémoire par
# `series_id` rejette la seconde requête concurrente au lieu de la laisser
# s'exécuter en double.
_processing_lock = threading.Lock()
_processing_series_ids = set()


def enrich_series(series_id, series_name, force_update=False):
    """
    Récupère les métadonnées existantes dans Kavita, scrape les fournisseurs
    externes configurés, applique les champs ciblés par l'utilisateur, puis
    envoie le résultat à Kavita (métadonnées, généralités, couverture).

    Retourne un tuple (success: bool, message: str, used_providers: list).
    """
    sid = int(series_id)
    with _processing_lock:
        if sid in _processing_series_ids:
            logging.warning(
                f"⏭️ [{series_name}] Traitement déjà en cours pour cette série ailleurs "
                "(Sync manuel / file d'attente / webhook) : requête ignorée pour éviter "
                "une écriture concurrente vers Kavita."
            )
            return False, "Déjà en cours de traitement.", []
        _processing_series_ids.add(sid)

    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
    try:
        kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

        if not kavita.authenticate():
            logging.error(t.get('log_auth_fail').format(series_name))
            return False, "Erreur Kavita.", []

        metadata = kavita.get_series_metadata(series_id)
        if not metadata:
            logging.error(t.get('log_meta_fail').format(series_name))
            return False, "Erreur de métadonnées.", []

        if metadata.get('summary') and not force_update:
            logging.info(t.get('log_skip').format(series_name))
            update_status(series_id, 'COMPLETED')
            return True, "Déjà à jour.", []

        # --- Détermination du type de bibliothèque ---
        library_type = kavita.get_library_type_for_series(series_id)

        # --- Détermination des requêtes de recherche et replis ---
        cache_data = get_all_cached_data().get(int(series_id), {})
        forced_id = cache_data.get('forced_id')
        search_query = forced_id or cache_data.get('alternative_title') or series_name
        fallback_query = cache_data.get('alternative_title') or series_name
        is_forced_id = bool(forced_id)

        # --- Récupération des champs ciblés (Scraping Granulaire) ---
        targeted_fields_raw = cache_data.get('targeted_fields', 'ALL')
        if targeted_fields_raw == 'ALL':
            active_fields = ['summary', 'cover', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles']
        else:
            active_fields = targeted_fields_raw.split(',')

        # --- LECTURE DE LA CONFIGURATION UTILISATEUR ---
        if library_type == "Comic":
            p1 = config.get("COMIC_PROVIDER_1")
            p2 = config.get("COMIC_PROVIDER_2")
            p3 = config.get("COMIC_PROVIDER_3")
        elif library_type == "Book":
            p1 = config.get("BOOK_PROVIDER_1")
            p2 = config.get("BOOK_PROVIDER_2")
            p3 = config.get("BOOK_PROVIDER_3")
        else:
            p1 = config.get("PROVIDER_1")
            p2 = config.get("PROVIDER_2")
            p3 = config.get("PROVIDER_3")

        # --- FILTRAGE DE SÉCURITÉ ET AUTO-RÉPARATION ---
        raw_providers = [p for p in [p1, p2, p3] if p and p != "NONE" and ScraperRegistry.get(p)]

        if not raw_providers:
            available_for_type = ScraperRegistry.get_by_type(library_type)
            if available_for_type:
                raw_providers = [available_for_type[0].id]
                logging.warning(f"[{series_name}] ⚠️ Config invalide. Auto-réparation : utilisation de {raw_providers[0]}")
            else:
                fallback = ScraperRegistry.get_by_type("Manga")
                if fallback:
                    raw_providers = [fallback[0].id]
                    logging.warning(f"[{series_name}] ⚠️ Config invalide. Secours absolu : utilisation de {raw_providers[0]}")

        providers_list = list(dict.fromkeys(raw_providers))

        # --- OVERRIDE DU FOURNISSEUR & AUTO-DÉTECTION URL ---
        forced_provider = cache_data.get('forced_provider', 'AUTO')

        if is_forced_id:
            if search_query.startswith('http://') or search_query.startswith('https://'):
                # 1. C'est une URL
                if forced_provider == 'AUTO':
                    for s in ScraperRegistry.get_all():
                        if s.extract_id_from_url(search_query):
                            forced_provider = s.id
                            logging.info(t.get('log_auto_url_found', "[{0}] 🕵️ URL reconnue ! Le scraper {1} prend le relais.").format(series_name, s.display_name))
                            break
            else:
                # 2. C'est un ID Brut (ex: 86865).
                if forced_provider == 'AUTO':
                    logging.info(f"[{series_name}] 🔄 ID brut détecté en mode AUTO. Lancement de la résolution intelligente (Smart ID Match).")
                    providers_list = [p for p in providers_list if getattr(ScraperRegistry.get(p), 'has_direct_id_support', False)]

        # 3. Application de l'Override
        if forced_provider != 'AUTO' and forced_provider in ScraperRegistry._scrapers:
            providers_list = [forced_provider]
            logging.info(t.get('log_forced_provider', "[{0}] 🎯 Scraping ciblé forcé sur : {1}").format(series_name, forced_provider))

        smart_completion = config.get("SMART_COMPLETION", False)
        smart_scoring = config.get("SMART_SCORING", True)

        # Log protégé contre les valeurs None
        safe_providers_log = [str(p) for p in providers_list if p is not None]
        logging.info(t.get('log_scraping').format(series_name, " > ".join(safe_providers_log), search_query))
        logging.info(t.get('log_lib_type_detected', "[{0}] 📂 Type de bibliothèque détecté : {1}").format(series_name, library_type))
        if smart_scoring:
            logging.info(f"[{series_name}] 🎯 Smart Scoring activé (meilleur score gagne).")
        else:
            logging.info(f"[{series_name}] 📋 Fallback classique (ordre de la liste des fournisseurs).")

        # --- DÉTECTION DES MÉTADONNÉES PROFONDES KAVITA (ISBN & AUTEURS) ---
        reset_context_on_force = config.get('RESET_CONTEXT_ON_FORCE', False)

        if force_update and reset_context_on_force:
            logging.info(t.get('log_force_reset_context', "[{0}] 🔄 Mode forcé avec réinitialisation du contexte.").format(series_name))
            existing_metadata = {
                'isbn': kavita.get_series_isbn(series_id),
                'authors': [],
                'publisher': None,
                'year': None,
                'genres': [],
                'localized_name': None,
                'publisher_pref': cache_data.get('publisher_pref', 'GLOBAL')
            }
        else:
            existing_metadata = kavita.get_series_deep_metadata(series_id)
            existing_metadata['publisher_pref'] = cache_data.get('publisher_pref', 'GLOBAL')
            if existing_metadata.get('isbn'):
                logging.info(t.get('log_isbn_detected', "[{0}] 📑 ISBN détecté dans Kavita : {1}").format(series_name, existing_metadata['isbn']))
            if existing_metadata.get('authors'):
                logging.info(t.get('log_authors_detected', "[{0}] ✍️ Auteur(s) détecté(s) dans Kavita : {1}").format(series_name, ', '.join(existing_metadata['authors'])))

        # --- APPEL DU SCRAPER ---
        from metadata_fetcher import fetch_metadata
        provider_data, used_providers = fetch_metadata(
            search_query,
            providers_list,
            smart_completion,
            fallback_query=fallback_query,
            library_type=library_type,
            is_forced_id=is_forced_id,
            forced_provider=forced_provider,
            existing_metadata=existing_metadata,
            smart_scoring=smart_scoring,
        )

        if not provider_data:
            logging.warning(t.get('log_not_found').format(series_name, "API(s)"))
            update_status(series_id, 'NOT_FOUND')
            return False, "Introuvable.", used_providers

        actual_provider = provider_data.pop('_provider_used', 'Inconnu')
        fusion_providers = provider_data.pop('_fusion_providers', [])
        # Purement diagnostique (Smart Scoring, voir metadata_fetcher.py) : jamais lu ni
        # envoyé à Kavita, mais on l'enlève pour ne pas polluer les dumps de debug.
        provider_data.pop(MATCH_SCORE_KEY, None)

        msg_found = t.get('log_found').format(series_name) + f" (Base: {actual_provider})"
        if fusion_providers:
            # Protection contre les None dans la liste de fusion
            safe_fusion = [str(fp) for fp in fusion_providers if fp is not None]
            if safe_fusion:
                msg_found += f" + 🧩 Fusion ({', '.join(safe_fusion)})"
        logging.info(msg_found)

        # =========================================================
        # --- APPLICATION FILTRÉE DES MÉTADONNÉES
        # =========================================================
        localized_name_to_update = None
        format_to_update = None

        # 1. Résumé (Appartient à Series/metadata selon le Swagger de Kavita !)
        if 'summary' in active_fields and provider_data.get('summary') and (not metadata.get('summary') or force_update):
            target_lang = config.get('TARGET_LANG', 'FR')
            metadata['summary'] = translate_text(provider_data['summary'], config.get('DEEPL_API_KEY'), target_lang)
            metadata['summaryLocked'] = True

        # 2. Année
        if 'year' in active_fields and provider_data.get('year'):
            metadata['releaseYear'] = provider_data['year']
            metadata['releaseYearLocked'] = True

        # 3. Statut de Publication
        if 'status' in active_fields and provider_data.get('status') in PUBLICATION_STATUS_MAP:
            metadata['publicationStatus'] = PUBLICATION_STATUS_MAP[provider_data['status']]
            metadata['publicationStatusLocked'] = True

        # 4. Genres
        if 'genres' in active_fields and provider_data.get('genres'):
            metadata['genres'] = [
                {"id": 0, "title": g}
                for g in provider_data['genres'][:get_max_genres(config)]
            ]
            metadata['genresLocked'] = True

        # 5. Tags & Personnages
        if 'tags' in active_fields:
            if provider_data.get('tags'):
                metadata['tags'] = [{"id": 0, "title": tag} for tag in provider_data['tags'][:get_max_tags(config)]]
                metadata['tagsLocked'] = True
            if provider_data.get('characters'):
                characters_payload = []
                for c in provider_data['characters']:
                    name = None
                    if isinstance(c, str):
                        name = c.strip()
                    elif isinstance(c, dict):
                        node = c.get('node') if isinstance(c.get('node'), dict) else {}
                        nested_name = node.get('name')
                        if isinstance(nested_name, dict):
                            name = (nested_name.get('full') or nested_name.get('romaji') or nested_name.get('native') or "").strip()
                        elif isinstance(nested_name, str):
                            name = nested_name.strip()
                        if not name:
                            raw = c.get('name') or c.get('full')
                            name = str(raw).strip() if raw else ""
                    if name:
                        characters_payload.append({"id": 0, "name": name})
                if characters_payload:
                    metadata['characters'] = characters_payload
                    metadata['characterLocked'] = True

        # 6. Titres Alternatifs (Localized Name - Va vers Series/update)
        if 'alt_titles' in active_fields:
            from localized_titles import resolve_effective_title_policy, resolve_localized_name
            mode, langs = resolve_effective_title_policy(
                config, cache_data.get('alt_title_langs') or ""
            )
            localized_name_to_update = resolve_localized_name(
                provider_data, mode=mode, langs=langs
            )

        # 7. Auteurs et Staff
        if 'staff' in active_fields:
            writers, pencillers, colorists, translators, cover_artists, editors, letterers, inkers = [], [], [], [], [], [], [], []
            for edge in provider_data.get('staff', []):
                role = edge.get('role', '').lower()
                name = edge.get('node', {}).get('name', {}).get('full', '')
                if not name: continue

                entry = {"id": 0, "name": name}

                if 'story' in role or 'original' in role or 'scénar' in role: writers.append(entry)
                elif 'art' in role or 'illustration' in role or 'dessin' in role or 'pencill' in role: pencillers.append(entry)
                elif 'color' in role or 'couleur' in role: colorists.append(entry)
                elif 'translat' in role or 'traduct' in role: translators.append(entry)
                elif 'cover' in role or 'couverture' in role: cover_artists.append(entry)
                elif 'edit' in role or 'éditeur' in role or 'editeur' in role: editors.append(entry)
                elif 'letter' in role or 'lettrage' in role: letterers.append(entry)
                elif 'ink' in role or 'encrage' in role: inkers.append(entry)

            if writers: metadata['writers'] = writers; metadata['writerLocked'] = True
            if pencillers: metadata['pencillers'] = pencillers; metadata['pencillerLocked'] = True
            if colorists: metadata['colorists'] = colorists; metadata['coloristLocked'] = True
            if translators: metadata['translators'] = translators; metadata['translatorLocked'] = True
            if cover_artists: metadata['coverArtists'] = cover_artists; metadata['coverArtistLocked'] = True
            if editors: metadata['editors'] = editors; metadata['editorLocked'] = True
            if letterers: metadata['letterers'] = letterers; metadata['lettererLocked'] = True
            if inkers: metadata['inkers'] = inkers; metadata['inkerLocked'] = True

        # 8. Éditeur (Maison d'édition - 'publishers' au PLURIEL comme vu sur le Swagger)
        if 'publisher' in active_fields and provider_data.get('publisher'):
            metadata['publishers'] = [{"id": 0, "name": provider_data['publisher']}]
            metadata['publisherLocked'] = True

        # 9. Classification d'âge
        if 'age' in active_fields and provider_data.get('age_rating'):
            mapped_rating = AGE_RATING_MAP.get(str(provider_data['age_rating']).lower())
            if mapped_rating is not None:
                metadata['ageRating'] = mapped_rating
                metadata['ageRatingLocked'] = True

        # 10. Sens de lecture (Format - Va vers Series/update)
        if 'format' in active_fields and config.get('AUTO_READING_DIR') and provider_data.get('format'):
            format_to_update = resolve_kavita_format_enum(provider_data['format'])

        # 11. Liens externes & IDs Natifs
        if 'weblinks' in active_fields:
            a_id = provider_data.get('anilist_id')
            m_id = provider_data.get('mal_id')
            mb_id = provider_data.get('mangabaka_id')

            if a_id or m_id or mb_id:
                kavita.update_series_external_ids(series_id, a_id, m_id, mb_id)

            existing_links_raw = metadata.get('webLinks')
            links_list = [link.strip() for link in str(existing_links_raw).split(',')] if existing_links_raw else []

            def add_weblink(url):
                if url and str(url).strip() and str(url).strip() not in links_list:
                    links_list.append(str(url).strip())

            if a_id: add_weblink(f"https://anilist.co/manga/{a_id}")
            if m_id: add_weblink(f"https://myanimelist.net/manga/{m_id}")
            if mb_id: add_weblink(f"https://mangabaka.org/{mb_id}")
            if provider_data.get('url'): add_weblink(provider_data['url'])
            for link in provider_data.get('accumulated_links', []): add_weblink(link)

            safe_links = [str(l) for l in links_list if l is not None and str(l).strip()]
            if safe_links:
                metadata['webLinks'] = ",".join(safe_links)

        # 12. Langue de l'œuvre — ne pas écraser à chaque sync juste parce que
        # TARGET_LANG a un défaut ("FR"). N'écrire que si Kavita n'a pas encore de
        # langue, ou en force_update.
        target_lang = (config.get('TARGET_LANG') or "").strip()
        if target_lang:
            current_lang = (metadata.get('language') or "").strip()
            if force_update or not current_lang:
                metadata['language'] = target_lang.lower()
                metadata['languageLocked'] = True

        # =========================================================
        # --- ENVOI FINAL À KAVITA
        # =========================================================
        metadata['seriesId'] = int(series_id)
        # Note : l'assainissement des champs système (created, lastModified, totalCount,
        # maxCount, pages, wordCount) est désormais centralisé dans
        # KavitaAPI.update_series_metadata() pour protéger tous les appelants (voir kavita_api.md).

        logging.info(t.get('log_sending').format(series_name))

        # 1. Envoi des Métadonnées (Auteurs, Tags, Publishers)
        success, msg = kavita.update_series_metadata(metadata)

        # 2. Envoi des Champs Généraux (Titre alternatif & Format uniquement)
        general_ok = True
        general_msg = ""
        if localized_name_to_update or format_to_update:
            general_ok, general_msg = kavita.update_series_general(
                series_id,
                localized_name=localized_name_to_update,
                format_val=format_to_update
            )
            if not general_ok:
                logging.error(
                    t.get('log_kavita_refused', "[{0}] ❌ Kavita a refusé la mise à jour : {1}").format(
                        series_name, f"champs généraux: {general_msg}"
                    )
                )

        if success and general_ok:
            logging.info(t.get('log_success').format(series_name))

            # 3. Upload de Couverture (Format v1.4 fiable)
            # Relecture fraîche de targeted_fields juste avant l'envoi : si l'utilisateur
            # a appliqué une couverture manuelle pendant que ce traitement tournait,
            # 'cover' a été retiré entre-temps par /update-cover et on ne doit pas l'écraser.
            fresh_targeted_fields = get_all_cached_data().get(int(series_id), {}).get('targeted_fields', 'ALL') or 'ALL'
            cover_still_targeted = fresh_targeted_fields == 'ALL' or 'cover' in fresh_targeted_fields.split(',')

            if 'cover' in active_fields and cover_still_targeted and config.get('AUTO_COVER') and provider_data.get('cover_url'):
                logging.info(t.get('log_cover_upload').format(series_name))
                cover_success, cover_msg = kavita.upload_series_cover(series_id, provider_data['cover_url'])
                if not cover_success:
                    logging.warning(t.get('log_cover_fail').format(series_name, cover_msg))
                else:
                    logging.info(t.get('log_cover_success').format(series_name))
            elif 'cover' in active_fields and not cover_still_targeted:
                logging.info(f"[{series_name}] ⏭️ Couverture ignorée : un choix manuel protégé a été détecté entre-temps.")

            update_status(series_id, 'COMPLETED')
            return True, "Succès", used_providers
        elif success and not general_ok:
            logging.error(
                f"[{series_name}] Métadonnées OK mais champs généraux refusés : {general_msg}"
            )
            return False, f"Erreur champs généraux: {general_msg}", used_providers
        else:
            logging.error(t.get('log_kavita_refused').format(series_name, msg))
            return False, f"Erreur: {msg}", used_providers

    except Exception as e:
        logging.error(t.get('log_crash').format(series_name, e))
        return False, "Erreur interne.", []
    finally:
        with _processing_lock:
            _processing_series_ids.discard(sid)
