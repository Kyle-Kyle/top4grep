from unittest.mock import patch

import sqlalchemy
from sqlalchemy.orm import sessionmaker

import top4grep.__main__ as cli
import top4grep.build_db as build_db
from top4grep.abstract import AbstractUSENIX
from top4grep.db import Base, Paper


def test_download_paper():
    papers = []

    def save_paper(conf, year, title, authors, abstract):
        papers.append((conf, year, title, authors, abstract))

    with patch("top4grep.build_db.paper_exist", return_value=False):
        with patch("top4grep.build_db.save_paper", side_effect=save_paper):
            build_db.get_papers("USENIX", 2020, build_abstract=False)

    assert papers
    papers2 = []
    for t in papers:
        item = {}
        item['conf'] = t[0]
        item['year'] = t[1]
        item['title'] = t[2]
        item['authors'] = t[3]
        item['abstract'] = t[4]
        papers2.append(item)
    assert all(p['conf'] == 'USENIX' for p in papers2)
    assert all(p['year'] == 2020 for p in papers2)
    assert all(not p['abstract'] for p in papers2)

def test_search_in_db():
    def word_tokenize(text):
        return text.split()

    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add_all([
            Paper(
                conference="CCS",
                year=2023,
                title="Exploiting Linux Kernel Bugs",
                authors="Alice, Bob",
                abstract="",
            ),
            Paper(
                conference="NDSS",
                year=2024,
                title="Linux Kernel Hardening",
                authors="Carol",
                abstract="",
            ),
            Paper(
                conference="USENIX",
                year=2022,
                title="Kernel Fuzzing",
                authors="Dan",
                abstract="",
            ),
        ])
        session.commit()

    old_session = cli.Session
    old_word_tokenize = cli.word_tokenize
    old_check_and_download_punkt = cli.check_and_download_punkt

    try:
        cli.Session = session_factory
        cli.word_tokenize = word_tokenize
        cli.check_and_download_punkt = lambda: None

        papers = cli.grep(["linux", "kernel"], abstract=False)
    finally:
        cli.Session = old_session
        cli.word_tokenize = old_word_tokenize
        cli.check_and_download_punkt = old_check_and_download_punkt
        Base.metadata.drop_all(engine)
        engine.dispose()

    assert len(papers) == 2
    assert [paper.title for paper in papers] == [
        "Linux Kernel Hardening",
        "Exploiting Linux Kernel Bugs",
    ]

def run_all():
    functions = globals()
    all_functions = {x:y for x, y in functions.items() if x.startswith('test_')}
    for f in sorted(all_functions.keys()):
        if hasattr(all_functions[f], '__call__'):
            all_functions[f]()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        globals()['test_' + sys.argv[1]]()
    else:
        run_all()
