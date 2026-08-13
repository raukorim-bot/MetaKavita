"""
Traduction des résumés, et la cadence qui évite de se faire bannir en le faisant.

Trois moteurs, trois régimes qui n'ont rien de commun :

**Google** est le seul qui puisse réellement bloquer votre adresse. `googletrans`
et le point d'entrée `translate_a/t` tapent l'API interne du site : aucune limite
publiée, aucun contrat, et des blocages rapportés après quelques dizaines de
requêtes rapprochées. C'est un site à ménager, comme Bédéthèque — la campagne qui
a fait bannir l'IP du développeur a exactement cette forme.

**DeepL** documente ses erreurs et ne bannit pas : sa limite est un volume, pas
une fréquence. La clé gratuite actuelle (*API Developer*) vaut 1 000 000 de
caractères **une fois pour toutes**, sans renouvellement, et répond 456 quand il
n'en reste plus ; les anciennes clés *API Free* fonctionnent sur 500 000
caractères par mois. Un 429 y est une rafale, pas une sanction : il passe si on
réessaie.

**Azure F0** est le plus confortable : 2 000 000 de caractères par mois, avec un
étranglement à 2 M/heure lissé sur une fenêtre glissante, soit 33 300 caractères
par minute. Dépasser ce débit rend un 429 même si le quota mensuel est intact.

Deux mesures en découlent, et ce module n'existe que pour elles.

**L'envoi groupé.** Les trois moteurs acceptent plusieurs textes par requête —
Google jusqu'à vingt par POST sur `translate_a/t`, DeepL cinquante, Azure mille.
Les quarante résumés d'une série tiennent donc en une ou deux requêtes au lieu de
quarante, ce qui divise le risque de blocage par le même facteur. L'ordre des
réponses suit l'ordre des textes, et **le nombre est vérifié** : une réponse
tronquée décalerait les résumés d'un album sur l'autre, et ils sont écrits
verrouillés.

**La cadence.** Elle est un intervalle *minimum depuis la dernière requête*, à la
manière de `services/provider_throttle.py` — dont ce module réutilise l'horloge,
pour la raison énoncée là-bas : le moteur ne connaît pas la fonctionnalité qui
l'appelle. Le temps passé ailleurs compte donc dans l'attente, et le chemin
série, qui traduit un résumé entre deux scrapings, ne paie rien.
"""

import logging
import random
import threading
import time

import requests

from config_manager import load_config
from services.provider_throttle import throttle_provider
from translations import get_ui_translations, translations

#: Intervalle minimum entre deux requêtes d'un même moteur, en secondes.
#:
#: Cinq secondes pour Google : les mainteneurs de py-googletrans conseillent 7 à
#: 10 s par *texte*, et une requête en porte désormais vingt. La marge réelle est
#: donc bien plus large qu'avant, pour une passe bien plus rapide.
MIN_INTERVAL = {"GOOGLE": 5.0, "DEEPL": 0.5, "AZURE": 1.0}

#: Gigue ajoutée à l'intervalle. Un rythme parfaitement régulier est ce qui
#: distingue le mieux un script d'un lecteur.
JITTER = {"GOOGLE": 1.5}

#: Débit lissé du palier Azure F0 : 2 M caractères/heure, soit 33 300 par minute.
#: L'attente est réglée sur ce que la requête *va* envoyer plutôt que sur ce
#: qu'elle vient d'envoyer — payer d'avance protège la première rafale, qui est
#: précisément celle qui déclenche le 429.
AZURE_CHARS_PER_SECOND = 555.0

#: Attentes successives sur un 429, par moteur. Google n'en a aucune : son 429
#: est un blocage d'adresse, et y revenir ne fait que le prolonger.
RETRY_DELAYS = {"GOOGLE": (), "DEEPL": (5.0, 15.0), "AZURE": (5.0, 15.0)}

