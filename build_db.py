from datetime import datetime
from abc import abstractmethod

import requests
import sqlalchemy
from sqlalchemy.orm import sessionmaker
from bs4 import BeautifulSoup

from utils import new_logger
from db import Base, Paper

logger = new_logger("DB")

KEYWORD = "kernel"
CONFERENCES = ["USENIX", "IEEE S&P", "NDSS", "CCS"]
NAME_MAP = {
        "USENIX": "uss",
        "IEEE S&P": "sp",
        "NDSS": "ndss",
        "CCS": "ccs",
        }

engine = sqlalchemy.create_engine(f'sqlite:///papers.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

def save_paper(conf, year, title, authors, abstract):
    session = Session()
    paper = Paper(conference=conf, year=year, title=title, authors=", ".join(authors), abstract=abstract)
    session.add(paper)
    session.commit()
    session.close()

def get_papers(name, year):
    cnt = 0
    conf = NAME_MAP[name]

    try:
        r = requests.get(f"https://dblp.org/db/conf/{conf}/{conf}{year}.html")
        assert r.status_code == 200

        html = BeautifulSoup(r.text, 'html.parser')
        paper_htmls = html.find_all("li", {'class': "inproceedings"})
        for paper_html in paper_htmls:
            title = paper_html.find('span', {'class': 'title'}).text
            authors = [x.text for x in paper_html.find_all('span', {'itemprop': 'author'})]
            abstract = ''
            save_paper(name, year, title, authors, abstract)
            cnt += 1
    except Exception as e:
        logger.warning(f"Failed to obtain papers at {name}-{year}")

    logger.debug(f"Found {cnt} papers at {name}-{year}...")


if __name__ == "__main__":
    for conf in CONFERENCES:
        for year in range(2000, datetime.now().year+1):
            get_papers(conf, year)
