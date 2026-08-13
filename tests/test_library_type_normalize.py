"""
`_normalize_library_type` : l'identifiant numérique fait foi, et il ne dit pas
ce qu'on croit.

Le piège est que `LibraryType.cs` donne à ses membres des descriptions qui ne
concordent pas avec leurs noms : c'est `Comic = 1` qui s'appelle
« Comic (Flexible) » dans l'interface de Kavita, et `ComicVine = 5` qui s'appelle
simplement « Comic ». MetaKavita lisait les identifiants dans l'autre sens, et
rangeait en plus Image (3) avec les livres et LightNovel (4) avec les mangas.

Ces tests encodaient l'ancienne convention (1 → Comic strict, 5 → flexible,
3 → Book) : ils passaient en décrivant un comportement faux. Ils décrivent
maintenant l'enum réel, vérifié sur Kareadita/Kavita develop (0.9.0.20).

Ce que la correspondance change concrètement : le type interne choisit la
cascade de fournisseurs. Une bibliothèque d'images ou de webtoons partait chez
Google Books, et un catalogue de light novels était traité comme du manga.
"""
from kavita_api import KavitaAPI


def test_the_id_1_is_the_flexible_comic_library_despite_its_member_name():
    """`Comic = 1`, description « Comic (Flexible) » : parsing souple."""
    assert KavitaAPI._normalize_library_type(1) == "ComicFlexible"
    assert KavitaAPI._normalize_library_type("1") == "ComicFlexible"


def test_the_id_5_is_the_strict_comic_library_despite_its_description():
    """`ComicVine = 5`, description « Comic » : parsing strict façon Comic Vine."""
    assert KavitaAPI._normalize_library_type(5) == "Comic"
    assert KavitaAPI._normalize_library_type("5") == "Comic"


def test_an_image_library_follows_the_manga_cascade_not_the_book_one():
    """`Image = 3` : c'est la bibliothèque des webtoons et des scans. La classer
    en Book faisait interroger Google Books pour des planches sans ISBN."""
    assert KavitaAPI._normalize_library_type(3) == "Manga"


def test_a_light_novel_library_follows_the_book_cascade():
    """`LightNovel = 4` : un light novel a un éditeur, un ISBN et un auteur de
    roman. Le traiter comme du manga lui refusait la cascade des livres."""
    assert KavitaAPI._normalize_library_type(4) == "Book"


def test_manga_and_book_ids_are_unchanged():
    assert KavitaAPI._normalize_library_type(0) == "Manga"
    assert KavitaAPI._normalize_library_type(2) == "Book"


def test_unknown_or_missing_type_falls_back_to_manga():
    assert KavitaAPI._normalize_library_type(None) == "Manga"
    assert KavitaAPI._normalize_library_type(99) == "Manga"
    assert KavitaAPI._normalize_library_type("") == "Manga"


class TestTextualFallback:
    """Repli pour les `LibraryDto` sérialisés avec le nom du membre plutôt qu'avec
    sa valeur. Il doit lui aussi distinguer « Comic (Flexible) » de « Comic »."""

    def test_flexible_label_maps_to_flexible(self):
        assert KavitaAPI._normalize_library_type("Comic (Flexible)") == "ComicFlexible"
        assert KavitaAPI._normalize_library_type("comicflexible") == "ComicFlexible"
        assert KavitaAPI._normalize_library_type("comic_flexible") == "ComicFlexible"

    def test_bare_comic_label_maps_to_strict_comic(self):
        assert KavitaAPI._normalize_library_type("comic") == "Comic"
        assert KavitaAPI._normalize_library_type("Comics") == "Comic"
        assert KavitaAPI._normalize_library_type("ComicVine") == "Comic"

    def test_novel_and_book_labels_map_to_book(self):
        assert KavitaAPI._normalize_library_type("Light Novel") == "Book"
        assert KavitaAPI._normalize_library_type("Book") == "Book"

    def test_manga_and_image_labels_map_to_manga(self):
        assert KavitaAPI._normalize_library_type("manga") == "Manga"
        assert KavitaAPI._normalize_library_type("Image") == "Manga"
