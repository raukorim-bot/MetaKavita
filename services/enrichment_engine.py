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

import json
import logging
import threading

from config_manager import load_config
from db_manager import (
    get_all_cached_data,
    update_status,
    record_enrichment_miss,
    get_lifetime_stats,
    get_pending_review,
    record_manual_review_telemetry,
)
from translations import translations
from kavita_api import KavitaAPI
from scrapers import ScraperRegistry
from scrapers.utils import MATCH_SCORE_KEY, apply_title_year_hint
from secure_logging import safe_exc_str
from services.kavita_payload import (
    build_kavita_payload,
    apply_kavita_payload,
    overlay_edited_preview,
    _broadcast_enrichment_stats,
    _emit_series_status,
)

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

ALL_TARGETED_FIELDS = [
    "summary", "cover", "staff", "genres", "tags", "year",
    "status", "publisher", "age", "format", "weblinks", "alt_titles", "language",
]


def resolve_active_fields(targeted_fields_raw, override=None):
    """
    Résout la liste des champs Kavita à écrire.
    `override` (masque batch éphémère) prime sur `targeted_fields_raw` (cache série).
    """
    raw = override if override is not None else targeted_fields_raw
    if raw is None or raw == "" or raw == "ALL":
        return list(ALL_TARGETED_FIELDS)
    if raw == "NONE":
        return []
    return [f.strip() for f in str(raw).split(",") if f.strip()]


def _providers_from_config(config, library_type, series_name):
    """Lit COMIC_/BOOK_/PROVIDER_* selon le type, avec auto-réparation si vide."""
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    if library_type == "Comic":
        keys = ("COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3")
        repair_type = "Comic"
    elif library_type == "Book":
        keys = ("BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3")
        repair_type = "Book"
    else:
        keys = ("PROVIDER_1", "PROVIDER_2", "PROVIDER_3")
        repair_type = "Manga"

    raw = [config.get(k) for k in keys]
    providers = [p for p in raw if p and p != "NONE" and ScraperRegistry.get(p)]

    if not providers:
        available = ScraperRegistry.get_by_type(repair_type)
        if available:
            providers = [available[0].id]
            logging.warning(t.get("log_config_repair", "[{0}] ⚠️ Config invalide. Auto-réparation : utilisation de {1}").format(series_name, providers[0]))
        else:
            fallback = ScraperRegistry.get_by_type("Manga")
            if fallback:
                providers = [fallback[0].id]
                logging.warning(t.get("log_config_repair_absolute", "[{0}] ⚠️ Config invalide. Secours absolu : utilisation de {1}").format(series_name, providers[0]))

    return list(dict.fromkeys(providers))


def _scraper_has_required_api_key(scraper, config) -> bool:
    """True si le scraper n'a pas besoin de clé, ou si `{ID}_API_KEY` est renseignée."""
    if not getattr(scraper, "needs_api_key", False):
        return True
    key = (config.get(f"{scraper.id}_API_KEY") or "").strip()
    return bool(key)


def _all_usable_provider_ids(config, library_type) -> list:
    """Tous les scrapers du type avec clé API présente si requise."""
    scrapers = ScraperRegistry.get_by_type(library_type) or []
    return [s.id for s in scrapers if _scraper_has_required_api_key(s, config)]


def expand_providers_for_super_review(config, library_type, preferred_ids=None) -> list:
    """
    Super Review : slots UI préférés en tête, puis tous les scrapers utilisables.
    """
    preferred = [p for p in (preferred_ids or []) if p and ScraperRegistry.get(p)]
    all_ids = _all_usable_provider_ids(config, library_type)
    usable = set(all_ids)
    ordered = []
    seen = set()
    for p in preferred:
        if p in usable and p not in seen:
            ordered.append(p)
            seen.add(p)
    for p in all_ids:
        if p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered or preferred or all_ids


def resolve_manual_review_flags(config, is_forced_id=False):
    """
    (manual_mode, super_review).

    Super Review : toujours la file manuelle + expansion scrapers — un override
    (forced_id / forced_provider) ne doit pas court-circuiter le parcours.

    Manuel classique : ID/URL forcé → auto-apply (choix déjà explicite).
    """
    want_manual = bool(config.get("MANUAL_REVIEW_MODE"))
    super_review = want_manual and bool(config.get("MANUAL_REVIEW_SUPER"))
    manual_mode = want_manual and (super_review or not bool(is_forced_id))
    return manual_mode, super_review


def apply_provider_overrides(
    providers_list,
    *,
    config,
    provider_family,
    forced_provider="AUTO",
    super_review=False,
):
    """
    Applique forced_provider : exclusif hors Super ; en Super, préfère puis expand all.
    """
    providers_list = list(providers_list or [])
    fp = forced_provider or "AUTO"
    if super_review:
        preferred = list(providers_list)
        if fp != "AUTO" and fp in ScraperRegistry._scrapers:
            preferred = [fp] + [p for p in preferred if p != fp]
        return expand_providers_for_super_review(
            config, provider_family, preferred_ids=preferred
        )
    if fp != "AUTO" and fp in ScraperRegistry._scrapers:
        return [fp]
    return providers_list


