import os
import time
import gzip
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.sax import (
        InputSource,
        SAXNotRecognizedException,
        SAXNotSupportedException,
        make_parser,
        handler,
        )
from xml.sax.handler import feature_external_ges

import requests
import sqlalchemy
from sqlalchemy.orm import sessionmaker
from bs4 import BeautifulSoup
from pypdl import Pypdl

from .utils import new_logger
from .db import Base, Paper
from .abstract import Abstracts

logger = new_logger("DB")
logger.setLevel("INFO")

CONFERENCES = ["NDSS", "IEEE S&P", "USENIX", "CCS"]
NAME_MAP = {
        "NDSS": "ndss",
        "IEEE S&P": "sp",
        "USENIX": "uss",
        "CCS": "ccs",
        }
CONF_PREFIXES = {
        f"conf/{dblp_name}/": conference
        for conference, dblp_name in NAME_MAP.items()
        }

PACKAGE_DIR = Path(__file__).resolve().parent
DB_PATH = str(PACKAGE_DIR / "data" / "papers.db")
DBLP_XML_PATH = str(PACKAGE_DIR / "data" / "dblp.xml.gz")
DBLP_DTD_PATH = str(PACKAGE_DIR / "data" / "dblp.dtd")
REQUEST_HEADERS = {
        "User-Agent": "top4grep",
        }
START_YEAR = 2000
REQUEST_TIMEOUT = (10, 120)
DOWNLOAD_CHUNK_SIZE = 1024 * 1024

engine = sqlalchemy.create_engine(f'sqlite:///{str(DB_PATH)}')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


@dataclass
class DblpPaper:
    conference: str
    year: int
    title: str
    authors: list
    publisher_url: str


class DblpDtdResolver(handler.EntityResolver):
    def __init__(self, dtd_path):
        self.dtd_path = Path(dtd_path)

    def resolveEntity(self, public_id, system_id):
        if system_id and system_id.endswith("dblp.dtd"):
            return str(self.dtd_path)
        return system_id


class DblpPaperHandler(handler.ContentHandler):
    FIELDS = {"author", "title", "year", "ee"}

    def __init__(self, on_paper, conferences, start_year, end_year):
        self.on_paper = on_paper
        self.conferences = set(conferences)
        self.start_year = start_year
        self.end_year = end_year
        self.current = None
        self.current_field = None
        self.buffer = []

    def startElement(self, name, attrs):
        if name == "inproceedings":
            conference = self._conference_from_key(attrs.get("key", ""))
            if conference in self.conferences:
                self.current = {
                        "conference": conference,
                        "title": "",
                        "year": "",
                        "authors": [],
                        "ees": [],
                        }
            else:
                self.current = None
            return

        if self.current is not None and name in self.FIELDS:
            self.current_field = name
            self.buffer = []

    def characters(self, content):
        if self.current_field:
            self.buffer.append(content)

    def endElement(self, name):
        if self.current is None:
            return

        if name == self.current_field:
            self._save_field(name, "".join(self.buffer).strip())
            self.current_field = None
            self.buffer = []
            return

        if name == "inproceedings":
            self._emit_current_paper()
            self.current = None

    def _conference_from_key(self, key):
        for prefix, conference in CONF_PREFIXES.items():
            if key.startswith(prefix):
                return conference
        return None

    def _save_field(self, field, value):
        if not value:
            return

        if field == "author":
            self.current["authors"].append(value)
        elif field == "ee":
            self.current["ees"].append(value)
        else:
            self.current[field] = value

    def _emit_current_paper(self):
        try:
            year = int(self.current["year"])
        except (TypeError, ValueError):
            logger.warning("Skipping paper with missing or invalid year: %r", self.current["title"])
            return

        if year < self.start_year or year > self.end_year:
            return

        if not self.current["title"]:
            logger.warning("Skipping %s-%s paper with missing title", self.current["conference"], year)
            return

        self.on_paper(DblpPaper(
                conference=self.current["conference"],
                year=year,
                title=self.current["title"],
                authors=self.current["authors"],
                publisher_url=self.current["ees"][0] if self.current["ees"] else "",
                ))


def save_paper(conf, year, title, authors, url, abstract):
    logger.debug("Adding paper %r with abstract prefix %r...", title, abstract[:20])
    session = Session()
    paper = Paper(conference=conf, year=year, title=title, authors=", ".join(authors), url=url, abstract=abstract)
    session.add(paper)
    session.commit()
    session.close()


def paper_exist(conf, year, title):
    session = Session()
    paper = session.query(Paper).filter(Paper.conference==conf, Paper.year==year, Paper.title==title).first()
    session.close()
    return paper is not None

