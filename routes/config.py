"""
Blueprint de configuration globale : /save-config, /regenerate-webhook-token,
GET/POST /api/config/field-mapping.

⚠️ Endpoints réels : 'config.save_config_ajax', 'config.regenerate_webhook_token',
'config.get_field_mapping', 'config.save_field_mapping'.
"""

import logging
import secrets

from flask import Blueprint, request, jsonify

from config_manager import (
    apply_light_mode,
    load_config,
    save_config,
    CONFIG_LOCK,
    CONFIG_FILE,
    format_disabled_libraries,
    normalize_auto_sync_trigger,
    normalize_auto_sync_mode,
    clamp_auto_sync_catchup_hours,
)
from scrapers import ScraperRegistry
from kavita_api import KavitaAPI
from translations import get_ui_translations
from services.field_assembly import AUTO_FIELD_PICK_KEYS
from services.field_mapping import (
    CASCADE,
    PLAN_SPECS,
    dropdown_providers,
    parse_mapping_default,
    parse_provider_map,
    resolve_mapping_plan,
    usable_ids_for_fetch_type,
)

config_bp = Blueprint('config', __name__)


@config_bp.route('/save-config', methods=['POST'])
def save_config_ajax():
    # CONFIG_LOCK englobe TOUT le cycle lire-modifier-écrire (pas seulement l'appel
    # à save_config()) : sinon, deux requêtes /save-config concurrentes (ex: deux
    # cases à cocher changées coup sur coup, voir config.js::saveConfig()) peuvent
    # quand même s'entrelacer ENTRE le load_config() et le save_config() de chacune,
    # et l'une écraserait silencieusement les changements de l'autre.
    with CONFIG_LOCK:
        config = load_config()

        # Sauvegarde partielle : cascades uniquement (providersModal)
        _PROVIDER_KEYS = (
            'PROVIDER_1', 'PROVIDER_2', 'PROVIDER_3',
            'COMIC_PROVIDER_1', 'COMIC_PROVIDER_2', 'COMIC_PROVIDER_3',
            'BOOK_PROVIDER_1', 'BOOK_PROVIDER_2', 'BOOK_PROVIDER_3',
        )
        if request.form.get('PROVIDERS_SAVE') == '1':
            for key in _PROVIDER_KEYS:
                if key in request.form:
                    config[key] = request.form.get(key, 'NONE').strip()
            save_config(config)
            return jsonify(success=True)

        # Partial: hygiene duplicate threshold preset (toolbar)
        if request.form.get('DUP_PRESET_SAVE') == '1':
            config['DUP_THRESHOLD_CUSTOM'] = True
            try:
                config['DUP_ACCEPT_THRESHOLD'] = float(
                    request.form.get('DUP_ACCEPT_THRESHOLD', 0.92)
                )
            except (TypeError, ValueError):
                config['DUP_ACCEPT_THRESHOLD'] = 0.92
            save_config(config)
            return jsonify(success=True)

        # Partial: hygiene duplicate folder paths (duplicates modal)
        if request.form.get('INVENTORY_FOLDER_SAVE') == '1':
            from services.library_audit.dup_script import (
                inventory_folder_path_prefix_from_config,
                normalize_inventory_folder_trash,
            )
            if (
                'INVENTORY_FOLDER_PATH_PREFIX' in request.form
                or 'INVENTORY_FOLDER_URL_PREFIX' in request.form
            ):
                config['INVENTORY_FOLDER_PATH_PREFIX'] = inventory_folder_path_prefix_from_config({
                    'INVENTORY_FOLDER_PATH_PREFIX': request.form.get('INVENTORY_FOLDER_PATH_PREFIX'),
                    'INVENTORY_FOLDER_URL_PREFIX': request.form.get('INVENTORY_FOLDER_URL_PREFIX'),
                })
                config.pop('INVENTORY_FOLDER_URL_PREFIX', None)
            if 'INVENTORY_FOLDER_TRASH' in request.form:
                config['INVENTORY_FOLDER_TRASH'] = normalize_inventory_folder_trash(
                    request.form.get('INVENTORY_FOLDER_TRASH')
                )
            save_config(config)
            return jsonify(success=True)

        config['TRANSLATION_PROVIDER'] = request.form.get('TRANSLATION_PROVIDER', 'GOOGLE').strip()
        config['KAVITA_URL'] = request.form.get('KAVITA_URL', '').strip().rstrip('/')
        config['KAVITA_EXTERNAL_URL'] = request.form.get('KAVITA_EXTERNAL_URL', '').strip().rstrip('/')

        # Champs secrets toujours vides à l'affichage : vide / ******** = conserver.
        # (Sinon un save sidebar avec champ vide effaçait la clé, ou l'autofill
        # écrasait Kavita avec le mot de passe MetaKavita.)
        def _apply_secret(form_key: str, config_key: str) -> bool:
            val = request.form.get(form_key, '').strip()
            if val and val != '********':
                config[config_key] = val
                return True
            return False

        kavita_key_updated = _apply_secret('KAVITA_API_KEY', 'KAVITA_API_KEY')
        _apply_secret('DEEPL_API_KEY', 'DEEPL_API_KEY')
        _apply_secret('AZURE_API_KEY', 'AZURE_API_KEY')

        for s in ScraperRegistry.get_all(scope="series"):
            if getattr(s, 'needs_api_key', False):
                key_name = f"{s.id}_API_KEY"
                _apply_secret(key_name, key_name)

        config['AZURE_REGION'] = request.form.get('AZURE_REGION', '').strip()

        config['TARGET_LANG'] = request.form.get('TARGET_LANG', 'FR').strip()
        config['UI_LANG'] = request.form.get('UI_LANG', 'fr').strip()

        config['PUBLISHER_PREFERENCE'] = request.form.get('PUBLISHER_PREFERENCE', 'LOCALIZED').strip()

        loc_mode = request.form.get('LOCALIZED_TITLE_MODE', 'all').strip().lower()
        config['LOCALIZED_TITLE_MODE'] = loc_mode if loc_mode in ('all', 'prefer', 'none') else 'all'
        config['LOCALIZED_TITLE_LANGS'] = request.form.get('LOCALIZED_TITLE_LANGS', '').strip()

        # Cascades absentes du form Config : ne pas écraser les valeurs existantes
        if any(k in request.form for k in _PROVIDER_KEYS):
            for key in _PROVIDER_KEYS:
                if key in request.form:
                    config[key] = request.form.get(key, 'NONE').strip()

        config['SMART_COMPLETION'] = request.form.get('SMART_COMPLETION') == 'true'
        config['SMART_SCORING'] = request.form.get('SMART_SCORING') == 'true'
        was_manual = bool(config.get('MANUAL_REVIEW_MODE'))
        was_confirm = bool(config.get('CONFIRM_BEFORE_WRITE'))
        config['MANUAL_REVIEW_MODE'] = request.form.get('MANUAL_REVIEW_MODE') == 'true'
        config['MANUAL_REVIEW_EDIT'] = request.form.get('MANUAL_REVIEW_EDIT') == 'true'
        config['CONFIRM_BEFORE_WRITE'] = request.form.get('CONFIRM_BEFORE_WRITE') == 'true'
        config['MANUAL_REVIEW_SOUNDS'] = request.form.get('MANUAL_REVIEW_SOUNDS') == 'true'
        config['MANUAL_REVIEW_SUPER'] = request.form.get('MANUAL_REVIEW_SUPER') == 'true'
        config['MANUAL_REVIEW_COVER_PICK'] = request.form.get('MANUAL_REVIEW_COVER_PICK') == 'true'
        if not config['MANUAL_REVIEW_MODE']:
            config['MANUAL_REVIEW_SUPER'] = False
            config['MANUAL_REVIEW_COVER_PICK'] = False
            config['MANUAL_REVIEW_SOUNDS'] = False
        config['MATCH_THRESHOLD_CUSTOM'] = request.form.get('MATCH_THRESHOLD_CUSTOM') == 'true'
        if config['MATCH_THRESHOLD_CUSTOM']:
            try:
                config['MATCH_ACCEPT_THRESHOLD'] = float(
                    request.form.get('MATCH_ACCEPT_THRESHOLD', 0.60)
                )
            except (TypeError, ValueError):
                config['MATCH_ACCEPT_THRESHOLD'] = 0.60
        else:
            config['MATCH_ACCEPT_THRESHOLD'] = 0.60
        if 'DUP_THRESHOLD_CUSTOM' in request.form or 'DUP_ACCEPT_THRESHOLD' in request.form:
            config['DUP_THRESHOLD_CUSTOM'] = request.form.get('DUP_THRESHOLD_CUSTOM') == 'true'
            if config['DUP_THRESHOLD_CUSTOM']:
                try:
                    config['DUP_ACCEPT_THRESHOLD'] = float(
                        request.form.get('DUP_ACCEPT_THRESHOLD', 0.92)
                    )
                except (TypeError, ValueError):
                    config['DUP_ACCEPT_THRESHOLD'] = 0.92
            else:
                config['DUP_ACCEPT_THRESHOLD'] = 0.92
        config['RESET_CONTEXT_ON_FORCE'] = request.form.get('RESET_CONTEXT_ON_FORCE') == 'true'

        config['TITLE_FALLBACK_TRANSLATION'] = request.form.get('TITLE_FALLBACK_TRANSLATION') == 'true'
        config['ENABLE_PLAYFUL_STATS'] = request.form.get('ENABLE_PLAYFUL_STATS') == 'true'
        config['AUTO_UPDATE_CORE_SCRAPERS'] = request.form.get('AUTO_UPDATE_CORE_SCRAPERS') == 'true'

        # C96 — présents seulement si le formulaire les envoie (saveConfig JS ou
        # POST complet). Un POST partiel (barre latérale) ne doit pas les écraser.
        if 'AUTO_SYNC_ENABLED' in request.form:
            config['AUTO_SYNC_ENABLED'] = request.form.get('AUTO_SYNC_ENABLED') == 'true'
        if 'AUTO_SYNC_TRIGGER' in request.form:
            config['AUTO_SYNC_TRIGGER'] = normalize_auto_sync_trigger(
                request.form.get('AUTO_SYNC_TRIGGER')
            )
        if 'AUTO_SYNC_MODE' in request.form:
            config['AUTO_SYNC_MODE'] = normalize_auto_sync_mode(
                request.form.get('AUTO_SYNC_MODE')
            )
        if 'AUTO_SYNC_FORCE_UPDATE' in request.form:
            config['AUTO_SYNC_FORCE_UPDATE'] = request.form.get('AUTO_SYNC_FORCE_UPDATE') == 'true'
        if 'AUTO_SYNC_CATCHUP_HOURS' in request.form:
            config['AUTO_SYNC_CATCHUP_HOURS'] = clamp_auto_sync_catchup_hours(
                request.form.get('AUTO_SYNC_CATCHUP_HOURS'), 24
            )
        if 'AUTO_SYNC_INTERVAL' in request.form:
            try:
                interval = int(request.form.get('AUTO_SYNC_INTERVAL', 0))
            except (TypeError, ValueError):
                interval = 0
            interval = max(0, interval)
            trigger = config.get('AUTO_SYNC_TRIGGER') or 'interval'
            enabled = bool(config.get('AUTO_SYNC_ENABLED'))
            if enabled and trigger == 'interval' and interval < 1:
                interval = 1
            config['AUTO_SYNC_INTERVAL'] = interval

        # Bibliothèques à synchroniser : checkboxes ENABLED_LIBRARY + re-fetch Kavita.
        # Ne traiter que si le formulaire a réellement rendu la liste (KNOWN_LIBRARY) —
        # sinon un setup frais (PRESENT=1, 0 case) désactivait toutes les biblios
        # dès que l'auth Kavita réussissait pendant le save.
        if request.form.get('SYNC_LIBRARIES_PRESENT') == '1':
            known_ids = {
                str(x).strip()
                for x in request.form.getlist('KNOWN_LIBRARY')
                if str(x).strip()
            }
            enabled_ids = {
                str(x).strip()
                for x in request.form.getlist('ENABLED_LIBRARY')
                if str(x).strip()
            }
            if not known_ids and not enabled_ids:
                t = get_ui_translations(config=config)
                logging.info(
                    t.get(
                        "log_config_sync_libs_empty",
                        "[Config] SYNC_LIBRARIES_PRESENT sans bibliothèque rendue — "
                        "dénylist inchangée (évite wipe au 1er save).",
                    )
                )
            else:
                all_ids = set()
                try:
                    if config.get('KAVITA_URL') and config.get('KAVITA_API_KEY'):
                        kavita = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])
                        if kavita.authenticate():
                            all_ids = {
                                str(lib.get('id'))
                                for lib in (kavita.get_libraries() or [])
                                if lib.get('id') is not None
                            }
                except Exception as e:
                    t = get_ui_translations(config=config)
                    logging.warning(
                        t.get(
                            "log_config_reload_libs_fail",
                            "[Config] Impossible de recharger les bibliothèques Kavita : %s",
                        ),
                        e,
                    )
                if all_ids:
                    config['DISABLED_LIBRARIES'] = format_disabled_libraries(all_ids - enabled_ids)
                elif not enabled_ids and not all_ids:
                    # Pas de biblio joignable : ne pas écraser la dénylist existante
                    pass

        config['AUTO_COVER'] = request.form.get('AUTO_COVER') == 'true'
        config['COVER_FORCE_OVERWRITE'] = request.form.get('COVER_FORCE_OVERWRITE') == 'true'
        if 'LIBRARY_INVENTORY_ENABLED' in request.form:
            config['LIBRARY_INVENTORY_ENABLED'] = (
                request.form.get('LIBRARY_INVENTORY_ENABLED') == 'true'
            )
        if (
            'INVENTORY_FOLDER_PATH_PREFIX' in request.form
            or 'INVENTORY_FOLDER_URL_PREFIX' in request.form
        ):
            from services.library_audit.dup_script import (
                inventory_folder_path_prefix_from_config,
                normalize_inventory_folder_trash,
            )
            config['INVENTORY_FOLDER_PATH_PREFIX'] = inventory_folder_path_prefix_from_config({
                'INVENTORY_FOLDER_PATH_PREFIX': request.form.get('INVENTORY_FOLDER_PATH_PREFIX'),
                'INVENTORY_FOLDER_URL_PREFIX': request.form.get('INVENTORY_FOLDER_URL_PREFIX'),
            })
            config.pop('INVENTORY_FOLDER_URL_PREFIX', None)
            if 'INVENTORY_FOLDER_TRASH' in request.form:
                config['INVENTORY_FOLDER_TRASH'] = normalize_inventory_folder_trash(
                    request.form.get('INVENTORY_FOLDER_TRASH')
                )
        elif 'INVENTORY_FOLDER_TRASH' in request.form:
            from services.library_audit.dup_script import normalize_inventory_folder_trash
            config['INVENTORY_FOLDER_TRASH'] = normalize_inventory_folder_trash(
                request.form.get('INVENTORY_FOLDER_TRASH')
            )
        # Enrichissement par tome : chaque interrupteur n'est lu que s'il est
        # présent, pour qu'un formulaire partiel (la sidebar en envoie un par
        # bloc) n'éteigne pas les deux autres au passage.
        for key in (
            'VOLUME_ENRICHMENT_ENABLED',
            'VOLUME_FORCE_OVERWRITE',
            'VOLUME_ENRICH_CREDITS',
            'VOLUME_ENRICH_EXPERIMENTAL',
            'VOLUME_NO_MANGA_FALLBACK',
        ):
            if key in request.form:
                config[key] = request.form.get(key) == 'true'
        if 'VOLUME_PROVIDER' in request.form:
            # Normalisé ici plutôt qu'à la lecture : la valeur se compare à des
            # identifiants de scrapers, qui sont en majuscules. « auto » est la
            # valeur du choix « laisser la cascade décider » et vaut vide.
            picked = (request.form.get('VOLUME_PROVIDER') or '').strip().upper()
            config['VOLUME_PROVIDER'] = '' if picked in ('', 'AUTO', 'NONE') else picked

        # Mode léger (C80) : trois cases qui retirent une catégorie de la barre
        # latérale. Lues seulement si présentes, comme les interrupteurs
        # ci-dessus, pour qu'un formulaire partiel n'en masque aucune au passage.
        for key in ('UI_SHOW_MANUAL_REVIEW', 'UI_SHOW_INVENTORY', 'UI_SHOW_VOLUMES',
                    'UI_SHOW_FIELD_MAPPING'):
            if key in request.form:
                config[key] = request.form.get(key) == 'true'
        if 'FIELD_MAPPING_ENABLED' in request.form:
            config['FIELD_MAPPING_ENABLED'] = request.form.get('FIELD_MAPPING_ENABLED') == 'true'
        # Masquée veut dire éteinte. L'interface éteint déjà la fonctionnalité au
        # moment où l'on décoche, mais la règle est réappliquée ici pour que
        # l'état enregistré soit cohérent quel que soit le formulaire reçu — et
        # surtout **avant** la purge de la file de relecture plus bas, qui compare
        # `was_manual` à la valeur finale : sans cela, masquer la relecture
        # manuelle aurait éteint le mode en laissant sa file gelée.
        apply_light_mode(config)

        t = get_ui_translations(config=config)
        try:
            save_config(config)
        except RuntimeError as exc:
            logging.error(
                t.get("log_config_persist_fail", "[Config] Échec persistance config.json : %s"),
                exc,
            )
            return jsonify(success=False, msg=str(exc)), 500

        has_url = bool((config.get('KAVITA_URL') or '').strip())
        has_key = bool((config.get('KAVITA_API_KEY') or '').strip())
        yes = t.get("log_yes", "oui")
        no = t.get("log_no", "non")
        empty = t.get("log_empty", "(vide)")
        logging.info(
            t.get(
                "log_config_save_ok",
                "[Config] Sauvegarde OK — fichier=%s KAVITA_URL=%s clé_API=%s (mise_à_jour=%s)",
            ),
            CONFIG_FILE,
            config.get('KAVITA_URL') or empty,
            yes if has_key else no,
            yes if kavita_key_updated else no,
        )

        # Désactivation du mode manuel : purge la file pour éviter des séries
        # gelées en PENDING_REVIEW (l'auto-sync les exclut).
        if was_manual and not config['MANUAL_REVIEW_MODE']:
            try:
                from services.manual_review import purge_all_reviews
                result = purge_all_reviews(reset_status="PENDING")
                deleted = int(result.get("deleted") or 0)
                if deleted:
                    logging.info(
                        t.get(
                            "log_config_manual_purged",
                            "[Config] Mode manuel désactivé — file purgée (%s review(s)).",
                        ),
                        deleted,
                    )
            except Exception as exc:
                logging.warning(
                    t.get(
                        "log_config_manual_purge_fail",
                        "[Config] Purge file manuelle après désactivation : %s",
                    ),
                    exc,
                )

        # Désactivation confirm-before-write : purge uniquement les parks auto.
        if was_confirm and not config['CONFIRM_BEFORE_WRITE'] and not config['MANUAL_REVIEW_MODE']:
            try:
                from services.manual_review import purge_auto_confirm_reviews
                result = purge_auto_confirm_reviews(reset_status="PENDING")
                deleted = int(result.get("deleted") or 0)
                if deleted:
                    logging.info(
                        t.get(
                            "log_config_confirm_purged",
                            "[Config] Confirm-before-write désactivé — %s preview(s) purgé(s).",
                        ),
                        deleted,
                    )
            except Exception as exc:
                logging.warning(
                    t.get(
                        "log_config_confirm_purge_fail",
                        "[Config] Purge auto-confirm après désactivation : %s",
                    ),
                    exc,
                )

        kavita_ok = False
        kavita_error = None
        if has_url and has_key:
            try:
                probe = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])
                kavita_ok = bool(probe.authenticate())
                if not kavita_ok:
                    kavita_error = getattr(probe, 'last_auth_error', None) or 'unknown'
            except Exception as exc:
                logging.warning(
                    t.get(
                        "log_config_kavita_probe_fail",
                        "[Config] Test connexion Kavita après save : %s",
                    ),
                    exc,
                )
                kavita_error = 'unknown'
        elif not has_url or not has_key:
            kavita_error = 'missing'

    return jsonify(
        success=True,
        kavita_url=config.get('KAVITA_URL') or '',
        has_kavita_api_key=has_key,
        kavita_ok=kavita_ok,
        kavita_error=kavita_error,
    )


