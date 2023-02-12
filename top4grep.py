import os

import sqlalchemy
from sqlalchemy.orm import sessionmaker

from db import Base, Paper
from utils import new_logger

DB_PATH = "papers.db"

engine = sqlalchemy.create_engine(f'sqlite:///{DB_PATH}')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

logger = new_logger("Top4Grep")

CONFERENCES = ["NDSS", "IEEE S&P", "USENIX", "CCS"]

def grep(keywords):
    # TODO: currently we only grep from title, also grep from other fields in the future maybe?
    constraints = [Paper.title.contains(x) for x in keywords]

    with Session() as session:
        papers = session.query(Paper).filter(*constraints).all()

    # perform customized sorthing
    papers = sorted(papers, key=lambda paper: paper.year + CONFERENCES.index(paper.conference)/10, reverse=True)
    return papers

def show_papers(papers):
    for paper in papers:
        print(paper)

if __name__ == "__main__":
    assert os.path.exists(DB_PATH), f"need to build a paper database first to perform wanted queries"

    import argparse
    parser = argparse.ArgumentParser(description='Scripts to query the paper database',
                                     usage="%(prog)s [options] -k <keywords>")
    parser.add_argument('-k', type=str, help="keywords to grep, separated by ','. For example, 'linux,kernel,exploit'", default='')
    args = parser.parse_args()

    keywords = [x.strip() for x in args.k.split(',')]
    if keywords:
        logger.info("Grep based on the following keywords: %s", ', '.join(keywords))
    else:
        logger.warning("No keyword is provided. Return all the papers.")

    papers = grep(keywords)
    logger.debug(f"Found {len(papers)} papers")

    show_papers(papers)
