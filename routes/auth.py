"""
Blueprint d'authentification : /login, /logout.

⚠️ Noms d'endpoints : ce blueprint est enregistré sous le nom 'auth', donc les
endpoints Flask réels sont 'auth.login' et 'auth.logout' (et non plus 'login'/
'logout' comme avant le passage aux Blueprints). Tous les `url_for('login')`
ont été mis à jour vers `url_for('auth.login')` dans app.py, templates/login.html
et templates/index.html — voir DEVELOPER.md section 11.C pour la checklist à
suivre si vous ajoutez un nouvel endpoint sensible à ce nommage (whitelist de
`require_login` dans app.py notamment).
"""

import time
import secrets

from flask import Blueprint, request, render_template, session, redirect, url_for

from config_manager import load_config
from translations import translations

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])

    if not config.get('ADMIN_PASSWORD'):
        return redirect(url_for('pages.index'))

    error = None
    if request.method == 'POST':
        user_input = request.form.get('password', '')
        real_password = config.get('ADMIN_PASSWORD', '')

        # compare_digest exige des longueurs égales ; sinon ValueError → traiter comme échec
        try:
            password_ok = secrets.compare_digest(
                user_input.encode('utf-8'),
                real_password.encode('utf-8'),
            )
        except (TypeError, ValueError):
            password_ok = False

        if password_ok:
            session.permanent = True
            session['logged_in'] = True
            return redirect(url_for('pages.index'))
        else:
            time.sleep(2)
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
