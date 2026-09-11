"""D'où vient exactement le code qui tourne.

`get_current_version()` lit le premier titre de `CHANGELOG.md`. C'est le numéro
que l'on *annonce*, et il est écrit au début d'un cycle, pas à sa fin : le titre
`## [1.7.2]` existait le 1ᵉʳ septembre alors que la 1.7.2 est sortie le 10. Une
image construite entre les deux dit donc « 1.7.2 » en toute bonne foi tout en
servant du code d'une semaine plus tôt — c'est exactement ce qui a laissé une
production sur du code du 3 septembre sans que rien ne le signale.

Le commit, lui, ne ment pas : il est gravé dans l'image au moment du build par
`--build-arg GIT_SHA`, et ne peut pas se désynchroniser de ce qui est copié à
côté. Les deux ensemble répondent à la seule question qui compte devant un
comportement inattendu : « est-ce que ce serveur fait bien tourner ce que je
crois ? »

Hors conteneur — un `python app.py` local, un test — la variable n'existe pas,
et l'absence se dit `""` plutôt que `"unknown"` : un appelant teste la vérité de
la chaîne, il n'a pas à connaître un mot magique.
"""

import os

#: Posée par le Dockerfile depuis `--build-arg GIT_SHA`, que la CI alimente
#: avec `github.sha`. Le nom porte le préfixe du projet : `GIT_SHA` seul est
#: assez générique pour qu'un autre outil de la même machine le revendique.
_COMMIT_ENV = "METAKAVITA_COMMIT"

#: Longueur d'affichage. Sept caractères, comme `git log --oneline` : assez
#: pour identifier un commit sans ambiguïté dans un dépôt de cette taille, et
#: assez court pour tenir dans une info-bulle ou un badge.
SHORT_LEN = 7


def build_commit() -> str:
    """Le SHA complet gravé dans l'image, ou `""` hors conteneur."""
    return (os.getenv(_COMMIT_ENV) or "").strip()


def build_commit_short() -> str:
    """Le SHA abrégé, ou `""` — jamais un placeholder à afficher tel quel."""
    return build_commit()[:SHORT_LEN]
