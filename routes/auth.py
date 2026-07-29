"""
Blueprint d'authentification : /setup, /login, /logout.

⚠️ Noms d'endpoints : ce blueprint est enregistré sous le nom 'auth', donc les
endpoints Flask réels sont 'auth.setup', 'auth.login' et 'auth.logout'. Ces noms
sont référencés dans les listes blanches de `auth_manager.py` (setup_gate /
login_gate) : les renommer déplace la frontière de sécurité. Voir DEVELOPER.md
section 11.C pour la checklist à suivre.

La logique d'authentification elle-même (hachage, stockage, verrouillage IP)
vit dans `auth_manager.py` ; ce module reste une couche HTTP fine.
"""

from flask import Blueprint, request, render_template, session, redirect, url_for

import auth_manager
from config_manager import load_config
from translations import translations

auth_bp = Blueprint('auth', __name__)


def _t():
    """(dictionnaire de traduction, config) pour la langue configurée."""
    config = load_config()
    return translations.get(config.get('UI_LANG', 'fr'), translations['fr']), config


@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """Création du compte au premier démarrage.

    Accessible UNIQUEMENT tant qu'aucun compte n'existe. Sans ce garde-fou,
    l'écran resterait un moyen non authentifié de créer un second compte — donc
    un contournement complet de l'authentification.

    Sur une instance qui tournait avec l'ancien `ADMIN_PASSWORD`, cet écran exige
    en plus ce mot de passe comme preuve de propriété : voir
    `auth_manager.legacy_proof_required`.
    """
    t, config = _t()

    if not auth_manager.setup_required():
        return redirect(url_for('auth.login'))

    legacy_required = auth_manager.legacy_proof_required()

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        confirm = request.form.get('password_confirm', '')

        # Le verrouillage est consulté d'abord et vaut aussi pour cet écran :
        # depuis qu'il vérifie un secret, il est devenu une cible de force brute
        # au même titre que /login.
        locked, remaining = auth_manager.is_locked_out()
        if locked:
            minutes = max(1, (remaining + 59) // 60)
            error = (t.get('login_err_locked') or '').replace('{}', str(minutes))
        elif legacy_required and not auth_manager.verify_legacy_password(
            request.form.get('legacy_password', '')
        ):
            auth_manager.register_failed_attempt()
            error = t.get('setup_err_legacy_password')
        elif password != confirm:
            error = t.get('setup_err_password_mismatch')
        else:
            ok, err_key = auth_manager.create_user(username, password)
            if ok:
                # L'ancien mot de passe en clair n'est jamais repris : il est
                # supprimé maintenant qu'un vrai compte existe (choix du
                # mainteneur — réinitialisation forcée, cf. issue #15).
                auth_manager.purge_legacy_admin_password()

                user = auth_manager.verify_credentials(username, password)
                if user:
                    # Le compte est créé : plus rien ne justifie de garder le
                    # propriétaire à distance du verrou déclenché par une rafale.
                    auth_manager.clear_failed_attempts()
                    auth_manager.login_session(user)
                    auth_manager.record_login(user['id'])
                    return redirect(url_for('pages.index'))
                error = t.get('setup_err_generic')
            else:
                error = t.get(err_key, t.get('setup_err_generic'))

    return render_template(
        'setup.html',
        error=error,
        t=t,
        config=config,
        min_password_length=auth_manager.MIN_PASSWORD_LENGTH,
        legacy_required=legacy_required,
    )


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    t, config = _t()

    # Aucun compte : l'utilisateur doit passer par le setup, pas par un
    # formulaire de connexion qu'aucun identifiant ne pourrait satisfaire.
    if auth_manager.setup_required():
        return redirect(url_for('auth.setup'))

    if auth_manager.is_authenticated():
        return redirect(url_for('pages.index'))

    error = None
    if request.method == 'POST':
        # Le verrouillage est vérifié AVANT toute vérification d'identifiants :
        # sinon chaque tentative continuerait de coûter un hachage complet, et
        # le verrou cesserait de protéger le CPU du worker unique.
        locked, remaining = auth_manager.is_locked_out()
        if locked:
            minutes = max(1, (remaining + 59) // 60)
            error = (t.get('login_err_locked') or '').replace('{}', str(minutes))
        else:
            user = auth_manager.verify_credentials(
                request.form.get('username', ''),
                request.form.get('password', ''),
            )
            if user:
                auth_manager.clear_failed_attempts()
                auth_manager.login_session(user)
                auth_manager.record_login(user['id'])
                return redirect(url_for('pages.index'))

            auth_manager.register_failed_attempt()
            # Message volontairement identique pour un utilisateur inconnu et un
            # mot de passe erroné : distinguer les deux revient à publier la
            # liste des comptes existants.
            error = t.get('login_error')

    return render_template('login.html', error=error, t=t, config=config)


@auth_bp.route('/logout')
def logout():
    from flask import current_app

    session.clear()
    session.permanent = False

    response = redirect(url_for('auth.login'))
    cookie_name = current_app.config.get('SESSION_COOKIE_NAME', 'session')
    response.set_cookie(cookie_name, '', expires=0)

    return response
