"""
Blueprint des pages HTML principales : tableau de bord (/), statistiques
(/stats) et atelier des tomes (`/volumes`, `/series/<id>/volumes`).

⚠️ Endpoints réels : 'pages.index', 'pages.stats', 'pages.volumes',
'pages.series_volumes' (voir routes/auth.py pour le rappel sur le nommage
des endpoints après passage aux Blueprints).
"""

import logging

from flask import Blueprint, request, render_template, session, abort

from config_manager import (
    load_config,
    get_kavita_ui_url,
    get_kavita_plus_url,
    get_disabled_library_ids,
)
from db_manager import (
    get_all_cached_data,
    clean_orphaned_cache,
    get_provider_stats,
    get_lifetime_stats,
    get_latest_auto_sync_report,
    get_series_audit_flags,
    get_volume_report_hygiene_map,
    get_hygiene_library_meta,
    list_hygiene_library_meta,
    count_volume_units_by_status,
    list_enriched_series_ids,
    list_catalog_expected_overrides,
    count_dup_dismissals,
    summarize_volume_writes,
)
from kavita_api import KavitaAPI
from scrapers.utils import get_dup_accept_threshold, get_match_accept_threshold
from translations import translations
from scrapers import ScraperRegistry
from services.changelog_service import get_current_version
from services.enrichment_engine import (
    alt_langs_chip_label,
    alt_langs_is_override,
    alt_title_is_override,
    publisher_pref_chip_label,
    publisher_pref_is_override,
    targeted_fields_is_granular,
)
from services.mr_achievements import evaluate_from_lifetime
from services.stats_service import compute_playful_stats, pick_hygiene_counts
from services.scraper_diagnostics import list_scrapers_inventory
from services.volume_enrichment.providers import (
    volume_provider_choices as list_volume_provider_choices,
)
from services.workshop import library_is_disabled, workshop_payload, workshop_rail
from routes.volume_enrichment import volume_enrichment_enabled

pages_bp = Blueprint('pages', __name__)


