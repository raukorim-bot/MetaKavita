"""
Choix du fournisseur et récupération de l'index des tomes.

Deux chemins, de coûts très différents :

* **l'index par série** — un appel réseau pour toute la série, quand le
  fournisseur sait lister ses albums (ComicVine, Planète BD, Bédéthèque,
  Manga-News) ; MangaDex n'y apporte que les couvertures ;
* **le chemin ISBN** — un appel par tome, réservé aux unités qui portent déjà un
  ISBN dans Kavita, pour ce que l'index n'a pas couvert.

Le second ne se déclenche que sur ce que le premier n'a pas couvert.

À ces deux chemins répondent deux familles de fournisseurs, et `VOLUME_PROVIDER`
peut nommer l'une ou l'autre : `volume_providers()` retient ceux qui savent lister
(scope `volume`), `UNIT_PROVIDERS` ceux qui répondent tome par tome. Imposer un
fournisseur de la seconde famille supprime l'index au lieu de le chercher chez
quelqu'un d'autre.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from secure_logging import safe_exc_str
from services.magic_input import detect_provider_from_url, is_http_url
from services.provider_throttle import throttle_provider

#: Cascade ISBN, dans l'ordre. Les trois acceptent `existing_metadata={"isbn": …}`.
ISBN_PROVIDERS = ("GOOGLEBOOKS", "OPENLIBRARY", "HARDCOVER")

#: Fournisseurs interrogeables par titre de série + numéro de tome. Chemin
#: expérimental : c'est une recherche, pas une correspondance d'identifiant.
TITLE_VOLUME_PROVIDERS = ("GOOGLEBOOKS",)

#: Les fournisseurs qui répondent à l'unité, et non à la série. Ils ne savent
#: pas lister les albums — donc `volume_providers()`, bâti sur le scope
#: `volume`, ne les a jamais contenus — mais ils servent bel et bien les tomes,
#: par ISBN pour les trois, et par titre + numéro pour Google Books. Sur un
#: manga, Manga-News liste désormais les tomes VF ; ce chemin-ci complète ce
#: que l'index n'a pas couvert (pas de fiche, pas d'ISBN dans Kavita).
#:
#: Ils sont réunis ici pour que `VOLUME_PROVIDER` puisse les nommer : le réglage
#: ne lisait que la liste des index, si bien qu'imposer Google Books pour les
#: tomes journalisait « fournisseur imposé inutilisable » et reprenait la
#: cascade — un réglage sans effet sur les fournisseurs qui font justement le
#: travail sur les mangas.
UNIT_PROVIDERS = tuple(dict.fromkeys(ISBN_PROVIDERS + TITLE_VOLUME_PROVIDERS))

#: Plafond du chemin expérimental. Un appel par tome, cadencé : au-delà, une
#: série-fleuve mangerait la passe entière.
TITLE_VOLUME_LIMIT = 60

#: Slots de la modale Fournisseurs, par type de bibliothèque.
#:
#: `ComicFlexible` — le type 1 de Kavita, « Comic (Flexible) » — enchaîne les deux
#: cascades : les fournisseurs comics, puis les manga en repli, comme le chemin
#: série le fait déjà. Sans cette ligne, `cascade_rank` retombait sur `Manga` et
#: classait MangaDex premier sur une bibliothèque de bandes dessinées.
CASCADE_SLOTS: Dict[str, Tuple[str, ...]] = {
    "Comic": ("COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3"),
    "ComicFlexible": (
        "COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3",
        "PROVIDER_1", "PROVIDER_2", "PROVIDER_3",
    ),
    "Book": ("BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3"),
    "Manga": ("PROVIDER_1", "PROVIDER_2", "PROVIDER_3"),
}

#: Rang des fournisseurs que la cascade ne nomme pas. Ils restent joignables en
#: repli — trois slots ne couvrent pas les cinq fournisseurs d'un type — mais
#: toujours après ceux que l'utilisateur a désignés.
_UNRANKED = 99

#: Manga-News est le seul index manga qui rende un titre, un résumé, un ISBN et
#: une date. La cascade série (MangaBaka, Kitsu, MangaDex) n'a rien à voir : la
#: suivre pour les tomes mettait MangaDex en tête, un appel pour des jaquettes
#: que Kavita a déjà. Sur une bibliothèque Manga il passe donc devant ; sur une
#: Comic (Flexible) il reste le dernier recours manga, après les comics, à la
#: place de MangaDex. Un fournisseur imposé (`VOLUME_PROVIDER`) reste prioritaire.
MANGA_VOLUME_LEAD = "MANGANEWS"


def forced_volume_provider(config: Optional[dict] = None) -> str:
    """Le fournisseur imposé pour les tomes, ou `""` si la cascade décide."""
    if config is None:
        from config_manager import load_config

        config = load_config()
    raw = str(config.get("VOLUME_PROVIDER") or "").strip().upper()
    return "" if raw in ("", "AUTO", "NONE") else raw


def forced_unit_provider(config: Optional[dict] = None) -> str:
    """Le fournisseur imposé, s'il répond à l'unité plutôt qu'à la série.

    Rend `""` dès que le forçage désigne un fournisseur d'index, ou personne :
    seuls les appelants qui interrogent tome par tome ont à s'en soucier.
    """
    forced = forced_volume_provider(config)
    return forced if forced in UNIT_PROVIDERS else ""


def provides_volume_index(scraper: Any) -> bool:
    """Vrai si ce scraper sait vraiment lister les albums d'une série.

    `hasattr(scraper, "fetch_volume_index")` répondait oui pour tout le monde :
    `BaseScraper` définit la méthode, et sa version rend `None`. Un scraper tiers
    qui déclare `scopes = {"volume"}` sans l'implémenter était donc consulté —
    `throttle_provider` payé, une seconde ou deux perdues par série — pour un
    `None` garanti. La question n'est pas de savoir si la méthode existe, mais si
    quelqu'un l'a écrite.
    """
    from scrapers.base import BaseScraper

    method = getattr(scraper, "fetch_volume_index", None)
    if not callable(method):
        return False
    # `__func__` pour une méthode liée ; l'attribut lui-même pour une fonction
    # posée sur l'instance, comme le font des tests et des scrapers générés.
    return getattr(method, "__func__", method) is not BaseScraper.fetch_volume_index


def volume_provider_choices() -> List[Dict[str, str]]:
    """Ce que le menu « fournisseur imposé » a le droit de proposer.

    Deux familles, et la distinction n'est pas cosmétique : elle dit ce qu'on
    obtient. Un fournisseur d'**index** liste les albums d'une série en un appel,
    titres et résumés compris — c'est le chemin des comics et de la BD. Un
    fournisseur à l'**unité** identifie un tome à la fois, par son ISBN ; sans
    ISBN dans Kavita, il ne rendra rien, et l'imposer sur une bibliothèque de
    comics scannés revient à n'interroger personne.

    La liste vit ici plutôt que dans `routes/pages.py` parce que c'est la même
    règle que `volume_providers()` et `resolve_index()` appliquent : un menu qui
    proposerait autre chose offrirait un réglage sans effet.
    """
    from scrapers import ScraperRegistry

    choices: List[Dict[str, str]] = []
    for scraper in ScraperRegistry.get_by_scope("volume"):
        if not provides_volume_index(scraper):
            continue
        choices.append({
            "id": scraper.id,
            "display_name": getattr(scraper, "localized_display_name", "") or scraper.display_name,
            "kind": "index",
        })

    listed = {choice["id"] for choice in choices}
    for provider_id in UNIT_PROVIDERS:
        scraper = ScraperRegistry.get(provider_id)
        if not scraper or scraper.id in listed:
            continue
        choices.append({
            "id": scraper.id,
            "display_name": getattr(scraper, "localized_display_name", "") or scraper.display_name,
            "kind": "unit",
        })
    return choices


def cascade_rank(library_type: str, config: Optional[dict] = None) -> Dict[str, int]:
    """Rang de chaque fournisseur dans la cascade réglée par l'utilisateur."""
    if config is None:
        from config_manager import load_config

        config = load_config()
    slots = CASCADE_SLOTS.get(library_type) or CASCADE_SLOTS["Manga"]
    ranks: Dict[str, int] = {}
    for rank, key in enumerate(slots):
        provider_id = str(config.get(key) or "").strip().upper()
        if provider_id and provider_id != "NONE":
            ranks.setdefault(provider_id, rank)
    return ranks