def _has_useful_provider_data(data):
    """Même critère que metadata_fetcher.has_useful_data (sans importer le privé)."""
    if not data:
        return False
    return bool(
        data.get('summary') or data.get('genres') or data.get('cover_url')
        or data.get('staff') or data.get('year')
    )


def _candidates_empty(payload):
    if not payload or not isinstance(payload, dict):
        return True
    return not (payload.get("above") or payload.get("below"))


def _candidates_have_a_strong_hit(payload):
    """True si au moins un candidat dépasse le VRAI seuil d'acceptation.

    En mode manuel, la cascade Comic tourne avec le seuil scrapers mis à 0.0
    (`_install_zero_match_threshold`) pour que l'utilisateur puisse voir les
    correspondances faibles au lieu de les perdre — elles finissent dans
    `below`, pas rejetées. `above` reste donc le seul signal comparable au
    critère Auto (`_has_useful_provider_data`, qui lui tourne avec le seuil
    réel et renvoie `None` sous ce seuil). Se baser sur `_candidates_empty`
    ici ferait dépendre le déclenchement du fallback Manga Comic Flexible du
    nombre de candidats FAIBLES trouvés plutôt que de l'existence d'un BON
    candidat — exactement la divergence Auto/Manuel que ce garde-fou évite.
    """
    return bool((payload or {}).get("above"))


def _apply_comic_flexible_manga_fallback(
    candidates_payload,
    used_providers,
    *,
    library_type,
    forced_provider,
    super_review,
    search_query,
    fallback_query,
    config,
    series_name,
    smart_completion,
    is_forced_id,
    existing_metadata,
    smart_scoring,
    t,
):
    """Bascule Comic → Manga pour une bibliothèque Flexible, cohérente avec le
    mode Auto : condition de déclenchement (`_candidates_have_a_strong_hit`,
    pas `_candidates_empty`) ET remplacement conditionnel (la vague Manga ne
    remplace la vague Comic que si elle a trouvé quelque chose — sinon
    l'utilisateur perdrait les candidats Comic faibles qu'il pouvait encore
    choisir manuellement, contrainte propre au mode manuel qui n'existe pas
    côté Auto).

    Retourne (candidates_payload, used_providers), inchangés si la bascule ne
    s'applique pas ou n'apporte rien.
    """
    if not (
        library_type == "ComicFlexible"
        and (forced_provider == "AUTO" or super_review)
        and not _candidates_have_a_strong_hit(candidates_payload)
    ):
        return candidates_payload, used_providers

    from metadata_fetcher import fetch_metadata

    manga_providers = _providers_from_config(config, "Manga", series_name)
    if super_review:
        manga_providers = expand_providers_for_super_review(
            config, "Manga", preferred_ids=manga_providers
        )
    if not manga_providers:
        return candidates_payload, used_providers

    logging.info(
        t.get(
            "log_flexible_manga_fallback",
            "[{0}] 🔀 Comic Flexible : aucun hit Comic — bascule vers les providers Manga ({1}).",
        ).format(series_name, " > ".join(manga_providers))
    )
    manga_payload, manga_used = fetch_metadata(
        search_query,
        manga_providers,
        smart_completion,
        return_candidates=True,
        fallback_query=fallback_query,
        library_type="Manga",
        is_forced_id=is_forced_id,
        forced_provider=forced_provider,
        existing_metadata=existing_metadata,
        smart_scoring=smart_scoring,
    )
    used_providers = list(dict.fromkeys((used_providers or []) + (manga_used or [])))
    if not _candidates_empty(manga_payload):
        candidates_payload = manga_payload
    return candidates_payload, used_providers