def _prepare_index_data(config, msg="", error_msg="", selected_lib=None):
    series_list = []
    libraries = []
    all_libraries = []

    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    disabled_ids = get_disabled_library_ids(config)

    if config.get('KAVITA_API_KEY') and config.get('KAVITA_URL'):
        kavita = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])

        if kavita.authenticate():
            all_libraries = kavita.get_libraries() or []

            # Dashboard = toutes les biblios. DISABLED_LIBRARIES ne borne que
            # le polling auto-sync (background_tasks), pas le batch ni le webhook.
            libraries = list(all_libraries)
            if selected_lib and not any(str(lib.get("id")) == str(selected_lib) for lib in libraries):
                selected_lib = None
            if all_libraries:
                series_list = kavita.get_all_series(library_id=selected_lib)

                if not selected_lib:
                    # Inventaire complet pour ne pas effacer le cache des séries
                    # temporairement hors sync (dénylist). Une bibliothèque qui
                    # n'a pas répondu rendrait ses séries orphelines : on ne
                    # purge que sur un inventaire intégralement lu.
                    if getattr(kavita, "last_inventory_complete", False):
                        full_ids = {s['id'] for s in series_list}
                        cleaned = clean_orphaned_cache(full_ids)
                        if cleaned > 0:
                            logging.info(t.get("log_orphans_cleaned", "🧹 Nettoyage : {0} séries orphelines retirées du cache.").format(cleaned))
                    else:
                        logging.warning(t.get("log_orphans_skipped", "🧹 Nettoyage des orphelines ignoré : inventaire Kavita incomplet."))
            else:
                error_msg = t.get('err_no_libraries', "Aucune bibliothèque trouvée dans Kavita.")
        else:
            err_key = {
                "localhost": "err_kavita_localhost",
                "http_401": "err_kavita_unauthorized",
                "timeout": "err_kavita_timeout",
                "dns": "err_kavita_dns",
                "connection": "err_kavita_connection",
                "ssl": "err_kavita_ssl",
            }.get(getattr(kavita, "last_auth_error", None), "err_kavita")
            error_msg = t.get(err_key, t.get('err_kavita', "Connexion à Kavita échouée."))
    else:
        error_msg = t.get('err_missing', "Données manquantes.")

    cached_info = get_all_cached_data()
    stats = {
        'total': len(cached_info),
        'completed': sum(1 for v in cached_info.values() if v.get('status') == 'COMPLETED'),
        'pending': sum(1 for v in cached_info.values() if v.get('status') == 'PENDING'),
        'pending_review': sum(1 for v in cached_info.values() if v.get('status') == 'PENDING_REVIEW'),
        'not_found': sum(1 for v in cached_info.values() if v.get('status') == 'NOT_FOUND'),
        'needs_relock': sum(1 for v in cached_info.values() if v.get('status') == 'NEEDS_RELOCK'),
        'ignored': sum(1 for v in cached_info.values() if v.get('status') == 'IGNORED')
    }

    # Hygiene SSR fields only after a real Analyser scan for this library.
    # "Toutes les bibliothèques" (selected_lib falsy) is scanned/stored under
    # the "all" key so the feature works there too (see hygiene_scan.py).
    # Inventaire coupé : on saute les deux lectures SQLite (et tout le rendu des
    # cartouches) plutôt que de les calculer pour une interface qui les masque.
    inventory_on = config.get("LIBRARY_INVENTORY_ENABLED", True) is not False
    hygiene_lib_key = str(selected_lib) if selected_lib else "all"
    hygiene_meta = get_hygiene_library_meta(hygiene_lib_key) if inventory_on else None
    audit_flags = get_series_audit_flags() if hygiene_meta else {}
    hygiene_map = get_volume_report_hygiene_map() if hygiene_meta else {}

    if libraries:
        for s in series_list:
            item_cache = cached_info.get(s['id'], {'status': 'PENDING', 'forced_id': '', 'alternative_title': ''})
            s['status'] = item_cache.get('status', 'PENDING')
            s['forced_id'] = item_cache.get('forced_id') or ''
            s['alternative_title'] = item_cache.get('alternative_title') or ''
            s['targeted_fields'] = item_cache.get('targeted_fields') or 'ALL'
            s['forced_provider'] = item_cache.get('forced_provider') or 'AUTO'
            s['publisher_pref'] = item_cache.get('publisher_pref') or 'GLOBAL'
            s['alt_title_langs'] = item_cache.get('alt_title_langs') or ''
            s['fields_override'] = targeted_fields_is_granular(s['targeted_fields'])
            s['alt_title_override'] = alt_title_is_override(s['alternative_title'], s.get('name'))
            s['publisher_override'] = publisher_pref_is_override(s['publisher_pref'])
            s['publisher_chip'] = publisher_pref_chip_label(s['publisher_pref']) if s['publisher_override'] else ''
            s['alt_langs_override'] = alt_langs_is_override(s['alt_title_langs'])
            s['alt_langs_chip'] = alt_langs_chip_label(s['alt_title_langs']) if s['alt_langs_override'] else ''
            s['cover_manual'] = bool(item_cache.get('cover_manual'))
            s['inventory_excluded'] = bool(item_cache.get('inventory_excluded'))
            if hygiene_meta and not s['inventory_excluded']:
                flag = audit_flags.get(s['id']) or {}
                hy = hygiene_map.get(s['id']) or {}
                s['has_external_id'] = (
                    bool(flag.get('has_external_id'))
                    if flag.get('has_external_id') is not None
                    else None
                )
                s['audit_badge'] = hy.get('badge') or ''
                s['duplicate_group_id'] = flag.get('duplicate_group_id') or ''
                s['missing_count'] = hy.get('missing_count') or 0
                s['catalog_expected'] = hy.get('catalog_expected')
                s['publication_status'] = hy.get('publication_status') or 'UNKNOWN'
                s['completion_state'] = hy.get('completion_state') or ''
                s['forced_expected'] = bool(hy.get('forced_expected'))
                s['audit_unit'] = hy.get('unit') or 'volumes'
            else:
                s['has_external_id'] = None
                s['audit_badge'] = ''
                s['duplicate_group_id'] = ''
                s['missing_count'] = 0
                s['catalog_expected'] = None
                s['publication_status'] = ''
                s['completion_state'] = ''
                s['forced_expected'] = False
                s['audit_unit'] = ''

    # Ne jamais injecter la vraie clé NI le sentinel « ******** » dans le HTML :
    # les navigateurs (autofill mot de passe) écrasent souvent ce champ, et un
    # saveConfig() sidebar renvoyait alors ******** / un mauvais secret / du vide,
    # ce qui faisait croire qu'un setup frais « n'écrivait pas » la config Kavita.
    # Champ toujours vide à l'affichage ; placeholder + flags has_* indiquent
    # qu'une clé est déjà enregistrée. POST vide = conserver (routes/config.py).
    safe_config = config.copy()
    has_kavita_api_key = bool((safe_config.get('KAVITA_API_KEY') or '').strip())
    has_deepl_api_key = bool((safe_config.get('DEEPL_API_KEY') or '').strip())
    has_azure_api_key = bool((safe_config.get('AZURE_API_KEY') or '').strip())
    safe_config['KAVITA_API_KEY'] = ''
    safe_config['DEEPL_API_KEY'] = ''
    safe_config['AZURE_API_KEY'] = ''

    scrapers_with_keys = [
        s for s in ScraperRegistry.get_all(scope="series")
        if getattr(s, 'needs_api_key', False)
    ]
    scraper_has_api_key = {}
    for s in scrapers_with_keys:
        key_name = f"{s.id}_API_KEY"
        scraper_has_api_key[s.id] = bool((safe_config.get(key_name) or '').strip())
        safe_config[key_name] = ''

    manga_providers = [{"id": s.id, "display_name": s.localized_display_name} for s in ScraperRegistry.get_by_type("Manga")]
    comic_providers = [{"id": s.id, "display_name": s.localized_display_name} for s in ScraperRegistry.get_by_type("Comic")]
    book_providers = [{"id": s.id, "display_name": s.localized_display_name} for s in ScraperRegistry.get_by_type("Book")]
    # Deux familles, celles que le module sait piloter : ceux qui listent les
    # albums d'une série, et ceux qui identifient un tome à la fois par son ISBN.
    # La règle vit dans le module et non ici, pour qu'un menu ne puisse pas
    # proposer un réglage que la cascade ignorerait.
    volume_provider_choices = list_volume_provider_choices()

    _series_scrapers = list(ScraperRegistry.get_all(scope="series"))
    provider_labels = {s.id: s.localized_display_name for s in _series_scrapers}
    magic_scrapers = [
        {"id": s.id, "display_name": s.localized_display_name, "supported_types": list(s.supported_types)}
        for s in _series_scrapers
        if getattr(s, 'has_direct_id_support', False)
    ]

    from services.scraper_manager import get_pending_core_updates
    pending_core_updates = get_pending_core_updates()

    # BF97 / #30 — virtual list above this size (light Jinja rows below).
    _VIRTUAL_SERIES_THRESHOLD = 120
    series_index_payload = [
        {
            "id": s["id"],
            "name": s.get("name") or "",
            "searchTitle": (s.get("name") or "").lower(),
            "libraryId": s.get("libraryId"),
            "status": s.get("status") or "PENDING",
            "forced_id": s.get("forced_id") or "",
            "alternative_title": s.get("alternative_title") or s.get("name") or "",
            "forced_provider": s.get("forced_provider") or "AUTO",
            "targeted_fields": s.get("targeted_fields") or "ALL",
            "publisher_pref": s.get("publisher_pref") or "GLOBAL",
            "alt_title_langs": s.get("alt_title_langs") or "",
            "cover_manual": bool(s.get("cover_manual")),
            "has_external_id": s.get("has_external_id"),
            "audit_badge": s.get("audit_badge") or "",
            "duplicate_group_id": s.get("duplicate_group_id") or "",
            "missing_count": int(s.get("missing_count") or 0),
            "catalog_expected": s.get("catalog_expected"),
            "publication_status": s.get("publication_status") or "",
            "completion_state": s.get("completion_state") or "",
            "forced_expected": bool(s.get("forced_expected")),
            "audit_unit": s.get("audit_unit") or "",
            "inventory_excluded": bool(s.get("inventory_excluded")),
        }
        for s in series_list
    ]
    use_virtual_series_list = len(series_list) >= _VIRTUAL_SERIES_THRESHOLD
    hygiene_counts = (hygiene_meta or {}).get("counts") or {}
    hygiene_scanned_at = (hygiene_meta or {}).get("scanned_at") or ""
    auto_sync_payload = get_latest_auto_sync_report()
    auto_sync_series_ids = [it["series_id"] for it in (auto_sync_payload.get("items") or [])]

    return render_template('index.html', config=safe_config, app_version=get_current_version(), msg=msg, error_msg=error_msg,
                           series_list=series_list, libraries=libraries, selected_lib=selected_lib,
                           all_libraries=all_libraries, disabled_library_ids=disabled_ids,
                           t=t, stats=stats,
                           hygiene_meta=hygiene_meta,
                           hygiene_counts=hygiene_counts,
                           hygiene_scanned_at=hygiene_scanned_at,
                           inventory_enabled=inventory_on,
                           lifetime=get_lifetime_stats(),
                           auto_sync_report=auto_sync_payload.get("badge") or {},
                           auto_sync_series_ids=auto_sync_series_ids,
                           kavita_ui_url=get_kavita_ui_url(config),
                           kavita_plus_url=get_kavita_plus_url(config),
                           manga_providers=manga_providers,
                           comic_providers=comic_providers,
                           book_providers=book_providers,
                           volume_provider_choices=volume_provider_choices,
                           magic_scrapers=magic_scrapers,
                           provider_labels=provider_labels,
                           scrapers_with_keys=scrapers_with_keys,
                           has_kavita_api_key=has_kavita_api_key,
                           has_deepl_api_key=has_deepl_api_key,
                           has_azure_api_key=has_azure_api_key,
                           scraper_has_api_key=scraper_has_api_key,
                           match_accept_threshold=get_match_accept_threshold(config),
                           dup_accept_threshold=get_dup_accept_threshold(config),
                           pending_core_updates=pending_core_updates,
                           series_index_payload=series_index_payload,
                           use_virtual_series_list=use_virtual_series_list)


