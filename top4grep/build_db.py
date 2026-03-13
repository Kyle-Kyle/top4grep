from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote

import requests
import sqlalchemy
from bs4 import BeautifulSoup
from sqlalchemy.orm import sessionmaker

from .cache import DATA_DIR, cache_key_path, cached_get_json, cached_get_text
from .utils import new_logger
from .db import Base, Paper
from .abstract import Abstracts, normalize_abstract

logger = new_logger("DB")
logger.setLevel('WARNING')

CONFERENCES = ["NDSS", "IEEE S&P", "USENIX", "CCS"]
NAME_MAP = {
        "NDSS": "ndss",
        "IEEE S&P": "sp",
        "USENIX": "uss",
        "CCS": "ccs",
        }
FRONT_MATTER_TITLES = {
    "Conference Organizers.",
    "External Reviewers.",
    "Message from the Program Chairs.",
    "Program Committee.",
}
PACKAGE_DIR = Path(__file__).resolve().parent
DB_PATH = PACKAGE_DIR / "data" / "papers.db"
DBLP_BASE_URL = "https://dblp.uni-trier.de"
TOC_API_HOSTS = [
    "https://dblp.org",
    "https://dblp.dagstuhl.de",
]
TOC_FIRST_YEARS = {
    "ndss": {2011, 2012, 2013, 2014},
}
RAW_DBLP_API_DIR = DATA_DIR / "raw" / "dblp" / "api"
RAW_DBLP_HTML_DIR = DATA_DIR / "raw" / "dblp" / "html"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = sqlalchemy.create_engine(f'sqlite:///{str(DB_PATH)}')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def normalize_metadata_text(value):
    if not value:
        return ""
    return " ".join(unescape(value).split())


def normalize_author_list(authors):
    normalized = []
    for author in authors:
        cleaned = normalize_metadata_text(author)
        if cleaned:
            normalized.append(cleaned)
    return normalized


def preferred_text(values):
    cleaned = [value for value in values if value]
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def should_skip_record(title, publisher_url=""):
    lowered_title = (title or "").casefold()
    lowered_url = (publisher_url or "").casefold()

    if title in FRONT_MATTER_TITLES:
        return True
    if lowered_title.startswith("poster:") or lowered_title.startswith("demo:"):
        return True
    if lowered_title.startswith("keynote:") or lowered_title.startswith("keynote address:"):
        return True
    if "(invited talk)" in lowered_title:
        return True
    if "/slides/" in lowered_url:
        return True
    return False


def migrate_database():
    normalized_rows = 0
    duplicate_rows = 0

    with Session.begin() as session:
        rows = session.query(Paper).order_by(Paper.id).all()
        grouped_rows = {}

        for row in rows:
            original = (row.title or "", row.authors or "", row.abstract or "")
            row.title = normalize_metadata_text(row.title)
            row.authors = normalize_metadata_text(row.authors)
            row.abstract = normalize_abstract(unescape(row.abstract or ""))

            if (row.title, row.authors, row.abstract) != original:
                normalized_rows += 1

            key = (row.conference or "", row.year, row.title)
            grouped_rows.setdefault(key, []).append(row)

        for row_group in grouped_rows.values():
            if len(row_group) == 1:
                continue

            survivor = row_group[0]
            survivor.authors = preferred_text([row.authors for row in row_group])
            survivor.abstract = preferred_text([row.abstract for row in row_group])

            for duplicate in row_group[1:]:
                session.delete(duplicate)
                duplicate_rows += 1

    return normalized_rows, duplicate_rows

def save_papers(papers):
    if not papers:
        return 0

    logger.debug("Adding %s new papers...", len(papers))
    with Session.begin() as session:
        session.add_all(papers)
    return len(papers)


def update_papers(paper_updates):
    if not paper_updates:
        return 0

    with Session.begin() as session:
        for paper_id, authors, abstract in paper_updates:
            paper = session.get(Paper, paper_id)
            if paper is None:
                continue
            if authors:
                paper.authors = authors
            if abstract and not paper.abstract:
                paper.abstract = abstract
    return len(paper_updates)


def load_existing_papers(conf, year):
    with Session() as session:
        rows = session.query(Paper).filter(
            Paper.conference == conf,
            Paper.year == year,
        ).all()

    existing = {}
    for row in rows:
        normalized_title = normalize_metadata_text(row.title)
        current = existing.get(normalized_title)
        candidate = {
            "id": row.id,
            "authors": normalize_metadata_text(row.authors),
            "abstract": normalize_abstract(unescape(row.abstract or "")),
        }
        if current is None or (not current["abstract"] and candidate["abstract"]):
            existing[normalized_title] = candidate
    return existing


def prune_stale_papers(conf, year, current_titles):
    if not current_titles:
        return 0

    removed = 0
    with Session.begin() as session:
        rows = session.query(Paper).filter(
            Paper.conference == conf,
            Paper.year == year,
        ).all()

        for row in rows:
            if normalize_metadata_text(row.title) in current_titles:
                continue
            session.delete(row)
            removed += 1
    return removed

def build_toc_query(conf, year):
    return f"toc:db/conf/{conf}/{conf}{year}.bht:"

def fetch_toc_api_records(conf, year):
    query = quote(build_toc_query(conf, year))
    last_error = None
    saw_not_found = False

    for host in TOC_API_HOSTS:
        url = f"{host}/search/publ/api?q={query}&h=1000&format=json"
        cache_path = cache_key_path(RAW_DBLP_API_DIR, url, ".json", f"{conf}-{year}")
        try:
            data = cached_get_json(url, cache_path)
            if data is None:
                saw_not_found = True
                continue
            hits = data["result"]["hits"].get("hit", [])
            if isinstance(hits, dict):
                hits = [hits]
            return hits
        except (requests.RequestException, ValueError, KeyError) as e:
            last_error = e

    if last_error is not None and not saw_not_found:
        raise requests.RequestException(last_error)
    return []