def _scrape_manual_candidates(
    series_id,
    series_name,
    search_query,
    fallback_query,
    *,
    config,
    kavita,
    cache_data=None,
    is_forced_id=False,
):
    """
    Collecte above/below pour le mode manuel (return_candidates=True).

    Retourne (candidates_payload, used_providers). Payload peut être vide.
    """
    from metadata_fetcher import fetch_metadata

    cache_data = cache_data or {}
    library_type = kavita.get_library_type_for_series(series_id)
    provider_family = "Comic" if library_type in ("Comic", "ComicFlexible") else library_type
    providers_list = _providers_from_config(config, provider_family, series_name)
    forced_provider = cache_data.get("forced_provider", "AUTO") or "AUTO"
    _, super_review = resolve_manual_review_flags(config, is_forced_id=is_forced_id)

    if is_forced_id:
        if str(search_query).startswith("http://") or str(search_query).startswith("https://"):
            if forced_provider == "AUTO":
                for s in ScraperRegistry.get_all():
                    if s.extract_id_from_url(search_query):
                        forced_provider = s.id
                        break
        elif forced_provider == "AUTO" and not super_review:
            providers_list = [
                p for p in providers_list
                if getattr(ScraperRegistry.get(p), "has_direct_id_support", False)
            ]

    # Re-recherche manuelle : toujours candidats (appelée depuis research_manual_review)
    providers_list = apply_provider_overrides(
        providers_list,
        config=config,
        provider_family=provider_family,
        forced_provider=forced_provider,
        super_review=super_review,
    )

    smart_completion = config.get("SMART_COMPLETION", False)
    smart_scoring = config.get("SMART_SCORING", True)
    reset_context_on_force = config.get("RESET_CONTEXT_ON_FORCE", False)
    # force_update N/A ici — re-recherche = toujours contexte courant sauf reset flag
    if reset_context_on_force:
        existing_metadata = {
            "isbn": kavita.get_series_isbn(series_id),
            "authors": [],
            "publisher": None,
            "year": None,
            "genres": [],
            "localized_name": None,
            "publisher_pref": cache_data.get("publisher_pref", "GLOBAL"),
        }
    else:
        existing_metadata = kavita.get_series_deep_metadata(series_id) or {}
        existing_metadata["publisher_pref"] = cache_data.get("publisher_pref", "GLOBAL")

    # Comic / Flexible : année de run dans le nom Kavita "(YYYY)" → contexte scrapers
    # avant la vague Comic (et avant tout fallback Manga).
    if library_type in ("Comic", "ComicFlexible"):
        apply_title_year_hint(existing_metadata, search_query, series_name)

    fetch_type = "Comic" if library_type == "ComicFlexible" else library_type
    if forced_provider != "AUTO" and forced_provider in ScraperRegistry._scrapers:
        scraper = ScraperRegistry.get(forced_provider)
        st = getattr(scraper, "supported_types", set()) or set()
        if library_type == "ComicFlexible":
            if "Comic" in st:
                fetch_type = "Comic"
            elif "Manga" in st:
                fetch_type = "Manga"

    fetch_kwargs = dict(
        fallback_query=fallback_query,
        library_type=fetch_type,
        is_forced_id=is_forced_id,
        forced_provider=forced_provider,
        existing_metadata=existing_metadata,
        smart_scoring=smart_scoring,
    )

    candidates_payload, used_providers = fetch_metadata(
        search_query,
        providers_list,
        smart_completion,
        return_candidates=True,
        **fetch_kwargs,
    )

    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    candidates_payload, used_providers = _apply_comic_flexible_manga_fallback(
        candidates_payload,
        used_providers,
        library_type=library_type,
        forced_provider=forced_provider,
        super_review=super_review,
        search_query=search_query,
        fallback_query=fallback_query,
        config=config,
        series_name=series_name,
        smart_completion=smart_completion,
        is_forced_id=is_forced_id,
        existing_metadata=existing_metadata,
        smart_scoring=smart_scoring,
        t=t,
    )

    if isinstance(candidates_payload, dict):
        candidates_payload["query"] = search_query
    return candidates_payload or {"above": [], "below": [], "query": search_query}, used_providers or []


def research_manual_review(review_id, query: str):
    """
    Re-scrape une pending review avec un nouveau titre (comme l'override
    alternative_title), écrase les candidats, conserve le même review_id.

    Retourne (ok, message_ou_detail, detail_dict|None).
    detail = { review lite pour l'UI } si ok.
    """
    from db_manager import save_series_override, update_pending_review
    from metadata_fetcher import candidate_card_for_ui
    from models import SeriesOverride
    from services.manual_review import (
        translate_candidate_summaries,
        emit_pending_count,
        _safe_emit,
    )

    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    query = (query or "").strip()
    if not query:
        return False, t.get("msg_search_title_empty", "Titre de recherche vide."), None

    review = get_pending_review(review_id)
    if not review:
        return False, t.get("msg_review_missing", "Review introuvable."), None

    series_id = int(review["series_id"])
    series_name = review.get("series_name") or str(series_id)

    with _processing_lock:
        if series_id in _processing_series_ids:
            return False, t.get("msg_already_processing", "Déjà en cours de traitement."), None
        _processing_series_ids.add(series_id)

    try:
        kavita = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
        if not kavita.authenticate():
            return False, t.get("msg_kavita_error", "Erreur Kavita."), None

        cache_data = get_all_cached_data().get(series_id, {})
        ov = SeriesOverride.from_cache_dict(series_id, cache_data)
        ov.alternative_title = query
        # Comme l'override titre, sans purger la review en cours.
        save_series_override(ov, purge_pending=False, status="PENDING_REVIEW")

        logging.info(t.get("log_mr_research", "[{0}] 🔎 Re-recherche manuelle : « {1} » (review {2})").format(series_name, query, review_id))
        candidates_payload, used_providers = _scrape_manual_candidates(
            series_id,
            series_name,
            query,
            query,
            config=config,
            kavita=kavita,
            cache_data=get_all_cached_data().get(series_id, {}),
            is_forced_id=False,
        )

        if _candidates_empty(candidates_payload):
            logging.warning(t.get("log_not_found").format(series_name, "API(s)"))
            return False, t.get("msg_no_candidates", "Aucun candidat pour cette recherche."), {
                "query": query,
                "used_providers": used_providers,
            }

        try:
            candidates_payload, n_tr = translate_candidate_summaries(candidates_payload, config=config)
            if n_tr:
                logging.info(
                    t.get(
                        "log_mr_summaries_translated_research",
                        "[manual_review] {0} résumé(s) traduit(s) (re-recherche {1})",
                    ).format(n_tr, series_name)
                )
        except Exception as exc:
            logging.warning(t.get("log_mr_retranslate_fail", "[manual_review] traduction re-recherche échouée : {0}").format(exc))

        update_pending_review(
            review_id,
            candidates_json=candidates_payload,
            preview_json=None,
            state="awaiting_pick",
            base_provider=None,
            chosen_score=None,
        )

        try:
            from db_manager import record_manual_research_telemetry
            record_manual_research_telemetry()
        except Exception as exc:
            logging.debug("[manual_review] research telemetry skipped: %s", exc)

        def _lite(cards):
            out = []
            for card in cards or []:
                ui = candidate_card_for_ui(card)
                if ui:
                    out.append(ui)
            return out

        lite = {
            "review_id": review_id,
            "series_id": series_id,
            "series_name": series_name,
            "state": "awaiting_pick",
            "base_provider": None,
            "chosen_score": None,
            "above": _lite(candidates_payload.get("above")),
            "below": _lite(candidates_payload.get("below")),
            "query": candidates_payload.get("query") or query,
            "preview": None,
            "used_providers": used_providers,
        }
        _safe_emit("manual_review_refreshed", {
            "review_id": review_id,
            "series_id": series_id,
            "above_count": len(lite["above"]),
            "below_count": len(lite["below"]),
            "query": lite["query"],
        })
        emit_pending_count()
        return True, "OK", lite
    except Exception as exc:
        logging.error(t.get("log_mr_research_crash", "[{0}] Crash re-recherche manuelle : {1}").format(series_name, exc))
        return False, t.get("err_internal", "Erreur interne."), None
    finally:
        with _processing_lock:
            _processing_series_ids.discard(series_id)


