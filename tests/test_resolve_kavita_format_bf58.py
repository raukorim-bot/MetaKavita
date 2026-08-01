"""BF58 — format enum: exact tokens + word split, no substring false positives."""
import pytest

from kavita_constants import resolve_kavita_format_enum

# Kavita Series format enum
_MANGA, _COMIC, _NOVEL, _WEBTOON = 1, 2, 3, 4


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("manga", _MANGA),
        ("comic", _COMIC),
        ("webtoon", _WEBTOON),
        ("book", _NOVEL),
        ("bd", _COMIC),
        ("manhwa", _WEBTOON),
        ("COMIC BOOK", _COMIC),  # was Novel via substring BOOK
        ("Light Novel", _NOVEL),
        ("Manhwa (KR)", _WEBTOON),
        ("graphic novel", _NOVEL),
        ("hardcover book", _NOVEL),
        ("American Comic", _COMIC),
        ("Japanese Manga", _MANGA),
        ("MUST READ", None),  # was Comic via substring US
        ("", None),
        (None, None),
    ],
)
def test_resolve_kavita_format_enum(raw, expected):
    assert resolve_kavita_format_enum(raw) == expected
