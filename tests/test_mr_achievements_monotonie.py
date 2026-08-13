"""
Un haut-fait « à vie » décroché ne se reprend pas (BF145).

`/stats` évalue le catalogue sur des compteurs cumulés qui ne redescendent
jamais. Quatre conditions étaient pourtant écrites pour une *session* : « une
seule confirmation », « rien confirmé », « jamais le #1 », « aucune retouche ».
À vie, chacune se referme dès l'action suivante : la carte repasse dans
« Encore à croquer », le compteur « {0} / {1} débloqués » régresse, et
l'utilisateur lit une remise à zéro de sa progression.

Ces tests comparent deux points dans le temps sur les mêmes compteurs — ce que
`tests/test_mr_achievements.py`, qui n'évalue qu'un instantané, ne pouvait pas
voir.
"""
from services.mr_achievements import evaluate
from translations import translations


def _bag(**kw):
    bag = {
        "done": 0,
        "skipped": 0,
        "top1": 0,
        "edits": 0,
        "purged": 0,
        "researches": 0,
        "fusions": 0,
        "weak_picks": 0,
        "score_sum": 0.0,
        "score_n": 0,
        "super_used": False,
    }
    bag.update(kw)
    return bag


def _unlocked(**kw):
    return {c["id"] for c in evaluate(_bag(**kw), translations["fr"])["unlocked"]}


def _locked(**kw):
    return {c["id"]: c for c in evaluate(_bag(**kw), translations["fr"])["locked"]}


def test_l_echauffement_reste_debloque_apres_la_deuxieme_confirmation():
    """
    « Échauffement » était testé sur `done == 1`.

    Piège : à vie, la deuxième confirmation le reverrouille — et sa jauge, elle,
    reste à 100 %. L'écran affichait donc une carte « Encore à croquer » pleine
    à ras bord, ce qui se lit comme un bug d'affichage doublé d'une régression.
    """
    assert "warmup" in _unlocked(done=1, top1=1, score_sum=0.9, score_n=1)
    assert "warmup" in _unlocked(done=2, top1=2, score_sum=1.8, score_n=2)


def test_le_spectateur_reste_debloque_apres_sa_premiere_confirmation():
    """
    « Spectateur VIP » exigeait `done == 0` en plus des séries passées.

    Piège : passer des séries est un acquis, ne rien confirmer n'en est pas un.
    La toute première confirmation effaçait le haut-fait.
    """
    assert "spectator" in _unlocked(skipped=3)
    assert "spectator" in _unlocked(skipped=3, done=1, top1=1, score_sum=0.9, score_n=1)


def test_le_contre_courant_reste_debloque_apres_un_top1_accepte():
    """
    « Contre-courant » exigeait `top1 == 0` sur tout le cumul.

    Piège : un seul top-1 accepté, des mois plus tard, effaçait des dizaines de
    choix à contre-courant. Le cumul qui compte est le nombre de confirmations
    qui ont écarté le #1, jamais l'absence totale de top-1.
    """
    assert "rebel" in _unlocked(done=2, top1=0)
    after = evaluate(_bag(done=3, top1=1), translations["fr"])
    ids = {c["id"] for c in after["unlocked"]}
    assert "rebel" in ids
    rebel = [c for c in after["unlocked"] if c["id"] == "rebel"][0]
    assert "2" in rebel["flavor"], (
        "le libellé doit annoncer les confirmations hors #1, pas le total des confirmations"
    )


def test_la_decision_eclair_ne_figure_plus_dans_le_cumul_a_vie():
    """
    « Décision éclair » (3 confirms sans aucune retouche) ne peut pas être rendue
    monotone : les compteurs à vie ne disent pas combien de confirmations ont
    précédé la première retouche. Le laisser au lifetime revenait à promettre un
    haut-fait qu'une seule retouche retirait pour toujours — il reste au
    catalogue session, comme la pause café.
    """
    result = evaluate(_bag(done=5, edits=0), translations["fr"])
    ids = {c["id"] for c in result["unlocked"]} | {c["id"] for c in result["locked"]}
    assert "lightning" not in ids


def test_le_compteur_de_hauts_faits_ne_regresse_jamais_au_fil_dune_vie():
    """
    Marche forcée : à chaque tour l'utilisateur confirme un top-1 à 0,90, passe
    une série et retouche un champ. Aucun compteur ne baisse, aucune moyenne ne
    se dégrade — la liste des hauts-faits ne peut donc que grandir.

    Piège : sans cette lecture dans la durée, chaque instantané paraît correct.
    C'est l'enchaînement qui trahit le verrouillage.
    """
    acquis: set = set()
    precedent = 0
    for tour in range(1, 13):
        result = evaluate(
            _bag(
                done=tour,
                top1=tour,
                skipped=tour,
                edits=tour,
                score_sum=0.9 * tour,
                score_n=tour,
            ),
            translations["fr"],
        )
        ids = {c["id"] for c in result["unlocked"]}
        perdus = acquis - ids
        assert not perdus, f"haut(s)-fait(s) repris à l'utilisateur au tour {tour} : {sorted(perdus)}"
        assert result["unlocked_count"] >= precedent
        acquis |= ids
        precedent = result["unlocked_count"]

    assert {"warmup", "curator", "spectator", "oracle", "gourmet"} <= acquis


def test_une_carte_verrouillee_n_affiche_jamais_une_jauge_pleine():
    """La barre suit le verdict : 100 % sur une carte « Encore à croquer » se lit
    comme un déblocage perdu."""
    for card in evaluate(_bag(done=2, top1=2, skipped=1), translations["fr"])["locked"]:
        assert card["progress"] < 1.0, f"{card['id']} : jauge pleine mais carte verrouillée"


def test_une_carte_debloquee_affiche_toujours_une_jauge_pleine():
    """
    Réciproque : la jauge d'une carte décrochée est remplie.

    Piège : `progress` est calculé par une lambda indépendante du verdict, et
    plusieurs comptent vers un palier plus haut que la condition de déblocage —
    « Spectateur VIP » tombe à la première série passée mais sa barre vise trois.
    Une carte fêtée avec une barre au tiers passe pour un déblocage à moitié
    acquis, donc reprenable.
    """
    for card in evaluate(_bag(skipped=1), translations["fr"])["unlocked"]:
        assert card["progress"] == 1.0, f"{card['id']} : carte débloquée mais jauge partielle"