def _top1_provider(candidates_payload):
    above = (candidates_payload or {}).get("above") or []
    below = (candidates_payload or {}).get("below") or []
    top = above if above else below
    if not top:
        return None
    return top[0].get("provider")


def enrich_series(series_id, series_name, force_update=False, targeted_fields_override=None):
    """
    Récupère les métadonnées existantes dans Kavita, scrape les fournisseurs
    externes configurés, applique les champs ciblés par l'utilisateur, puis
    envoie le résultat à Kavita (métadonnées, généralités, couverture).

    `targeted_fields_override` : masque éphémère (ex. batch) qui prime sur le
    `targeted_fields` persisté en cache pour CE run uniquement.

    Retourne un tuple (success: bool, message: str, used_providers: list).
    """
    sid = int(series_id)
    with _processing_lock:
        if sid in _processing_series_ids:
            config = load_config()
            t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
            logging.warning(t.get("log_already_processing_detail", "⏭️ [{0}] Traitement déjà en cours pour cette série ailleurs (Sync manuel / file d'attente / webhook) : requête ignorée pour éviter une écriture concurrente vers Kavita.").format(series_name))
            return False, t.get("msg_already_processing", "Déjà en cours de traitement."), []
        _processing_series_ids.add(sid)

    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
    try:
        kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

        if not kavita.authenticate():
            logging.error(t.get('log_auth_fail').format(series_name))
            return False, t.get("msg_kavita_error", "Erreur Kavita."), []

        metadata = kavita.get_series_metadata(series_id)
        if not metadata:
            logging.error(t.get('log_meta_fail').format(series_name))
            return False, t.get("msg_meta_error", "Erreur de métadonnées."), []

        # Cache tôt : besoin du statut / forced_id avant le court-circuit « déjà à jour ».
        cache_data = get_all_cached_data().get(int(series_id), {})
        if metadata.get('summary') and not force_update:
            # Ne pas clobber une série garée en review manuelle (sinon COMPLETED +
            # ligne pending_reviews orpheline).
            if cache_data.get('status') == 'PENDING_REVIEW':
                logging.info(t.get("log_pending_review_skip", "[{0}] ⏭️ Déjà en PENDING_REVIEW — skip (résumé Kavita présent).").format(series_name))
                return True, "PENDING_REVIEW", []
            # Données présentes mais verrous en attente → tenter seal seul.
            if cache_data.get('status') == 'NEEDS_RELOCK':
                ok_seal, seal_msg = kavita.seal_series_locks(series_id)
                if ok_seal:
                    update_status(series_id, 'COMPLETED')
                    _emit_series_status(series_id, 'COMPLETED', series_name)
                    logging.info(t.get("log_seal_deferred_ok", "[{0}] ✅ Seal différé OK — COMPLETED").format(series_name))
                    return True, t.get("msg_success", "Succès"), []
                logging.warning(t.get("log_still_needs_relock", "[{0}] ⚠️ Toujours À sceller ({1})").format(series_name, seal_msg))
                _emit_series_status(series_id, "NEEDS_RELOCK", series_name)
                return True, "NEEDS_RELOCK", []
            logging.info(t.get('log_skip').format(series_name))
            update_status(series_id, 'COMPLETED')
            _emit_series_status(series_id, 'COMPLETED', series_name)
            # Nettoie toute review orpheline éventuelle
            try:
                from db_manager import delete_pending_by_series
                delete_pending_by_series(int(series_id))
            except Exception as e:
                logging.debug(
                    "[%s] orphan pending_review purge failed: %s",
                    series_name,
                    safe_exc_str(e),
                )
            return True, t.get("msg_already_up_to_date", "Déjà à jour."), []

        # --- Détermination du type de bibliothèque ---
        library_type = kavita.get_library_type_for_series(series_id)

        # --- Détermination des requêtes de recherche et replis ---
        forced_id = cache_data.get('forced_id')
        search_query = forced_id or cache_data.get('alternative_title') or series_name
        fallback_query = cache_data.get('alternative_title') or series_name
        is_forced_id = bool(forced_id)

        # --- Récupération des champs ciblés (Scraping Granulaire) ---
        active_fields = resolve_active_fields(
            cache_data.get('targeted_fields', 'ALL'),
            override=targeted_fields_override,
        )

        # --- LECTURE DE LA CONFIGURATION UTILISATEUR ---
        # ComicFlexible : vague Comic d'abord ; la vague Manga est construite plus bas si besoin.
        provider_family = "Comic" if library_type in ("Comic", "ComicFlexible") else library_type
        providers_list = _providers_from_config(config, provider_family, series_name)

        # --- OVERRIDE DU FOURNISSEUR & AUTO-DÉTECTION URL ---
        forced_provider = cache_data.get('forced_provider', 'AUTO')

        # Super : file manuelle même avec forced_id ; expand tous scrapers même avec forced_provider.
        # Manuel classique : ID/URL forcé → auto-apply.
        smart_completion = config.get("SMART_COMPLETION", False)
        smart_scoring = config.get("SMART_SCORING", True)
        manual_mode, super_review = resolve_manual_review_flags(
            config, is_forced_id=is_forced_id
        )

        if is_forced_id:
            if search_query.startswith('http://') or search_query.startswith('https://'):
                if forced_provider == 'AUTO':
                    for s in ScraperRegistry.get_all():
                        if s.extract_id_from_url(search_query):
                            forced_provider = s.id
                            logging.info(t.get('log_auto_url_found', "[{0}] 🕵️ URL reconnue ! Le scraper {1} prend le relais.").format(series_name, s.display_name))
                            break
            else:
                # ID brut : filtre ID-capable uniquement hors Super (Super expand all ensuite)
                if forced_provider == 'AUTO' and not super_review:
                    logging.info(t.get("log_smart_id", "[{0}] 🔄 ID brut détecté en mode AUTO. Lancement de la résolution intelligente (Smart ID Match).").format(series_name))
                    providers_list = [p for p in providers_list if getattr(ScraperRegistry.get(p), 'has_direct_id_support', False)]

        before_override = list(providers_list)
        providers_list = apply_provider_overrides(
            providers_list,
            config=config,
            provider_family=provider_family,
            forced_provider=forced_provider,
            super_review=super_review,
        )
        if (
            not super_review
            and forced_provider != 'AUTO'
            and forced_provider in ScraperRegistry._scrapers
        ):
            logging.info(t.get('log_forced_provider', "[{0}] 🎯 Scraping ciblé forcé sur : {1}").format(series_name, forced_provider))
        elif super_review:
            logging.info(
                "[%s] Super Review : %d scrapers (slots %d → tous utilisables)%s.",
                series_name,
                len(providers_list),
                len(before_override),
                t.get("log_override_preferred", ", override {0} préféré").format(forced_provider) if forced_provider != "AUTO" else "",
            )

        # Log protégé contre les valeurs None
        safe_providers_log = [str(p) for p in providers_list if p is not None]
        logging.info(t.get('log_scraping').format(series_name, " > ".join(safe_providers_log), search_query))
        logging.info(t.get('log_lib_type_detected', "[{0}] 📂 Type de bibliothèque détecté : {1}").format(series_name, library_type))
        if manual_mode:
            mode_label = "Super Review" if super_review else t.get("label_manual_mode", "manuel")
            logging.info(t.get("log_pending_review_counts", "[{0}] 👁️ Mode {1} : candidats → file de review.").format(series_name, mode_label))
        elif smart_scoring:
            logging.info(t.get("log_smart_scoring_on", "[{0}] 🎯 Smart Scoring activé (meilleur score gagne).").format(series_name))
        else:
            logging.info(t.get("log_classic_fallback", "[{0}] 📋 Fallback classique (ordre de la liste des fournisseurs).").format(series_name))

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

        # Comic / Flexible : année "(YYYY)" du nom → existing_metadata avant vague Comic.
        if library_type in ("Comic", "ComicFlexible"):
            apply_title_year_hint(existing_metadata, search_query, series_name)

        # --- APPEL DU SCRAPER ---
        from metadata_fetcher import fetch_metadata

        # Type passé aux scrapers : ComicFlexible n'existe pas dans supported_types.
        # Vague 1 = Comic (ou type natif) ; vague 2 Manga seulement pour Flexible sans forçage.
        fetch_type = "Comic" if library_type == "ComicFlexible" else library_type
        if forced_provider != 'AUTO' and forced_provider in ScraperRegistry._scrapers:
            scraper = ScraperRegistry.get(forced_provider)
            st = getattr(scraper, 'supported_types', set()) or set()
            if library_type == "ComicFlexible":
                if "Comic" in st:
                    fetch_type = "Comic"
                elif "Manga" in st:
                    fetch_type = "Manga"

        fetch_kwargs = dict(
            fallback_query=fallback_query,
            library_type=fetch_type,
            is_forced_id=is_forced_id,
            forced_provider=forced_provider,
            existing_metadata=existing_metadata,
            smart_scoring=smart_scoring,
        )

        # ========== MODE MANUEL (C29) ==========
        if manual_mode:
            candidates_payload, used_providers = fetch_metadata(
                search_query,
                providers_list,
                smart_completion,
                return_candidates=True,
                **fetch_kwargs,
            )
            # Comic Flexible : même critère de bascule Manga qu'en Auto (voir
            # _apply_comic_flexible_manga_fallback).
            candidates_payload, used_providers = _apply_comic_flexible_manga_fallback(
                candidates_payload,
                used_providers,
                library_type=library_type,
                forced_provider=forced_provider,
                super_review=super_review,
                search_query=search_query,
                fallback_query=fallback_query,
                config=config,
                series_name=series_name,
                smart_completion=smart_completion,
                is_forced_id=is_forced_id,
                existing_metadata=existing_metadata,
                smart_scoring=smart_scoring,
                t=t,
            )

            if _candidates_empty(candidates_payload):
                logging.warning(t.get("log_not_found").format(series_name, "API(s)"))
                update_status(series_id, "NOT_FOUND")
                _emit_series_status(series_id, "NOT_FOUND", series_name)
                _broadcast_enrichment_stats(record_enrichment_miss())
                return False, "Introuvable.", used_providers or []

            from services.manual_review import create_review_from_candidates

            create_review_from_candidates(
                series_id,
                series_name,
                candidates_payload,
                library_id=kavita.get_cached_library_id(series_id),
            )
            _emit_series_status(series_id, "PENDING_REVIEW", series_name)
            logging.info(
                f"[{series_name}] 👁️ PENDING_REVIEW "
                f"(above={len((candidates_payload or {}).get('above') or [])}, "
                f"below={len((candidates_payload or {}).get('below') or [])})"
            )
            return True, "PENDING_REVIEW", used_providers or []

        # ========== MODE AUTO ==========
        provider_data, used_providers = fetch_metadata(
            search_query,
            providers_list,
            smart_completion,
            **fetch_kwargs,
        )

        # C35 : Comic Flexible — si la vague Comic échoue et qu'aucun provider n'est forcé,
        # bascule sur la cascade Manga (PROVIDER_*).
        if (
            library_type == "ComicFlexible"
            and forced_provider == 'AUTO'
            and not _has_useful_provider_data(provider_data)
        ):
            manga_providers = _providers_from_config(config, "Manga", series_name)
            if is_forced_id and not (search_query.startswith('http://') or search_query.startswith('https://')):
                manga_providers = [
                    p for p in manga_providers
                    if getattr(ScraperRegistry.get(p), 'has_direct_id_support', False)
                ]
            if manga_providers:
                logging.info(
                    t.get(
                        'log_flexible_manga_fallback',
                        "[{0}] 🔀 Comic Flexible : aucun hit Comic — bascule vers les providers Manga ({1})."
                    ).format(series_name, " > ".join(manga_providers))
                )
                manga_data, manga_used = fetch_metadata(
                    search_query,
                    manga_providers,
                    smart_completion,
                    fallback_query=fallback_query,
                    library_type="Manga",
                    is_forced_id=is_forced_id,
                    forced_provider=forced_provider,
                    existing_metadata=existing_metadata,
                    smart_scoring=smart_scoring,
                )
                used_providers = list(dict.fromkeys((used_providers or []) + (manga_used or [])))
                if _has_useful_provider_data(manga_data):
                    provider_data = manga_data

        if not provider_data:
            logging.warning(t.get('log_not_found').format(series_name, "API(s)"))
            update_status(series_id, 'NOT_FOUND')
            _emit_series_status(series_id, 'NOT_FOUND', series_name)
            _broadcast_enrichment_stats(record_enrichment_miss())
            return False, "Introuvable.", used_providers

        actual_provider = provider_data.pop('_provider_used', 'Inconnu')
        fusion_providers = provider_data.pop('_fusion_providers', [])
        # Purement diagnostique (Smart Scoring, voir metadata_fetcher.py) : jamais lu ni
        # envoyé à Kavita, mais on l'enlève pour ne pas polluer les dumps de debug.
        chosen_score = provider_data.pop(MATCH_SCORE_KEY, None)
        # BF68: égalité de score → awaiting_pick (pas confirm silencieux).
        score_tie = bool(provider_data.pop('_score_tie', False))
        tie_review_payload = provider_data.pop('_tie_review_payload', None)

        msg_found = t.get('log_found').format(series_name) + f" (Base: {actual_provider})"
        if fusion_providers:
            # Protection contre les None dans la liste de fusion
            safe_fusion = [str(fp) for fp in fusion_providers if fp is not None]
            if safe_fusion:
                msg_found += f" + 🧩 Fusion ({', '.join(safe_fusion)})"
        logging.info(msg_found)

        built = build_kavita_payload(
            provider_data, metadata, active_fields, config, cache_data, force_update, series_id
        )

        # Confirm-before-write (MR off) : park preview, pas d'écriture immédiate.
        # BF68: score tie → pick normal (pas awaiting_confirm).
        if not manual_mode and bool(config.get("CONFIRM_BEFORE_WRITE")):
            if score_tie:
                from services.manual_review import create_review_from_candidates

                payload = tie_review_payload if isinstance(tie_review_payload, dict) else None
                if not payload or not ((payload.get("above") or []) or (payload.get("below") or [])):
                    # Filet rare : reconstruire une carte unique depuis le vainqueur.
                    from metadata_fetcher import build_candidate_card
                    import copy as _copy
                    card = build_candidate_card(
                        actual_provider,
                        _copy.deepcopy(provider_data),
                        below_threshold=False,
                    )
                    payload = {
                        "above": [card],
                        "below": [],
                        "query": search_query,
                    }
                create_review_from_candidates(
                    series_id,
                    series_name,
                    payload,
                    library_id=kavita.get_cached_library_id(series_id),
                )
                _emit_series_status(series_id, "PENDING_REVIEW", series_name)
                logging.info(
                    f"[{series_name}] 👁️ PENDING_REVIEW "
                    f"(score tie → pick; "
                    f"above={len((payload or {}).get('above') or [])}, "
                    f"below={len((payload or {}).get('below') or [])})"
                )
                return True, "PENDING_REVIEW", used_providers or []

            import copy
            from services.manual_review import create_confirm_from_auto

            data_for_park = copy.deepcopy(provider_data)
            create_confirm_from_auto(
                series_id,
                series_name,
                data_for_park,
                built.get("preview_fields") or {},
                actual_provider=actual_provider,
                fusion_providers=fusion_providers,
                chosen_score=chosen_score,
                query=search_query,
                force_update=force_update,
                library_id=kavita.get_cached_library_id(series_id),
            )
            _emit_series_status(series_id, "PENDING_REVIEW", series_name)
            return True, "PENDING_REVIEW", used_providers or []

        return apply_kavita_payload(
            kavita, series_id, series_name, built, active_fields, config, used_providers, t
        )

    except Exception as e:
        logging.error(t.get('log_crash').format(series_name, e))
        return False, t.get("err_internal", "Erreur interne."), []
    finally:
        with _processing_lock:
            _processing_series_ids.discard(sid)


