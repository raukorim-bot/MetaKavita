import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from scrapers import ScraperRegistry
from scrapers.utils import get_match_accept_threshold, MATCH_SCORE_KEY
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
    - clé absente / None / non numérique → seuil effectif ("juste accepté")
    - booléen → rejeté (en Python `True` est un int, ce qui fausserait le classement)
    - score numérique hors [0.0, 1.0] → clampé dans cet intervalle
    """
    threshold = get_match_accept_threshold()
    if not isinstance(candidate, dict):
        return threshold
    raw = candidate.get(MATCH_SCORE_KEY, threshold)
    if isinstance(raw, bool) or raw is None:
        return threshold
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return threshold
    if score != score:  # NaN
        return threshold
    return max(0.0, min(1.0, score))


def _is_explicit_adult(data) -> bool:
    """True when age_rating is pornographic or erotica (BF68 tie-break only)."""
    return str((data or {}).get("age_rating") or "").lower() in ("pornographic", "erotica")


_FUSION_SKIP_KEYS = (
    '_provider_used', '_fusion_providers', 'anilist_id', 'mal_id', 'mangabaka_id',
    'links', 'external_links', 'url', MATCH_SCORE_KEY,
)


def merge_candidates(ordered_entries, smart_fusion=False):
    """
    Fusionne une liste ordonnée `(provider_id, data_dict)`.

    Le premier entrée utile devient la base (`_provider_used`). Si `smart_fusion`,
    les suivantes comblent les trous (même logique que `apply_accepted` en cascade auto).
    """
    if not ordered_entries:
        return None

    master_data = None
    base_set = False

    for provider_id, data in ordered_entries:
        if not isinstance(data, dict):
            continue
        if not base_set:
            master_data = data.copy()
            master_data['_provider_used'] = provider_id
            base_set = True
            continue

        if not smart_fusion:
            continue

        if not data:
            continue

        filled_something = False
        for key, value in data.items():
            if key in _FUSION_SKIP_KEYS:
                continue
            if key == 'titles' and isinstance(value, list):
                from localized_titles import merge_title_entries
                merged = merge_title_entries(master_data.get('titles') or [], value)
                if merged and merged != (master_data.get('titles') or []):
                    master_data['titles'] = merged
                    filled_something = True
                continue
            if not master_data.get(key) and value:
                master_data[key] = value
                filled_something = True

        if filled_something:
            master_data['_fusion_providers'] = master_data.get('_fusion_providers', []) + [provider_id]

    return master_data


def _as_str_list(value, limit=16):
    """Normalise genres/tags/staff en liste de chaînes pour l'UI review."""
    if value is None or value is False:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
        return parts[:limit]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                name = _dict_display_name(item)
                if name:
                    out.append(name)
            if len(out) >= limit:
                break
        return out
    text = str(value).strip()
    return [text] if text else []


def _dict_display_name(item):
    """Nom affichable depuis un dict plat ou un edge AniList `{node: {name: {full}}}`."""
    if not isinstance(item, dict):
        return ""
    node = item.get("node")
    if isinstance(node, dict):
        n = node.get("name")
        if isinstance(n, dict):
            full = n.get("full") or n.get("native") or n.get("userPreferred")
            if full and str(full).strip():
                return str(full).strip()
        if isinstance(n, str) and n.strip():
            return n.strip()
    name = item.get("name") or item.get("Name") or item.get("title")
    if isinstance(name, dict):
        full = name.get("full") or name.get("native") or name.get("userPreferred")
        if full and str(full).strip():
            return str(full).strip()
    if isinstance(name, str) and name.strip():
        return name.strip()
    if item.get("full") and str(item.get("full")).strip():
        return str(item.get("full")).strip()
    return ""


def _staff_entry_label(item):
    """« Nom » ou « Nom (Role) » depuis string / edge AniList / dict simple."""
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        text = str(item).strip()
        return text
    name = _dict_display_name(item)
    if not name:
        return ""
    role = str(item.get("role") or "").strip()
    return f"{name} ({role})" if role else name


