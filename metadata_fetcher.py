import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from scrapers import ScraperRegistry
from scrapers.utils import MATCH_ACCEPT_THRESHOLD, MATCH_SCORE_KEY
from config_manager import load_config
from translations import translations

ALLOWED_PROXY_DOMAINS = ScraperRegistry.get_all_proxy_domains()

# 🎯 DÉCTIONNAIRE D'HORODATAGE GLOBAL (Mémoire des derniers appels par scraper)
LAST_REQUEST_TIMES = {}

# --- GARDE ANTI-COURSE PAR SCRAPER ---
# `throttle_provider()` fait un cycle lire (last_call) -> éventuellement dormir
# -> écrire (nouvel horodatage), en 3 étapes séparées. Sans verrou, deux appels
# concurrents pour LE MÊME scraper (ex: le bouton "Sync" d'une série pendant que
# la file de fond traite une AUTRE série qui utilise aussi ce fournisseur comme
# provider #1) peuvent tous les deux lire le même `last_call` périmé AVANT que
# l'un des deux n'ait écrit son propre horodatage : les deux jugent alors,
# indépendamment, qu'il n'y a pas besoin d'attendre, et partent quasi
# simultanément vers l'API externe — violant le rate_limit qu'on croyait
# respecter, avec un risque de 429/ban IP chez le fournisseur. Un verrou par
# scraper (pas un verrou global, pour ne pas ralentir des fournisseurs
# indépendants entre eux) rend tout le cycle lire-dormir-écrire atomique.
_THROTTLE_LOCKS_GUARD = threading.Lock()
_THROTTLE_LOCKS = {}


def _get_throttle_lock(scraper_id):
    with _THROTTLE_LOCKS_GUARD:
        lock = _THROTTLE_LOCKS.get(scraper_id)
        if lock is None:
            lock = threading.Lock()
            _THROTTLE_LOCKS[scraper_id] = lock
        return lock


def throttle_provider(scraper):
    """
    Attend uniquement le temps strictement nécessaire pour respecter le rate_limit 
    du scraper ciblé. Si l'API était inactive, délai = 0.0s !
    """
    with _get_throttle_lock(scraper.id):
        now = time.time()
        last_call = LAST_REQUEST_TIMES.get(scraper.id, 0.0)
        elapsed = now - last_call
        required_delay = getattr(scraper, 'rate_limit', 1.0)

        if elapsed < required_delay:
            sleep_needed = required_delay - elapsed
            time.sleep(sleep_needed)

        LAST_REQUEST_TIMES[scraper.id] = time.time()


def _safe_match_score(candidate):
    """
    Extrait un score de matching numérique sûr depuis un candidat renvoyé par un scraper.

    Pourquoi cette garde existe : les scrapers communautaires (`data/scrapers/`) ne sont
    PAS obligés d'appeler `score_candidate()` ni `attach_match_score()`. Sans elle, un
    `_match_score` absent, `None`, une chaîne, une liste, un booléen ou toute autre
    valeur non coercible en float ferait planter `accepted.sort(...)` (TypeError /
    comparaison invalide) et tuerait tout le pipeline d'enrichissement pour la série.
    Comportement :
    - clé absente / None / non numérique → `MATCH_ACCEPT_THRESHOLD` ("juste accepté")
    - booléen → rejeté (en Python `True` est un int, ce qui fausserait le classement)
    - score numérique hors [0.0, 1.0] → clampé dans cet intervalle
    """
    if not isinstance(candidate, dict):
        return MATCH_ACCEPT_THRESHOLD
    raw = candidate.get(MATCH_SCORE_KEY, MATCH_ACCEPT_THRESHOLD)
    if isinstance(raw, bool) or raw is None:
        return MATCH_ACCEPT_THRESHOLD
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return MATCH_ACCEPT_THRESHOLD
    if score != score:  # NaN
        return MATCH_ACCEPT_THRESHOLD
    return max(0.0, min(1.0, score))


