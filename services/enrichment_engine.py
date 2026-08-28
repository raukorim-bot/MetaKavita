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
from secure_logging import safe_exc_str, series_label
from services.kavita_payload import (
    build_kavita_payload,
    apply_kavita_payload,
    overlay_edited_preview,
    _broadcast_enrichment_stats,
    _emit_series_status,
)
from services.magic_input import detect_provider_from_url

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

# Le champ « format » (sens de lecture) a été retiré de cette liste : il ne
# correspondait à aucune écriture. `build_kavita_payload` n'a jamais eu de
# branche `"format" in active`, parce que `UpdateSeriesDto` ne porte ni `Format`
# ni `FormatLocked` — le sens de lecture est une préférence par lecteur
# (`AppUserPreferences.ReadingDirection`), pas une propriété de série. La notion
# reste dans `kavita_constants.resolve_kavita_format_enum` et l'aperçu de review
# manuelle continue d'AFFICHER le format renvoyé par un fournisseur ; c'est de
# la lecture, jamais de l'écriture.
ALL_TARGETED_FIELDS = [
    "summary", "cover", "staff", "genres", "tags", "year",
    "status", "publisher", "age", "weblinks", "alt_titles", "language",
]

# Champs que la fiche « Ajuster avant envoi » peut cocher / décocher (C87).
# weblinks + language n'y figurent pas : ils suivent uniquement l'override série.
MR_EDIT_SENDABLE_FIELDS = frozenset({
    "summary", "cover", "staff", "genres", "tags", "year",
    "status", "publisher", "age", "alt_titles",
})
_SEND_FIELD_ALIASES = {
    "age_rating": "age",
    "cover_url": "cover",
    "localized_name": "alt_titles",
}


def resolve_active_fields(targeted_fields_raw, override=None):
    """
    Résout la liste des champs Kavita à écrire.
    `override` (masque batch éphémère) prime sur `targeted_fields_raw` (cache série).

    Les masques déjà enregistrés en base ne sont ni migrés ni filtrés : un jeton
    inconnu (« format », d'anciennes cases retirées) traverse la résolution et
    n'active aucune écriture, faute de branche qui le lise. Le nettoyer serait
    au mieux inutile, au pire dangereux — un masque réduit à « format » seul
    deviendrait une liste vide, que la ligne ci-dessous confond avec « ALL ».
    """
    raw = override if override is not None else targeted_fields_raw
    if raw is None or raw == "" or raw == "ALL":
        return list(ALL_TARGETED_FIELDS)
    if raw == "NONE":
        return []
    return [f.strip() for f in str(raw).split(",") if f.strip()]


def targeted_fields_is_granular(raw) -> bool:
    """True dès qu'un masque série n'écrit plus *tous* les champs (un seul décoché suffit)."""
    return set(resolve_active_fields(raw)) != set(ALL_TARGETED_FIELDS)


def alt_title_is_override(alternative_title, series_name) -> bool:
    """Le panneau préremplit le nom Kavita : ce n'est un override que s'il diffère."""
    alt = str(alternative_title or "").strip()
    name = str(series_name or "").strip()
    return bool(alt) and alt.casefold() != name.casefold()


def publisher_pref_is_override(raw) -> bool:
    v = str(raw or "GLOBAL").strip().upper()
    return v not in ("", "GLOBAL")


def alt_langs_is_override(raw) -> bool:
    return bool(str(raw or "").strip())


def alt_langs_chip_label(raw) -> str:
    parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    return ", ".join(parts)


def publisher_pref_chip_label(raw) -> str:
    v = str(raw or "GLOBAL").strip().upper()
    if v in ("ORIGINAL", "VO"):
        return "VO"
    if v in ("LOCALIZED", "VF", "VA", "VF/VA"):
        return "VF/VA"
    return str(raw or "").strip()