def _staff_from_data(data):
    """Agrège staff / writers / pencillers pour affichage review (format AniList inclus)."""
    if not isinstance(data, dict):
        return []
    names = []
    for key in ("staff", "writers", "pencillers", "colorists", "editors", "inkers"):
        raw = data.get(key)
        if raw is None or raw is False:
            continue
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        for item in items:
            label = _staff_entry_label(item)
            if label and label not in names:
                names.append(label)
            if len(names) >= 16:
                return names
    return names


def _localized_name_for_card(payload):
    """
    Titre localisé pour l'UI pick : champ explicite, sinon dérivé de `titles` /
    `alternative_titles` (même logique que l'écriture Kavita en mode `all`).
    """
    if not isinstance(payload, dict):
        return ""
    raw = payload.get("localized_name")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if raw is not None and not isinstance(raw, str) and str(raw).strip():
        return str(raw).strip()
    try:
        from localized_titles import resolve_localized_name
        resolved = resolve_localized_name(payload, mode="all")
        if resolved:
            return resolved
    except Exception:
        pass
    alts = _as_str_list(payload.get("alternative_titles"), limit=8)
    return " / ".join(alts) if alts else ""


def build_candidate_card(provider, data, below_threshold=False):
    """Sérialise une carte candidat pour la review manuelle / le store pending."""
    score = _safe_match_score(data) if isinstance(data, dict) else 0.0
    payload = data if isinstance(data, dict) else {}
    title = payload.get("title") or ""
    cover_url = payload.get("cover_url") or ""
    summary = payload.get("summary") or ""
    if not isinstance(title, str):
        title = str(title) if title else ""
    if not isinstance(cover_url, str):
        cover_url = str(cover_url) if cover_url else ""
    if not isinstance(summary, str):
        summary = str(summary) if summary else ""

    year = payload.get("year")
    if year is not None and not isinstance(year, (str, int, float)):
        year = str(year)
    status = payload.get("status") or ""
    if not isinstance(status, str):
        status = str(status) if status else ""
    publisher = payload.get("publisher") or ""
    if not isinstance(publisher, str):
        publisher = str(publisher) if publisher else ""
    localized = _localized_name_for_card(payload)
    age_rating = payload.get("age_rating") or ""
    if not isinstance(age_rating, str):
        age_rating = str(age_rating) if age_rating else ""
    fmt = payload.get("format") or ""
    if not isinstance(fmt, str):
        fmt = str(fmt) if fmt else ""

    return {
        "provider": provider,
        "score": score,
        "title": title,
        "cover_url": cover_url,
        # Résumé intégral pour le pick UI — l'extrait reste pour compat / listes denses.
        "summary": summary,
        "summary_excerpt": summary[:280],
        "year": year,
        "status": status,
        "publisher": publisher,
        "genres": _as_str_list(payload.get("genres"), limit=20),
        "tags": _as_str_list(payload.get("tags"), limit=20),
        "staff": _staff_from_data(payload),
        "localized_name": localized,
        "age_rating": age_rating,
        "format": fmt,
        "below_threshold": bool(below_threshold),
        "data": payload,
    }


