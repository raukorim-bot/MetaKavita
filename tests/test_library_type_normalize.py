"""
C35 — `_normalize_library_type` doit distinguer Comic (ID 1) de Comic Flexible (ID 5).
"""
from kavita_api import KavitaAPI


def test_normalize_comic_strict_id_1():
    assert KavitaAPI._normalize_library_type(1) == "Comic"
    assert KavitaAPI._normalize_library_type("1") == "Comic"
    assert KavitaAPI._normalize_library_type("comic") == "Comic"
    assert KavitaAPI._normalize_library_type("Comics") == "Comic"


def test_normalize_comic_flexible_id_5():
    assert KavitaAPI._normalize_library_type(5) == "ComicFlexible"
    assert KavitaAPI._normalize_library_type("5") == "ComicFlexible"
    assert KavitaAPI._normalize_library_type("Comic (Flexible)") == "ComicFlexible"
    assert KavitaAPI._normalize_library_type("comicflexible") == "ComicFlexible"
    assert KavitaAPI._normalize_library_type("comic_flexible") == "ComicFlexible"


def test_normalize_book_and_manga():
    assert KavitaAPI._normalize_library_type(2) == "Book"
    assert KavitaAPI._normalize_library_type(3) == "Book"
    assert KavitaAPI._normalize_library_type(0) == "Manga"
    assert KavitaAPI._normalize_library_type(None) == "Manga"
    assert KavitaAPI._normalize_library_type("manga") == "Manga"