def normalize_send_fields(raw):
    """C87 : ``None`` = clé absente (legacy). Liste (même vide) = choix explicite."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    seen = set()
    for item in raw:
        key = str(item or "").strip()
        key = _SEND_FIELD_ALIASES.get(key, key)
        if key not in ALL_TARGETED_FIELDS or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def resolve_mr_write_fields(targeted_fields_raw, send_fields=None):
    """
    Masque d'écriture d'un confirm MR / SMR.

    Override série uniquement (pas le granulaire batch sidebar). ``send_fields``
    ``None`` = comportement historique. Les jetons de la fiche (cover, âge…)
    s'intersectent avec le masque ; weblinks / language restent ceux de la série.
    """
    series = resolve_active_fields(targeted_fields_raw)
    wanted = normalize_send_fields(send_fields)
    if wanted is None:
        return series
    wanted_set = set(wanted)
    out = []
    for field in series:
        if field in MR_EDIT_SENDABLE_FIELDS:
            if field in wanted_set:
                out.append(field)
        else:
            out.append(field)
    return out


def _providers_from_config(config, library_type, series_name, series_id=None):
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
        label = series_label(series_name, series_id)
        if available:
            providers = [available[0].id]
            logging.warning(t.get("log_config_repair", "[{0}] ⚠️ Config invalide. Auto-réparation : utilisation de {1}").format(label, providers[0]))
        else:
            fallback = ScraperRegistry.get_by_type("Manga")
            if fallback:
                providers = [fallback[0].id]
                logging.warning(t.get("log_config_repair_absolute", "[{0}] ⚠️ Config invalide. Secours absolu : utilisation de {1}").format(label, providers[0]))

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


def mapping_applies_here(config, *, forced_provider, manual_mode) -> bool:
    from services.field_mapping import mapping_should_run

    return mapping_should_run(
        config, forced_provider=forced_provider, manual_mode=manual_mode
    )


def field_mapping_log_line(label, assembled) -> str:
    sources = (assembled or {}).get("_field_sources") or {}
    base = (assembled or {}).get("_provider_used") or "?"
    extra = " ".join(f"{field}={provider}" for field, provider in sources.items())
    line = f"Base: {base}"
    if extra:
        line += " " + extra
    return line


def attach_mapping_preview(preview, assembled):
    if not isinstance(preview, dict):
        preview = {}
    sources = (assembled or {}).get("_field_sources") if isinstance(assembled, dict) else None
    if sources:
        preview["_field_sources"] = dict(sources)
        preview["_field_picks"] = {field: [provider] for field, provider in sources.items()}
    return preview


def _filter_id_capable(providers, search_query, is_forced_id):
    if not (
        is_forced_id
        and not (str(search_query).startswith("http://") or str(search_query).startswith("https://"))
    ):
        return list(providers or [])
    return [
        p for p in (providers or [])
        if getattr(ScraperRegistry.get(p), "has_direct_id_support", False)
    ]


def fetch_auto_series_metadata(
    *,
    search_query,
    providers_list,
    smart_completion,
    fetch_kwargs,
    library_type,
    forced_provider,
    config,
    series_name,
    series_id,
    is_forced_id,
    existing_metadata,
    smart_scoring,
    fallback_query,
    t,
    label,
):
    """Auto fetch : cascade actuelle si mapping off, sinon run_mapping_wave."""
    from metadata_fetcher import fetch_metadata
    from services.field_mapping import resolve_mapping_plan
    from services.field_mapping_fetch import run_mapping_wave

    if not mapping_applies_here(
        config, forced_provider=forced_provider, manual_mode=False
    ):
        provider_data, used_providers = fetch_metadata(
            search_query,
            providers_list,
            smart_completion,
            **fetch_kwargs,
        )
        if (
            library_type == "ComicFlexible"
            and forced_provider == "AUTO"
            and not _has_useful_provider_data(provider_data)
        ):
            manga_providers = _filter_id_capable(
                _providers_from_config(config, "Manga", series_name, series_id),
                search_query,
                is_forced_id,
            )
            if manga_providers:
                logging.info(
                    t.get(
                        "log_flexible_manga_fallback",
                        "[{0}] 🔀 Comic Flexible : aucun hit Comic — bascule vers les providers Manga ({1}).",
                    ).format(label, " > ".join(manga_providers))
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
        return provider_data, used_providers

    wave_kwargs = dict(
        smart_fusion=smart_completion,
        config=config,
        fallback_query=fallback_query,
        is_forced_id=is_forced_id,
        forced_provider=forced_provider,
        existing_metadata=existing_metadata,
        smart_scoring=smart_scoring,
    )

    if library_type == "ComicFlexible":
        comic_providers = _filter_id_capable(
            _providers_from_config(config, "Comic", series_name, series_id),
            search_query,
            is_forced_id,
        )
        plan_c = resolve_mapping_plan(config, "ComicFlexible", flexible_wave="comic")
        w1 = run_mapping_wave(
            plan_c,
            search_query,
            providers_list=comic_providers,
            library_type="Comic",
            **wave_kwargs,
        )
        if w1.score_tie or w1.useful:
            return w1.data, w1.used
        manga_providers = _filter_id_capable(
            _providers_from_config(config, "Manga", series_name, series_id),
            search_query,
            is_forced_id,
        )
        if not manga_providers:
            return w1.data, w1.used
        logging.info(
            t.get(
                "log_flexible_manga_fallback",
                "[{0}] 🔀 Comic Flexible : aucun hit Comic — bascule vers les providers Manga ({1}).",
            ).format(label, " > ".join(manga_providers))
        )
        plan_m = resolve_mapping_plan(config, "ComicFlexible", flexible_wave="manga")
        w2 = run_mapping_wave(
            plan_m,
            search_query,
            providers_list=manga_providers,
            library_type="Manga",
            **wave_kwargs,
        )
        used = list(dict.fromkeys((w1.used or []) + (w2.used or [])))
        if w2.useful or w2.score_tie:
            return w2.data, used
        return w1.data or w2.data, used

    plan = resolve_mapping_plan(config, library_type)
    wave = run_mapping_wave(
        plan,
        search_query,
        providers_list=providers_list,
        library_type=fetch_kwargs.get("library_type") or plan.fetch_library_type,
        **wave_kwargs,
    )
    return wave.data, wave.used


def _candidates_empty(payload):
    if not payload or not isinstance(payload, dict):
        return True
    return not (payload.get("above") or payload.get("below"))


def _candidates_have_a_strong_hit(payload):
    """True si au moins un candidat dépasse le VRAI seuil d'acceptation.

    En mode manuel, la cascade Comic tourne avec le seuil scrapers mis à 0.0
    (`scrapers.utils.match_accept_threshold_scope`) pour que l'utilisateur voie les
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
    on_candidate=None,
    series_id=None,
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

    manga_providers = _providers_from_config(config, "Manga", series_name, series_id)
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
        ).format(series_label(series_name, series_id), " > ".join(manga_providers))
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
        on_candidate=on_candidate,
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
    providers_list = _providers_from_config(config, provider_family, series_name, series_id)
    forced_provider = cache_data.get("forced_provider", "AUTO") or "AUTO"
    _, super_review = resolve_manual_review_flags(config, is_forced_id=is_forced_id)

    if is_forced_id:
        if str(search_query).startswith("http://") or str(search_query).startswith("https://"):
            if forced_provider == "AUTO":
                detected = detect_provider_from_url(search_query)
                if detected:
                    forced_provider = detected
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
        series_id=series_id,
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
    label = series_label(review.get("series_name"), series_id)

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

        logging.info(t.get("log_mr_research", "[{0}] 🔎 Re-recherche manuelle : « {1} » (review {2})").format(label, query, review_id))
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
            logging.warning(t.get("log_not_found").format(label, "API(s)"))
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
                    ).format(n_tr, label)
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
        logging.error(t.get("log_mr_research_crash", "[{0}] Crash re-recherche manuelle : {1}").format(label, exc))
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


