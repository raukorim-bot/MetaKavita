# Translation

[English](README.md) · [Français](../fr/translation.md)

← [Documentation](README.md)

To keep scraped descriptions in their original language, set the translation provider to **Disabled (Keep original)** (`NONE`).

Engines: **Google Translate** (zero-config, free), **Microsoft Azure Translator**, **DeepL API**.

DeepL's current **API Developer** plan is **1,000,000 characters in total, once** — it does not reset; DeepL answers HTTP 456 when spent. Older **API Free** keys (no longer sold) are 500,000 characters *per month*. Count roughly 700 characters per summary.

For stability, Azure Translator Free Tier F0 (**2,000,000 characters per month**) as primary, with DeepL or Google as fallbacks, is the usual recommendation.

MetaKavita paces itself. Google's free engine is the site's internal entry point, not a contracted API: it has no published limit and can block an address that queries too quickly. A blocked translation lands in Kavita as the original-language summary — locked, on the per-volume path. All summaries of a series leave in one request (Google twenty at a time, DeepL fifty, Azure a thousand), identical texts are sent once, and a delay separates two requests. If an engine answers *too many requests*, it is set aside for a while and the log says so.

See `TRANSLATION_PROVIDER`, `AZURE_API_KEY`, `AZURE_REGION`, `DEEPL_API_KEY`, `TARGET_LANG` in [Configuration](configuration.md).
