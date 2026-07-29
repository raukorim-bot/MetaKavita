"""
Génère une valeur pour la variable d'environnement `ADMIN_PASSWORD_HASH`.

Destiné aux déploiements docker-compose qui veulent une instance déjà
configurée, sans passer par l'écran de setup au premier démarrage.

    python debug/hash_password.py
    python debug/hash_password.py "mon mot de passe"

Le hachage produit est sans danger dans un `docker-compose.yml` ou un `.env` :
il ne permet pas de retrouver le mot de passe. Le mot de passe en clair, lui,
n'a aucune raison d'y figurer — c'est précisément ce que cette variable évite.

⚠️ Le mot de passe passé en ARGUMENT reste visible dans l'historique du shell et
dans la liste des processus. Sans argument, le script le demande de façon
masquée : c'est la façon recommandée de l'utiliser.
"""

import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import getpass

from werkzeug.security import generate_password_hash

from auth_manager import MIN_PASSWORD_LENGTH, PASSWORD_HASH_METHOD


def main():
    if len(sys.argv) > 1:
        password = sys.argv[1]
        print(
            "ATTENTION : mot de passe fourni en argument, il reste donc dans "
            "l'historique du shell. Relancez sans argument pour une saisie "
            "masquee.\n"
        )
    else:
        password = getpass.getpass("Mot de passe : ")
        confirm = getpass.getpass("Confirmer     : ")
        if password != confirm:
            print("Erreur : les deux saisies different.")
            return 1

    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Erreur : mot de passe trop court ({MIN_PASSWORD_LENGTH} caracteres minimum).")
        return 1

    # Même méthode que `auth_manager.create_user`, importée plutôt que recopiée :
    # un hachage généré ici doit rester vérifiable par l'application, y compris si
    # la méthode change un jour.
    hashed = generate_password_hash(password, method=PASSWORD_HASH_METHOD)

    print("\nAjoutez ceci à votre docker-compose.yml :\n")
    print("    environment:")
    print("      - ADMIN_USERNAME=admin")
    print(f"      - ADMIN_PASSWORD_HASH={hashed}")
    print(
        "\nLe compte est créé au premier démarrage. Si un compte existe déjà, "
        "ces variables sont ignorées : elles ne peuvent pas écraser un mot de "
        "passe en place."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