def parse_dblp_db():
    seen_buckets = set()
    paper_count = 0

    def save_record(record):
        nonlocal paper_count
        bucket = (record.conference, record.year)
        if bucket not in seen_buckets:
            #print(record.conference, record.year)
            seen_buckets.add(bucket)

        if not paper_exist(record.conference, record.year, record.title):
            save_paper(record.conference, record.year, record.title, record.authors, record.publisher_url, "")
        paper_count += 1

    start_year = START_YEAR
    end_year = datetime.now().year
    parser = make_parser()
    try:
        parser.setFeature(feature_external_ges, True)
    except (SAXNotRecognizedException, SAXNotSupportedException) as e:
        raise RuntimeError("DBLP XML parsing requires external entity support") from e

    parser.setEntityResolver(DblpDtdResolver(DBLP_DTD_PATH))
    parser.setContentHandler(DblpPaperHandler(save_record, CONFERENCES, start_year, end_year))

    source = InputSource(DBLP_XML_PATH)
    with gzip.open(DBLP_XML_PATH, "rb") as xml_stream:
        source.setByteStream(xml_stream)
        parser.parse(source)

def has_papers():
    with Session() as session:
        return session.query(Paper.id).first() is not None

def build_fresh_db():
    # download dblp database files first
    logger.info("Downloading dblp database...")
    dl = Pypdl()
    dl.start("https://dblp.org/xml/dblp.dtd", DBLP_DTD_PATH)
    dl = Pypdl()
    dl.start("https://dblp.org/xml/dblp.xml.gz", DBLP_XML_PATH)

    # parse the db
    logger.info("Parsing dblp database...")
    parse_dblp_db()

    # delete it
    os.unlink(DBLP_DTD_PATH)
    os.unlink(DBLP_XML_PATH)

def safe_dblp_query(url):
    for i in range(20):
        delay = 30
        try:
            r = requests.get(url)
        except requests.exceptions.ConnectionError:
            logger.warning("being rate limited by dblp, sleeping for %d seconds", delay)
            time.sleep(delay)
            continue

        if r.status_code in [200, 404]:
            return r
        if r.status_code == 429:
            logger.warning("hit dblp rate limit, sleeping for %d seconds before retrying %s", delay, url)
            time.sleep(delay)

def get_papers(name, year):
    cnt = 0
    conf = NAME_MAP[name]

    url = f"https://dblp.org/db/conf/{conf}/{conf}{year}.html"
    try:
        r = safe_dblp_query(url)

        html = BeautifulSoup(r.text, 'html.parser')
        paper_htmls = html.find_all("li", {'class': "inproceedings"})
        for paper_html in paper_htmls:
            title = paper_html.find('span', {'class': 'title'}).text
            authors = [x.text for x in paper_html.find_all('span', {'itemprop': 'author'})]
            elem = paper_html.find('nav', {'class': 'publ'})
            paper_url = elem.find_all('li')[0].div.a.attrs['href']
            # insert the entry only if the paper does not exist
            if not paper_exist(name, year, title):
                save_paper(name, year, title, authors, paper_url, "")
            cnt += 1
    except requests.RequestException as e:
        logger.warning("Failed to fetch papers for %s-%s from %s: %s", name, year, url, e)
    except (AttributeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse papers for %s-%s from %s: %s", name, year, url, e)
    except Exception as e:
        logger.exception("Unexpected error while obtaining papers for %s-%s from %s: %s", name, year, url, e)

    logger.info("Found %d papers at %s-%s...", cnt, name, year)

def update_db():
    # get the start year
    with Session() as session:
        years = session.query(Paper.year).all()
        start_year = sorted({x[0] for x in years})[-1]
    assert start_year >= START_YEAR

    # now look for new papers
    for conf in CONFERENCES:
        for year in range(start_year, datetime.now().year+1):
            get_papers(conf, year)

def download_abstract():
    # step 1: get all papers with no abstract
    with Session() as session:
        papers = session.query(Paper).filter(Paper.abstract == '').all()
    # step 2: getting abstracts and save it into the database
    logger.info("grabbing abstract for %d papers", len(papers))
    papers = sorted(papers, key=lambda x: x.year)
    for paper in papers:
        if paper.conference != 'USENIX':
            continue
        if not paper.url:
            continue
        abstract = Abstracts[paper.conference].get_abstract(paper)
        print(paper.year, paper.url)
        print(abstract)
    #session = Session()
    #paper = Paper(conference=conf, year=year, title=title, authors=", ".join(authors), url=url, abstract=abstract)
    #session.add(paper)
    #session.commit()
    #session.close()
    #def _get_abstract(conference, title, authors, publisher_url):
    #import IPython; IPython.embed()

def build_db(build_abstract):
    # step 1, download basic paper information
    if not has_papers():
        logger.info("No existing db detected, building one from the dblp database, it will take around 5 minutes...")
        build_fresh_db()
    else:
        update_db()

    # step 2, update abstract information
    #download_abstract()
