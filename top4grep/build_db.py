import gzip
import os
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

from .utils import new_logger
from .db import Base, Paper
from .abstract import Abstracts

logger = new_logger("DB")
logger.setLevel("WARNING")

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
DB_PATH = PACKAGE_DIR / "data" / "papers.db"
DBLP_DUMP_DIR = PACKAGE_DIR / "data" / "dblp"
DBLP_XML_GZ_FILENAME = "dblp.xml.gz"
DBLP_DTD_FILENAME = "dblp.dtd"
DBLP_XML_GZ_URL = "https://dblp.org/xml/dblp.xml.gz"
DBLP_DTD_URL = "https://dblp.org/xml/dblp.dtd"
REQUEST_HEADERS = {
        "User-Agent": "top4grep",
        }
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
        if system_id and system_id.endswith(DBLP_DTD_FILENAME):
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


def save_paper(conf, year, title, authors, abstract):
    logger.debug("Adding paper %r with abstract prefix %r...", title, abstract[:20])
    session = Session()
    paper = Paper(conference=conf, year=year, title=title, authors=", ".join(authors), abstract=abstract)
    session.add(paper)
    session.commit()
    session.close()


def paper_exist(conf, year, title, authors, abstract):
    session = Session()
    paper = session.query(Paper).filter(Paper.conference==conf, Paper.year==year, Paper.title==title, Paper.abstract==abstract).first()
    session.close()
    return paper is not None


def download_dblp_dump(dump_dir=DBLP_DUMP_DIR, force=False):
    dump_dir = Path(dump_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)

    dtd_path = dump_dir / DBLP_DTD_FILENAME
    xml_gz_path = dump_dir / DBLP_XML_GZ_FILENAME
    _download_file(DBLP_DTD_URL, dtd_path, force)
    _download_file(DBLP_XML_GZ_URL, xml_gz_path, force)
    return xml_gz_path, dtd_path


def _download_file(url, destination, force):
    if not force and _destination_is_current(url, destination):
        logger.info("Using cached DBLP file: %s", destination)
        return

    print(f"Downloading {url} to {destination}")
    temporary_destination = destination.with_name(destination.name + ".tmp")
    try:
        with requests.get(url, headers=REQUEST_HEADERS, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            with temporary_destination.open("wb") as f:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            _set_file_mtime(temporary_destination, response.headers.get("Last-Modified"))
        temporary_destination.replace(destination)
    finally:
        if temporary_destination.exists():
            temporary_destination.unlink()


def _destination_is_current(url, destination):
    if not destination.exists():
        return False

    try:
        response = requests.head(url, headers=REQUEST_HEADERS, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to check freshness for %s, using cached %s: %s", url, destination, e)
        return True

    remote_size = response.headers.get("Content-Length")
    if remote_size and destination.stat().st_size != int(remote_size):
        return False

    remote_mtime = _parse_http_timestamp(response.headers.get("Last-Modified"))
    if remote_mtime is not None:
        return destination.stat().st_mtime >= remote_mtime

    return remote_size is not None


def _set_file_mtime(path, http_timestamp):
    mtime = _parse_http_timestamp(http_timestamp)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _parse_http_timestamp(http_timestamp):
    if not http_timestamp:
        return None
    try:
        return parsedate_to_datetime(http_timestamp).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None


def parse_dblp_dump(xml_gz_path, dtd_path, on_paper, conferences=None, start_year=2000, end_year=None):
    xml_gz_path = Path(xml_gz_path)
    dtd_path = Path(dtd_path)
    if end_year is None:
        end_year = datetime.now().year
    if conferences is None:
        conferences = CONFERENCES
    if not xml_gz_path.exists():
        raise FileNotFoundError(f"Missing DBLP XML dump: {xml_gz_path}")
    if not dtd_path.exists():
        raise FileNotFoundError(f"Missing DBLP DTD: {dtd_path}")

    parser = make_parser()
    try:
        parser.setFeature(feature_external_ges, True)
    except (SAXNotRecognizedException, SAXNotSupportedException) as e:
        raise RuntimeError("DBLP XML parsing requires external entity support") from e

    parser.setEntityResolver(DblpDtdResolver(dtd_path))
    parser.setContentHandler(DblpPaperHandler(on_paper, conferences, start_year, end_year))

    source = InputSource(str(xml_gz_path.with_suffix("")))
    with gzip.open(xml_gz_path, "rb") as xml_stream:
        source.setByteStream(xml_stream)
        parser.parse(source)


def get_papers(name, year, build_abstract, download=True, dump_dir=DBLP_DUMP_DIR):
    build_db(
            build_abstract,
            download=download,
            dump_dir=dump_dir,
            conferences=[name],
            start_year=year,
            end_year=year,
            )


def _get_abstract(conference, title, authors, publisher_url):
    if not publisher_url:
        logger.warning("Failed to obtain publisher URL for paper %r", title)
        return ""

    try:
        return Abstracts[conference].get_abstract_from_publisher(publisher_url, authors)
    except requests.RequestException as e:
        logger.warning("Failed to fetch abstract for paper %r from %s: %s", title, publisher_url, e)
    except Exception as e:
        logger.exception("Failed to extract abstract for paper %r from %s: %s", title, publisher_url, e)
    return ""


def build_db(build_abstract, download=True, dump_dir=DBLP_DUMP_DIR, force_download=False,
             conferences=None, start_year=2000, end_year=None):
    if end_year is None:
        end_year = datetime.now().year
    if conferences is None:
        conferences = CONFERENCES

    if download:
        xml_gz_path, dtd_path = download_dblp_dump(dump_dir=dump_dir, force=force_download)
    else:
        dump_dir = Path(dump_dir)
        xml_gz_path = dump_dir / DBLP_XML_GZ_FILENAME
        dtd_path = dump_dir / DBLP_DTD_FILENAME

    seen_buckets = set()
    paper_count = 0

    def save_record(record):
        nonlocal paper_count
        bucket = (record.conference, record.year)
        if bucket not in seen_buckets:
            print(record.conference, record.year)
            seen_buckets.add(bucket)

        if build_abstract:
            abstract = _get_abstract(record.conference, record.title, record.authors, record.publisher_url)
        else:
            abstract = ""

        if not paper_exist(record.conference, record.year, record.title, record.authors, abstract):
            save_paper(record.conference, record.year, record.title, record.authors, abstract)
        paper_count += 1

    parse_dblp_dump(
            xml_gz_path,
            dtd_path,
            save_record,
            conferences=conferences,
            start_year=start_year,
            end_year=end_year,
            )
    logger.debug("Found %d papers from DBLP XML dump", paper_count)