#: Durée de mise à l'écart d'un moteur qui a rendu un 429 jusqu'au bout. Google
#: dit lui-même que son blocage « expire peu après l'arrêt des requêtes ».
BLOCK_SECONDS = {"GOOGLE": 900.0, "DEEPL": 300.0, "AZURE": 300.0}

#: Quota épuisé (DeepL 456) : rien ne changera avant un rechargement du crédit.
#: Assez long pour ne plus insister, assez court pour qu'un redémarrage ne soit
#: pas nécessaire après une montée d'offre.
QUOTA_BLOCK_SECONDS = 6 * 3600.0

# Limites de regroupement. Chacune reste sous celle du moteur, avec une marge :
# une requête refusée pour cause de taille coûte le même blocage qu'une rafale.
GOOGLE_MAX_TEXTS, GOOGLE_MAX_CHARS = 20, 8000        # non documenté ; mesuré
DEEPL_MAX_TEXTS, DEEPL_MAX_CHARS = 50, 100_000       # 50 textes, corps < 128 KiB
AZURE_MAX_TEXTS, AZURE_MAX_CHARS = 100, 40_000       # 1 000 éléments, 50 000 car.

GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/t"
_GOOGLE_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_PACING_LOCK = threading.Lock()
_BLOCKED_UNTIL: dict = {}


class _EngineClock:
    """Ce que `throttle_provider` sait cadencer : un identifiant, un intervalle.

    Recréé à chaque appel : l'état vit dans `LAST_REQUEST_TIMES`, indexé par cet
    identifiant, et le verrou de `provider_throttle` l'est aussi.
    """

    __slots__ = ("id", "rate_limit")

    def __init__(self, engine, interval):
        self.id = f"translate:{engine}"
        self.rate_limit = interval


def _throttle(engine, chars=0):
    interval = MIN_INTERVAL.get(engine, 1.0)
    if engine == "AZURE" and chars:
        interval = max(interval, chars / AZURE_CHARS_PER_SECOND)
    jitter = JITTER.get(engine, 0.0)
    if jitter:
        interval += random.uniform(0.0, jitter)
    throttle_provider(_EngineClock(engine, interval))


def engine_blocked(engine):
    """Vrai tant qu'un moteur est à l'écart après un 429 ou un quota épuisé."""
    with _PACING_LOCK:
        until = _BLOCKED_UNTIL.get(engine, 0.0)
        if not until:
            return False
        if time.monotonic() >= until:
            del _BLOCKED_UNTIL[engine]
            return False
        return True


