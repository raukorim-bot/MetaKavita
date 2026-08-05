"""
Non-régression : le rendu HTML du CHANGELOG doit échapper `<script>` etc.
Sinon innerHTML dans la modale tronque tout le document après la balise.
"""
from services.changelog_service import _format_inline_markdown, get_full_changelog_html


def test_format_escapes_script_tags_inside_backticks():
    out = _format_inline_markdown("seven plain `<script>` files")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<code" in out


def test_format_escapes_raw_angle_brackets():
    out = _format_inline_markdown("compare a < b && c > d")
    assert "< b" not in out
    assert "&lt;" in out
    assert "&gt;" in out


def test_format_renders_https_markdown_links():
    out = _format_inline_markdown(
        "Download [chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)."
    )
    assert 'href="https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip"' in out
    assert "chrome.zip</a>" in out
    assert 'target="_blank"' in out


def test_format_rejects_javascript_markdown_links():
    out = _format_inline_markdown("[x](javascript:alert(1))")
    assert "<a " not in out
    assert "javascript:alert(1)" in out


def test_full_changelog_html_does_not_embed_raw_script_tags():
    """Le CHANGELOG réel mentionne `<script>` (modularisation frontend)."""
    html_out = get_full_changelog_html()
    assert html_out
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "1.5.8" in html_out or "1.5.7" in html_out
