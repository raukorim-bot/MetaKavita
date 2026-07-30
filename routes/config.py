"""
Blueprint de configuration globale : /save-config, /regenerate-webhook-token.

⚠️ Endpoints réels : 'config.save_config_ajax' et 'config.regenerate_webhook_token'.
"""

import logging
import secrets

from flask import Blueprint, request, jsonify

from config_manager import load_config, save_config, CONFIG_LOCK, format_disabled_libraries
from scrapers import ScraperRegistry
from kavita_api import KavitaAPI

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

        for s in ScraperRegistry.get_all():
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
        config['RESET_CONTEXT_ON_FORCE'] = request.form.get('RESET_CONTEXT_ON_FORCE') == 'true'

        config['TITLE_FALLBACK_TRANSLATION'] = request.form.get('TITLE_FALLBACK_TRANSLATION') == 'true'
        config['ENABLE_PLAYFUL_STATS'] = request.form.get('ENABLE_PLAYFUL_STATS') == 'true'

        try:
            config['AUTO_SYNC_INTERVAL'] = int(request.form.get('AUTO_SYNC_INTERVAL', 0))
        except ValueError:
            config['AUTO_SYNC_INTERVAL'] = 0

        # Bibliothèques à synchroniser : checkboxes ENABLED_LIBRARY + re-fetch Kavita
        if request.form.get('SYNC_LIBRARIES_PRESENT') == '1':
            enabled_ids = {
                str(x).strip()
                for x in request.form.getlist('ENABLED_LIBRARY')
                if str(x).strip()
            }
            all_ids = set()
            try:
                if config.get('KAVITA_URL') and config.get('KAVITA_API_KEY'):
                    kavita = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])
                    if kavita.authenticate():
                        all_ids = {str(lib.get('id')) for lib in (kavita.get_libraries() or []) if lib.get('id') is not None}
            except Exception as e:
                logging.warning("[Config] Impossible de recharger les bibliothèques Kavita : %s", e)
            if all_ids:
                config['DISABLED_LIBRARIES'] = format_disabled_libraries(all_ids - enabled_ids)
            elif not enabled_ids and not all_ids:
                # Pas de biblio joignable : ne pas écraser la dénylist existante
                pass

        config['AUTO_COVER'] = request.form.get('AUTO_COVER') == 'true'
        config['AUTO_READING_DIR'] = request.form.get('AUTO_READING_DIR') == 'true'

        save_config(config)

        has_url = bool((config.get('KAVITA_URL') or '').strip())
        has_key = bool((config.get('KAVITA_API_KEY') or '').strip())
        logging.info(
            "[Config] Sauvegarde OK — KAVITA_URL=%s clé_API=%s (mise_à_jour=%s)",
            config.get('KAVITA_URL') or '(vide)',
            'oui' if has_key else 'non',
            'oui' if kavita_key_updated else 'non',
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
                        "[Config] Mode manuel désactivé — file purgée (%s review(s)).",
                        deleted,
                    )
            except Exception as exc:
                logging.warning("[Config] Purge file manuelle après désactivation : %s", exc)

        # Désactivation confirm-before-write : purge uniquement les parks auto.
        if was_confirm and not config['CONFIRM_BEFORE_WRITE'] and not config['MANUAL_REVIEW_MODE']:
            try:
                from services.manual_review import purge_auto_confirm_reviews
                result = purge_auto_confirm_reviews(reset_status="PENDING")
                deleted = int(result.get("deleted") or 0)
                if deleted:
                    logging.info(
                        "[Config] Confirm-before-write désactivé — %s preview(s) purgé(s).",
                        deleted,
                    )
            except Exception as exc:
                logging.warning("[Config] Purge auto-confirm après désactivation : %s", exc)

        kavita_ok = False
        kavita_error = None
        if has_url and has_key:
            try:
                probe = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])
                kavita_ok = bool(probe.authenticate())
                if not kavita_ok:
                    kavita_error = getattr(probe, 'last_auth_error', None) or 'unknown'
            except Exception as exc:
                logging.warning("[Config] Test connexion Kavita après save : %s", exc)
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
    logging.info("🔑 [Sécurité] Nouveau jeton Webhook généré depuis l'interface web.")
    return jsonify(success=True, new_token=new_token)