def volume_providers(library_type: str = "Comic", *, config: Optional[dict] = None) -> list:
    """Fournisseurs de tomes, dans l'ordre de préférence de l'utilisateur.

    L'ordre décide de tout, puisque `fetch_index` garde le premier index qui
    couvre la série. Or `get_by_scope` trie par nom d'affichage, ce qui plaçait
    Bédéthèque avant ComicVine sur toute bibliothèque Comic : une homonymie
    franco-belge suffisait à faire écrire les tomes d'une autre œuvre, sans que
    ComicVine soit consulté, et au prix de cinquante pages HTML là où deux
    appels d'API auraient suffi. On suit donc la cascade de la modale Fournisseurs, celle qui
    sert déjà à l'enrichissement par série, plutôt que l'alphabet.

    Sauf pour les tomes manga : Manga-News passe devant sur une bibliothèque
    Manga, et sert de dernier recours sur une Comic (Flexible), après les
    comics — c'est le seul index qui y rende autre chose que des couvertures.
    La cascade série n'est pas touchée.
    """
    from scrapers import ScraperRegistry

    if config is None:
        from config_manager import load_config

        config = load_config()

    # `VOLUME_NO_MANGA_FALLBACK` — une bibliothèque « Comic (Flexible) » enchaîne
    # les fournisseurs comics puis les manga en repli. C'est utile à qui y range
    # les deux ; c'est du temps perdu et un risque d'homonymie à qui n'y range que
    # de la bande dessinée, et les journaux le montrent : MangaDex interrogé pour
    # « Gaston Lagaffe », à sa propre cadence, pour rien.
    comics_only = library_type == "ComicFlexible" and bool(
        config.get("VOLUME_NO_MANGA_FALLBACK", False)
    )

    ranks = cascade_rank(library_type, config)
    out = []
    for scraper in ScraperRegistry.get_by_scope("volume"):
        supported = getattr(scraper, "supported_types", set()) or set()
        if library_type in ("ComicFlexible", "") or not supported:
            if comics_only and supported and "Comic" not in supported:
                continue
            out.append(scraper)
        elif library_type in supported:
            out.append(scraper)

    forced = forced_volume_provider(config)
    if forced:
        picked = [s for s in out if s.id == forced]
        if picked:
            return picked
        if forced in UNIT_PROVIDERS:
            # Il répond à l'unité, pas à la série : il n'a aucun index à rendre,
            # et ce n'est pas un échec — `resolve_index` l'interroge tome par
            # tome. Reprendre la cascade ici irait contre le réglage, en
            # interrogeant précisément les fournisseurs qu'il écarte.
            return []
        # Le fournisseur imposé ne sait pas servir ce type de bibliothèque — ou
        # n'est pas installé. Le retenir quand même rendrait une liste vide, donc
        # un « aucun fournisseur ne connaît cette série » qui accuserait le
        # fournisseur au lieu du réglage. Un forçage ne doit pas non plus casser
        # les autres bibliothèques : la cascade reprend, en le disant.
        logging.info(
            "[Tomes] fournisseur imposé %s inutilisable pour une bibliothèque %s — cascade appliquée",
            forced,
            library_type or "?",
        )
    # Tri stable : à rang égal, l'ordre alphabétique du registre est conservé.
    # Un fournisseur imposé a déjà rendu plus haut, il n'est pas recalé.
    # Triplet (vague, préférence manga, rang de cascade) : même longueur partout,
    # Python 3 refuse de comparer des tuples de tailles différentes.
    def _rank(scraper):
        cascade = ranks.get(scraper.id, _UNRANKED)
        manga_lead = 0 if scraper.id == MANGA_VOLUME_LEAD else 1
        if library_type == "Manga":
            return (0, manga_lead, cascade)
        if library_type == "ComicFlexible":
            supported = getattr(scraper, "supported_types", set()) or set()
            # Vague comics d'abord, vague manga ensuite. Dans la seconde,
            # Manga-News passe devant MangaDex : le secours d'un manga rangé
            # ici doit rendre un titre, pas seulement une jaquette.
            wave = 0 if "Comic" in supported else 1
            return (wave, manga_lead, cascade)
        return (0, 1, cascade)

    return sorted(out, key=_rank)


