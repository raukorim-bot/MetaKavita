"""
Non-régression : migration de MangaDex, MangaUpdates, Manga-News et Shikimori vers la matrice
unifiée `score_candidate()` (voir CODE_REVIEW.md section 6 et DEVELOPER.md section 11.B). Ces
4 scrapers avaient chacun leur propre heuristique titre-seul, sans jamais comparer l'auteur — ce
qui désactivait complètement la protection anti-homonyme pour eux.

Ces tests ne couvrent pas le réseau (recherche/HTTP), déjà indirectement couvert par
`debug/debug_scoring.py` pour la matrice elle-même : ils vérifient que le "candidate builder"
de chaque scraper produit bien un dictionnaire `staff` dans la forme attendue par
`score_candidate()` (`[{"role": ..., "node": {"name": {"full": ...}}}]`), condition nécessaire
et suffisante pour que la protection anti-homonyme fonctionne réellement une fois branchée.
"""
from scrapers.mangadex import MangaDexScraper
from scrapers.mangaupdates import MangaUpdatesScraper
from scrapers.manganews import MangaNewsScraper
from scrapers.shikimori import ShikimoriScraper
from scrapers.utils import score_candidate


def _staff_names_by_role(staff, role):
    return {
        s["node"]["name"]["full"]
        for s in staff
        if s.get("role") == role
    }


class TestMangaDexCandidateBuilder:
    def _fake_manga_data(self, with_author=True):
        return {
            "id": "abc-123",
            "attributes": {
                "title": {"en": "Chainsaw Man"},
                "altTitles": [{"ja": "チェンソーマン"}],
                "description": {"en": "A long enough description to be meaningful for testing."},
                "year": 2018,
                "status": "ongoing",
                "contentRating": "safe",
                "originalLanguage": "ja",
                "tags": [],
            },
            "relationships": (
                [
                    {"type": "author", "attributes": {"name": "Tatsuki Fujimoto"}},
                    {"type": "artist", "attributes": {"name": "Tatsuki Fujimoto"}},
                    {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}},
                ]
                if with_author
                else []
            ),
        }

    def test_build_candidate_extracts_staff_from_relationships(self):
        scraper = MangaDexScraper()
        candidate = scraper._build_candidate(self._fake_manga_data(), target_lang="fr")

        assert candidate is not None
        assert candidate["title"] == "Chainsaw Man"
        assert "Tatsuki Fujimoto" in _staff_names_by_role(candidate["staff"], "Story")
        assert "Tatsuki Fujimoto" in _staff_names_by_role(candidate["staff"], "Art")
        assert candidate["cover_url"] == "https://uploads.mangadex.org/covers/abc-123/cover.jpg"

    def test_build_candidate_returns_none_without_title(self):
        scraper = MangaDexScraper()
        data = self._fake_manga_data()
        data["attributes"]["title"] = {}
        assert scraper._build_candidate(data, target_lang="fr") is None

    def test_candidate_staff_enables_anti_homonym_penalty_in_score_candidate(self):
        """Preuve que le staff construit par _build_candidate() est bien utilisable par
        score_candidate() : un candidat au titre identique mais d'un autre auteur doit être
        pénalisé (score_candidate catégorie A), ce qui était impossible avant la migration
        puisque le staff n'était jamais comparé du tout."""
        scraper = MangaDexScraper()
        candidate = scraper._build_candidate(self._fake_manga_data(), target_lang="fr")

        matching_author_score = score_candidate(
            candidate, "Chainsaw Man", {"authors": ["Tatsuki Fujimoto"]}
        )
        wrong_author_score = score_candidate(
            candidate, "Chainsaw Man", {"authors": ["Naoki Urasawa"]}
        )

        assert matching_author_score > wrong_author_score
        assert wrong_author_score < 0.60


class TestMangaUpdatesCandidateBuilder:
    def _fake_search_record(self):
        # Même forme que /v1/series/search ET /v1/series/{id} (voir commentaire dans
        # mangaupdates.py::fetch()).
        return {
            "series_id": 42,
            "title": "One Piece",
            "description": "A long enough description for testing purposes here.",
            "associated": [{"title": "OP"}],
            "authors": [
                {"name": "Eiichiro Oda", "type": "Story & Art"},
            ],
            "genres": [{"genre": "Action"}],
            "publishers": [{"publisher_name": "Shueisha", "type": "Original"}],
            "year": "1997",
            "completed": False,
            "type": "Manga",
        }

    def test_parse_series_record_builds_staff_from_authors(self):
        scraper = MangaUpdatesScraper()
        candidate = scraper._parse_series_record(self._fake_search_record(), pub_pref="LOCALIZED")

        assert candidate is not None
        assert candidate["title"] == "One Piece"
        assert "Eiichiro Oda" in _staff_names_by_role(candidate["staff"], "Story")

    def test_hit_title_can_be_appended_to_alternative_titles(self):
        """Reproduit le comportement de fetch() : hit_title doit pouvoir s'ajouter à
        alternative_titles sans planter (la clé doit toujours être une liste)."""
        scraper = MangaUpdatesScraper()
        candidate = scraper._parse_series_record(self._fake_search_record(), pub_pref="LOCALIZED")

        assert isinstance(candidate["alternative_titles"], list)
        candidate["alternative_titles"].append("One Piece (Search Hit)")
        assert "One Piece (Search Hit)" in candidate["alternative_titles"]


class TestMangaNewsCandidateBuilder:
    def _fake_html(self):
        return """
        <html><body>
            <h1 class="entry-page-title">One Piece</h1>
            <li class="book-by"><a>Eiichiro Oda</a></li>
            <li class="book-by2"><a>Eiichiro Oda</a></li>
            <div id="summary"><div class="bigsize">Un resume suffisamment long pour les tests.</div></div>
        </body></html>
        """

    def test_parse_html_page_builds_staff_for_score_candidate(self):
        scraper = MangaNewsScraper()
        candidate = scraper._parse_html_page(self._fake_html(), "https://www.manga-news.com/index.php/serie/one-piece")

        assert candidate is not None
        assert candidate["title"] == "One Piece"
        assert "Eiichiro Oda" in _staff_names_by_role(candidate["staff"], "Story")
        assert "Eiichiro Oda" in _staff_names_by_role(candidate["staff"], "Art")


class TestShikimoriCandidateBuilder:
    def test_parse_record_builds_staff_from_roles_endpoint(self, mocker):
        """_parse_shikimori_record() fait un appel HTTP séparé vers /roles pour le staff : on
        le mocke pour vérifier que le staff qui en résulte est bien dans la forme attendue par
        score_candidate(), sans dépendre du réseau."""
        scraper = ShikimoriScraper()

        fake_roles_response = mocker.Mock()
        fake_roles_response.status_code = 200
        fake_roles_response.json.return_value = [
            {"person": {"name": "Eiichiro Oda"}, "roles": ["Story & Art"]},
        ]
        mocker.patch("scrapers.shikimori.requests.get", return_value=fake_roles_response)

        data = {
            "id": 1,
            "name": "One Piece",
            "description": "Resume suffisant pour les tests.",
            "status": "released",
            "kind": "manga",
            "genres": [{"name": "Action"}],
            "publishers": [{"name": "Shueisha"}],
        }

        candidate = scraper._parse_shikimori_record(data, headers={})

        assert candidate is not None
        assert "Eiichiro Oda" in _staff_names_by_role(candidate["staff"], "Story")
        assert "Eiichiro Oda" in _staff_names_by_role(candidate["staff"], "Art")