def apply_manual_review(
    review_id,
    base_provider,
    include_providers=None,
    edited_preview=None,
    field_edits=0,
    force_update=True,
    fused=None,
    weak_pick=False,
    super_review=False,
    force_cover_upload=False,
):
    """
    Applique un choix de review manuelle : merge → (overlay edits) → build → write Kavita.

    Retourne (success: bool, message: str, detail: dict|None).
    """
    from services.manual_review import choice_and_merge, confirm_pending_review

    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    review = get_pending_review(review_id)
    if not review:
        return False, t.get("msg_review_missing", "Review introuvable."), None

    series_id = int(review["series_id"])
    with _processing_lock:
        if series_id in _processing_series_ids:
            return False, t.get("msg_already_processing", "Déjà en cours de traitement."), None
        _processing_series_ids.add(series_id)

    try:
        return _apply_manual_review_locked(
            review,
            review_id,
            base_provider,
            include_providers=include_providers,
            edited_preview=edited_preview,
            field_edits=field_edits,
            force_update=force_update,
            fused=fused,
            weak_pick=weak_pick,
            super_review=super_review,
            force_cover_upload=force_cover_upload,
            choice_and_merge=choice_and_merge,
            confirm_pending_review=confirm_pending_review,
        )
    finally:
        with _processing_lock:
            _processing_series_ids.discard(series_id)