def block_engine(engine, seconds, reason=""):
    """Écarte un moteur. Journalisé une seule fois par mise à l'écart.

    Sans cela, une passe de mille tomes réessaierait mille fois un moteur qui
    vient de bloquer l'adresse — c'est-à-dire exactement le trafic qui prolonge
    le blocage.
    """
    with _PACING_LOCK:
        already = _BLOCKED_UNTIL.get(engine, 0.0) > time.monotonic()
        _BLOCKED_UNTIL[engine] = time.monotonic() + float(seconds)
    if not already:
        logging.error(
            "🚫 [Translator] %s écarté pour %d min%s. Les textes partent dans "
            "leur langue d'origine en attendant.",
            engine,
            int(seconds // 60),
            f" : {reason}" if reason else "",
        )


def reset_pacing_state():
    """Vide cadence et mises à l'écart. Pour les tests (état global de module)."""
    with _PACING_LOCK:
        _BLOCKED_UNTIL.clear()
    from services.provider_throttle import LAST_REQUEST_TIMES

    for key in [k for k in LAST_REQUEST_TIMES if str(k).startswith("translate:")]:
        del LAST_REQUEST_TIMES[key]


def _chunks(texts, max_texts, max_chars):
    """Découpe en paquets qui tiennent dans une requête, ordre préservé."""
    chunk, size = [], 0
    for text in texts:
        length = len(text)
        if chunk and (len(chunk) >= max_texts or size + length > max_chars):
            yield chunk
            chunk, size = [], 0
        chunk.append(text)
        size += length
    if chunk:
        yield chunk


def _send(engine, call, chars=0):
    """Envoie en respectant la cadence, réessaie un 429 quand cela a un sens.

    Rend la réponse, mise à l'écart du moteur comprise si le 429 persiste.
    """
    delays = RETRY_DELAYS.get(engine, ())
    response = None
    for attempt in range(len(delays) + 1):
        _throttle(engine, chars)
        response = call()
        if getattr(response, "status_code", 0) != 429:
            return response
        if attempt < len(delays):
            time.sleep(delays[attempt])
    block_engine(engine, BLOCK_SECONDS.get(engine, 300.0), "trop de requêtes (429)")
    return response


def _azure_lang(target_lang):
    lang_code = str(target_lang or "FR").lower()
    return "zh-Hans" if lang_code == "zh" else lang_code


def _google_lang(target_lang):
    lang_code = str(target_lang or "FR").lower()
    if lang_code == "pt-br":
        return "pt"
    if lang_code == "zh":
        return "zh-cn"
    return lang_code


def translate_azure_batch(texts, key, region, target_lang):
    """API Microsoft Azure Translator F0, plusieurs textes par requête."""
    t = get_ui_translations()
    lang_code = _azure_lang(target_lang)
    url = "https://api.cognitive.microsofttranslator.com/translate"
    headers = {"Ocp-Apim-Subscription-Key": key, "Content-type": "application/json"}
    if region:
        headers["Ocp-Apim-Subscription-Region"] = region

    out = []
    for chunk in _chunks(texts, AZURE_MAX_TEXTS, AZURE_MAX_CHARS):
        chars = sum(len(text) for text in chunk)
        logging.info(
            t.get(
                "log_azure_attempt",
                "[Azure Translator] Tentative vers '{0}' (Région: {1}). Payload: {2} caractères.",
            ).format(lang_code, region or t.get("label_global_region", "Globale"), chars)
        )
        response = _send(
            "AZURE",
            lambda: requests.post(
                url,
                params={"api-version": "3.0", "to": lang_code},
                headers=headers,
                json=[{"Text": text} for text in chunk],
                timeout=20,
            ),
            chars=chars,
        )
        if response.status_code != 200:
            logging.error(
                t.get(
                    "log_azure_reject", "[Azure Translator] Requête rejetée ({0}) : {1}"
                ).format(response.status_code, response.text)
            )
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or len(payload) != len(chunk):
            raise ValueError(
                f"Azure a rendu {len(payload) if isinstance(payload, list) else '?'} "
                f"traduction(s) pour {len(chunk)} texte(s)"
            )
        out.extend(item["translations"][0]["text"] for item in payload)
    return out


def translate_deepl_batch(texts, key, target_lang):
    """API DeepL, plusieurs textes par requête (50 au plus)."""
    url = (
        "https://api-free.deepl.com/v2/translate"
        if key.endswith(":fx")
        else "https://api.deepl.com/v2/translate"
    )
    headers = {"Authorization": f"DeepL-Auth-Key {key}"}

    out = []
    for chunk in _chunks(texts, DEEPL_MAX_TEXTS, DEEPL_MAX_CHARS):
        response = _send(
            "DEEPL",
            lambda: requests.post(
                url,
                json={"text": list(chunk), "target_lang": target_lang},
                headers=headers,
                timeout=20,
            ),
        )
        if response.status_code == 456:
            # Crédit épuisé : la clé gratuite ne se recharge pas d'elle-même.
            block_engine("DEEPL", QUOTA_BLOCK_SECONDS, "crédit de caractères épuisé (456)")
        if response.status_code != 200:
            response.raise_for_status()
        items = (response.json() or {}).get("translations") or []
        if len(items) != len(chunk):
            raise ValueError(
                f"DeepL a rendu {len(items)} traduction(s) pour {len(chunk)} texte(s)"
            )
        out.extend(str(item.get("text") or "") for item in items)
    return out


def _google_values(parsed, expected):
    """Extrait les traductions d'une réponse `translate_a/t`.

    Deux formes selon la langue source : `sl=auto` rend `[texte, langue
    détectée]` par entrée, un `sl` explicite rend la chaîne seule. Le nombre est
    vérifié parce qu'une réponse tronquée écrirait le résumé d'un album sur le
    suivant — et l'écriture verrouille.
    """
    if not isinstance(parsed, list):
        raise ValueError("réponse inattendue de Google")
    values = []
    for item in parsed:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, list) and item and isinstance(item[0], str):
            values.append(item[0])
        else:
            raise ValueError("entrée inattendue dans la réponse de Google")
    if len(values) != expected:
        raise ValueError(f"Google a rendu {len(values)} traduction(s) pour {expected} texte(s)")
    return values


