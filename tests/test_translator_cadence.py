"""Cadence et envoi groupé du traducteur : ce qui évite de se faire bloquer.

La traduction partait sans aucune cadence, une requête par texte. Sur une passe
de tomes, cela donnait des dizaines de requêtes rapprochées vers le point d'entrée
interne de Google — exactement le profil de trafic qui a fait bannir l'IP du
développeur chez Bédéthèque pendant cette campagne, et que les rapports publics
décrivent comme bloquant après quelques dizaines d'appels.

Deux mesures sont vérifiées ici, et leurs conséquences :

**Le regroupement.** Les trois moteurs acceptent plusieurs textes par requête.
Le nombre de réponses est contrôlé, parce qu'une réponse tronquée décalerait les
résumés d'un album sur l'autre — et l'enrichissement écrit *et verrouille*.

**La cadence.** Un intervalle minimum depuis la dernière requête du même moteur,
partagé avec l'horloge des fournisseurs. Un 429 de Google écarte le moteur au
lieu d'insister : son 429 est un blocage d'adresse, y revenir le prolonge.
"""
from __future__ import annotations

import time
import types

import pytest

import translator
from services import provider_throttle
from services.provider_throttle import LAST_REQUEST_TIMES


@pytest.fixture(autouse=True)
def _etat_propre():
    """Cadence et mises à l'écart sont des états de module."""
    translator.reset_pacing_state()
    yield
    translator.reset_pacing_state()


@pytest.fixture(autouse=True)
def _config_neutre(monkeypatch):
    """Aucun test ne doit lire la configuration réelle du dépôt.

    Elle contient une vraie clé DeepL : un test qui la trouverait enverrait le
    texte chez un moteur payant, et dépenserait un crédit qui ne se recharge pas.
    """
    monkeypatch.setattr(
        translator,
        "load_config",
        lambda: {"TRANSLATION_PROVIDER": "GOOGLE", "TARGET_LANG": "FR", "UI_LANG": "fr"},
    )


@pytest.fixture(autouse=True)
def _horloge_simulee(monkeypatch, real_provider_throttle_sleep):
    """Enregistre les attentes au lieu de les subir.

    Sans cela, un test de cadence à 5 s d'intervalle — et les réessais de DeepL,
    qui attendent 5 puis 15 s — mettraient la suite à genoux. La vraie question
    n'est pas que le processus dorme, c'est que l'attente demandée soit la bonne.

    La fixture demande `real_provider_throttle_sleep` pour écarter le garde-fou
    global du conftest, qui rend `sleep` muet : on veut le mesurer, pas le taire.
    """
    attentes = []

    def _sleep(seconds):
        attentes.append(seconds)
        # L'horloge de `provider_throttle` compare des `time.time()` réels : sans
        # avancer, l'intervalle ne serait jamais considéré comme écoulé et la
        # requête suivante attendrait de nouveau. On triche sur le temps, pas sur
        # la logique.
        for key in list(LAST_REQUEST_TIMES):
            LAST_REQUEST_TIMES[key] -= seconds

    monkeypatch.setattr(
        provider_throttle, "time", types.SimpleNamespace(time=time.time, sleep=_sleep)
    )
    monkeypatch.setattr(
        translator, "time", types.SimpleNamespace(sleep=_sleep, monotonic=time.monotonic)
    )
    return attentes


@pytest.fixture(autouse=True)
def _pas_de_repli_googletrans(monkeypatch):
    """Le repli `googletrans` sort réellement sur le réseau.

    Il n'a de sens que si Google change son point d'entrée interne ; ici, on
    vérifie qu'il est bien tenté, pas qu'il fonctionne.
    """
    tentatives = []

    def _refuse(texts, target_lang="FR"):
        tentatives.append(list(texts))
        raise RuntimeError("bibliothèque indisponible en test")

    monkeypatch.setattr(translator, "translate_google_via_library", _refuse)
    return tentatives


class _Reponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def poste(monkeypatch):
    """Intercepte `requests.post` du traducteur, et rend ce qu'on lui dit."""
    appels = []
    reponses = []

    def _post(url, **kwargs):
        appels.append({"url": url, **kwargs})
        if reponses:
            suivante = reponses.pop(0)
            return suivante() if callable(suivante) else suivante
        # Par défaut : la forme `sl=auto` de Google, un couple par texte.
        textes = [valeur for cle, valeur in (kwargs.get("data") or []) if cle == "q"]
        return _Reponse([[f"[FR] {texte}", "en"] for texte in textes])

    monkeypatch.setattr(translator.requests, "post", _post)
    return {"appels": appels, "reponses": reponses}


GOOGLE = {"TRANSLATION_PROVIDER": "GOOGLE", "TARGET_LANG": "FR", "UI_LANG": "fr"}
DEEPL = {**GOOGLE, "TRANSLATION_PROVIDER": "DEEPL", "DEEPL_API_KEY": "clé:fx"}
AZURE = {**GOOGLE, "TRANSLATION_PROVIDER": "AZURE", "AZURE_API_KEY": "clé", "AZURE_REGION": "westeurope"}