def candidate_card_for_ui(card):
    """
    Vue légère pour `/api/manual-reviews` : résumé complet + métadonnées utiles,
    sans renvoyer tout le blob `data` (souvent très lourd).

    Lit d'abord les champs top-level (cartes récentes), puis retombe sur `data`
    pour les reviews déjà en file avant l'enrichissement des cartes.
    """
    if not isinstance(card, dict):
        return None
    data = card.get("data") if isinstance(card.get("data"), dict) else {}

    def pick(key, default=None):
        val = card.get(key)
        if val is None or val == "" or val == []:
            val = data.get(key, default)
        return val

    summary = pick("summary") or card.get("summary_excerpt") or data.get("summary") or ""
    if not isinstance(summary, str):
        summary = str(summary) if summary else ""

    title = pick("title") or ""
    if not isinstance(title, str):
        title = str(title) if title else ""
    cover_url = pick("cover_url") or ""
    if not isinstance(cover_url, str):
        cover_url = str(cover_url) if cover_url else ""

    year = pick("year")
    if year is not None and not isinstance(year, (str, int, float)):
        year = str(year)
    status = pick("status") or ""
    if not isinstance(status, str):
        status = str(status) if status else ""
    publisher = pick("publisher") or ""
    if not isinstance(publisher, str):
        publisher = str(publisher) if publisher else ""
    localized = pick("localized_name") or ""
    if not isinstance(localized, str):
        localized = str(localized) if localized else ""
    if not (localized or "").strip():
        # Cartes legacy / scrapers : titres dans data.titles / alternative_titles
        localized = _localized_name_for_card(data) or _localized_name_for_card(card)
    age_rating = pick("age_rating") or ""
    if not isinstance(age_rating, str):
        age_rating = str(age_rating) if age_rating else ""
    fmt = pick("format") or ""
    if not isinstance(fmt, str):
        fmt = str(fmt) if fmt else ""

    genres = pick("genres")
    tags = pick("tags")
    staff = pick("staff")
    # Cartes récentes : liste de labels ; legacy / raw : edges AniList dans staff ou data
    if isinstance(staff, list) and staff and all(isinstance(x, str) for x in staff):
        staff = [s.strip() for s in staff if str(s).strip()][:16]
    else:
        staff = _staff_from_data({"staff": staff} if staff else {}) or _staff_from_data(data)
    if not staff:
        staff = _staff_from_data(data)

    return {
        "provider": card.get("provider"),
        "score": card.get("score"),
        "title": title,
        "cover_url": cover_url,
        "summary": summary,
        "summary_excerpt": summary[:280] if summary else (card.get("summary_excerpt") or ""),
        "year": year,
        "status": status,
        "publisher": publisher,
        "genres": _as_str_list(genres, limit=20),
        "tags": _as_str_list(tags, limit=20),
        "staff": staff if isinstance(staff, list) else _as_str_list(staff, limit=16),
        "localized_name": localized,
        "age_rating": age_rating,
        "format": fmt,
        "below_threshold": card.get("below_threshold"),
    }


def _install_zero_match_threshold():
    """
    Force `get_match_accept_threshold()` → 0.0 pendant la collect manuelle.

    Les scrapers font `from .utils import get_match_accept_threshold` : patcher
    uniquement `scrapers.utils` ne suffit pas. On rebind aussi chaque module
    `scrapers*` déjà chargé qui tient encore la référence d'origine, plus ce module.
    """
    import scrapers.utils as utils_mod

    original = utils_mod.get_match_accept_threshold

    def _zero(config=None):
        return 0.0

    patched = []

    def _bind(mod):
        if getattr(mod, "get_match_accept_threshold", None) is original:
            setattr(mod, "get_match_accept_threshold", _zero)
            patched.append(mod)

    utils_mod.get_match_accept_threshold = _zero
    patched.append(utils_mod)

    this_mod = sys.modules.get(__name__)
    if this_mod is not None:
        _bind(this_mod)

    for name, mod in list(sys.modules.items()):
        if mod is None or mod is utils_mod or mod is this_mod:
            continue
        if (
            name == "scrapers"
            or name.startswith("scrapers.")
            or name == "custom_scrapers"
            or name.startswith("custom_scrapers.")
        ):
            _bind(mod)

    def restore():
        for mod in patched:
            try:
                setattr(mod, "get_match_accept_threshold", original)
            except Exception:
                pass

    return restore