def forced_id_for(scraper, forced_id: str, forced_provider: str = "") -> Optional[str]:
    """L'identifiant forcé, mais seulement pour le fournisseur auquel il appartient.

    Un identifiant du Champ Magique ne veut rien dire hors de son fournisseur :
    `30002` désigne une série AniList, et ComicVine l'accepterait volontiers
    comme numéro de volume — il rendrait l'index complet d'un run sans aucun
    rapport, que l'appariement écrirait tome par tome, verrous compris, sans
    que rien à l'écran ne le signale. On ne transmet donc l'identifiant qu'au
    fournisseur nommé, ou à celui que l'URL désigne d'elle-même.
    """
    raw = str(forced_id or "").strip()
    if not raw:
        return None
    if is_http_url(raw):
        # Une URL porte son fournisseur : c'est le domaine qui tranche, pas la
        # préférence enregistrée, qui peut être restée sur AUTO.
        return raw if detect_provider_from_url(raw) == scraper.id else None
    return raw if (forced_provider or "").strip().upper() == scraper.id else None


#: Balises qu'un résumé ne contient pas quand le fournisseur a fini son travail.
#: Une page coupée en cours de route en laisse le début dans la valeur — le cas
#: mesuré est `{"1": {"summary": '<div class="al'}}`. Écrit tel quel, ce
#: fragment est **verrouillé** par MetaKavita, donc épargné par la passe
#: suivante (`plan.py`) : il ne se corrige plus qu'à la main, tome par tome. Les
#: fournisseurs livrés rendent tous du texte (ComicVine passe par
#: `html_to_summary_text`), la liste ne vise donc que les pages tronquées et les
#: scrapers tiers approximatifs.
_MARKUP_RE = re.compile(
    r"<\s*/?\s*(?:div|span|p|br|a|img|ul|ol|li|table|tr|td|th|script|style|html|"
    r"head|body|section|article|header|footer|nav|form|iframe|strong|em|h[1-6])\b",
    re.IGNORECASE,
)