def translate_google_batch(texts, target_lang):
    """Google Translate, sans clé, plusieurs textes par requête POST.

    `translate_a/t` accepte un `q` répété et rend un résultat par `q`, dans
    l'ordre — ce que `googletrans` ne fait pas : sa méthode de lot boucle sur une
    requête par texte, ce qui est exactement le trafic qui fait bloquer.
    """
    lang_code = _google_lang(target_lang)
    out = []
    for chunk in _chunks(texts, GOOGLE_MAX_TEXTS, GOOGLE_MAX_CHARS):
        response = _send(
            "GOOGLE",
            lambda: requests.post(
                GOOGLE_ENDPOINT,
                params={"client": "gtx", "sl": "auto", "tl": lang_code},
                data=[("q", text) for text in chunk],
                headers={"User-Agent": _GOOGLE_UA},
                timeout=20,
            ),
        )
        response.raise_for_status()
        out.extend(_google_values(response.json(), len(chunk)))
    return out


def translate_google_via_library(texts, target_lang):
    """Dernier recours : `googletrans`, un texte par requête.

    Il ne sert que si `translate_a/t` cesse de répondre comme prévu — Google peut
    changer son point d'entrée interne du jour au lendemain, et cette
    bibliothèque s'y adapte, là où notre appel direct attendrait un correctif.
    Cadencé comme le reste, donc lent : c'est un filet, pas une voie.
    """
    from googletrans import Translator

    translator = Translator()
    lang_code = _google_lang(target_lang)
    out = []
    for text in texts:
        _throttle("GOOGLE")
        out.append(translator.translate(text, dest=lang_code).text)
    return out


# --- Compatibilité : les appels à un seul texte passent par le lot ---


def translate_azure(text, key, region, target_lang):
    return translate_azure_batch([text], key, region, target_lang)[0]


def translate_deepl(text, key, target_lang):
    return translate_deepl_batch([text], key, target_lang)[0]


def translate_google(text, target_lang):
    return translate_google_batch([text], target_lang)[0]


def _clean(text):
    return text.replace("<br>", "\n").replace("<i>", "").replace("</i>", "")