# ===== Regroupement =====


def test_vingt_textes_partent_en_une_requete(real_translator, poste):
    textes = [f"Blurb number {n}" for n in range(20)]

    out = translator.translate_texts(textes, config=GOOGLE)

    assert len(poste["appels"]) == 1, "une requête, pas vingt"
    assert out == [f"[FR] {texte}" for texte in textes]


def test_au_dela_de_la_limite_le_lot_est_decoupe(real_translator, poste):
    textes = [f"Texte {n}" for n in range(45)]

    out = translator.translate_texts(textes, config=GOOGLE)

    assert len(poste["appels"]) == 3, "20 + 20 + 5"
    assert out == [f"[FR] {texte}" for texte in textes]


def test_un_paquet_est_aussi_borne_en_caracteres(real_translator, poste):
    """Une requête trop grosse est refusée, et un refus coûte le même blocage."""
    textes = [f"{n} " + "x" * 3000 for n in range(5)]

    translator.translate_texts(textes, config=GOOGLE)

    assert len(poste["appels"]) == 3, "8 000 caractères par requête au plus"


def test_les_textes_identiques_ne_partent_qu_une_fois(real_translator, poste):
    """Un fournisseur qui répète le pitch de la série sur chaque album ne doit
    pas être payé quarante fois — DeepL facture au caractère."""
    out = translator.translate_texts(["Même texte", "Même texte", "Autre"], config=GOOGLE)

    envoyes = [v for c, v in poste["appels"][0]["data"] if c == "q"]
    assert envoyes == ["Même texte", "Autre"]
    assert out == ["[FR] Même texte", "[FR] Même texte", "[FR] Autre"]


def test_l_ordre_des_reponses_suit_l_ordre_des_textes(real_translator, poste):
    poste["reponses"].append(_Reponse(["un", "deux", "trois"]))

    out = translator.translate_texts(["a", "b", "c"], config=GOOGLE)

    assert out == ["un", "deux", "trois"]


def test_la_forme_sans_langue_detectee_est_acceptee(real_translator, poste):
    """`sl=auto` rend `[texte, langue]`, un `sl` explicite la chaîne seule."""
    poste["reponses"].append(_Reponse(["Bonjour le monde"]))

    assert translator.translate_texts(["Hello world"], config=GOOGLE) == ["Bonjour le monde"]


def test_une_reponse_tronquee_ne_decale_pas_les_resumes(
    real_translator, poste, _pas_de_repli_googletrans
):
    """Le garde-fou qui compte. Deux textes envoyés, une réponse : accepter
    reviendrait à poser le résumé du tome 1 sur le tome 2, verrouillé au passage.

    Une forme inattendue est aussi le signe que Google a changé son point
    d'entrée : le repli par la bibliothèque est tenté avant d'abandonner.
    """
    poste["reponses"].append(_Reponse(["Une seule traduction"]))

    out = translator.translate_texts(["Premier", "Second"], config=GOOGLE)

    assert out == ["Premier", "Second"], "la langue d'origine, pas un décalage"
    assert _pas_de_repli_googletrans == [["Premier", "Second"]], "le repli est tenté"


# ===== Cadence =====


def test_deux_requetes_de_suite_sont_espacees(real_translator, poste, _horloge_simulee):
    translator.translate_texts(["un"], config=GOOGLE)
    translator.translate_texts(["deux"], config=GOOGLE)

    assert _horloge_simulee, "la seconde requête doit attendre"
    assert max(_horloge_simulee) >= translator.MIN_INTERVAL["GOOGLE"] - 0.01


def test_la_premiere_requete_n_attend_pas(real_translator, poste, _horloge_simulee):
    """Une cadence qui fait attendre à froid ferait payer un moteur inactif."""
    translator.translate_texts(["un"], config=GOOGLE)

    assert _horloge_simulee == []


def test_la_cadence_est_partagee_avec_l_horloge_des_fournisseurs(real_translator, poste):
    """Le moteur ne connaît pas la fonctionnalité qui l'appelle : deux chemins
    qui traduiraient chacun sur son horloge frapperaient à la somme des deux."""
    translator.translate_texts(["un"], config=GOOGLE)

    assert "translate:GOOGLE" in LAST_REQUEST_TIMES


def test_azure_attend_a_proportion_des_caracteres_envoyes(
    real_translator, poste, _horloge_simulee
):
    """Le palier F0 lisse 2 M caractères/heure, soit 33 300 par minute : un gros
    lot doit s'étaler, sinon le 429 tombe alors que le quota mensuel est intact.
    """
    poste["reponses"].append(_Reponse([{"translations": [{"text": "ok"}]}]))
    poste["reponses"].append(_Reponse([{"translations": [{"text": "ok"}]}]))
    translator.translate_texts(["a"], config=AZURE)
    _horloge_simulee.clear()

    gros = "x" * 20_000
    translator.translate_texts([gros], config=AZURE)

    attendu = 20_000 / translator.AZURE_CHARS_PER_SECOND
    assert max(_horloge_simulee) >= attendu - 0.01