#: Part des unités de la série qu'un index doit couvrir pour clore la cascade à
#: lui seul. En dessous, il n'est pas jeté — ce qu'il porte reste prioritaire —
#: mais il est complété par le fournisseur suivant, comme `resolve_index` le
#: fait déjà pour un index sans texte. Un fournisseur en tête de cascade dont la
#: page est coupée après une entrée gagnait sinon la série entière, et celui qui
#: la connaissait vraiment n'était appelé zéro fois.
INDEX_MIN_COVERAGE = 0.34


def usable_index(index: Any, provider_id: str = "") -> Dict[str, Any]:
    """L'index débarrassé de ce qui n'est pas exploitable, ou `{}`.

    Deux rebuts, tous deux constatés sans toucher au dépôt puisque
    `CUSTOM_SCRAPERS.md` documente le chargement de scrapers tiers : un
    `fetch_volume_index` qui rend une chaîne — page d'erreur rendue telle
    quelle, `return` oublié — et une valeur qui n'est que du balisage rescapé
    d'une page tronquée. Le premier faisait lever `AttributeError` sur la série
    entière, sans repli sur le fournisseur suivant.
    """
    if not isinstance(index, dict):
        if index:
            logging.warning(
                "[Tomes] %s : index ignoré, %s reçu au lieu d'un dictionnaire",
                provider_id or "?",
                type(index).__name__,
            )
        return {}
    out: Dict[str, Any] = {}
    dropped = 0
    for key, payload in index.items():
        if not isinstance(payload, dict):
            dropped += 1
            continue
        clean = {
            field: value
            for field, value in payload.items()
            if not (isinstance(value, str) and _MARKUP_RE.search(value))
        }
        dropped += len(payload) - len(clean)
        if clean:
            out[key] = clean
    if dropped:
        logging.warning(
            "[Tomes] %s : %s valeur(s) écartée(s) de l'index (balisage ou entrée illisible)",
            provider_id or "?",
            dropped,
        )
    return out


