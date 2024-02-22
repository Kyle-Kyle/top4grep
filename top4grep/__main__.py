import os

import sqlalchemy
from sqlalchemy.orm import sessionmaker
from nltk import download, word_tokenize
from nltk.data import find
from nltk.stem import PorterStemmer

from .db import Base, Paper
from .build_db import build_db
from .utils import new_logger
import argparse

DB_PATH = "papers.db"

engine = sqlalchemy.create_engine(f'sqlite:///{DB_PATH}')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

logger = new_logger("Top4Grep")
stemmer = PorterStemmer()

CONFERENCES = ["NDSS", "IEEE S&P", "USENIX", "CCS"]

# Function to check and download 'punkt' if not already available
def check_and_download_punkt():
    try:
        # Check if 'punkt' is available, this will raise a LookupError if not found
        find('tokenizers/punkt')
        #print("'punkt' tokenizer models are already installed.")
    except LookupError:
        print("'punkt' tokenizer models not found. Downloading...")
        # Download 'punkt' tokenizer models
        download('punkt')
        
# trim word tokens from tokenizer to stem i.e. exploiting to exploit
def fuzzy_match(title):
    tokens = word_tokenize(title)
    return [stemmer.stem(token) for token in tokens]

def grep(keywords, abstract):
    # TODO: currently we only grep either from title or from abstract, also grep from other fields in the future maybe?
    if abstract:
        constraints = [Paper.abstract.contains(x) for x in keywords]
    else:
        constraints = [Paper.title.contains(x) for x in keywords]
    with Session() as session:
        papers = session.query(Paper).filter(*constraints).all()
    #check whether whether nltk tokenizer data is downloaded
    check_and_download_punkt()
    #tokenize the title and filter out the substring matches
    filter_paper = []
    for paper in papers:
        if all([stemmer.stem(x.lower()) in fuzzy_match(paper.title.lower()) for x in keywords]):
            filter_paper.append(paper)
            
    # perform customized sorthing
    papers = sorted(filter_paper, key=lambda paper: paper.year + CONFERENCES.index(paper.conference)/10, reverse=True)
    return papers


def show_papers(papers):
    for paper in papers:
        print(paper)


def main():
    parser = argparse.ArgumentParser(description='Scripts to query the paper database',
                                     usage="%(prog)s [options] -k <keywords>")
    parser.add_argument('-k', type=str, help="keywords to grep, separated by ','. For example, 'linux,kernel,exploit'", default='')
    parser.add_argument('--build-db', action="store_true", help="Builds the database of conference papers")
    parser.add_argument('--abstract', action="store_true", help="Involve abstract into the database's building or query (Need Chrome for building)")
    args = parser.parse_args()

    if args.k:
        if args.abstract:
            logger.info("Abstract query is not implemented and we are only grepping title now.")
        assert os.path.exists(DB_PATH), f"need to build a paper database first to perform wanted queries"
        keywords = [x.strip() for x in args.k.split(',')]
        if keywords:
            logger.info("Grep based on the following keywords: %s", ', '.join(keywords))
        else:
            logger.warning("No keyword is provided. Return all the papers.")

        papers = grep(keywords, args.abstract)
        logger.debug(f"Found {len(papers)} papers")

        show_papers(papers)
    elif args.build_db:
        print("Building db...")
        build_db(args.abstract)


if __name__ == "__main__":
    main()
