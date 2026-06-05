from datetime import datetime
from pathlib import Path
import re

import requests
import sqlalchemy
from sqlalchemy.orm import sessionmaker

from .utils import new_logger
from .db import Base, Paper
from .abstract import Abstracts

logger = new_logger("DB")
logger.setLevel('WARNING')

CONFERENCES = ["NDSS", "IEEE S&P", "USENIX", "CCS"]
NAME_MAP = {
        "NDSS": "ndss",
        "IEEE S&P": "sp",
        "USENIX": "uss",
        "CCS": "ccs",
        }
SPARQL_ENDPOINT = "https://sparql.dblp.org/sparql"
REQUEST_TIMEOUT = 120
HEADERS = {"Accept": "application/sparql-results+json"}
PACKAGE_DIR = Path(__file__).resolve().parent
DB_PATH = PACKAGE_DIR / "data" / "papers.db"

engine = sqlalchemy.create_engine(f'sqlite:///{str(DB_PATH)}')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def clean_author(author):
    # dblp disambiguates homonyms as "Name 0001"; keep the display name.
    return re.sub(r"\s+0\d{3}$", "", author).strip()


def existing_paper_keys():
    with Session() as session:
        papers = session.query(Paper.conference, Paper.year, Paper.title, Paper.abstract).all()
        return set(map(tuple, papers))


def save_papers(papers):
    if not papers:
        return

    with Session() as session:
        session.bulk_insert_mappings(Paper, papers)
        session.commit()


def sparql_query():
    current_year = datetime.now().year
    streams = " ".join(f'(<https://dblp.org/streams/conf/{NAME_MAP[conf]}> "{conf}")' for conf in CONFERENCES)
    return f"""
PREFIX dblp: <https://dblp.org/rdf/schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?conf ?year ?publ ?title ?ordinal ?author ?url WHERE {{
  VALUES (?stream ?conf) {{ {streams} }}
  ?publ dblp:publishedInStream ?stream ;
        rdf:type dblp:Inproceedings ;
        dblp:title ?title ;
        dblp:yearOfPublication ?year ;
        dblp:hasSignature ?sig .
  ?sig dblp:signatureDblpName ?author ;
       dblp:signatureOrdinal ?ordinal .
  OPTIONAL {{ ?publ dblp:primaryDocumentPage ?url . }}
  FILTER(?year >= "2000"^^xsd:gYear && ?year <= "{current_year}"^^xsd:gYear)
}}
ORDER BY ?conf ?year ?publ xsd:integer(?ordinal)
"""


def fetch_papers():
    r = requests.get(SPARQL_ENDPOINT, params={"query": sparql_query()}, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    papers = {}
    for binding in r.json()["results"]["bindings"]:
        publ = binding["publ"]["value"]
        if publ not in papers:
            papers[publ] = {
                    "conference": binding["conf"]["value"],
                    "year": int(binding["year"]["value"]),
                    "title": binding["title"]["value"],
                    "authors": [],
                    "publisher_url": binding.get("url", {}).get("value"),
                    "abstract": "",
                    }
        papers[publ]["authors"].append((
                int(binding["ordinal"]["value"]),
                clean_author(binding["author"]["value"]),
                ))

    for paper in papers.values():
        paper["authors"] = [author for _, author in sorted(paper["authors"])]

    return list(papers.values())


def add_abstract(paper):
    if not paper["publisher_url"]:
        return
    if paper["conference"] == "NDSS" and paper["year"] in (2016, 2018):
        return

    try:
        paper["abstract"] = Abstracts[paper["conference"]].get_abstract_from_publisher(
                paper["publisher_url"], paper["authors"])
    except Exception:
        logger.debug(f"Failed to extract abstract from publisher URL {paper['publisher_url']}.")


def paper_record(paper):
    return {
            "conference": paper["conference"],
            "year": paper["year"],
            "title": paper["title"],
            "authors": ", ".join(paper["authors"]),
            "abstract": paper["abstract"],
            }


def build_db(build_abstract):
    papers = fetch_papers()
    existing = existing_paper_keys()
    new_papers = []

    for paper in papers:
        if build_abstract:
            add_abstract(paper)

        paper = paper_record(paper)
        key = (paper["conference"], paper["year"], paper["title"], paper["abstract"])
        if key not in existing:
            existing.add(key)
            new_papers.append(paper)

    save_papers(new_papers)