def enrich_series(
    series_id,
    series_name,
    force_update=False,
    targeted_fields_override=None,
    *,
    super_review_override=None,
    force_auto=False,
):
    """
    Récupère les métadonnées existantes dans Kavita, scrape les fournisseurs
    externes configurés, applique les champs ciblés par l'utilisateur, puis
    envoie le résultat à Kavita (métadonnées, généralités, couverture).

    `targeted_fields_override` : masque éphémère (ex. batch) qui prime sur le
    `targeted_fields` persisté en cache pour CE run uniquement.

    C33 Companion (webhook one-shot) :
    - `super_review_override=True` : MR + expand scrapers même si Super sidebar off.
    - `force_auto=True` : chemin Auto (écriture) même si MANUAL_REVIEW_MODE on ;
      ignore aussi CONFIRM_BEFORE_WRITE. Si les deux sont demandés, Super gagne.

    Retourne un tuple (success: bool, message: str, used_providers: list).
    """
    sid = int(series_id)
    label = series_label(series_name, sid)
    with _processing_lock:
        already_running = sid in _processing_series_ids
        if not already_running:
            _processing_series_ids.add(sid)

    if already_running:
        try:
            t = translations.get(load_config().get("UI_LANG", "fr"), translations["fr"])
        except Exception:
            t = translations["fr"]
        logging.warning(t.get("log_already_processing_detail", "⏭️ [{0}] Traitement déjà en cours pour cette série ailleurs (Sync manuel / file d'attente / webhook) : requête ignorée pour éviter une écriture concurrente vers Kavita.").format(label))
        return False, t.get("msg_already_processing", "Déjà en cours de traitement."), []

    # Verrou posé : plus rien ne s'exécute hors du try/finally qui le relâche. La
    # lecture de la configuration se faisait dans l'intervalle et peut lever
    # (config.json valide mais qui n'est pas un objet — restauration de sauvegarde
    # interrompue, montage tronqué) : la série restait alors marquée « en cours de
    # traitement » jusqu'au redémarrage, et tout sync suivant la refusait.
    t = translations["fr"]
    try:
        config = load_config()
        t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
        kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

        if not kavita.authenticate():
            logging.error(t.get('log_auth_fail').format(label))
            return False, t.get("msg_kavita_error", "Erreur Kavita."), []

        metadata = kavita.get_series_metadata(series_id)
        if not metadata:
            logging.error(t.get('log_meta_fail').format(label))
            return False, t.get("msg_meta_error", "Erreur de métadonnées."), []

        # Cache tôt : besoin du statut / forced_id / champs ciblés avant le skip.
        cache_data = get_all_cached_data().get(int(series_id), {})
        active_fields = resolve_active_fields(
            cache_data.get('targeted_fields', 'ALL'),
            override=targeted_fields_override,
        )
        # Série garée en review manuelle : un run non forcé (batch avec sélection
        # explicite, webhook Kavita) ne doit pas la re-scraper. Le mode manuel
        # parke une review vide AVANT de scraper, et park_pending_review supprime
        # la review existante : la modale ouverte perdrait son identifiant et le
        # travail en cours. Le résumé Kavita n'est pas un critère — une série est
        # justement en review parce qu'elle n'en a pas. Le re-scrape volontaire
        # (bouton de la série, force=true, Companion) passe par force_update.
        if cache_data.get('status') == 'PENDING_REVIEW' and not force_update:
            logging.info(t.get("log_pending_review_skip", "[{0}] ⏭️ Déjà en review manuelle — skip (relancer en mode forcé pour re-scraper).").format(label))
            return True, "PENDING_REVIEW", []

        if metadata.get('summary') and not force_update:
            # Données présentes mais verrous en attente → tenter seal seul.
            if cache_data.get('status') == 'NEEDS_RELOCK':
                ok_seal, seal_msg = kavita.seal_series_locks(series_id)
                if ok_seal:
                    update_status(series_id, 'COMPLETED')
                    _emit_series_status(series_id, 'COMPLETED', series_name)
                    logging.info(t.get("log_seal_deferred_ok", "[{0}] ✅ Seal différé OK — COMPLETED").format(label))
                    return True, t.get("msg_success", "Succès"), []
                logging.warning(t.get("log_still_needs_relock", "[{0}] ⚠️ Toujours À sceller ({1})").format(label, seal_msg))
                _emit_series_status(series_id, "NEEDS_RELOCK", series_name)
                return True, "NEEDS_RELOCK", []
            # BF102: summary présent mais âge Pending/vide + champ age actif → enrichir.
            age_rating_kavita = metadata.get("ageRating")
            age_needs_fill = (
                "age" in active_fields
                and age_rating_kavita in (None, "", 0, 1)
            )
            if not age_needs_fill:
                logging.info(t.get('log_skip').format(label))
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

        # --- LECTURE DE LA CONFIGURATION UTILISATEUR ---
        # ComicFlexible : vague Comic d'abord ; la vague Manga est construite plus bas si besoin.
        provider_family = "Comic" if library_type in ("Comic", "ComicFlexible") else library_type
        providers_list = _providers_from_config(config, provider_family, series_name, series_id)

        # --- OVERRIDE DU FOURNISSEUR & AUTO-DÉTECTION URL ---
        forced_provider = cache_data.get('forced_provider', 'AUTO')

        # Super : file manuelle même avec forced_id ; expand tous scrapers même avec forced_provider.
        # Manuel classique : ID/URL forcé → auto-apply.
        smart_completion = config.get("SMART_COMPLETION", False)
        smart_scoring = config.get("SMART_SCORING", True)
        manual_mode, super_review = resolve_manual_review_flags(
            config, is_forced_id=is_forced_id
        )
        # C33 : overrides webhook Companion (Super > force_auto).
        if super_review_override is True:
            manual_mode = True
            super_review = True
        elif force_auto:
            manual_mode = False
            super_review = False

        if is_forced_id:
            if search_query.startswith('http://') or search_query.startswith('https://'):
                if forced_provider == 'AUTO':
                    detected = detect_provider_from_url(search_query)
                    if detected:
                        scraper = ScraperRegistry.get(detected)
                        display = (
                            scraper.display_name
                            if scraper
                            else detected
                        )
                        logging.info(
                            t.get(
                                'log_auto_url_found',
                                "[{0}] 🕵️ URL reconnue ! Le scraper {1} prend le relais.",
                            ).format(label, display)
                        )
                        from services.field_mapping import url_detect_should_pin_provider
                        if url_detect_should_pin_provider(
                            config, manual_mode=manual_mode
                        ):
                            forced_provider = detected
            else:
                # ID brut : filtre ID-capable uniquement hors Super (Super expand all ensuite)
                if forced_provider == 'AUTO' and not super_review:
                    logging.info(t.get("log_smart_id", "[{0}] 🔄 ID brut détecté en mode AUTO. Lancement de la résolution intelligente (Smart ID Match).").format(label))
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
            logging.info(t.get('log_forced_provider', "[{0}] 🎯 Scraping ciblé forcé sur : {1}").format(label, forced_provider))
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
        logging.info(t.get('log_scraping').format(label, " > ".join(safe_providers_log), search_query))
        logging.info(t.get('log_lib_type_detected', "[{0}] 📂 Type de bibliothèque détecté : {1}").format(label, library_type))
        if manual_mode:
            mode_label = "Super Review" if super_review else t.get("label_manual_mode", "manuel")
            logging.info(t.get("log_pending_review_counts", "[{0}] 👁️ Mode {1} : candidats → file de review.").format(label, mode_label))
        elif smart_scoring:
            logging.info(t.get("log_smart_scoring_on", "[{0}] 🎯 Smart Scoring activé (meilleur score gagne).").format(label))
        else:
            logging.info(t.get("log_classic_fallback", "[{0}] 📋 Fallback classique (ordre de la liste des fournisseurs).").format(label))

        # --- DÉTECTION DES MÉTADONNÉES PROFONDES KAVITA (ISBN & AUTEURS) ---
        reset_context_on_force = config.get('RESET_CONTEXT_ON_FORCE', False)

        if force_update and reset_context_on_force:
            logging.info(t.get('log_force_reset_context', "[{0}] 🔄 Mode forcé avec réinitialisation du contexte.").format(label))
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
                logging.info(t.get('log_isbn_detected', "[{0}] 📑 ISBN détecté dans Kavita : {1}").format(label, existing_metadata['isbn']))
            if existing_metadata.get('authors'):
                logging.info(t.get('log_authors_detected', "[{0}] ✍️ Auteur(s) détecté(s) dans Kavita : {1}").format(label, ', '.join(existing_metadata['authors'])))

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
            from services.manual_review import (
                append_streaming_candidate,
                begin_streaming_review,
                finalize_streaming_review,
            )
            from db_manager import delete_pending_by_series

            library_id = kavita.get_cached_library_id(series_id)
            # Park empty review immediately so Companion / MR UI can open and
            # stream cards as each scraper finishes (covers-like UX).
            review_id = begin_streaming_review(
                series_id,
                series_name,
                query=search_query,
                library_id=library_id,
            )
            _emit_series_status(series_id, "PENDING_REVIEW", series_name)

            def _on_candidate(card, band):
                append_streaming_candidate(review_id, series_id, card, band)

            candidates_payload, used_providers = fetch_metadata(
                search_query,
                providers_list,
                smart_completion,
                return_candidates=True,
                on_candidate=_on_candidate,
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
                on_candidate=_on_candidate,
                series_id=series_id,
            )

            if _candidates_empty(candidates_payload):
                logging.warning(t.get("log_not_found").format(label, "API(s)"))
                try:
                    delete_pending_by_series(series_id)
                except Exception:
                    pass
                from services.manual_review import emit_pending_count
                emit_pending_count()
                update_status(series_id, "NOT_FOUND")
                _emit_series_status(series_id, "NOT_FOUND", series_name)
                _broadcast_enrichment_stats(record_enrichment_miss())
                return False, "Introuvable.", used_providers or []

            finalize_streaming_review(
                review_id,
                series_id,
                series_name,
                candidates_payload,
                library_id=library_id,
            )
            logging.info(
                f"[{label}] 👁️ PENDING_REVIEW "
                f"(above={len((candidates_payload or {}).get('above') or [])}, "
                f"below={len((candidates_payload or {}).get('below') or [])})"
            )
            return True, "PENDING_REVIEW", used_providers or []

        # ========== MODE AUTO ==========
        provider_data, used_providers = fetch_auto_series_metadata(
            search_query=search_query,
            providers_list=providers_list,
            smart_completion=smart_completion,
            fetch_kwargs=fetch_kwargs,
            library_type=library_type,
            forced_provider=forced_provider,
            config=config,
            series_name=series_name,
            series_id=series_id,
            is_forced_id=is_forced_id,
            existing_metadata=existing_metadata,
            smart_scoring=smart_scoring,
            fallback_query=fallback_query,
            t=t,
            label=label,
        )

        if not provider_data:
            logging.warning(t.get('log_not_found').format(label, "API(s)"))
            update_status(series_id, 'NOT_FOUND')
            _emit_series_status(series_id, 'NOT_FOUND', series_name)
            _broadcast_enrichment_stats(record_enrichment_miss())
            return False, "Introuvable.", used_providers

        actual_provider = provider_data.pop('_provider_used', 'Inconnu')
        fusion_providers = provider_data.pop('_fusion_providers', [])
        field_sources = provider_data.pop('_field_sources', None)
        provider_data.pop('_cascade_blobs', None)
        # Purement diagnostique (Smart Scoring, voir metadata_fetcher.py) : jamais lu ni
        # envoyé à Kavita, mais on l'enlève pour ne pas polluer les dumps de debug.
        chosen_score = provider_data.pop(MATCH_SCORE_KEY, None)
        # BF68: égalité de score → awaiting_pick (pas confirm silencieux).
        score_tie = bool(provider_data.pop('_score_tie', False))
        tie_review_payload = provider_data.pop('_tie_review_payload', None)

        msg_found = t.get('log_found').format(label) + f" (Base: {actual_provider})"
        if fusion_providers:
            # Protection contre les None dans la liste de fusion
            safe_fusion = [str(fp) for fp in fusion_providers if fp is not None]
            if safe_fusion:
                msg_found += f" + 🧩 Fusion ({', '.join(safe_fusion)})"
        logging.info(msg_found)
        if field_sources:
            logging.info(
                "[%s] %s",
                label,
                field_mapping_log_line(
                    label,
                    {"_provider_used": actual_provider, "_field_sources": field_sources},
                ),
            )

        # BF102: diagnostic âge / champs ciblés (évite le piège « age décoché »).
        prov_age = str((provider_data or {}).get("age_rating") or "").strip() or "—"
        will_write_age = "age" in active_fields and bool(
            str((provider_data or {}).get("age_rating") or "").strip()
        )
        logging.info(
            t.get(
                "log_age_write_diag",
                "[{0}] Âge: provider={1} | champ age actif={2} | écriture prévue={3}",
            ).format(
                label,
                prov_age,
                "age" in active_fields,
                will_write_age,
            )
        )

        built = build_kavita_payload(
            provider_data, metadata, active_fields, config, cache_data, force_update, series_id
        )

        # Confirm-before-write (MR off) : park preview, pas d'écriture immédiate.
        # BF68: score tie → pick normal (pas awaiting_confirm).
        # C33 force_auto : Companion Auto doit écrire sans park CBW.
        if not manual_mode and bool(config.get("CONFIRM_BEFORE_WRITE")) and not force_auto:
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
                    f"[{label}] 👁️ PENDING_REVIEW "
                    f"(score tie → pick; "
                    f"above={len((payload or {}).get('above') or [])}, "
                    f"below={len((payload or {}).get('below') or [])})"
                )
                return True, "PENDING_REVIEW", used_providers or []

            import copy
            from services.manual_review import create_confirm_from_auto

            data_for_park = copy.deepcopy(provider_data)
            preview_fields = built.get("preview_fields") or {}
            attach_mapping_preview(
                preview_fields,
                {"_field_sources": field_sources or {}},
            )
            create_confirm_from_auto(
                series_id,
                series_name,
                data_for_park,
                preview_fields,
                actual_provider=actual_provider,
                fusion_providers=fusion_providers,
                chosen_score=chosen_score,
                query=search_query,
                force_update=force_update,
                library_id=kavita.get_cached_library_id(series_id),
                active_fields=active_fields,
            )
            _emit_series_status(series_id, "PENDING_REVIEW", series_name)
            return True, "PENDING_REVIEW", used_providers or []

        return apply_kavita_payload(
            kavita, series_id, series_name, built, active_fields, config, used_providers, t
        )

    except Exception as e:
        logging.error(t.get('log_crash').format(label, e))
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
    field_picks=None,
    merge_fields=False,
    manual_completion=None,
    send_fields=None,
):
    """
    Applique un choix de review manuelle : merge → (overlay edits) → build → write Kavita.

    Retourne (success: bool, message: str, detail: dict|None).
    ``send_fields`` ``None`` = masque série seul (bulk / apply direct / vieux clients).
    """
    from services.manual_review import (
        choice_and_merge,
        confirm_pending_review,
        revert_pick_after_failed_write,
    )

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
            field_picks=field_picks,
            merge_fields=merge_fields,
            manual_completion=manual_completion,
            send_fields=send_fields,
            choice_and_merge=choice_and_merge,
            confirm_pending_review=confirm_pending_review,
            revert_pick_after_failed_write=revert_pick_after_failed_write,
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
    field_picks,
    merge_fields,
    manual_completion,
    send_fields,
    choice_and_merge,
    confirm_pending_review,
    revert_pick_after_failed_write,
):
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    # État avant le pick : lui seul dit si l'avancement vers `awaiting_confirm`
    # a été décidé par cet appel (donc annulable) ou par l'utilisateur avant lui.
    prior_state = review.get("state") or "awaiting_pick"
    try:
        prev = json.loads(review.get("preview_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        prev = {}
    if not isinstance(prev, dict):
        prev = {}
    # Mode manuel : les cases « Fusionner » pilotent seules le comblement des trous.
    # Indépendant du toggle sidebar SMART_COMPLETION (batch auto).
    # include_providers is None → client omitted the key → restore from preview.
    # include_providers [] → intentional base-only (clear Sources).
    if include_providers is None:
        includes = [
            p for p in (prev.get("_fusion_providers") or [])
            if p and p != base_provider
        ]
    else:
        includes = [p for p in include_providers if p and p != base_provider]
    # False = complétion manuelle décochée : jamais restaurer un ancien _field_picks.
    # None + preview C86 = restore. True / dict = chemin cases par champ.
    if manual_completion is False:
        field_picks = None
        merge_fields = False
    elif field_picks is None and prev.get("_manual_completion"):
        field_picks = prev.get("_field_picks")
        if not isinstance(field_picks, dict):
            field_picks = {}
        merge_fields = bool(prev.get("_merge_fields"))
    elif field_picks is not None and not isinstance(field_picks, dict):
        field_picks = {}
    smart_fusion = bool(includes) and field_picks is None
    if fused is None:
        if field_picks is not None:
            fused = any(
                p and p != base_provider
                for picked in (field_picks or {}).values()
                for p in (picked if isinstance(picked, (list, tuple)) else [picked])
            )
        else:
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
        field_picks=field_picks,
        merge_fields=bool(merge_fields) if field_picks is not None else False,
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
    label = series_label(review.get("series_name"), series_id)
    cache_data = get_all_cached_data().get(series_id, {})
    active_fields = resolve_mr_write_fields(
        cache_data.get("targeted_fields", "ALL"),
        send_fields,
    )

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
    if (
        "alt_titles" in active_fields
        and edited_preview
        and isinstance(edited_preview, dict)
        and "localized_name" in edited_preview
    ):
        built["localized_name"] = edited_preview.get("localized_name") or None
        if built.get("preview_fields") is not None:
            built["preview_fields"]["localized_name"] = edited_preview.get("localized_name") or ""

    # Confirm MR = la couverture assemblée part, même sans phase cover picker
    # et même si AUTO_COVER est off. Case d'envoi / masque série sans cover → non.
    if "cover" not in active_fields:
        built.pop("force_cover_upload", None)
    elif built.get("cover_url"):
        built["force_cover_upload"] = True
    elif force_cover_upload or (
        isinstance(edited_preview, dict) and edited_preview.get("cover_url")
    ):
        built["force_cover_upload"] = True

    ok, msg, used = apply_kavita_payload(
        kavita, series_id, series_name, built, active_fields, config, used_providers, t
    )
    if not ok:
        # `choice_and_merge` a déjà avancé la review alors que rien n'a été écrit :
        # la remettre à l'écran de choix, sans quoi elle sort du périmètre de
        # « Tout accepter ≥ seuil » et n'y rentre plus jamais (BF144).
        if prior_state == "awaiting_pick":
            try:
                revert_pick_after_failed_write(review_id)
            except Exception as exc:
                logging.debug("manual review state revert failed: %s", safe_exc_str(exc))
        return False, msg, {"preview": built.get("preview_fields")}

    write_status = "NEEDS_RELOCK" if msg == "NEEDS_RELOCK" else "COMPLETED"

    # Kavita a écrit : clôturer AVANT de mesurer (BF144). La télémétrie et le
    # broadcast touchent SQLite, qui peut refuser (base verrouillée par un batch,
    # partage réseau momentanément absent) ; laisser la review en attente après
    # une écriture réussie amène l'utilisateur à reconfirmer, et la série part
    # une deuxième fois chez Kavita — couverture ré-uploadée, compteurs doublés.
    confirm_pending_review(review_id, new_status=write_status)

    # Auto-confirm : pas de télémétrie Manual Review (pick/top1) — enrichissement déjà
    # compté par apply_kavita_payload.
    if not is_auto_confirm:
        try:
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
        except Exception as exc:
            logging.warning(
                t.get(
                    "log_mr_telemetry_failed",
                    "[manual_review] télémétrie non enregistrée pour {0} : {1}",
                ).format(label, safe_exc_str(exc))
            )
    return True, ("NEEDS_RELOCK" if write_status == "NEEDS_RELOCK" else t.get("msg_success", "Succès")), {
        "preview": built.get("preview_fields"),
        "is_top1": is_top1,
        "score": chosen_score,
        "used_providers": used,
        "flow": "auto_confirm" if is_auto_confirm else "manual",
        "status": write_status,
    }


def preview_manual_review(
    review_id,
    base_provider,
    include_providers=None,
    field_picks=None,
    merge_fields=False,
    manual_completion=None,
):
    """
    Merge + build preview sans écrire Kavita. Stocke preview_json sur la review.
    Retourne (ok, preview_fields|error_msg, built_or_none).
    """
    from services.field_assembly import normalize_field_picks
    from services.manual_review import choice_and_merge
    from db_manager import update_pending_review

    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    review = get_pending_review(review_id)
    if not review:
        return False, t.get("msg_review_missing", "Review introuvable."), None

    # Mode manuel : fusion = cases cochées uniquement (pas SMART_COMPLETION sidebar).
    includes = [p for p in (include_providers or []) if p and p != base_provider]
    if manual_completion is False:
        use_field_picks = False
        field_picks = None
        merge_fields = False
    else:
        use_field_picks = field_picks is not None
    smart_fusion = bool(includes) and not use_field_picks
    provider_data = choice_and_merge(
        review_id,
        base_provider,
        include_providers=includes,
        smart_fusion=smart_fusion,
        field_picks=field_picks if use_field_picks else None,
        merge_fields=bool(merge_fields) if use_field_picks else False,
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
    preview["_active_fields"] = list(active_fields)
    if use_field_picks:
        preview["_manual_completion"] = True
        preview["_merge_fields"] = bool(merge_fields)
        preview["_field_picks"] = normalize_field_picks(
            field_picks, merge_fields=bool(merge_fields)
        )
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
