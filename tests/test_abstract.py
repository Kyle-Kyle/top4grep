import unittest
from requests import RequestException
from unittest.mock import patch

from bs4 import BeautifulSoup
from top4grep.abstract import (
    AbstractCCS,
    extract_abstract_from_pdf_text,
    extract_doi,
    find_pdf_url_in_soup,
    get_openalex_abstract_for_title,
    get_openalex_abstract,
    get_semantic_scholar_abstract_for_title,
    normalize_abstract,
    normalize_source_url,
    normalize_title_key,
    reconstruct_abstract,
)


class AbstractTests(unittest.TestCase):
    def test_extract_doi_from_url(self):
        doi = extract_doi("https://doi.org/10.1145/3576915.3616615")
        self.assertEqual(doi, "10.1145/3576915.3616615")

    def test_reconstruct_openalex_abstract(self):
        text = reconstruct_abstract(
            {
                "hello": [0],
                "world": [1],
                "again": [2],
            }
        )
        self.assertEqual(text, "hello world again")

    def test_normalize_abstract_collapses_whitespace(self):
        text = normalize_abstract("First line\n\n  Second   line  ")
        self.assertEqual(text, "First line\nSecond line")

    def test_normalize_abstract_unescapes_html_entities(self):
        text = normalize_abstract("&quot;Quoted&quot;  text")
        self.assertEqual(text, '"Quoted" text')

    def test_normalize_title_key_ignores_entities_and_punctuation(self):
        key = normalize_title_key('&quot;AttackGNN&quot;: Red-Teaming GNNs!')
        self.assertEqual(key, "attackgnnredteaminggnns")

    def test_normalize_title_key_strips_html_markup_and_diacritics(self):
        key = normalize_title_key("<i>Avara:</i> Voge\u0308le and \u03bcCFI")
        self.assertEqual(key, "avaravogeleandcfi")

    def test_extract_abstract_from_pdf_text(self):
        text = extract_abstract_from_pdf_text(
            "Paper Title\nAuthors\nAbstract\nThis is the abstract.\n1 Introduction\nBody"
        )
        self.assertEqual(text, "This is the abstract.")

    def test_find_pdf_url_in_soup_prefers_pdf_links(self):
        soup = BeautifulSoup(
            '<html><head><meta name="citation_pdf_url" content="/paper.pdf"></head><body></body></html>',
            "html.parser",
        )

        self.assertEqual(
            find_pdf_url_in_soup("https://example.com/paper", soup),
            "https://example.com/paper.pdf",
        )

    def test_normalize_source_url_rewrites_legacy_ndss_pdf_host(self):
        self.assertEqual(
            normalize_source_url(
                "http://wp.internetsociety.org/ndss/wp-content/uploads/sites/25/2017/09/paper.pdf"
            ),
            "https://www.ndss-symposium.org/wp-content/uploads/2017/09/paper.pdf",
        )

    def test_ccs_falls_back_to_non_boilerplate_meta_description(self):
        soup = BeautifulSoup(
            '<html><head><meta property="og:description" content="A real page summary."></head></html>',
            "html.parser",
        )
        with patch("top4grep.abstract.resolve_doi", return_value=""), \
             patch("top4grep.abstract.load_publisher_soup", return_value=soup):
            text = AbstractCCS().get_abstract_from_publisher("https://example.com/paper", [])

        self.assertEqual(text, "A real page summary.")

    @patch("top4grep.abstract.cached_get_json", side_effect=RequestException("dns failed"))
    def test_openalex_request_errors_return_empty_abstract(self, _cached_get_json):
        self.assertEqual(get_openalex_abstract("10.1145/3658644.3670278"), "")

    @patch("top4grep.abstract.cached_get_json")
    def test_openalex_title_search_returns_exact_title_match(self, cached_get_json):
        cached_get_json.return_value = {
            "results": [
                {
                    "display_name": "AttackGNN: Red-Teaming GNNs in Hardware Security Using Reinforcement Learning",
                    "abstract_inverted_index": {
                        "hello": [0],
                        "world": [1],
                    },
                }
            ]
        }

        text = get_openalex_abstract_for_title(
            "AttackGNN: Red-Teaming GNNs in Hardware Security Using Reinforcement Learning"
        )

        self.assertEqual(text, "hello world")

    @patch("top4grep.abstract.cached_get_json")
    def test_semantic_scholar_title_search_returns_exact_title_match(self, cached_get_json):
        cached_get_json.return_value = {
            "data": [
                {
                    "title": "Avara: A Uniform Evaluation System for Perceptibility Analysis Against Adversarial Object Evasion Attacks",
                    "authors": [{"name": "Xinyao Ma"}],
                    "abstract": "Semantic Scholar abstract",
                }
            ]
        }

        text = get_semantic_scholar_abstract_for_title(
            "Avara: A Uniform Evaluation System for Perceptibility Analysis Against Adversarial Object Evasion Attacks.",
            ["Xinyao Ma"],
        )

        self.assertEqual(text, "Semantic Scholar abstract")

    @patch("top4grep.abstract.load_publisher_soup")
    @patch("top4grep.abstract.get_openalex_abstract")
    def test_ccs_doi_urls_use_openalex_before_publisher_html(self, get_openalex_abstract, load_publisher_soup):
        get_openalex_abstract.return_value = "abstract from openalex"

        text = AbstractCCS().get_abstract_from_publisher("https://doi.org/10.1145/3658644.3670278", [])

        self.assertEqual(text, "abstract from openalex")
        load_publisher_soup.assert_not_called()
        get_openalex_abstract.assert_called_once_with("10.1145/3658644.3670278")

    @patch("top4grep.abstract.load_publisher_soup")
    @patch("top4grep.abstract.get_openalex_abstract")
    def test_ccs_falls_back_to_publisher_html_when_openalex_is_empty(self, get_openalex_abstract, load_publisher_soup):
        get_openalex_abstract.return_value = ""
        load_publisher_soup.return_value.find.return_value.get_text.return_value = "publisher abstract"

        text = AbstractCCS().get_abstract_from_publisher("https://doi.org/10.1145/3658644.3670278", [])

        self.assertEqual(text, "publisher abstract")
        load_publisher_soup.assert_called_once()

    @patch.object(AbstractCCS, "get_abstract_from_publisher", return_value="")
    @patch("top4grep.abstract.get_semantic_scholar_abstract", return_value="semantic scholar abstract")
    @patch("top4grep.abstract.resolve_doi", side_effect=AssertionError("resolve_doi should not be retried"))
    @patch("top4grep.abstract.get_openalex_abstract_for_title", return_value="")
    def test_direct_doi_urls_use_semantic_scholar_before_title_search(self, _title_fallback, _resolve_doi, _semantic_doi_fallback, _get_abstract_from_publisher):
        text = AbstractCCS().get_abstract_from_url(
            "https://doi.org/10.1145/3658644.3670278",
            "example title",
            [],
        )

        self.assertEqual(text, "semantic scholar abstract")

    @patch.object(AbstractCCS, "get_abstract_from_publisher", return_value="")
    @patch("top4grep.abstract.resolve_doi", side_effect=RuntimeError("publisher fetch failed"))
    @patch("top4grep.abstract.get_semantic_scholar_abstract_for_title", return_value="semantic scholar title fallback")
    @patch("top4grep.abstract.get_openalex_abstract_for_title", return_value="title fallback abstract")
    def test_publisher_resolution_failures_fall_back_to_title_search(self, _title_fallback, _semantic_title_fallback, _resolve_doi, _get_abstract_from_publisher):
        text = AbstractCCS().get_abstract_from_url(
            "https://example.com/paper",
            "example title",
            [],
        )

        self.assertEqual(text, "title fallback abstract")

    @patch.object(AbstractCCS, "get_abstract_from_publisher", return_value="")
    @patch("top4grep.abstract.resolve_doi", side_effect=RuntimeError("publisher fetch failed"))
    @patch("top4grep.abstract.get_semantic_scholar_abstract_for_title", return_value="semantic scholar title fallback")
    @patch("top4grep.abstract.get_openalex_abstract_for_title", return_value="")
    def test_title_search_falls_back_to_semantic_scholar_when_openalex_is_empty(self, _title_fallback, _semantic_title_fallback, _resolve_doi, _get_abstract_from_publisher):
        text = AbstractCCS().get_abstract_from_url(
            "https://example.com/paper",
            "example title",
            [],
        )

        self.assertEqual(text, "semantic scholar title fallback")


if __name__ == "__main__":
    unittest.main()