def _apply_manual_review_locked(
    review,
    review_id,
    base_provider,
    *,
    include_providers,
    edited_preview,
    field_edits,
    force_update,
    fused,
    weak_pick,
    super_review,
    force_cover_upload,
    choice_and_merge,
    confirm_pending_review,
):
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    # Mode manuel : les cases « Fusionner » pilotent seules le comblement des trous.
    # Indépendant du toggle sidebar SMART_COMPLETION (batch auto).
    includes = [p for p in (include_providers or []) if p and p != base_provider]
    smart_fusion = bool(includes)
    if fused is None:
        fused = smart_fusion
    else:
        fused = bool(fused)

    try:
        candidates_payload = json.loads(review.get("candidates_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        candidates_payload = {"above": [], "below": []}

    is_auto_confirm = (
        isinstance(candidates_payload, dict)
        and candidates_payload.get("flow") == "auto_confirm"
    )
    if is_auto_confirm and "force_update" in candidates_payload:
        force_update = bool(candidates_payload.get("force_update"))

    # Si déjà awaiting_confirm avec même base, on peut re-merger ; sinon choice_and_merge
    provider_data = choice_and_merge(
        review_id,
        base_provider,
        include_providers=includes,
        smart_fusion=smart_fusion,
    )
    if not provider_data:
        return False, t.get("msg_merge_impossible", "Fusion impossible (provider invalide)."), None

    is_top1 = True if is_auto_confirm else (base_provider == _top1_provider(candidates_payload))
    chosen_score = None
    for band in ("above", "below"):
        for card in candidates_payload.get(band) or []:
            if card.get("provider") == base_provider:
                chosen_score = card.get("score")
                break
        if chosen_score is not None:
            break

    provider_data = overlay_edited_preview(provider_data, edited_preview)
    # Nettoyage clés internes avant write
    used_providers = [provider_data.get("_provider_used") or base_provider]
    for fp in provider_data.get("_fusion_providers") or []:
        if fp and fp not in used_providers:
            used_providers.append(fp)

    series_id = int(review["series_id"])
    series_name = review.get("series_name") or str(series_id)
    cache_data = get_all_cached_data().get(series_id, {})
    active_fields = resolve_active_fields(cache_data.get("targeted_fields", "ALL"))

    kavita = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    if not kavita.authenticate():
        return False, t.get("msg_kavita_error", "Erreur Kavita."), None

    metadata = kavita.get_series_metadata(series_id)
    if not metadata:
        return False, t.get("msg_meta_error", "Erreur de métadonnées."), None

    built = build_kavita_payload(
        provider_data, metadata, active_fields, config, cache_data, force_update, series_id
    )

    # Si preview édité porte localized_name sans passer par provider overlay
    if edited_preview and isinstance(edited_preview, dict) and "localized_name" in edited_preview:
        built["localized_name"] = edited_preview.get("localized_name") or None
        if built.get("preview_fields") is not None:
            built["preview_fields"]["localized_name"] = edited_preview.get("localized_name") or ""

    # Couverture choisie explicitement (phase cover / edit) → upload même sans AUTO_COVER
    explicit_cover = bool(force_cover_upload)
    if not explicit_cover and isinstance(edited_preview, dict) and edited_preview.get("cover_url"):
        explicit_cover = True
    if explicit_cover:
        built["force_cover_upload"] = True

    ok, msg, used = apply_kavita_payload(
        kavita, series_id, series_name, built, active_fields, config, used_providers, t
    )
    if not ok:
        return False, msg, {"preview": built.get("preview_fields")}

    write_status = "NEEDS_RELOCK" if msg == "NEEDS_RELOCK" else "COMPLETED"

    # Auto-confirm : pas de télémétrie Manual Review (pick/top1) — enrichissement déjà
    # compté par apply_kavita_payload.
    if not is_auto_confirm:
        deltas = record_manual_review_telemetry(
            chosen_score,
            is_top1,
            field_edits=field_edits,
            fused=fused,
            weak_pick=bool(weak_pick),
            super_review=bool(super_review),
        )
        # Lifetime déjà mis à jour par apply (enrichment) + manual ; rebroadcast avec extras
        _broadcast_enrichment_stats({
            **(deltas or {}),
            "series_enriched_delta": 0,
            "matches_won_delta": 0,
            "series_missed_delta": 0,
            "lifetime": get_lifetime_stats(),
        })
    confirm_pending_review(review_id, new_status=write_status)
    return True, ("NEEDS_RELOCK" if write_status == "NEEDS_RELOCK" else t.get("msg_success", "Succès")), {
        "preview": built.get("preview_fields"),
        "is_top1": is_top1,
        "score": chosen_score,
        "used_providers": used,
        "flow": "auto_confirm" if is_auto_confirm else "manual",
        "status": write_status,
    }


def preview_manual_review(review_id, base_provider, include_providers=None):
    """
    Merge + build preview sans écrire Kavita. Stocke preview_json sur la review.
    Retourne (ok, preview_fields|error_msg, built_or_none).
    """
    from services.manual_review import choice_and_merge
    from db_manager import update_pending_review

    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    review = get_pending_review(review_id)
    if not review:
        return False, t.get("msg_review_missing", "Review introuvable."), None

    # Mode manuel : fusion = cases cochées uniquement (pas SMART_COMPLETION sidebar).
    includes = [p for p in (include_providers or []) if p and p != base_provider]
    smart_fusion = bool(includes)
    provider_data = choice_and_merge(
        review_id,
        base_provider,
        include_providers=includes,
        smart_fusion=smart_fusion,
    )
    if not provider_data:
        return False, t.get("msg_merge_impossible", "Fusion impossible (provider invalide)."), None

    series_id = int(review["series_id"])
    cache_data = get_all_cached_data().get(series_id, {})
    active_fields = resolve_active_fields(cache_data.get("targeted_fields", "ALL"))

    # Preview UI : ne pas bloquer si Kavita est momentanément indisponible.
    # Le confirm réessaiera l'auth / écriture.
    metadata = {}
    try:
        kavita = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
        if kavita.authenticate():
            metadata = kavita.get_series_metadata(series_id) or {}
    except Exception as exc:
        logging.warning(t.get("log_mr_preview_no_meta", "[manual_review] preview sans métadonnées Kavita: {0}").format(exc))

    built = build_kavita_payload(
        provider_data, metadata, active_fields, config, cache_data, True, series_id
    )
    preview = built.get("preview_fields") or {}
    # Conservés hors build_kavita_payload (poppés avant envoi Kavita) pour le bandeau edit.
    preview["_provider_used"] = provider_data.get("_provider_used") or base_provider
    preview["_fusion_providers"] = list(provider_data.get("_fusion_providers") or [])
    update_pending_review(review_id, preview_json=preview, state="awaiting_confirm")
    return True, preview, built


def skip_manual_review(review_id):
    """Skip une pending review + broadcast compteur (via helper)."""
    from services.manual_review import skip_pending_review

    ok = skip_pending_review(review_id)
    if ok:
        _broadcast_enrichment_stats({
            "manual_skips_delta": 1,
            "lifetime": get_lifetime_stats(),
        })
    return ok
