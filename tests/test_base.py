import gzip
import tempfile
from pathlib import Path
from unittest.mock import patch

import sqlalchemy
from sqlalchemy.orm import sessionmaker

import top4grep.__main__ as cli
import top4grep.build_db as build_db
from top4grep.db import Base, Paper


def write_dblp_fixture(dump_dir):
    dtd = '<!ENTITY testentity "Entity">\n'
    xml = """<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE dblp SYSTEM "dblp.dtd">
<dblp>
  <inproceedings key="conf/uss/example20">
    <author>Alice Example</author>
    <author>Bob Example</author>
    <title>USENIX &testentity; Paper.</title>
    <year>2020</year>
    <ee>https://www.usenix.org/conference/usenixsecurity20/presentation/example</ee>
  </inproceedings>
  <inproceedings key="conf/uss/example19">
    <author>Carol Example</author>
    <title>Older USENIX Paper.</title>
    <year>2019</year>
    <ee>https://www.usenix.org/conference/usenixsecurity19/presentation/example</ee>
  </inproceedings>
  <inproceedings key="conf/sp/example20">
    <author>Dan Example</author>
    <title>IEEE S&amp;P Paper.</title>
    <year>2020</year>
    <ee>https://doi.org/10.1109/SP46215.2023.10179381</ee>
  </inproceedings>
</dblp>
"""
    dump_dir = Path(dump_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / build_db.DBLP_DTD_FILENAME).write_text(dtd, encoding="ascii")
    with gzip.open(dump_dir / build_db.DBLP_XML_GZ_FILENAME, "wb") as f:
        f.write(xml.encode("ascii"))


def test_download_paper():
    papers = []

    def save_paper(conf, year, title, authors, abstract):
        papers.append((conf, year, title, authors, abstract))

    with tempfile.TemporaryDirectory() as dump_dir:
        write_dblp_fixture(dump_dir)

        with patch("top4grep.build_db.paper_exist", return_value=False):
            with patch("top4grep.build_db.save_paper", side_effect=save_paper):
                build_db.get_papers("USENIX", 2020, build_abstract=False, download=False, dump_dir=dump_dir)

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
    assert [p['title'] for p in papers2] == ["USENIX Entity Paper."]

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
