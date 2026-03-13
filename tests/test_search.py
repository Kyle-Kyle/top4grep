import unittest
from types import SimpleNamespace

from top4grep.search import paper_matches, paper_sort_key, parse_query


def make_paper(**kwargs):
    defaults = {
        "title": "Exploiting Linux Kernel Drivers",
        "abstract": "This paper studies exploit chains in kernel subsystems.",
        "authors": "Alice Example, Bob Example",
        "conference": "CCS",
        "year": 2024,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class SearchTests(unittest.TestCase):
    def test_and_query_matches_title(self):
        paper = make_paper()
        self.assertTrue(paper_matches(paper, parse_query("linux,exploit"), "title"))

    def test_or_query_matches_title(self):
        paper = make_paper()
        self.assertTrue(paper_matches(paper, parse_query("kernel|driver"), "title"))

    def test_stemming_matches_variants(self):
        paper = make_paper(title="Exploitability Signals for Linux Drivers")
        self.assertTrue(paper_matches(paper, parse_query("exploiting"), "title"))

    def test_abstract_field_can_match_without_title_hit(self):
        paper = make_paper(title="Artifact-Centric Analysis", abstract="Dependency risk in package supply chains.")
        self.assertTrue(paper_matches(paper, parse_query("dependency,supply"), "abstract"))

    def test_all_field_can_match_across_non_title_content(self):
        paper = make_paper(title="Artifact-Centric Analysis", abstract="Dependency risk in package supply chains.")
        self.assertTrue(paper_matches(paper, parse_query("dependency,supply"), "all"))

    def test_missing_term_rejects_match(self):
        paper = make_paper()
        self.assertFalse(paper_matches(paper, parse_query("windows"), "title"))

    def test_sort_order_matches_original_cli_behavior(self):
        papers = [
            make_paper(conference="NDSS", title="ndss"),
            make_paper(conference="IEEE S&P", title="sp"),
            make_paper(conference="USENIX", title="usenix"),
            make_paper(conference="CCS", title="ccs"),
        ]
        ordered = sorted(papers, key=paper_sort_key)
        self.assertEqual([paper.conference for paper in ordered], ["CCS", "USENIX", "IEEE S&P", "NDSS"])


if __name__ == "__main__":
    unittest.main()
