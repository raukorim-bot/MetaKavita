"""Planète BD (planetebd.com) — métadonnées BD / comics FR (HTML, pas d'API)."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from config_manager import get_max_genres, get_max_tags
from scrapers.base import BaseScraper
from scrapers.utils import (
    album_number_key,
    attach_match_score,
    clean_title,
    extract_volume_number,
    get_match_accept_threshold,
    response_is_ok,
    score_candidate,
    select_wanted_album_links,
)

_BASE = "https://www.planetebd.com"
_NON_ISBN = re.compile(r"[^0-9Xx]")
_ALBUM_RE = re.compile(
    r"^/(?P<kind>bd|comics|mangas)/(?P<publisher>[^/]+)/(?P<series>[^/]+)/(?P<album>[^/]+)/(?P<id>\d+)\.html",
    re.I,
)
_SERIES_RE = re.compile(
    r"^/(?P<kind>bd|comics|mangas)/series/(?P<slug>[^/]+)/(?P<id>\d+)\.html",
    re.I,
)
_YEAR = re.compile(r"(1[0-9]{3}|20[0-9]{2})")

# Catégories Planetebd acceptées pour library_type Comic
_COMIC_CATS = {"bande dessinée", "bandes dessinées", "comics", "comic"}


def _normalize_isbn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = _NON_ISBN.sub("", str(raw)).upper()
    if len(cleaned) in (10, 13):
        return cleaned
    return None


def _abs(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return urljoin(_BASE, url.split("#", 1)[0])


def _album_number(text: str) -> Optional[str]:
    """Numéro de tome d'un libellé Planète BD (« Astérix T41 : … »).

    `extract_volume_number` ne connaît pas la forme « T41 », qui est pourtant la
    seule qu'emploie le site : sans ce parseur, aucun album ne s'apparierait.

    Le numéro est rendu sous forme de chaîne, et non d'entier, pour que les
    hors-série intercalaires (« T1.5 », « T3,5 » — le site emploie l'un et
    l'autre séparateur) restent exprimables. Les rendre en entier les
    ramenait au tome plein qui les précède : le hors-série 1.5, croisé avant
    le tome 1, occupait sa clé dans l'index et lui volait ses métadonnées.
    """
    raw = str(text or "")
    match = re.search(r"\bT(?:ome)?\.?\s*(\d{1,4}(?:[.,]\d{1,2})?)\b", raw, re.I)
    if not match:
        match = re.match(r"^\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*[.\-–:]", raw)
    if match:
        return album_number_key(match.group(1))
    return album_number_key(extract_volume_number(raw))


def _same_series_only(
    albums: List[Dict[str, Any]], series_slug: str
) -> List[Dict[str, Any]]:
    """Ne garde que les albums de la série consultée.

    Le slug de la page série tranche quand il correspond. Il ne correspond pas
    toujours : quand la page a été atteinte par un identifiant forcé, l'URL de
    sondage ne porte pas le vrai slug, et une redirection non suivie la laisse
    telle quelle. On retombe alors sur le groupe le plus nombreux, parce qu'une
    fiche série est faite de ses propres albums, tandis que les blocs « à lire
    aussi » apportent un ou deux liens par série étrangère.
    """
    if not albums:
        return []
    if series_slug:
        own = [a for a in albums if a["series"] == series_slug]
        if own:
            return own
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for album in albums:
        groups.setdefault(album["series"], []).append(album)
    return max(groups.values(), key=len)


def _series_title_from_album_label(label: str) -> str:
    """'Astérix T41 : …' / 'Watchmen T12' → titre de série approximatif."""
    label = (label or "").strip()
    if not label:
        return ""
    # Couper sous-titre après " : "
    head = label.split(" : ", 1)[0].strip()
    head = re.sub(r"\s+T(?:ome)?\s*\d+\s*$", "", head, flags=re.I).strip()
    head = re.sub(r",\s*T\d+\s*$", "", head, flags=re.I).strip()
    return head or label


class PlanetebdScraper(BaseScraper):
    id = "PLANETEBD"
    is_core = True
    display_name = "Planète BD"
    supported_types = {"Comic"}
    scopes = {"series", "volume"}
    # 1.2.1 : le formulaire du site poste vers `/recherche.html`. L'ancienne
    # URL `/recherche/?mot-clef=` redirige vers `/recherche.html` *sans* le
    # mot-clé, donc `fetch()` voyait une page d'accueil et renvoyait None.
    # 1.3.0 : crawl ciblé (`wanted_numbers` / `should_cancel`) dans la boucle
    # d'albums. La jaquette et l'ISBN restent lus sur la fiche déjà visitée.
    version = "1.3.0"
    rate_limit = 2.5  # HTML — anti-ban IP
    # Une page par album à 2,5 s : au-delà, l'index coûterait plus de deux
    # minutes pour une série que personne ne possède en entier.
    VOLUME_INDEX_MAX = 50
    proxy_domains = ["planetebd.com", "static.planetebd.com", "www.planetebd.com"]
    has_direct_id_support = True
    requires_proxy = False
    needs_api_key = False
    uses_unified_scoring = True

    translations = {
        "fr": {
            "direct_id": "🎯 [PlanèteBD] Requête directe id={0}",
            "search_title": "🔍 [PlanèteBD] Recherche pour '{0}'…",
            "no_match": "⚠️ [PlanèteBD] Aucun résultat pertinent pour '{0}' (Score max: {1}%)",
            "matched": "🎯 [PlanèteBD] Match validé : '{0}' (Score: {1}%)",
            "err": "❌ [PlanèteBD] Erreur : {0}",
            "covers_err": "❌ [Covers] PlanèteBD : {0}",
        },
        "en": {
            "direct_id": "🎯 [PlanèteBD] Direct id request={0}",
            "search_title": "🔍 [PlanèteBD] Searching for '{0}'…",
            "no_match": "⚠️ [PlanèteBD] No relevant result for '{0}' (Max score: {1}%)",
            "matched": "🎯 [PlanèteBD] Match validated: '{0}' (Score: {1}%)",
            "err": "❌ [PlanèteBD] Error: {0}",
            "covers_err": "❌ [Covers] PlanèteBD: {0}",
        },
    }

    def extract_id_from_url(self, url: str) -> Optional[str]:
        if not url or not isinstance(url, str):
            return None
        url = url.strip()
        if url.isdigit():
            return url
        path = urlparse(url).path if "://" in url else url
        m = _SERIES_RE.match(path)
        if m:
            return m.group("id")
        m = _ALBUM_RE.match(path)
        if m:
            return m.group("id")
        m = re.search(r"/(?:bd|comics|mangas)/series/[^/]+/(\d+)\.html", path)
        if m:
            return m.group(1)
        return None

    def fetch(
        self,
        query: str,
        library_type: str = "Comic",
        is_id: bool = False,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if library_type not in self.supported_types and library_type != "ComicFlexible":
            if not is_id:
                return None

        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
                "Referer": f"{_BASE}/",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        try:
            if is_id:
                sid = self.extract_id_from_url(query) or (
                    query.strip() if query.strip().isdigit() else None
                )
                if not sid:
                    return None
                logging.info(self.t("direct_id").format(sid))
                # Bare numeric ID: probe with a placeholder slug — the site
                # redirects to the canonical /series/<slug>/<id>.html URL.
                for kind in ("bd", "comics", "mangas"):
                    probe = f"{_BASE}/{kind}/series/s/{sid}.html"
                    try:
                        res = self._http_get(
                            session, probe, timeout=20, allow_redirects=True
                        )
                        if res is None or getattr(res, "status_code", 0) != 200:
                            continue
                        final = getattr(res, "url", None) or probe
                        cand = self._candidate_from_series_or_album(session, final)
                        if cand:
                            return attach_match_score(cand, 1.0)
                    except Exception as e:
                        logging.debug("PlaneteBD bare-id probe %s failed: %s", probe, e)
                # Fallback : URL complète fournie
                if "planetebd.com" in query or query.startswith("/"):
                    cand = self._candidate_from_series_or_album(session, query)
                    if cand:
                        return attach_match_score(cand, 1.0)
                return None

            cleaned = clean_title(query, library_type="Comic")
            if not cleaned:
                return None

            logging.info(self.t("search_title").format(cleaned))
            hits = self._search(session, cleaned)
            if not hits:
                return None

            # Dédupliquer par slug série album, préférer tome 1
            by_series: Dict[str, dict] = {}
            for hit in hits:
                key = hit.get("series_key") or hit.get("url")
                if not key:
                    continue
                vol = extract_volume_number(hit.get("label") or "")
                prev = by_series.get(key)
                if not prev:
                    by_series[key] = hit
                    continue
                prev_vol = extract_volume_number(prev.get("label") or "")
                if vol == 1 and prev_vol != 1:
                    by_series[key] = hit
                elif (prev_vol is None or prev_vol > 1) and vol is not None and (
                    prev_vol is None or vol < prev_vol
                ):
                    by_series[key] = hit

            ranked_hits = list(by_series.values())[:8]

            best_match = None
            best_score = -1.0
            for hit in ranked_hits:
                candidate = self._candidate_from_series_or_album(
                    session, hit["url"], search_hint=cleaned, hit=hit
                )
                if not candidate or not candidate.get("title"):
                    continue
                score = score_candidate(candidate, cleaned, existing_metadata)
                if (candidate.get("title") or "").casefold() == cleaned.casefold():
                    score = min(1.0, score + 0.12)
                # Bonus franchise courte dans le titre
                if cleaned.casefold() in (candidate.get("title") or "").casefold():
                    score = min(1.0, max(score, 0.72))
                if score > best_score:
                    best_score = score
                    best_match = candidate

            if not best_match or best_score < get_match_accept_threshold():
                logging.warning(
                    self.t("no_match").format(cleaned, int(max(best_score, 0) * 100))
                )
                return None

            logging.info(
                self.t("matched").format(best_match.get("title"), int(best_score * 100))
            )
            return attach_match_score(best_match, best_score)

        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_volume(
        self,
        query: str,
        library_type: str = "Comic",
        volume_number: Optional[Any] = None,
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Une fiche album, par URL `/bd|comics|mangas/.../*.html`."""
        url = str(query or "").strip()
        path = urlparse(url).path if "://" in url else url
        if not _ALBUM_RE.match(path):
            return None
        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
                "Referer": f"{_BASE}/",
            }
        )
        try:
            album = self._parse_album(session, url if url.startswith("http") else urljoin(_BASE, url))
            if not album:
                return None
            payload = {
                "provider_ref": url,
                "title": album.get("album_title") or "",
                "summary": album.get("summary") or "",
                "release_date": str(album.get("year") or ""),
                "isbn": album.get("isbn") or "",
                "cover_url": album.get("cover_url") or "",
            }
            return {k: v for k, v in payload.items() if v} or None
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Comic",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
        wanted_numbers: Optional[set] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Index des albums d'une série BD.

        Une page par album, à 2,5 s de cadence : c'est lent, d'où le plafond.
        Une série de plus de cinquante albums est rarissime en BD franco-belge,
        et le tronquer vaut mieux qu'un quart d'heure de scraping muet.
        """
        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
                "Referer": f"{_BASE}/",
            }
        )
        try:
            series_url = self._resolve_series_url(session, query, library_type, series_id)
            if not series_url:
                return None

            index: Dict[str, Any] = {}
            for link in select_wanted_album_links(
                self._album_links_from_series(session, series_url),
                wanted_numbers,
                self.VOLUME_INDEX_MAX,
            ):
                if should_cancel and should_cancel():
                    break
                if link["number"] is None:
                    continue
                key = link["number"]
                if key in index:
                    continue
                album = self._parse_album(session, link["url"])
                if not album:
                    continue
                payload = {
                    "provider_ref": link["url"],
                    "title": album.get("album_title") or "",
                    "summary": album.get("summary") or "",
                    "release_date": str(album.get("year") or ""),
                    "isbn": album.get("isbn") or "",
                    "cover_url": album.get("cover_url") or "",
                }
                payload = {k: v for k, v in payload.items() if v}
                if payload:
                    index[key] = payload
            return index or None
        except Exception as e:
            logging.error(self.t("err").format(e))
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _resolve_series_url(
        self, session, query: str, library_type: str, series_id: Optional[str]
    ) -> Optional[str]:
        """URL de la page série, par identifiant forcé si possible, par recherche sinon."""
        raw = str(series_id or "").strip()
        if raw:
            sid = self.extract_id_from_url(raw) or (raw if raw.isdigit() else None)
            if sid:
                for kind in ("bd", "comics", "mangas"):
                    probe = f"{_BASE}/{kind}/series/s/{sid}.html"
                    try:
                        res = self._http_get(
                            session, probe, timeout=20, allow_redirects=True
                        )
                    except Exception:
                        continue
                    if res is not None and getattr(res, "status_code", 0) == 200:
                        return getattr(res, "url", None) or probe
            if "planetebd.com" in raw:
                return raw

        cleaned = clean_title(query, library_type="Comic")
        if not cleaned:
            return None
        for hit in self._search(session, cleaned)[:5]:
            url = hit.get("url") or ""
            path = urlparse(urljoin(_BASE, url)).path
            if _SERIES_RE.match(path):
                return urljoin(_BASE, url)
            if _ALBUM_RE.match(path):
                # Un résultat d'album porte le lien vers sa série.
                album = self._parse_album(session, urljoin(_BASE, url))
                if album and album.get("series_url"):
                    return album["series_url"]
        return None

    def fetch_covers(
        self, query: str, library_type: str = "Comic"
    ) -> List[Dict[str, str]]:
        covers: List[Dict[str, str]] = []
        cleaned = clean_title(query, library_type="Comic")
        if not cleaned:
            return covers
        session = requests.Session(impersonate="chrome110")
        session.headers.update(
            {
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": f"{_BASE}/",
            }
        )
        try:
            hits = self._search(session, cleaned)
            for hit in hits:
                url = hit.get("cover")
                title = _series_title_from_album_label(hit.get("label") or cleaned)
                if url and url not in [c["url"] for c in covers]:
                    covers.append(
                        {
                            "provider": self.display_name,
                            "title": title,
                            "url": url,
                        }
                    )
                if len(covers) >= 5:
                    break
        except Exception as e:
            logging.error(self.t("covers_err").format(e))
        finally:
            try:
                session.close()
            except Exception:
                pass
        return covers

    # ------------------------------------------------------------------ Search

    def _search(self, session, terms: str) -> List[dict]:
        res = self._http_get(
            session,
            f"{_BASE}/recherche.html",
            params={"mot-clef": terms},
            timeout=25,
        )
        if not response_is_ok(self, res, context="recherche"):
            return []
        soup = self._soup(res)
        hits: List[dict] = []
        for art in soup.select("article.featured"):
            cat_el = art.select_one(".cat")
            cat = (cat_el.get_text(" ", strip=True) if cat_el else "").casefold()
            if cat and cat not in _COMIC_CATS:
                # Laisser passer si pas de cat (rare)
                if cat not in {"", "tous"}:
                    continue
            a = art.select_one(".image a[href], a[href*='/bd/'], a[href*='/comics/']")
            if not a:
                continue
            href = _abs(a.get("href"))
            if not href:
                continue
            path = urlparse(href).path
            m = _ALBUM_RE.match(path)
            if not m:
                continue
            img = art.select_one("img[src]")
            label = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
            # Nettoyer label type "… (0), bd chez …"
            label = re.split(r",\s*(?:bd|comics)\s+chez\s+", label, maxsplit=1, flags=re.I)[
                0
            ].strip()
            hits.append(
                {
                    "url": href,
                    "label": label,
                    "cover": img.get("src") if img else None,
                    "cat": cat,
                    "series_key": f"{m.group('kind')}/{m.group('publisher')}/{m.group('series')}",
                    "kind": m.group("kind"),
                }
            )
        return hits

    # ------------------------------------------------------------------ Detail

    def _candidate_from_series_or_album(
        self,
        session,
        url_or_path: str,
        *,
        search_hint: str = "",
        hit: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        url = _abs(url_or_path)
        if not url:
            return None
        path = urlparse(url).path

        # Si déjà une page série
        sm = _SERIES_RE.match(path)
        album_meta: Dict[str, Any] = {}
        series_url = None
        series_title = None

        # La page série est chargée UNE fois et gardée : le titre, le statut de
        # publication et le premier album en sortent tous les trois. Chacun
        # passait par son propre `_get_soup`, soit la même page téléchargée deux
        # à trois fois par candidat — sur huit candidats, à 2,5 s de cadence, ce
        # sont plusieurs dizaines de secondes de requêtes inutiles offertes à un
        # site qui bannit à vue.
        series_soup = None

        if sm:
            series_url = url
            series_soup = self._get_soup(session, url)
            series_title = self._series_title(series_soup)
            # Prendre un album de la série pour cover/staff
            album_meta = self._first_album_from_series(session, series_soup) or {}
        else:
            album_meta = self._parse_album(session, url) or {}
            if not album_meta:
                return None
            series_url = album_meta.get("series_url")
            series_title = album_meta.get("series_title")
            # Affiner le titre série via page série
            if series_url:
                series_soup = self._get_soup(session, series_url)
                st = self._series_title(series_soup)
                if st:
                    series_title = st

        title = (
            series_title
            or _series_title_from_album_label(
                (hit or {}).get("label") or album_meta.get("album_title") or ""
            )
            or search_hint
        )
        if not title:
            return None

        cover = album_meta.get("cover_url") or (hit or {}).get("cover")
        staff = album_meta.get("staff") or []
        genres = album_meta.get("genres") or []
        tags = album_meta.get("tags") or []
        summary = album_meta.get("summary") or ""
        publisher = album_meta.get("publisher")
        year = album_meta.get("year")
        isbn = album_meta.get("isbn")
        # `_parse_album` ne renseigne jamais `status` : le statut vient de la
        # page série, celle déjà chargée plus haut.
        status = album_meta.get("status") or self._series_status(series_soup)

        out: Dict[str, Any] = {
            "title": title,
            "alternative_titles": [],
            "summary": summary,
            "cover_url": cover,
            "genres": genres[: get_max_genres()] if genres else ["Comic"],
            "tags": tags[: get_max_tags()],
            "year": year,
            "staff": staff,
            "publisher": publisher,
            "format": "comic",
            "url": series_url or url,
            "links": [u for u in [series_url, url] if u],
        }
        if isbn:
            out["isbn"] = isbn
        if status:
            out["status"] = status
        # Pas d'age_rating inventé
        return out

    @staticmethod
    def _soup(res) -> BeautifulSoup:
        """Soupe construite sur les OCTETS de la réponse, pas sur `res.text`.

        `curl_cffi` suppose UTF-8 quand le serveur n'annonce pas de `charset`, et
        décode avec `errors="replace"` : sur une page en ISO-8859-1, les accents
        d'un titre ou d'un résumé français devenaient des U+FFFD irrécupérables,
        écrits puis verrouillés dans Kavita. En recevant les octets,
        BeautifulSoup lit le `<meta charset>` de la page et retombe juste.

        Le repli sur `res.text` vise les doublures de test : un `MagicMock`
        fabrique un `.content` factice qu'il ne faut pas confondre avec des
        octets réels, d'où le contrôle de type plutôt qu'un test de nullité.
        """
        raw = getattr(res, "content", None)
        if not isinstance(raw, (bytes, bytearray)):
            raw = res.text
        return BeautifulSoup(raw, "html.parser")

    def _get_soup(self, session, url: str) -> Optional[BeautifulSoup]:
        res = self._http_get(session, url, timeout=25)
        if not response_is_ok(self, res, context=url):
            return None
        return self._soup(res)

    @staticmethod
    def _series_title(soup: Optional[BeautifulSoup]) -> Optional[str]:
        if soup is None:
            return None
        if soup.h1:
            t = soup.h1.get_text(" ", strip=True)
            if t and "oops" not in t.casefold():
                return t
        return None

    @staticmethod
    def _series_status(soup: Optional[BeautifulSoup]) -> Optional[str]:
        if soup is None:
            return None
        text = soup.get_text(" ", strip=True).casefold()
        if "série terminée" in text or "serie terminee" in text:
            return "FINISHED"
        if "série en cours" in text or "serie en cours" in text:
            return "RELEASING"
        return None

    def _first_album_from_series(
        self, session, soup: Optional[BeautifulSoup]
    ) -> Optional[Dict[str, Any]]:
        if soup is None:
            return None
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            path = urlparse(urljoin(_BASE, href)).path
            if _ALBUM_RE.match(path):
                return self._parse_album(session, urljoin(_BASE, href))
        return None

    def _album_links_from_series(self, session, series_url: str) -> List[Dict[str, Any]]:
        """Les albums **de cette série**, avec leur numéro de tome.

        Généralise `_first_album_from_series`, qui s'arrêtait au premier lien :
        c'est cette liste qui permet d'écrire tome par tome plutôt que de ne
        connaître que le tome 1.

        Le filtre sur le slug de série n'est pas une précaution de confort : une
        fiche Planète BD porte des blocs « à lire aussi », des critiques et des
        albums du même éditeur, tous sous la même forme d'URL. Un de ces liens
        dont le libellé contient « T2 » prendrait la place du vrai tome 2, et
        l'utilisateur recevrait le résumé et la couverture d'une autre série.
        """
        soup = self._get_soup(session, series_url)
        if not soup:
            return []
        series_match = _SERIES_RE.match(urlparse(series_url).path)
        series_slug = (series_match.group("slug") if series_match else "").lower()

        found: List[Dict[str, Any]] = []
        seen = set()
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            absolute = urljoin(_BASE, href)
            path = urlparse(absolute).path
            album_match = _ALBUM_RE.match(path)
            if not album_match or path in seen:
                continue
            seen.add(path)
            # Le numéro vient du libellé du lien (« Astérix T41 : … ») ; à
            # défaut, du slug de l'album, qui le porte presque toujours. On le
            # cherche dans le seul segment d'album : le reste de l'URL porte un
            # identifiant numérique qui passerait pour un numéro de tome.
            label = a.get_text(" ", strip=True) or (a.get("title") or "")
            number = _album_number(label)
            if number is None:
                number = _album_number(album_match.group("album").replace("-", " "))
            found.append(
                {
                    "url": absolute,
                    "number": number,
                    "label": label,
                    "series": album_match.group("series").lower(),
                }
            )
        return _same_series_only(found, series_slug)

    def _parse_album(self, session, album_url: str) -> Optional[Dict[str, Any]]:
        soup = self._get_soup(session, album_url)
        if not soup or not soup.title:
            return None

        og_title = soup.select_one('meta[property="og:title"]')
        og_desc = soup.select_one('meta[property="og:description"]')
        og_img = soup.select_one('meta[property="og:image"]')
        og_isbn = soup.select_one('meta[property="og:isbn"]')

        album_title = None
        if soup.h1:
            album_title = soup.h1.get_text(" ", strip=True)
        if not album_title and og_title:
            album_title = (og_title.get("content") or "").strip()

        # Série : lien /bd|comics/series/slug/id.html — préférer celui
        # dont le slug apparaît dans l'URL album
        path = urlparse(album_url).path
        am = _ALBUM_RE.match(path)
        series_slug = am.group("series") if am else ""
        series_url = None
        series_title = None
        series_id = None
        for a in soup.select("a[href*='/series/']"):
            href = _abs(a.get("href"))
            if not href:
                continue
            sm = _SERIES_RE.match(urlparse(href).path)
            if not sm:
                continue
            if series_slug and sm.group("slug") == series_slug:
                series_url = href
                series_title = a.get_text(" ", strip=True) or None
                series_id = sm.group("id")
                break
            if series_url is None:
                series_url = href
                series_title = a.get_text(" ", strip=True) or None
                series_id = sm.group("id")

        # Staff via /auteur/
        authors: List[str] = []
        seen = set()
        for a in soup.select("a[href*='/auteur/']"):
            name = a.get_text(" ", strip=True) or (a.get("title") or "").strip()
            key = name.casefold()
            if name and key not in seen and len(name) > 1:
                seen.add(key)
                authors.append(name)
        staff: List[Dict[str, Any]] = []
        for i, name in enumerate(authors[:6]):
            role = "Story" if i == 0 else ("Art" if i == 1 else "Art")
            if len(authors) == 1:
                role = "Story & Art"
            staff.append({"role": role, "node": {"name": {"full": name}}})

        # Fallback title tag: "… bd chez Éditeur de A, B"
        if not staff and soup.title:
            m = re.search(
                r"(?:bd|comics)\s+chez\s+.+?\s+de\s+(.+)$",
                soup.title.get_text(" ", strip=True),
                flags=re.I,
            )
            if m:
                for i, name in enumerate(
                    [x.strip() for x in m.group(1).split(",") if x.strip()][:4]
                ):
                    role = "Story" if i == 0 else "Art"
                    staff.append({"role": role, "node": {"name": {"full": name}}})

        editor = soup.select_one("[itemprop=editor]")
        publisher = editor.get_text(" ", strip=True) if editor else None

        year = None
        dp = soup.select_one('meta[itemprop="datePublished"]')
        if dp and dp.get("content"):
            ym = _YEAR.search(dp["content"])
            if ym:
                year = int(ym.group(1))

        genres = []
        for g in soup.select("[itemprop=genre]"):
            label = g.get_text(" ", strip=True)
            if label and label not in genres:
                genres.append(label)

        return {
            "album_title": album_title,
            "series_url": series_url,
            "series_title": series_title or _series_title_from_album_label(album_title or ""),
            "series_id": series_id,
            "cover_url": (og_img.get("content") if og_img else None),
            "summary": (og_desc.get("content") if og_desc else "") or "",
            "isbn": _normalize_isbn(og_isbn.get("content") if og_isbn else None),
            "publisher": publisher,
            "year": year,
            "staff": staff,
            "genres": genres,
            "tags": [],
            "status": None,
        }