def normalize_api_authors(authors):
    if not authors:
        return []

    author_entries = authors.get("author", [])
    if isinstance(author_entries, dict):
        author_entries = [author_entries]

    normalized = []
    for author in author_entries:
        if isinstance(author, dict):
            name = author.get("text", "").strip()
        else:
            name = str(author).strip()
        if name:
            normalized.append(name)
    return normalize_author_list(normalized)

def normalize_toc_api_records(hits):
    records = []
    for hit in hits:
        info = hit.get("info", {})
        if info.get("type") == "Editorship":
            continue

        title = normalize_metadata_text(info.get("title"))
        if not title:
            continue

        publisher_url = info.get("ee") or ""
        if should_skip_record(title, publisher_url):
            continue

        records.append({
            "title": title,
            "authors": normalize_api_authors(info.get("authors")),
            "publisher_url": publisher_url,
        })
    return records

def load_records(conf, year):
    if year >= datetime.now().year or year in TOC_FIRST_YEARS.get(conf, set()):
        hits = fetch_toc_api_records(conf, year)
        return normalize_toc_api_records(hits)

    try:
        url = f"{DBLP_BASE_URL}/db/conf/{conf}/{conf}{year}.html"
        cache_path = cache_key_path(RAW_DBLP_HTML_DIR, url, ".html", f"{conf}-{year}")
        html_text = cached_get_text(url, cache_path)
        if html_text is None:
            return []

        html = BeautifulSoup(html_text, 'html.parser')
        paper_htmls = html.find_all("li", {'class': "inproceedings"})
        records = []
        for paper_html in paper_htmls:
            title_tag = paper_html.find('span', {'class': 'title'})
            if title_tag is None:
                continue

            ee = paper_html.find('li', {'class': 'ee'})
            publisher_url = ee.find('a').get('href') if ee and ee.find('a') else ""
            title = normalize_metadata_text(title_tag.get_text(" ", strip=True))
            if should_skip_record(title, publisher_url):
                continue

            records.append({
                "title": title,
                "authors": normalize_author_list(
                    [x.get_text(" ", strip=True) for x in paper_html.find_all('span', {'itemprop': 'author'})]
                ),
                "paper_html": paper_html,
                "publisher_url": publisher_url,
            })
        return records
    except requests.RequestException:
        hits = fetch_toc_api_records(conf, year)
        return normalize_toc_api_records(hits)

def get_papers(name, year, build_abstract):
    conf = NAME_MAP[name]
    processed = 0
    existing_papers = load_existing_papers(name, year)
    extract_abstract = build_abstract

    try:
        records = load_records(conf, year)
        new_papers = []
        paper_updates = []

        for record in records:
            title = normalize_metadata_text(record["title"])
            authors = normalize_author_list(record["authors"])
            try:
                if extract_abstract:
                    if "paper_html" in record:
                        abstract = Abstracts[name].get_abstract(record["paper_html"], title, authors) or ""
                    else:
                        abstract = Abstracts[name].get_abstract_from_url(record.get("publisher_url"), title, authors) or ""
                else:
                    abstract = ''
            except Exception as e:
                logger.debug(f"Failed to extract abstract for {name}-{year}: {title}: {e}")
                abstract = ''

            abstract = normalize_abstract(unescape(abstract))

            authors_text = ", ".join(authors)
            existing = existing_papers.get(title)
            if existing is not None:
                if (authors_text and authors_text != existing["authors"]) or (abstract and not existing["abstract"]):
                    paper_updates.append((existing["id"], authors_text, abstract))
                    existing["authors"] = authors_text
                    if abstract:
                        existing["abstract"] = abstract
                processed += 1
                continue

            existing_papers[title] = {
                "id": None,
                "authors": authors_text,
                "abstract": abstract,
            }
            new_papers.append(Paper(
                conference=name,
                year=year,
                title=title,
                authors=authors_text,
                abstract=abstract,
            ))
            processed += 1
    except requests.RequestException as e:
        if existing_papers:
            logger.debug(f"Keeping existing records for {name}-{year} after refresh failure: {e}")
            return len(existing_papers), 0
        logger.warning(f"Failed to obtain papers at {name}-{year}: {e}")
        return 0, 0
    except Exception as e:
        if existing_papers:
            logger.debug(f"Keeping existing records for {name}-{year} after parse failure: {e}")
            return len(existing_papers), 0
        logger.warning(f"Failed to parse papers at {name}-{year}: {e}")
        return 0, 0

    removed = prune_stale_papers(name, year, {record["title"] for record in records})
    added = save_papers(new_papers)
    updated = update_papers(paper_updates)
    logger.debug(f"Found {processed} papers at {name}-{year}, added {added}, updated {updated}, removed {removed}...")
    return processed, added + updated + removed


def build_db(build_abstract, conferences=None, start_year=2000, end_year=None):
    if end_year is None:
        end_year = datetime.now().year

    normalized_rows, duplicate_rows = migrate_database()
    if normalized_rows or duplicate_rows:
        logger.info(
            "Normalized %s records and removed %s duplicates before rebuild.",
            normalized_rows,
            duplicate_rows,
        )

    selected_conferences = conferences or CONFERENCES
    processed = 0
    added = 0
    for conf in selected_conferences:
        for year in range(start_year, end_year + 1):
            current_processed, current_added = get_papers(conf, year, build_abstract)
            processed += current_processed
            added += current_added
    return processed, added