@config_bp.route('/regenerate-webhook-token', methods=['POST'])
def regenerate_webhook_token():
    with CONFIG_LOCK:
        config = load_config()
        new_token = secrets.token_urlsafe(16)
        config['WEBHOOK_TOKEN'] = new_token
        save_config(config)
        t = get_ui_translations(config=config)
    logging.info(
        t.get(
            "log_webhook_token_regenerated",
            "🔑 [Sécurité] Nouveau jeton Webhook généré depuis l'interface web.",
        )
    )
    return jsonify(success=True, new_token=new_token)


def _serialize_mapping_wave(config, plan_id, library_type, wave):
    plan = resolve_mapping_plan(config, library_type, flexible_wave=wave)
    return {
        "plan": plan_id,
        "default": plan.default,
        "overrides": dict(plan.overrides),
        "providers": dropdown_providers(config, plan.fetch_library_type),
        "fetch_library_type": plan.fetch_library_type,
    }


@config_bp.route("/api/config/field-mapping", methods=["GET"])
def get_field_mapping():
    config = load_config()
    plans = {}
    for plan_id, library_type, wave, _default_key, _map_key in PLAN_SPECS:
        plans[plan_id] = _serialize_mapping_wave(config, plan_id, library_type, wave)
    return jsonify(success=True, plans=plans)


@config_bp.route("/api/config/field-mapping", methods=["POST"])
def save_field_mapping():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(success=False, msg="JSON required"), 400
    incoming = body.get("plans")
    if not isinstance(incoming, dict):
        incoming = {}

    with CONFIG_LOCK:
        config = load_config()
        for plan_id, library_type, wave, default_key, map_key in PLAN_SPECS:
            if plan_id not in incoming:
                continue
            spec = incoming.get(plan_id) or {}
            if not isinstance(spec, dict):
                spec = {}
            fetch_lt = resolve_mapping_plan(
                config, library_type, flexible_wave=wave
            ).fetch_library_type
            allowed = usable_ids_for_fetch_type(config, fetch_lt)
            default = parse_mapping_default(spec.get("default"))
            if default != CASCADE and default not in {p.upper() for p in allowed}:
                default = CASCADE
            overrides = parse_provider_map(
                spec.get("overrides") or {},
                allowed_fields=AUTO_FIELD_PICK_KEYS,
                allowed_providers=allowed,
            )
            if default != CASCADE:
                overrides = {f: p for f, p in overrides.items() if p != default}
            config[default_key] = default
            config[map_key] = overrides
        save_config(config)

    return jsonify(success=True)
