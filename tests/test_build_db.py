import unittest
from unittest.mock import patch
from types import SimpleNamespace

import sqlalchemy
from sqlalchemy.orm import sessionmaker
from requests import RequestException

import top4grep.build_db as build_db
from top4grep.db import Base, Paper


class BuildDbTests(unittest.TestCase):
    def test_normalize_toc_api_records_unescapes_titles_and_authors(self):
        hits = [
            {
                "info": {
                    "title": "&quot;Do Anything Now&quot;: Testing &amp; Evaluation.",
                    "authors": {
                        "author": [
                            {"text": "Alice &amp; Bob"},
                            {"text": "Carol"},
                        ]
                    },
                    "ee": "https://doi.org/10.1145/3658644.3670278",
                }
            }
        ]

        records = build_db.normalize_toc_api_records(hits)

        self.assertEqual(records[0]["title"], '"Do Anything Now": Testing & Evaluation.')
        self.assertEqual(records[0]["authors"], ["Alice & Bob", "Carol"])

    def test_normalize_toc_api_records_skips_front_matter_entries(self):
        hits = [
            {"info": {"title": "Conference Organizers.", "authors": {"author": []}, "ee": ""}},
            {"info": {"title": "Poster: A Short Result.", "authors": {"author": [{"text": "Alice"}]}, "ee": ""}},
            {"info": {"title": "Real Paper.", "authors": {"author": [{"text": "Bob"}]}, "ee": ""}},
        ]

        records = build_db.normalize_toc_api_records(hits)

        self.assertEqual([record["title"] for record in records], ["Real Paper."])

    def test_should_skip_record_detects_slides_and_keynotes(self):
        self.assertTrue(build_db.should_skip_record("Keynote Address: Back to the Future.", ""))
        self.assertTrue(build_db.should_skip_record("Interesting Topic.", "https://www.usenix.org/slides/talk.pdf"))
        self.assertFalse(build_db.should_skip_record("Interesting Topic.", "https://example.com/paper.pdf"))

    def test_migrate_database_normalizes_and_deduplicates_titles(self):
        engine = sqlalchemy.create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        test_session = sessionmaker(bind=engine)

        with test_session.begin() as session:
            session.add_all(
                [
                    Paper(
                        conference="CCS",
                        year=2024,
                        title='&quot;Do Anything Now&quot;: Characterizing Jailbreak Prompts.',
                        authors="Alice",
                        abstract="",
                    ),
                    Paper(
                        conference="CCS",
                        year=2024,
                        title='"Do Anything Now": Characterizing Jailbreak Prompts.',
                        authors="Alice",
                        abstract="Useful abstract",
                    ),
                ]
            )

        with patch.object(build_db, "Session", test_session):
            normalized_rows, duplicate_rows = build_db.migrate_database()

        self.assertGreaterEqual(normalized_rows, 1)
        self.assertEqual(duplicate_rows, 1)

        with test_session() as session:
            rows = session.query(Paper).all()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].title, '"Do Anything Now": Characterizing Jailbreak Prompts.')
        self.assertEqual(rows[0].abstract, "Useful abstract")

    def test_prune_stale_papers_removes_rows_missing_from_latest_source(self):
        engine = sqlalchemy.create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        test_session = sessionmaker(bind=engine)

        with test_session.begin() as session:
            session.add_all(
                [
                    Paper(conference="CCS", year=2024, title="Current Title", authors="Alice", abstract=""),
                    Paper(conference="CCS", year=2024, title="Stale Title", authors="Bob", abstract=""),
                ]
            )

        with patch.object(build_db, "Session", test_session):
            removed = build_db.prune_stale_papers("CCS", 2024, {"Current Title"})

        self.assertEqual(removed, 1)
        with test_session() as session:
            rows = session.query(Paper).order_by(Paper.title).all()

        self.assertEqual([row.title for row in rows], ["Current Title"])

    @patch.object(build_db, "TOC_API_HOSTS", ["https://one.example", "https://two.example"])
    @patch("top4grep.build_db.cached_get_json")
    def test_fetch_toc_api_records_retries_other_hosts_for_current_year(self, cached_get_json):
        cached_get_json.side_effect = [
            RequestException("first host timeout"),
            {"result": {"hits": {"hit": [{"info": {"title": "Paper"}}]}}},
        ]

        hits = build_db.fetch_toc_api_records("ccs", 2026)

        self.assertEqual(len(hits), 1)
        self.assertEqual(cached_get_json.call_count, 2)

    @patch.object(build_db, "TOC_API_HOSTS", ["https://one.example", "https://two.example"])
    @patch("top4grep.build_db.cached_get_json", side_effect=RequestException("network down"))
    def test_fetch_toc_api_records_raises_when_all_hosts_fail(self, _cached_get_json):
        with self.assertRaises(RequestException):
            build_db.fetch_toc_api_records("ccs", 2026)

    def test_get_papers_continues_when_one_record_extraction_fails(self):
        engine = sqlalchemy.create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        test_session = sessionmaker(bind=engine)

        with test_session.begin() as session:
            session.add_all(
                [
                    Paper(conference="USENIX", year=2024, title="Broken Paper", authors="Alice", abstract=""),
                    Paper(conference="USENIX", year=2024, title="Recoverable Paper", authors="Bob", abstract=""),
                ]
            )

        records = [
            {"title": "Broken Paper", "authors": ["Alice"], "paper_html": SimpleNamespace(marker="broken")},
            {"title": "Recoverable Paper", "authors": ["Bob"], "paper_html": SimpleNamespace(marker="ok")},
        ]

        def fake_get_abstract(paper_html, title, authors):
            if paper_html.marker == "broken":
                raise RuntimeError("boom")
            return "Recovered abstract"

        with patch.object(build_db, "Session", test_session), \
             patch.object(build_db, "load_records", return_value=records), \
             patch.object(build_db, "prune_stale_papers", return_value=0), \
             patch.dict(build_db.Abstracts, {"USENIX": SimpleNamespace(get_abstract=fake_get_abstract)}):
            processed, changed = build_db.get_papers("USENIX", 2024, True)

        self.assertEqual(processed, 2)
        self.assertEqual(changed, 1)
        with test_session() as session:
            recoverable = session.query(Paper).filter(Paper.title == "Recoverable Paper").one()
            broken = session.query(Paper).filter(Paper.title == "Broken Paper").one()

        self.assertEqual(recoverable.abstract, "Recovered abstract")
        self.assertEqual(broken.abstract, "")

    def test_ndss_legacy_years_still_attempt_abstract_fallbacks(self):
        engine = sqlalchemy.create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        test_session = sessionmaker(bind=engine)

        records = [
            {"title": "Legacy NDSS Paper", "authors": ["Alice"], "paper_html": SimpleNamespace(marker="legacy")},
        ]

        with patch.object(build_db, "Session", test_session), \
             patch.object(build_db, "load_records", return_value=records), \
             patch.object(build_db, "prune_stale_papers", return_value=0), \
             patch.dict(build_db.Abstracts, {"NDSS": SimpleNamespace(get_abstract=lambda *_args: "Recovered abstract")}):
            processed, changed = build_db.get_papers("NDSS", 2016, True)

        self.assertEqual(processed, 1)
        self.assertEqual(changed, 1)
        with test_session() as session:
            row = session.query(Paper).filter(Paper.title == "Legacy NDSS Paper").one()

        self.assertEqual(row.abstract, "Recovered abstract")

    def test_abstract_build_keeps_rows_without_recoverable_abstracts(self):
        engine = sqlalchemy.create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        test_session = sessionmaker(bind=engine)

        with test_session.begin() as session:
            session.add(Paper(conference="CCS", year=2024, title="Unrecoverable Paper", authors="Alice", abstract=""))

        records = [
            {"title": "Unrecoverable Paper", "authors": ["Alice"], "paper_html": SimpleNamespace(marker="missing")},
        ]

        with patch.object(build_db, "Session", test_session), \
             patch.object(build_db, "load_records", return_value=records), \
             patch.dict(build_db.Abstracts, {"CCS": SimpleNamespace(get_abstract=lambda *_args: "")}):
            processed, changed = build_db.get_papers("CCS", 2024, True)

        self.assertEqual(processed, 1)
        self.assertEqual(changed, 0)
        with test_session() as session:
            row = session.query(Paper).one()

        self.assertEqual(row.title, "Unrecoverable Paper")
        self.assertEqual(row.abstract, "")


if __name__ == "__main__":
    unittest.main()