@pages_bp.route('/', methods=['GET'])
def index():
    config = load_config()
    selected_lib = request.args.get('library_id')
    msg = (session.pop('ui_banner', None) or '').strip()
    return _prepare_index_data(config, msg=msg, error_msg="", selected_lib=selected_lib)


@pages_bp.route('/stats')
def stats():
    """Document HTML autonome (`templates/stats.html` + `static/css/stats.css`).

    Ce n'est pas un volet du tableau de bord : ne pas envelopper le récit
    dans `.dashboard-wrapper` / `.content` (`style.css` y fige 100vh et
    `overflow: hidden`).
    """
    config = load_config()
    cached_data = get_all_cached_data()
    total = len(cached_data)
    completed = sum(1 for v in cached_data.values() if v.get('status') == 'COMPLETED')
    needs_relock = sum(1 for v in cached_data.values() if v.get('status') == 'NEEDS_RELOCK')
    pending = sum(1 for v in cached_data.values() if v.get('status') == 'PENDING')
    pending_review = sum(1 for v in cached_data.values() if v.get('status') == 'PENDING_REVIEW')
    not_found = sum(1 for v in cached_data.values() if v.get('status') == 'NOT_FOUND')
    ignored = sum(1 for v in cached_data.values() if v.get('status') == 'IGNORED')

    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])

    playful_enabled = bool(config.get('ENABLE_PLAYFUL_STATS', True))
    lifetime = get_lifetime_stats()
    playful = None
    if playful_enabled:
        hygiene_counts = pick_hygiene_counts(
            get_hygiene_library_meta("all"),
            list_hygiene_library_meta(),
        )
        playful = compute_playful_stats(
            cached_data,
            get_provider_stats(),
            lifetime,
            translations_dict=t,
            config=config,
            hygiene_counts=hygiene_counts,
            volume_status_counts=count_volume_units_by_status(),
            volume_series_done=len(list_enriched_series_ids()),
            expected_overrides=len(list_catalog_expected_overrides()),
            dup_dismissals=count_dup_dismissals(),
            volume_writes=summarize_volume_writes(),
        )
        mr_achievements = playful.get("mr_achievements") or evaluate_from_lifetime(lifetime, t)
    else:
        # Ancre #mr-achievements (lien recap MR) reste valide même sans stats playful.
        mr_achievements = evaluate_from_lifetime(lifetime, t)

    return render_template(
        'stats.html',
        config=config,
        t=t,
        total=total,
        completed=completed,
        needs_relock=needs_relock,
        pending=pending,
        pending_review=pending_review,
        not_found=not_found,
        ignored=ignored,
        playful_enabled=playful_enabled,
        playful=playful,
        mr_achievements=mr_achievements,
    )


