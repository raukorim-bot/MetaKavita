"""Confirmation explicite avant qu'un script de `debug/` sorte sur Internet.

Plusieurs scripts de ce dossier appellent les VRAIS fournisseurs : ils lancent
`fetch()` sur les scrapers installés, parfois sur les vingt et un d'affilée, et
plusieurs le font au niveau module — il suffisait donc de lancer le fichier,
sans même un `if __name__`, pour envoyer une rafale de requêtes chez Bédéthèque
ou Planète BD. Ces deux sites n'ont pas d'API, refusent le crawl et bannissent
l'adresse IP ; c'est déjà arrivé à l'utilisateur de ce dépôt, et le
bannissement ne se lève pas sur demande.

D'où cette porte : rien ne part sans que quelqu'un l'ait voulu explicitement.
Elle ne remplace pas la prudence, elle empêche le lancement accidentel — un
double-clic, une complétion de shell, un agent qui « vérifie juste une fois ».

Usage, en tête du script, avant la première requête :

    from _live_network_guard import confirm_live_network
    confirm_live_network("debug_all.py", "les 21 fournisseurs configurés")

Non interactif (CI, pipe, agent) : le script s'arrête, sauf si
`METAKAVITA_LIVE_DEBUG=1` est posé délibérément dans l'environnement.
"""

from __future__ import annotations

import os
import sys

_ENV_OPT_IN = "METAKAVITA_LIVE_DEBUG"
_MOT_DE_PASSE = "OUI"


def confirm_live_network(script: str, cibles: str, *, details: str = "") -> None:
    """Demande confirmation, ou interrompt le script.

    `cibles` est affiché tel quel : il doit nommer les fournisseurs réellement
    contactés, pour que la personne qui confirme sache ce qu'elle autorise.
    """
    if os.environ.get(_ENV_OPT_IN) == "1":
        print(
            f"[{script}] {_ENV_OPT_IN}=1 : requêtes réelles autorisées vers {cibles}.",
            flush=True,
        )
        return

    banniere = (
        "\n" + "=" * 78 + "\n"
        f"  ATTENTION — {script} émet de VRAIES requêtes réseau.\n"
        + "=" * 78 + "\n"
        f"  Cibles : {cibles}\n"
    )
    if details:
        banniere += f"  {details}\n"
    banniere += (
        "\n"
        "  Les fournisseurs français sans API (Bédéthèque, Planète BD, Decitre,\n"
        "  Babelio, SensCritique) bannissent l'IP qui les interroge en rafale.\n"
        "  Ce bannissement est déjà arrivé sur ce projet et ne se lève pas sur\n"
        "  demande : la machine perd l'accès au fournisseur pour de bon.\n"
        "\n"
        "  N'exécutez ceci que si vous en avez besoin, depuis une machine dont\n"
        "  le bannissement éventuel est acceptable.\n"
        + "=" * 78 + "\n"
    )
    print(banniere, flush=True)

    if not sys.stdin or not sys.stdin.isatty():
        print(
            "Entrée non interactive : abandon. Pour forcer en connaissance de "
            f"cause, posez {_ENV_OPT_IN}=1 dans l'environnement.",
            flush=True,
        )
        raise SystemExit(1)

    try:
        reponse = input(f"Taper « {_MOT_DE_PASSE} » pour continuer : ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAbandon.", flush=True)
        raise SystemExit(1)

    if reponse != _MOT_DE_PASSE:
        print("Abandon : rien n'a été émis.", flush=True)
        raise SystemExit(1)
