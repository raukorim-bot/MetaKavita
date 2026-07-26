"""
Sélection des titres pour Kavita `localizedName` (une seule string).

Modes globaux (`LOCALIZED_TITLE_MODE`) :
  - all    : tous les titres uniques, joints par " / " (défaut — philo MetaKavita)
  - prefer : filtre/ordonne selon une liste de tags langue (BCP-47-ish)
  - none   : ne pas écrire localizedName

Override série (`alt_title_langs`) : si non vide, force le mode prefer avec cette liste
(vide = hérite du global).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def parse_lang_list(raw: Optional[str]) -> List[str]:
    """'en, ja-ro, ja' → ['en', 'ja-ro', 'ja'] (normalisés, uniques, ordre conservé)."""
    if not raw or not str(raw).strip():
        return []
    out: List[str] = []
    seen = set()
    for part in str(raw).replace(";", ",").split(","):
        tag = normalize_lang_tag(part.strip())
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def normalize_lang_tag(tag: str) -> str:
    """Normalise les variantes courantes des scrapers vers des tags conventionnels."""
    if not tag:
        return ""
    t = str(tag).strip().lower().replace("_", "-")
    aliases = {
        "eng": "en",
        "en-us": "en",
        "en-gb": "en",
        "jp": "ja",
        "jpn": "ja",
        "ja-jp": "ja",
        "en-jp": "ja-ro",
        "ja-latn": "ja-ro",
        "romaji": "ja-ro",
        "japanese-romaji": "ja-ro",
        "ko-kr": "ko",
        "kor": "ko",
        "en-kr": "ko-ro",
        "ko-latn": "ko-ro",
        "zh-cn": "zh",
        "zh-tw": "zh",
        "zh-hk": "zh",
        "chi": "zh",
        "en-cn": "zh-ro",
        "zh-latn": "zh-ro",
        "fra": "fr",
        "fre": "fr",
        "deu": "de",
        "ger": "de",
        "spa": "es",
        "por": "pt",
        "pt-br": "pt-br",
        "pt-pt": "pt",
    }
    return aliases.get(t, t)


def native_lang_from_country(country: Optional[str]) -> str:
    c = (country or "").strip().upper()
    return {"JP": "ja", "KR": "ko", "CN": "zh", "TW": "zh", "HK": "zh"}.get(c, "ja")


def entries_from_provider(provider_data: Optional[dict]) -> List[Tuple[str, str]]:
    """Liste (lang, value) à partir de `titles` structurés ou de `alternative_titles` plats."""
    if not provider_data:
        return []
    entries: List[Tuple[str, str]] = []
    seen_values = set()

    structured = provider_data.get("titles")
    if isinstance(structured, list) and structured:
        for item in structured:
            if not isinstance(item, dict):
                continue
            val = str(item.get("value") or "").strip()
            if not val:
                continue
            lang = normalize_lang_tag(item.get("lang") or "")
            key = val.casefold()
            if key in seen_values:
                continue
            seen_values.add(key)
            entries.append((lang, val))
        return entries

    for raw in provider_data.get("alternative_titles") or []:
        val = str(raw).strip() if raw is not None else ""
        if not val:
            continue
        key = val.casefold()
        if key in seen_values:
            continue
        seen_values.add(key)
        entries.append(("", val))
    return entries


def resolve_localized_name(
    provider_data: Optional[dict],
    *,
    mode: str = "all",
    langs: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Construit la string `localizedName` ou None si on ne doit pas écrire."""
    mode_n = (mode or "all").strip().lower()
    if mode_n == "none":
        return None

    preferred = parse_lang_list(",".join(langs) if isinstance(langs, (list, tuple)) else (langs or ""))
    # Liste déjà normalisée si passée en Sequence[str]
    if langs and not isinstance(langs, str) and not preferred:
        preferred = []
        seen = set()
        for x in langs:
            tag = normalize_lang_tag(str(x))
            if tag and tag not in seen:
                seen.add(tag)
                preferred.append(tag)

    entries = entries_from_provider(provider_data)
    if not entries:
        return None

    if mode_n == "prefer" and preferred:
        picked: List[str] = []
        seen = set()
        for want in preferred:
            for lang, val in entries:
                if lang == want:
                    k = val.casefold()
                    if k not in seen:
                        seen.add(k)
                        picked.append(val)
        if picked:
            return " / ".join(picked)
        # Aucun match langue → repli sur tous (évite de vider localizedName par erreur)
        mode_n = "all"

    # mode all (défaut) ou prefer sans langs / sans match
    values = [val for _lang, val in entries]
    return " / ".join(values) if values else None


def merge_title_entries(*lists: Iterable[Any]) -> List[Dict[str, str]]:
    """Fusionne des listes `titles` [{lang, value}] sans doublon de valeur."""
    out: List[Dict[str, str]] = []
    seen = set()
    for lst in lists:
        if not lst:
            continue
        for item in lst:
            if not isinstance(item, dict):
                continue
            val = str(item.get("value") or "").strip()
            if not val:
                continue
            k = val.casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append({
                "lang": normalize_lang_tag(item.get("lang") or ""),
                "value": val,
            })
    return out


def resolve_effective_title_policy(
    config: dict,
    series_alt_title_langs: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    Retourne (mode, langs) effectifs pour une série.
    Override série non vide → mode prefer + langs de la série.
    """
    override = (series_alt_title_langs or "").strip()
    if override:
        return "prefer", parse_lang_list(override)

    mode = (config.get("LOCALIZED_TITLE_MODE") or "all").strip().lower()
    if mode not in ("all", "prefer", "none"):
        mode = "all"
    langs = parse_lang_list(config.get("LOCALIZED_TITLE_LANGS") or "")
    return mode, langs