def fetch_metadata(query, providers_list, smart_fusion=False, fallback_query=None, library_type="Manga", is_forced_id=False, forced_provider="AUTO", existing_metadata=None, smart_scoring=None, return_candidates=False):
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

    `return_candidates=True` (mode manuel) : ne construit pas de master_data.
    Collecte tous les candidats utiles (seuil scrapers temporairement à 0.0),
    partitionne above/below selon le vrai seuil UI, retourne
    `({"above": [...], "below": [...], "query": query}, used_providers)`.
    """
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    if smart_scoring is None:
        smart_scoring = bool(config.get('SMART_SCORING', True))

    master_data = {}
    used_providers = []
    base_provider_set = False
    collected = []  # [(idx, p, data), ...] — mode return_candidates uniquement

    accumulated_ids = {'anilist_id': None, 'mal_id': None, 'mangabaka_id': None}
    accumulated_links = set()

    current_existing = existing_metadata.copy() if existing_metadata else {}

    def has_useful_data(d):
        return bool(d.get('summary') or d.get('genres') or d.get('cover_url') or d.get('staff') or d.get('year'))

    def has_results():
        if return_candidates:
            return bool(collected)
        return base_provider_set

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
        if return_candidates:
            for entry in accepted:
                collected.append(entry)
                absorb_candidate(entry[2])
            return

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
                        if key in _FUSION_SKIP_KEYS:
                            continue
                        if key == 'titles' and isinstance(value, list):
                            from localized_titles import merge_title_entries
                            merged = merge_title_entries(master_data.get('titles') or [], value)
                            if merged and merged != (master_data.get('titles') or []):
                                master_data['titles'] = merged
                                filled_something = True
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

        # Meilleur score gagne. Auto (non-return_candidates) : égalité →
        # non-adult d'abord (BF68), puis ordre de fallback. MR/return_candidates :
        # tri neutre (-score, idx) uniquement — pas de dépriorisation NSFW.
        if return_candidates:
            accepted.sort(
                key=lambda entry: (-_safe_match_score(entry[2]), entry[0])
            )
            tie = []
        else:
            accepted.sort(
                key=lambda entry: (
                    -_safe_match_score(entry[2]),
                    1 if _is_explicit_adult(entry[2]) else 0,
                    entry[0],
                )
            )
            max_s = _safe_match_score(accepted[0][2])
            tie = [
                e for e in accepted
                if abs(_safe_match_score(e[2]) - max_s) < 0.001
            ]
            prefer_safe = (
                len(tie) >= 2
                and any(_is_explicit_adult(e[2]) for e in tie)
                and any(not _is_explicit_adult(e[2]) for e in tie)
            )
            if prefer_safe:
                winner_provider = accepted[0][1]
                msg = t.get(
                    "log_tiebreak_prefer_safe",
                    "[{0}] Tie at {1:.2f}: preferring safer match ({2}) over explicit-adult candidate(s).",
                )
                logging.info(msg.format(current_query, max_s, winner_provider))

        apply_accepted(accepted)

        if (not return_candidates) and base_provider_set and len(tie) >= 2:
            master_data["_score_tie"] = True
            # Payload pick prêt pour CBW — tri d'affichage neutre (-score, idx).
            display = sorted(
                accepted,
                key=lambda entry: (-_safe_match_score(entry[2]), entry[0]),
            )
            real_threshold = get_match_accept_threshold()
            above, below = [], []
            for _, p, data in display:
                score = _safe_match_score(data)
                is_below = score < real_threshold
                card = build_candidate_card(p, data, below_threshold=is_below)
                if is_below:
                    below.append(card)
                else:
                    above.append(card)
            master_data["_tie_review_payload"] = {
                "above": above,
                "below": below,
                "query": current_query,
            }

    restore_threshold = None
    if return_candidates:
        restore_threshold = _install_zero_match_threshold()

    try:
        # --- 1ER PASSAGE CLASSIQUE ---
        run_cascade(query, is_forced_id)

        # --- 2ÈME PASSAGE : repli titre/alt si ID/URL forcé a échoué ---
        # `fallback_query` est calculé par enrichment_engine (alt title ou nom de série).
        # Sans ce passage, un forced_id/URL invalide restait en NOT_FOUND alors qu'une
        # recherche textuelle aurait pu réussir.
        if (
            not has_results()
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
        if not has_results() and config.get('TITLE_FALLBACK_TRANSLATION') and not is_forced_id:
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
                if (not return_candidates) and base_provider_set and '_provider_used' in master_data:
                    master_data['_provider_used'] += " (Titre Traduit)"
    finally:
        if restore_threshold is not None:
            restore_threshold()

    if return_candidates:
        collected.sort(key=lambda entry: (-_safe_match_score(entry[2]), entry[0]))
        real_threshold = get_match_accept_threshold()
        above = []
        below = []
        used = []
        for _, p, data in collected:
            used.append(p)
            score = _safe_match_score(data)
            is_below = score < real_threshold
            card = build_candidate_card(p, data, below_threshold=is_below)
            if is_below:
                below.append(card)
            else:
                above.append(card)
        return {"above": above, "below": below, "query": query}, used

    if base_provider_set:
        for id_key, id_val in accumulated_ids.items():
            if id_val: master_data[id_key] = id_val
        master_data['accumulated_links'] = list(accumulated_links)
        return master_data, used_providers

    return None, used_providers