def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None, library_type="Manga", is_forced_id=False, forced_provider="AUTO", existing_metadata=None, smart_scoring=None):
    """
    Orchestre la cascade multi-fournisseurs.

    Deux modes (toggle UI `SMART_SCORING`, case à côté de SMART_COMPLETION) :

    - **smart_scoring=True** (défaut) : Smart Scoring
      1. Sélection par score : tous les providers sont appelés, leurs `_match_score`
         (via `attach_match_score()`) sont comparés, le MEILLEUR gagne — égalité →
         ordre de fallback. Si SMART_COMPLETION est activé, le remplissage des trous
         suit aussi l'ordre des scores décroissants.
      2. Exécution en deux vagues : provider #1 seul (amorce ISBN/auteurs), puis
         les autres EN PARALLÈLE contre un instantané de ce contexte enrichi.

    - **smart_scoring=False** : fallback classique (« bête »)
      Cascade 100 % séquentielle dans l'ordre de `providers_list`. Le PREMIER
      provider utile devient la base ; SMART_COMPLETION comble ensuite dans cet
      ordre brut, sans comparaison de scores ni parallélisation.

    `smart_scoring=None` lit la valeur depuis `config.json` (`SMART_SCORING`).
    """
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    if smart_scoring is None:
        smart_scoring = bool(config.get('SMART_SCORING', True))

    master_data = {}
    used_providers = []
    base_provider_set = False
    
    accumulated_ids = {'anilist_id': None, 'mal_id': None, 'mangabaka_id': None}
    accumulated_links = set()
    
    current_existing = existing_metadata.copy() if existing_metadata else {}

    def has_useful_data(d):
        return bool(d.get('summary') or d.get('genres') or d.get('cover_url') or d.get('staff') or d.get('year'))

    def call_provider(p, current_query, is_id_search_forced, existing_ctx):
        """Appelle UN provider et retourne (p, data|None). Isolé de la boucle pour être
        utilisable aussi bien pour l'appel séquentiel du provider #1 que pour les appels
        parallèles des providers suivants (soumis au ThreadPoolExecutor)."""
        scraper = ScraperRegistry.get(p)
        if not scraper:
            return p, None

        if library_type not in scraper.supported_types and "Manga" not in scraper.supported_types:
            if forced_provider == p or is_id_search_forced:
                msg = t.get('log_scraper_type_bypass', "⚠️ [Scraper {0}] Forçage du type '{1}'")
                logging.warning(msg.format(p, library_type))
            else:
                return p, None

        if is_id_search_forced:
            raw_input = current_query
            if str(raw_input).startswith("http://") or str(raw_input).startswith("https://"):
                extracted_id = scraper.extract_id_from_url(raw_input)
                if extracted_id:
                    provider_query = extracted_id
                    is_id_search = True
                else:
                    msg_skip = t.get('log_url_not_recognized', "⏭️ [Scraper {0}] URL non reconnue, on passe.")
                    logging.info(msg_skip.format(p))
                    return p, None
            else:
                provider_query = raw_input
                is_id_search = True
        else:
            provider_query = current_query
            is_id_search = False

        if not provider_query:
            return p, None

        throttle_provider(scraper)

        try:
            data = scraper.fetch(provider_query, library_type=library_type, is_id=is_id_search, existing_metadata=existing_ctx)
        except Exception as e:
            logging.error(f"❌ [Scraper {p}] Erreur lors de la récupération pour '{provider_query}': {e}")
            data = None

        return p, data

    def absorb_candidate(data):
        """Fusionne dans le contexte partagé (ISBN/auteurs/IDs externes/liens) les
        informations glanées chez CE candidat accepté. Appelé pour chaque candidat retenu,
        pas seulement le vainqueur final, pour ne perdre aucun ISBN/ID externe trouvé par un
        provider moins bien noté que le vainqueur."""
        if data.get('isbn') and not current_existing.get('isbn'):
            current_existing['isbn'] = data['isbn']
        if data.get('staff') and not current_existing.get('authors'):
            current_existing['authors'] = [s['node']['name']['full'] for s in data['staff'] if isinstance(s, dict) and s.get('node', {}).get('name', {}).get('full')]

        for id_key in ['anilist_id', 'mal_id', 'mangabaka_id']:
            if data.get(id_key) and not accumulated_ids[id_key]:
                accumulated_ids[id_key] = data[id_key]

        if data.get('url'):
            accumulated_links.add(data['url'])
        if data.get('links'):
            for link in data['links']:
                if link: accumulated_links.add(link)
        if data.get('external_links'):
            for link_obj in data['external_links']:
                if isinstance(link_obj, dict) and link_obj.get('url'):
                    accumulated_links.add(link_obj['url'])
                elif isinstance(link_obj, str):
                    accumulated_links.add(link_obj)

    def apply_accepted(accepted):
        """Applique la liste ordonnée de candidats (vainqueur + éventuelle fusion)."""
        nonlocal base_provider_set, master_data
        for _, p, data in accepted:
            used_providers.append(p)
            absorb_candidate(data)

            if not base_provider_set:
                master_data = data.copy()
                master_data['_provider_used'] = p
                base_provider_set = True
            else:
                if smart_fusion:
                    filled_something = False
                    for key, value in data.items():
                        if key in ['_provider_used', '_fusion_providers', 'anilist_id', 'mal_id', 'mangabaka_id', 'links', 'external_links', 'url', MATCH_SCORE_KEY]:
                            continue
                        if not master_data.get(key) and value:
                            master_data[key] = value
                            filled_something = True

                    if filled_something:
                        master_data['_fusion_providers'] = master_data.get('_fusion_providers', []) + [p]

    def run_cascade(current_query, is_id_search_forced):
        nonlocal base_provider_set, master_data

        if not providers_list:
            return

        # --- MODE FALLBACK CLASSIQUE (SMART_SCORING désactivé) ---
        # Séquentiel strict dans l'ordre de la liste : le 1er résultat utile devient
        # la base ; SMART_COMPLETION comble ensuite dans cet ordre, sans tri par score.
        if not smart_scoring:
            for idx, p in enumerate(providers_list):
                _, data = call_provider(p, current_query, is_id_search_forced, current_existing)
                if not data or not has_useful_data(data):
                    continue
                apply_accepted([(idx, p, data)])
                # Continuer la boucle uniquement pour la fusion / accumulation d'IDs ;
                # sans smart_fusion, absorb_candidate a déjà été fait et master_data
                # est figé — on continue quand même pour glaner ISBN/IDs/liens.
            return

        # --- MODE SMART SCORING ---
        accepted = []  # [(index_fallback, provider_id, data), ...]

        # Vague 1 (séquentielle) : le provider #1 amorce le contexte (ISBN/auteurs).
        p0 = providers_list[0]
        _, p0_data = call_provider(p0, current_query, is_id_search_forced, current_existing)
        if p0_data and has_useful_data(p0_data):
            accepted.append((0, p0, p0_data))
            # Snapshot obligatoire pour le contexte wave-2 (ISBN/auteurs/IDs).
            # apply_accepted() en fin de run ré-absorbe aussi — double absorb
            # intentionnel et idempotent (ne pas retirer ce bloc).
            absorb_candidate(p0_data)

        # Vague 2 (parallèle) : providers restants sur un instantané figé du contexte.
        rest = providers_list[1:]
        if rest:
            context_snapshot = dict(current_existing)
            with ThreadPoolExecutor(max_workers=len(rest)) as executor:
                future_to_meta = {
                    executor.submit(call_provider, p, current_query, is_id_search_forced, context_snapshot): (idx, p)
                    for idx, p in enumerate(rest, start=1)
                }
                for future in as_completed(future_to_meta):
                    idx, p = future_to_meta[future]
                    try:
                        _, data = future.result()
                    except Exception as e:
                        logging.error(f"❌ [Scraper {p}] Erreur inattendue en exécution parallèle : {e}")
                        data = None
                    if data and has_useful_data(data):
                        accepted.append((idx, p, data))

        if not accepted:
            return

        # Meilleur score gagne ; égalité → ordre de fallback. `_safe_match_score()`
        # protège contre les scrapers communautaires mal formés.
        accepted.sort(key=lambda entry: (-_safe_match_score(entry[2]), entry[0]))
        apply_accepted(accepted)

    # --- 1ER PASSAGE CLASSIQUE ---
    run_cascade(query, is_forced_id)

    # --- 2ÈME PASSAGE : repli titre/alt si ID/URL forcé a échoué ---
    # `fallback_query` est calculé par enrichment_engine (alt title ou nom de série).
    # Sans ce passage, un forced_id/URL invalide restait en NOT_FOUND alors qu'une
    # recherche textuelle aurait pu réussir.
    if (
        not base_provider_set
        and is_forced_id
        and fallback_query
        and str(fallback_query).strip()
        and str(fallback_query).strip().lower() != str(query).strip().lower()
    ):
        fb = str(fallback_query).strip()
        msg_id_fallback = t.get(
            'log_forced_id_fallback',
            "🔄 [Fallback] ID/URL forcé '{0}' sans résultat. Nouvelle tentative avec : '{1}'",
        )
        logging.info(msg_id_fallback.format(query, fb))
        run_cascade(fb, False)

    # --- 3ÈME PASSAGE : TITRE DE SECOURS (TRADUCTION) ---
    # Si on n'a rien trouvé + Option cochée + Ce n'est pas un ID forcé
    if not base_provider_set and config.get('TITLE_FALLBACK_TRANSLATION') and not is_forced_id:
        from translator import translate_text
        # On force la traduction en anglais car c'est la langue pivot des API asiatiques
        translated_query = translate_text(query, target_lang="EN")
        
        # On vérifie que la traduction a donné un vrai résultat différent de la requête d'origine
        if translated_query and translated_query.strip().lower() != query.strip().lower():
            msg_fallback = t.get('log_title_fallback', "🔄 [Fallback] Aucun résultat pour '{0}'. Traduction automatique tentée : '{1}'")
            logging.info(msg_fallback.format(query, translated_query))
            
            # On relance exactement la même cascade, mais avec le titre traduit
            run_cascade(translated_query, False)
            
            # Si on a trouvé, on ajoute une petite mention au provider pour que ça se voie dans les logs
            if base_provider_set and '_provider_used' in master_data:
                master_data['_provider_used'] += " (Titre Traduit)"

    if base_provider_set:
        for id_key, id_val in accumulated_ids.items():
            if id_val: master_data[id_key] = id_val
        master_data['accumulated_links'] = list(accumulated_links)
        return master_data, used_providers
        
    return None, used_providers