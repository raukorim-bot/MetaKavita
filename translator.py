import logging
import requests
from config_manager import load_config
from translations import translations

def translate_azure(text, key, region, target_lang):
    """
    Appelle l'API Microsoft Azure Translator F0 (2M car/mois).
    """
    lang_code = target_lang.lower()
    if lang_code == "zh":
        lang_code = "zh-Hans"
        
    url = "https://api.cognitive.microsofttranslator.com/translate"
    params = {
        "api-version": "3.0",
        "to": lang_code
    }
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-type": "application/json"
    }
    if region:
        headers["Ocp-Apim-Subscription-Region"] = region
        
    payload = [{"Text": text}]
    
    logging.info(f"[Azure Translator] Tentative vers '{lang_code}' (Région: {region or 'Globale'}). Payload: {len(text)} caractères.")
    
    response = requests.post(url, params=params, headers=headers, json=payload, timeout=12)
    
    if response.status_code == 200:
        result = response.json()
        return result[0]["translations"][0]["text"]
    else:
        logging.error(f"[Azure Translator] Rejet de l'API (Code {response.status_code}) : {response.text}")
        response.raise_for_status()

def translate_deepl(text, key, target_lang):
    """
    Appelle l'API DeepL (Détecte si c'est la version Pro ou Free selon la clé).
    """
    if key.endswith(":fx"):
        url = "https://api-free.deepl.com/v2/translate"
    else:
        url = "https://api.deepl.com/v2/translate"
        
    headers = {"Authorization": f"DeepL-Auth-Key {key}"}
    payload = {"text": [text], "target_lang": target_lang}
    
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    if response.status_code == 200:
        return response.json()['translations'][0]['text']
    else:
        response.raise_for_status()

def translate_google(text, target_lang):
    """
    Appelle Google Translate de manière non officielle via py-googletrans.
    Totalement gratuit, aucune clé requise.
    """
    from googletrans import Translator
    translator = Translator()
    
    # Formatage du code langue pour googletrans
    lang_code = target_lang.lower()
    if lang_code == "pt-br": lang_code = "pt"
    if lang_code == "zh": lang_code = "zh-cn"
    
    result = translator.translate(text, dest=lang_code)
    return result.text

def translate_text(text, api_key_fallback_ignored=None, target_lang="FR"):
    """
    Couche d'abstraction : Écoute le choix de l'utilisateur. 
    Si l'API payante crash, effectue une bascule de secours automatique vers Google.
    """
    if not text:
        return text
        
    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
    
    text_clean = text.replace('<br>', '\n').replace('<i>', '').replace('</i>', '')
    
    # Récupération du choix utilisateur
    provider = config.get("TRANSLATION_PROVIDER", "GOOGLE")
    
    # NOUVEAU : Interception absolue si le système est désactivé
    if provider == "NONE":
        logging.info(t.get('log_trans_disabled', "⏭️ [Translator] Traduction désactivée, conservation de la VO."))
        return text_clean

    azure_key = config.get("AZURE_API_KEY", "").strip()
    azure_region = config.get("AZURE_REGION", "").strip()
    deepl_key = config.get("DEEPL_API_KEY", "").strip()
        
    # 1. Si l'utilisateur a choisi AZURE
    if provider == "AZURE" and azure_key:
        try:
            return translate_azure(text_clean, azure_key, azure_region, target_lang)
        except Exception as e:
            logging.warning(t.get('log_azure_fail', "⚠️ [Azure Translator] Échec : {0}").format(e))
            logging.info(t.get('log_google_fallback', "🔄 [Translator] Bascule automatique vers Google Translate..."))
            
    # 2. Si l'utilisateur a choisi DEEPL
    elif provider == "DEEPL" and deepl_key:
        try:
            return translate_deepl(text_clean, deepl_key, target_lang)
        except Exception as e:
            logging.error(t.get('log_deepl_fail_general', "❌ [DeepL] Échec : {0}").format(e))
            logging.info(t.get('log_google_fallback', "🔄 [Translator] Bascule automatique vers Google Translate..."))
            
    # 3. Moteur GOOGLE (Choix par défaut ou Secours Ultime)
    try:
        # On affiche le log uniquement si l'utilisateur avait volontairement choisi Google
        if provider == "GOOGLE" or (provider != "GOOGLE" and not azure_key and not deepl_key):
            logging.info(f"✨ [Google Translate] Traduction vers {target_lang}...")
        return translate_google(text_clean, target_lang)
    except Exception as e:
        logging.error(t.get('log_google_fail', "❌ [Google Translate] Échec : {0}").format(e))

    return text