import argparse
from datetime import datetime
from pathlib import Path

import sqlalchemy
from sqlalchemy.orm import sessionmaker

from .bundle import create_cache_bundle, install_cache_bundle
from .db import Base, Paper
from .build_db import DB_PATH, build_db, migrate_database
from .search import SEARCH_FIELDS, paper_matches, paper_sort_key, parse_query
from .utils import new_logger

engine = sqlalchemy.create_engine(f'sqlite:///{str(DB_PATH)}')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

logger = new_logger("Top4Grep")

CONFERENCES = ["NDSS", "IEEE S&P", "USENIX", "CCS"]


def grep(query, field, conferences=None, year_from=2000, year_to=None):
    query_groups = parse_query(query)

    with Session() as session:
        paper_query = session.query(Paper)
        if conferences:
            paper_query = paper_query.filter(Paper.conference.in_(conferences))
        if year_from is not None:
            paper_query = paper_query.filter(Paper.year >= year_from)
        if year_to is not None:
            paper_query = paper_query.filter(Paper.year <= year_to)
        papers = paper_query.all()

    filtered = [paper for paper in papers if paper_matches(paper, query_groups, field)]
    return sorted(filtered, key=paper_sort_key)


def show_papers(papers):
    for paper in papers:
        print(paper)


def main():
    parser = argparse.ArgumentParser(description='Scripts to query the paper database',
                                     usage="%(prog)s [options] -k <keywords>")
    parser.add_argument('-k', type=str, help="keywords to grep. Use ',' for AND and '|' for OR, for example 'linux,kernel|driver'", default='')
    parser.add_argument('--build-db', action="store_true", help="Builds the database of conference papers")
    parser.add_argument('--abstract', action="store_true", help="During builds, fetch abstracts. During queries, search abstracts unless --field is provided.")
    parser.add_argument('--field', choices=SEARCH_FIELDS, help="Field to search for queries. Default is 'title' unless --abstract is set.")
    parser.add_argument('--conference', action='append', choices=CONFERENCES, help="Restrict builds or queries to one or more conferences. May be repeated.")
    parser.add_argument('--year-from', type=int, default=2000, help="Inclusive lower year bound for builds or queries.")
    parser.add_argument('--year-to', type=int, default=datetime.now().year, help="Inclusive upper year bound for builds or queries.")
    parser.add_argument('--export-cache-bundle', type=Path, help="Create a single zip bundle containing papers.db and all cached raw fetches.")
    parser.add_argument('--install-cache-bundle', type=Path, help="Install a previously exported cache bundle into the package data directory.")
    parser.add_argument('--replace-data', action='store_true', help="When installing a cache bundle, replace existing papers.db and raw cache first.")
    args = parser.parse_args()

    if args.year_from > args.year_to:
        parser.error("--year-from must be less than or equal to --year-to")
    if args.replace_data and not args.install_cache_bundle:
        parser.error("--replace-data can only be used with --install-cache-bundle")

    special_actions = [bool(args.export_cache_bundle), bool(args.install_cache_bundle)]
    if sum(special_actions) > 1:
        parser.error("--export-cache-bundle and --install-cache-bundle are mutually exclusive")
    if any(special_actions) and (args.k or args.build_db):
        parser.error("cache bundle operations cannot be combined with queries or --build-db")

    if args.export_cache_bundle:
        result = create_cache_bundle(args.export_cache_bundle)
        print(
            f"Created cache bundle at {result['output_path']} "
            f"({result['archive_bytes']} bytes, {result['file_count']} files)."
        )
        return
    if args.install_cache_bundle:
        result = install_cache_bundle(args.install_cache_bundle, replace=args.replace_data)
        normalized_rows, duplicate_rows = migrate_database()
        print(
            f"Installed cache bundle from {result['bundle_path']} into {result['data_dir']} "
            f"({result['extracted_files']} files)."
        )
        if normalized_rows or duplicate_rows:
            print(f"Normalized {normalized_rows} rows and removed {duplicate_rows} duplicates after install.")
        return

    if args.k:
        if not DB_PATH.exists():
            parser.error("need to build a paper database first to perform queries")
        normalized_rows, duplicate_rows = migrate_database()
        if normalized_rows or duplicate_rows:
            logger.info(
                "Normalized %s records and removed %s duplicates.",
                normalized_rows,
                duplicate_rows,
            )
        field = args.field or ('abstract' if args.abstract else 'title')
        query_groups = parse_query(args.k)
        if query_groups:
            logger.info("Query: %s", args.k)
            logger.info("Field: %s", field)
        else:
            logger.warning("No keyword is provided. Return all the papers.")

        papers = grep(
            args.k,
            field=field,
            conferences=args.conference,
            year_from=args.year_from,
            year_to=args.year_to,
        )
        logger.debug(f"Found {len(papers)} papers")

        show_papers(papers)
    elif args.build_db:
        print("Building db...")
        processed, added = build_db(
            args.abstract,
            conferences=args.conference,
            start_year=args.year_from,
            end_year=args.year_to,
        )
        print(f"Build complete. Processed {processed} papers and changed {added} records.")


if __name__ == "__main__":
    main()