# ===== 429, quotas et mises à l'écart =====


def test_un_429_de_google_ecarte_le_moteur_sans_insister(real_translator, poste):
    """Le 429 de Google est un blocage d'adresse, pas une cadence : y revenir ne
    fait que le prolonger. Aucun réessai, et le moteur est écarté."""
    poste["reponses"].append(_Reponse(status_code=429))

    out = translator.translate_texts(["Hello"], config=GOOGLE)

    assert out == ["Hello"], "la langue d'origine, pas d'exception"
    assert len(poste["appels"]) == 1, "aucun réessai"
    assert translator.engine_blocked("GOOGLE")


def test_un_moteur_ecarte_n_est_plus_interroge(real_translator, poste):
    translator.block_engine("GOOGLE", 900, "test")

    out = translator.translate_texts(["Hello"], config=GOOGLE)

    assert out == ["Hello"]
    assert poste["appels"] == [], "pas une requête de plus tant que c'est bloqué"


def test_la_mise_a_l_ecart_expire(real_translator, poste, monkeypatch):
    translator.block_engine("GOOGLE", 900, "test")
    depart = time.monotonic()
    monkeypatch.setattr(
        translator,
        "time",
        types.SimpleNamespace(sleep=lambda _s: None, monotonic=lambda: depart + 1000),
    )

    assert translator.engine_blocked("GOOGLE") is False
    assert translator.translate_texts(["Hello"], config=GOOGLE) == ["[FR] Hello"]


def test_un_429_de_deepl_est_reessaye_puis_bascule_sur_google(real_translator, poste):
    """DeepL ne bannit pas : son 429 est une rafale, elle passe si on réessaie."""
    for _ in range(len(translator.RETRY_DELAYS["DEEPL"]) + 1):
        poste["reponses"].append(_Reponse(status_code=429))
    poste["reponses"].append(_Reponse([["[FR] Hello", "en"]]))

    out = translator.translate_texts(["Hello"], config=DEEPL)

    urls = [appel["url"] for appel in poste["appels"]]
    assert urls.count("https://api-free.deepl.com/v2/translate") == 3, "deux réessais"
    assert translator.GOOGLE_ENDPOINT in urls, "puis le secours"
    assert out == ["[FR] Hello"]
    assert translator.engine_blocked("DEEPL")


def test_un_credit_deepl_epuise_ecarte_la_cle_pour_longtemps(real_translator, poste):
    """456 : la clé gratuite ne se recharge pas d'elle-même. Réessayer à chaque
    série n'apporterait rien qu'une ligne d'erreur par tome."""
    poste["reponses"].append(_Reponse(status_code=456))
    poste["reponses"].append(_Reponse([["[FR] Hello", "en"]]))

    out = translator.translate_texts(["Hello"], config=DEEPL)

    assert out == ["[FR] Hello"], "le secours Google prend la suite"
    assert translator.engine_blocked("DEEPL")


def test_une_cle_deepl_absente_passe_directement_a_google(real_translator, poste):
    out = translator.translate_texts(["Hello"], config={**GOOGLE, "TRANSLATION_PROVIDER": "DEEPL"})

    assert out == ["[FR] Hello"]
    assert poste["appels"][0]["url"] == translator.GOOGLE_ENDPOINT


# ===== Traduction éteinte, entrées vides =====


def test_traduction_eteinte_ne_sort_pas_du_tout(real_translator, poste):
    out = translator.translate_texts(["Hello"], config={**GOOGLE, "TRANSLATION_PROVIDER": "NONE"})

    assert out == ["Hello"]
    assert poste["appels"] == []


def test_les_textes_vides_ne_partent_pas(real_translator, poste):
    out = translator.translate_texts(["", "   ", None], config=GOOGLE)

    assert out == ["", "   ", ""]
    assert poste["appels"] == []


def test_une_liste_vide_rend_une_liste_vide(real_translator, poste):
    assert translator.translate_texts([], config=GOOGLE) == []
    assert poste["appels"] == []


def test_le_balisage_de_resume_est_nettoye(real_translator, poste):
    """`<br>` et `<i>` viennent des fournisseurs HTML et n'ont rien à faire dans
    un résumé Kavita."""
    translator.translate_texts(["Un <i>mot</i><br>et la suite"], config=GOOGLE)

    envoyes = [v for c, v in poste["appels"][0]["data"] if c == "q"]
    assert envoyes == ["Un mot\net la suite"]


# ===== L'appel à un texte reste servi =====


def test_translate_text_passe_par_le_lot(real_translator, poste):
    """Le chemin série n'a pas changé de contrat : un texte, un texte rendu."""
    assert translator.translate_text("Hello", None, target_lang="FR") == "[FR] Hello"
    assert len(poste["appels"]) == 1


def test_translate_text_rend_un_texte_vide_tel_quel(real_translator, poste):
    assert translator.translate_text("") == ""
    assert poste["appels"] == []