def translate_texts(texts, target_lang="FR", quiet=False, config=None):
    """Traduit une liste de textes et les rend dans le même ordre.

    Ne lève jamais : un moteur en panne, écarté ou sans clé rend les textes
    d'origine. C'est la dégradation que tous les appelants attendent — mais elle
    a un coût qu'il faut connaître : l'enrichissement écrit ce qu'on lui rend, et
    verrouille. Un texte non traduit est donc un texte non traduit pour de bon.

    Les textes identiques ne sont envoyés qu'une fois, et les vides pas du tout.
    """
    if not texts:
        return []

    cfg = config if isinstance(config, dict) else load_config()
    t = translations.get(cfg.get("UI_LANG", "fr"), translations["fr"])
    cleaned = [_clean(text) if isinstance(text, str) else "" for text in texts]

    provider = str(cfg.get("TRANSLATION_PROVIDER", "GOOGLE") or "GOOGLE").upper()
    if provider == "NONE":
        if not quiet:
            logging.info(
                t.get(
                    "log_trans_disabled",
                    "⏭️ [Translator] Traduction désactivée, conservation de la VO.",
                )
            )
        return cleaned

    # Dédoublonnage avant l'envoi : deux albums au même résumé, un seul texte
    # dans la requête. Sur un run où le fournisseur répète le pitch de la série,
    # cela divise le volume facturé par le nombre d'albums.
    uniques = list(dict.fromkeys(text for text in cleaned if text.strip()))
    if not uniques:
        return cleaned

    azure_key = str(cfg.get("AZURE_API_KEY", "") or "").strip()
    azure_region = str(cfg.get("AZURE_REGION", "") or "").strip()
    deepl_key = str(cfg.get("DEEPL_API_KEY", "") or "").strip()

    translated = None
    if provider == "AZURE" and azure_key:
        if engine_blocked("AZURE"):
            logging.info(t.get("log_google_fallback", "🔄 [Translator] Bascule automatique vers Google Translate..."))
        else:
            try:
                translated = translate_azure_batch(uniques, azure_key, azure_region, target_lang)
            except Exception as exc:
                logging.warning(t.get("log_azure_fail", "⚠️ [Azure Translator] Échec : {0}").format(exc))
                logging.info(t.get("log_google_fallback", "🔄 [Translator] Bascule automatique vers Google Translate..."))
    elif provider == "DEEPL" and deepl_key:
        if engine_blocked("DEEPL"):
            logging.info(t.get("log_google_fallback", "🔄 [Translator] Bascule automatique vers Google Translate..."))
        else:
            try:
                translated = translate_deepl_batch(uniques, deepl_key, target_lang)
            except Exception as exc:
                logging.error(t.get("log_deepl_fail_general", "❌ [DeepL] Échec : {0}").format(exc))
                logging.info(t.get("log_google_fallback", "🔄 [Translator] Bascule automatique vers Google Translate..."))

    if translated is None:
        translated = _google_texts(uniques, target_lang, provider, azure_key, deepl_key, quiet, t)

    if translated is None or len(translated) != len(uniques):
        return cleaned

    table = dict(zip(uniques, translated))
    return [table.get(text) or text for text in cleaned]


def _google_texts(uniques, target_lang, provider, azure_key, deepl_key, quiet, t):
    """Le moteur par défaut, et le secours ultime des deux autres."""
    if engine_blocked("GOOGLE"):
        return None

    # Une ligne par requête, pas par texte : à un texte par ligne, une passe de
    # tomes noyait sa propre progression sous des dizaines de lignes identiques.
    if not quiet and (provider == "GOOGLE" or (not azure_key and not deepl_key)):
        logging.info(
            t.get(
                "log_google_translating", "✨ [Google Translate] Traduction vers {0}..."
            ).format(target_lang)
            + f" ({len(uniques)} texte(s))"
        )
    try:
        return translate_google_batch(uniques, target_lang)
    except Exception as exc:
        logging.error(t.get("log_google_fail", "❌ [Google Translate] Échec : {0}").format(exc))

    # Le point d'entrée direct a échoué autrement que par un 429 : la
    # bibliothèque sait peut-être encore parler à Google.
    if engine_blocked("GOOGLE"):
        return None
    try:
        return translate_google_via_library(uniques, target_lang)
    except Exception as exc:
        logging.error(t.get("log_google_fail", "❌ [Google Translate] Échec : {0}").format(exc))
    return None


def translate_text(text, api_key_fallback_ignored=None, target_lang="FR", quiet=False):
    """
    Couche d'abstraction : Écoute le choix de l'utilisateur.
    Si l'API payante crash, effectue une bascule de secours automatique vers Google.

    `quiet` supprime la ligne de journal par requête, sans rien changer d'autre.
    Un appelant qui traduit un texte par série peut l'annoncer ; l'enrichissement
    par tome en traduit quarante d'un coup et rend un décompte à la place. Les
    échecs restent journalisés dans les deux cas.
    """
    if not text:
        return text
    return translate_texts([text], target_lang=target_lang, quiet=quiet)[0]