def index_coverage(index: Dict[str, Any], units: List[Dict[str, Any]]) -> float:
    """Part des unités de la série que cet index sait renseigner."""
    from services.volume_enrichment.matching import number_key, unit_number

    wanted = {
        key
        for key in (unit_number(u) for u in units if not u.get("is_special"))
        if key is not None
    }
    if not wanted:
        return 1.0
    known = {key for key in (number_key(raw) for raw in index) if key is not None}
    return len(wanted & known) / len(wanted)


def _covers_enough(index: Dict[str, Any], units: Optional[List[Dict[str, Any]]]) -> bool:
    """Vrai si l'index en sait assez pour qu'on arrête d'interroger la cascade."""
    if not units:
        # Appelant qui ne passe pas la série (outils, aperçu d'un seul tome) :
        # il n'y a rien à quoi comparer la couverture.
        return True
    return index_coverage(index, units) >= INDEX_MIN_COVERAGE


def fetch_index(
    series_name: str,
    library_type: str = "Comic",
    *,
    forced_id: str = "",
    forced_provider: str = "",
    existing_metadata: Optional[Dict[str, Any]] = None,
    providers: Optional[list] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    config: Optional[dict] = None,
    units: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Le premier index de la cascade qui couvre la série. Rend `(id, index)`.

    Un fournisseur qui échoue ne fait pas échouer la série : on passe au
    suivant. Rendre `("", {})` signifie « personne ne connaît cette série », ce
    qui est un résultat, pas une erreur.

    Un index qui ne couvre qu'une part dérisoire de la série ne clôt plus la
    cascade : il est gardé, mais complété par le fournisseur suivant, dont il
    reste prioritaire champ par champ. Un index qui ne porte que des couvertures
    non plus — MangaDex les rend pour tout le manga, et s'en contenter
    empêcherait Manga-News (titres, résumés, ISBN) d'être jamais consulté.
    Sans `units`, la couverture n'est pas jugée et le premier index **textuel**
    non vide gagne.
    """
    if providers is None:
        providers = volume_providers(library_type, config=config)
    partial_provider, partial_index = "", {}
    consulted: List[str] = []
    for scraper in providers:
        if not provides_volume_index(scraper):
            continue
        consulted.append(getattr(scraper, "id", "?"))
        if should_cancel and should_cancel():
            # Un index Bédéthèque dure deux minutes : sans ce contrôle, une
            # annulation ne se verrait qu'une fois la série entière parcourue.
            break
        try:
            throttle_provider(scraper)
            index = scraper.fetch_volume_index(
                series_name,
                library_type=library_type,
                series_id=forced_id_for(scraper, forced_id, forced_provider),
                existing_metadata=existing_metadata or {},
            )
        except Exception as exc:
            logging.warning(
                "[Tomes] %s : index indisponible pour « %s » (%s)",
                scraper.id,
                series_name,
                safe_exc_str(exc),
            )
            continue
        index = usable_index(index, getattr(scraper, "id", ""))
        if not index:
            continue
        if partial_index:
            provider_id = f"{partial_provider}+{scraper.id}"
            index = merge_indexes(partial_index, index)
        else:
            provider_id = scraper.id
        if _covers_enough(index, units) and not _is_cover_only(index):
            return provider_id, index
        logging.info(
            "[Tomes] %s : index partiel pour « %s » (%.0f %% des tomes) — on complète",
            provider_id,
            series_name,
            index_coverage(index, units or []) * 100,
        )
        partial_provider, partial_index = provider_id, index
    if not partial_index:
        # Une ligne, et une seule : à la maille du fournisseur, une passe de
        # bibliothèque en produirait cinq par série. Sans elle, un échec de
        # cascade ne laissait aucune trace — impossible de distinguer « ComicVine
        # a été consulté et n'a rien rendu » de « ComicVine n'a pas été consulté »,
        # ce qui est précisément la question qu'on se pose devant un aperçu vide.
        logging.info(
            "[Tomes] aucun index pour « %s » — fournisseur(s) consulté(s) : %s",
            series_name,
            ", ".join(consulted) or "aucun",
        )
    return partial_provider, partial_index


#: Champs qui font d'un index une vraie source de métadonnées. Un index qui
#: n'en porte aucun ne propose que des couvertures — c'est le cas de MangaDex.
TEXT_FIELDS = ("title", "summary", "release_date", "isbn")


def _is_cover_only(index: Any) -> bool:
    # Le type est revérifié ici : `resolve_index` n'est pas le seul appelant, et
    # un index qui n'est pas un dictionnaire faisait lever `AttributeError` pour
    # la série entière au lieu de rendre la main au fournisseur suivant.
    if not isinstance(index, dict):
        return False
    return bool(index) and not any(
        field in payload
        for payload in index.values()
        if isinstance(payload, dict)
        for field in TEXT_FIELDS
    )


def merge_indexes(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    """Complète `primary` avec `secondary`, sans jamais l'écraser."""
    merged = {key: dict(payload) for key, payload in primary.items()}
    for key, payload in (secondary or {}).items():
        merged.setdefault(key, {}).update(
            {k: v for k, v in payload.items() if k not in merged.get(key, {})}
        )
    return merged


def resolve_index(
    series_name: str,
    units: List[Dict[str, Any]],
    *,
    library_type: str,
    forced_id: str = "",
    forced_provider: str = "",
    existing_metadata: Optional[Dict[str, Any]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    experimental: bool = False,
    config: Optional[dict] = None,
) -> Tuple[str, Dict[str, Any]]:
    """L'index le plus complet qu'on puisse bâtir pour une série.

    L'index par série passe d'abord, parce qu'il coûte un appel là où l'ISBN en
    coûte un par tome. Mais il ne suffit pas toujours : MangaDex ne connaît que
    les couvertures, et Manga-News s'arrête à quarante tomes. S'en contenter
    priverait le reste des titres et résumés, alors que leurs ISBN sont là, dans
    Kavita, et que la cascade sait les lire. Les deux se complètent donc au lieu
    de s'exclure — l'index par série reste prioritaire champ par champ.

    Un fournisseur à l'unité imposé (`VOLUME_PROVIDER`) restreint les deux
    cascades par tome à lui seul, et supprime l'index : il n'en rend pas, et
    interroger quand même ceux qui en rendent irait contre le réglage. S'il sait
    chercher par titre et numéro, l'imposer suffit à ouvrir ce chemin :
    `VOLUME_ENRICH_EXPERIMENTAL` garde la cascade automatique, il ne barre plus
    un fournisseur nommé à la main.
    """
    from services.volume_enrichment.matching import matchable_numbers

    # Un fournisseur à l'unité imposé n'a pas d'index à rendre : `volume_providers`
    # rend une liste vide pour lui, et c'est ici que la conséquence se lit — les
    # cascades par tome ne consultent plus que lui.
    unit_only = forced_unit_provider(config)
    unit_ids = [unit_only] if unit_only else None

    # `units` vide veut dire « l'appelant ne dit rien de la série », pas « la série
    # n'a pas de numéro » — c'est déjà la convention de `_covers_enough`, que des
    # outils et l'aperçu d'un seul tome empruntent. Ne rien savoir ne doit pas
    # fermer l'index par série.
    if units and not matchable_numbers(units):
        # Aucun numéro de tome : un index par série est numéroté, il n'a rien à
        # quoi s'apparier ici, et le demander coûterait la recherche entière pour
        # un résultat nul. L'ISBN, lui, désigne l'album sans numéro — c'est le
        # seul chemin d'un one-shot, et il ne coûte un appel que pour les unités
        # qui en portent un. La recherche titre + numéro est hors jeu : il n'y a
        # pas de numéro à chercher.
        by_isbn = fetch_by_isbn(
            units,
            library_type=library_type,
            provider_ids=unit_ids,
            config=config,
            should_cancel=should_cancel,
        )
        return ("ISBN", by_isbn) if by_isbn else ("", {})

    provider, index = "", {}
    if not unit_only:
        provider, index = fetch_index(
            series_name,
            library_type=library_type,
            forced_id=forced_id,
            forced_provider=forced_provider,
            existing_metadata=existing_metadata,
            should_cancel=should_cancel,
            config=config,
            units=units,
        )
        # Un index partiel est traité comme un index sans texte : la cascade ISBN
        # peut le compléter, et elle ne coûte un appel que sur les tomes qui portent
        # un ISBN dans Kavita — aucun, sur une bibliothèque de comics.
        if index and not _is_cover_only(index) and _covers_enough(index, units):
            return provider, index
        if should_cancel and should_cancel():
            return provider, index

    by_isbn = fetch_by_isbn(
        units,
        library_type=library_type,
        provider_ids=unit_ids,
        config=config,
        should_cancel=should_cancel,
    )
    if by_isbn:
        if not index:
            return "ISBN", by_isbn
        return f"{provider}+ISBN", merge_indexes(index, by_isbn)

    if should_cancel and should_cancel():
        return provider, index

    if unit_only and unit_only not in TITLE_VOLUME_PROVIDERS:
        # Un fournisseur à l'unité imposé qui n'a rien rendu, et plus rien à
        # tenter : Open Library et Hardcover n'identifient un tome que par son
        # ISBN, et sans ISBN dans Kavita ils n'ont aucune prise. C'est le réglage
        # qui ferme la porte, pas le fournisseur ni la série — et l'aperçu, lui,
        # affichera « aucun fournisseur ne connaît cette série ».
        logging.info(
            "[Tomes] aucun ISBN exploitable pour « %s », et %s n'identifie un tome que par "
            "son ISBN — renseignez les ISBN dans Kavita, imposez un fournisseur qui cherche "
            "par titre + numéro (%s), ou laissez la cascade décider",
            series_name,
            unit_only,
            ", ".join(TITLE_VOLUME_PROVIDERS),
        )
        return provider, index

    if not experimental:
        if not unit_only:
            return provider, index
        # Imposer un fournisseur qui sait chercher par titre et numéro **est**
        # l'acte explicite que l'interrupteur expérimental réclame : il est
        # nommé, il est seul consulté, et rien d'autre ne peut plus répondre.
        # Exiger en plus l'interrupteur rendait un aperçu vide au geste même qui
        # demandait la recherche — le cas de tous les mangas sans ISBN, où c'est
        # le seul chemin qui rende un titre et un résumé.
        logging.info(
            "[Tomes] « %s » : %s imposé pour les tomes — recherche par titre + numéro, "
            "vérifiée titre et numéro chez le fournisseur",
            series_name,
            unit_only,
        )

    # Dernier recours : la recherche par titre et numéro. Elle ne se déclenche
    # que si tout le reste a échoué à produire du texte, et seulement quand
    # l'utilisateur l'a demandée — interrupteur coché, ou fournisseur imposé.
    by_title = fetch_by_title_volume(
        series_name,
        units,
        library_type=library_type,
        provider_ids=unit_ids,
        should_cancel=should_cancel,
    )
    if not by_title:
        return provider, index
    if not index:
        return "TITRE", by_title
    return f"{provider}+TITRE", merge_indexes(index, by_title)


def fetch_by_title_volume(
    series_name: str,
    units: List[Dict[str, Any]],
    *,
    library_type: str = "Manga",
    provider_ids: Optional[List[str]] = None,
    limit: int = TITLE_VOLUME_LIMIT,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Index bâti tome par tome, par recherche « titre de série + numéro ».

    Expérimental, et pour une raison précise : c'est le seul chemin de tout le
    module qui ne s'appuie sur aucun identifiant. Quand Manga-News n'a pas de
    fiche et que Kavita n'a pas d'ISBN, il ne reste que la recherche — avec ce
    qu'elle comporte de risque, d'où la vérification du titre et du numéro
    côté fournisseur, et l'interrupteur côté configuration.
    """
    from scrapers import ScraperRegistry
    from services.volume_enrichment.matching import unit_number

    index: Dict[str, Dict[str, Any]] = {}
    wanted = list(provider_ids or TITLE_VOLUME_PROVIDERS)
    scrapers = [
        s
        for s in (ScraperRegistry.get(pid) for pid in wanted)
        if s and callable(getattr(s, "fetch_volume", None))
    ]
    if not scrapers or not series_name:
        return index

    for unit in units[:limit]:
        if should_cancel and should_cancel():
            break
        key = unit_number(unit)
        if key is None or key in index or unit.get("is_special"):
            continue
        for scraper in scrapers:
            try:
                throttle_provider(scraper)
                found = scraper.fetch_volume(
                    series_name, volume_number=key, library_type=library_type
                )
            except Exception as exc:
                logging.debug(
                    "[Tomes] %s tome %s via %s : %s",
                    series_name, key, scraper.id, safe_exc_str(exc),
                )
                continue
            if not found:
                continue
            payload = {
                "title": (found.get("title") or "").strip(),
                "summary": (found.get("summary") or "").strip(),
                "release_date": found.get("release_date") or found.get("year") or "",
                "isbn": found.get("isbn") or "",
                "cover_url": found.get("cover_url") or "",
            }
            payload = {k: v for k, v in payload.items() if v}
            if payload:
                index[key] = payload
            break
    return index


def credits_fetcher(provider_id: str) -> Optional[Callable[[str], Optional[Dict[str, List[str]]]]]:
    """Passe crédits du fournisseur, cadencée. Un appel réseau par album.

    C'est le seul chemin de la fonctionnalité qui coûte un appel par unité :
    la cadence est portée ici plutôt que chez l'appelant, qui n'a pas le
    `rate_limit` du scraper sous la main.
    """
    from scrapers import ScraperRegistry

    scraper = ScraperRegistry.get(provider_id) if provider_id else None
    fetcher = getattr(scraper, "fetch_volume_credits", None)
    if not callable(fetcher):
        return None

    def throttled(provider_ref):
        throttle_provider(scraper)
        return fetcher(provider_ref)

    return throttled


def fetch_by_isbn(
    units: List[Dict[str, Any]],
    *,
    library_type: str = "Manga",
    provider_ids: Optional[List[str]] = None,
    limit: int = 200,
    config: Optional[dict] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Index bâti tome par tome, à partir des ISBN déjà présents dans Kavita.

    Complète un index qui n'a pas tout dit — couvertures seules, plafond
    Manga-News, série absente du catalogue VF. Coûte un appel par tome, d'où
    le plafond.

    `should_cancel` est testé à chaque tome, comme dans `fetch_index` et
    `fetch_by_title_volume` : quand l'index n'a pas clôturé, cette cascade
    prend le relais, et trois fournisseurs cadencés à une seconde par appel
    tiennent jusqu'à onze minutes au plafond — pendant lesquelles l'annulation
    répondait pourtant « annulée », `/status` disait `running` et aucune
    nouvelle passe n'était acceptée.
    """
    from scrapers import ScraperRegistry
    from services.volume_enrichment.matching import unit_isbn, unit_key

    index: Dict[str, Dict[str, Any]] = {}
    wanted = list(provider_ids or ISBN_PROVIDERS)
    scrapers = [s for s in (ScraperRegistry.get(pid) for pid in wanted) if s]
    if provider_ids is None:
        # Un appelant qui nomme lui-même ses fournisseurs impose son ordre ;
        # sinon la préférence de l'utilisateur tranche, comme pour l'index.
        ranks = cascade_rank(library_type, config)
        scrapers.sort(key=lambda s: ranks.get(s.id, _UNRANKED))
    if not scrapers:
        return index

    for unit in units[:limit]:
        if should_cancel and should_cancel():
            break
        isbn = unit_isbn(unit)
        # `unit_key` et non `unit_number` : une unité sans numéro — un one-shot —
        # s'indexe sur son propre ISBN. C'est le seul chemin qui lui reste, et
        # c'est le plus sûr des deux, l'ISBN désignant une édition précise.
        key = unit_key(unit)
        if not isbn or key is None or key in index or unit.get("is_special"):
            continue
        for scraper in scrapers:
            try:
                throttle_provider(scraper)
                found = scraper.fetch(
                    isbn,
                    library_type=library_type,
                    existing_metadata={"isbn": isbn},
                )
            except Exception as exc:
                logging.debug("[Tomes] ISBN %s via %s : %s", isbn, scraper.id, safe_exc_str(exc))
                continue
            if not found:
                continue
            payload = {
                "title": (found.get("title") or "").strip(),
                "summary": (found.get("summary") or "").strip(),
                "release_date": found.get("release_date") or found.get("year") or "",
                "isbn": isbn,
                "cover_url": found.get("cover_url") or "",
            }
            payload = {k: v for k, v in payload.items() if v}
            if payload:
                index[key] = payload
            break
    return index
