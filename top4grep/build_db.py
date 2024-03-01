from datetime import datetime

import requests
import sqlalchemy
from sqlalchemy.orm import sessionmaker
from bs4 import BeautifulSoup

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

engine = sqlalchemy.create_engine(f'sqlite:///papers.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

def save_paper(conf, year, title, authors, abstract):
    logger.debug(f'Adding paper {title} with abstract {abstract[:20]}...')
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

def get_papers(name, year, build_abstract):
    cnt = 0
    conf = NAME_MAP[name]

    if build_abstract and name == "NDSS" and (year == 2018 or year == 2016):
        logger.warning(f"Skipping the abstract for NDSS {year} becuase the website does not contain abstracts.")
        extract_abstract = False
    else:
        extract_abstract = build_abstract
    try:
        r = requests.get(f"https://dblp.org/db/conf/{conf}/{conf}{year}.html")
        assert r.status_code == 200

        html = BeautifulSoup(r.text, 'html.parser')
        paper_htmls = html.find_all("li", {'class': "inproceedings"})
        for paper_html in paper_htmls:
            title = paper_html.find('span', {'class': 'title'}).text
            authors = [x.text for x in paper_html.find_all('span', {'itemprop': 'author'})]
            if extract_abstract:
                abstract = Abstracts[name].get_abstract(paper_html, title, authors)
            else:
                abstract = ''
            # insert the entry only if the paper does not exist
            if not paper_exist(name, year, title, authors, abstract):
                save_paper(name, year, title, authors, abstract)
            cnt += 1
    except Exception as e:
        logger.warning(f"Failed to obtain papers at {name}-{year}")

    logger.debug(f"Found {cnt} papers at {name}-{year}...")


def build_db(build_abstract):
    for conf in CONFERENCES:
        for year in range(2000, datetime.now().year+1):
            get_papers(conf, year, build_abstract)
