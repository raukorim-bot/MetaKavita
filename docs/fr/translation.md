# Traduction

[English](../en/translation.md) · [Français](README.md)

← [Documentation](README.md)

Pour garder les résumés d'origine, choisis **Désactivé (Conserver l'original)** (`NONE`).

Moteurs : **Google Translate** (sans config, gratuit), **Microsoft Azure Translator**, **API DeepL**.

L'offre actuelle **DeepL API Developer**, c'est **1 000 000 de caractères une fois pour toutes** — le crédit ne se renouvelle pas ; DeepL répond HTTP 456 quand il est épuisé. Les anciennes clés **API Free** (plus vendues) : 500 000 caractères *par mois*. Compte environ 700 caractères par résumé.

Pour la stabilité : Azure Translator Free Tier F0 (**2 000 000 de caractères par mois**) en principal, DeepL ou Google en secours.

MetaKavita se cadence. Le Google gratuit n'est pas une API sous contrat : pas de limite publiée, et une adresse trop pressée peut être bloquée. Une traduction bloquée arrive dans Kavita dans la langue d'origine — verrouillée, sur le chemin par tome. Tous les résumés d'une série partent en une requête (Google vingt, DeepL cinquante, Azure mille), les textes identiques une seule fois, un délai entre deux requêtes. Si un moteur répond « trop de requêtes », il est mis de côté un moment et le journal le dit.

Voir `TRANSLATION_PROVIDER`, `AZURE_API_KEY`, `AZURE_REGION`, `DEEPL_API_KEY`, `TARGET_LANG` dans [Configuration](configuration.md).