@pages_bp.route('/diagnostics')
def diagnostics():
    """Page premium de diagnostic (préflight Internet/Kavita + probes scrapers)."""
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    return render_template(
        'diagnostics.html',
        config=config,
        t=t,
        app_version=get_current_version(),
        scrapers=list_scrapers_inventory(config),
        active_tab="diagnostics",
    )


_EMPTY_WORKSHOP_PAYLOAD = {
    "series": {},
    "units": [],
    "history": [],
    "lookups": {},
    "force": True,
    "pass_running": False,
    "skipped_reason": "",
}


def _workshop_libraries(rail):
    libraries = []
    seen = {}
    for item in rail:
        lib = item.get("libraryId")
        name = item.get("libraryName") or ""
        if lib is None or lib in seen:
            continue
        seen[lib] = True
        libraries.append({"id": lib, "name": name})
    libraries.sort(key=lambda x: (x["name"] or "").casefold())
    return libraries


def _workshop_api(config):
    if not volume_enrichment_enabled(config):
        abort(403)
    if not config.get('KAVITA_API_KEY') or not config.get('KAVITA_URL'):
        abort(404)
    return KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))


def _render_workshop_page(config, t, api, payload):
    rail = workshop_rail(api, config=config)
    return render_template(
        'volumes.html',
        config=config,
        t=t,
        payload=payload or dict(_EMPTY_WORKSHOP_PAYLOAD),
        rail=rail,
        libraries=_workshop_libraries(rail),
        kavita_ui_url=get_kavita_ui_url(config),
        match_accept_threshold=get_match_accept_threshold(config),
    )


@pages_bp.route('/volumes')
def volumes():
    """Atelier sans série imposée : même document que `/series/<id>/volumes`.

    Le rail (et le dernier sid en localStorage) choisit la fiche. 403 si la
    fonctionnalité est éteinte.
    """
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    api = _workshop_api(config)
    return _render_workshop_page(config, t, api, dict(_EMPTY_WORKSHOP_PAYLOAD))


@pages_bp.route('/series/<int:series_id>/volumes')
def series_volumes(series_id):
    """Atelier des tomes : document autonome, comme `/stats`.

    Aucun scrape à l'ouverture. 403 si la fonctionnalité est éteinte ou si la
    bibliothèque de la série est désactivée.
    """
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    api = _workshop_api(config)
    series = api.get_series(series_id)
    if not isinstance(series, dict) or not series.get('id'):
        abort(404)
    if library_is_disabled(series, config):
        abort(403)
    payload = workshop_payload(api, series_id, config=config)
    if not payload:
        abort(404)
    return _render_workshop_page(config, t, api, payload)
