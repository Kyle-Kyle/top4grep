import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from html import unescape
from urllib.parse import unquote, urljoin, urlparse

import requests

from .cache import DATA_DIR, cache_key_path, cached_get_bytes, cached_get_json, cached_get_text
from .utils import new_logger

logger = new_logger('PaperAbstract')
logger.setLevel('WARNING')

RAW_PUBLISHER_DIR = DATA_DIR / "raw" / "publisher_html"
RAW_PDF_DIR = DATA_DIR / "raw" / "pdf"
RAW_OPENALEX_DIR = DATA_DIR / "raw" / "openalex"
RAW_OPENALEX_SEARCH_DIR = RAW_OPENALEX_DIR / "title_search"
RAW_SEMANTIC_SCHOLAR_DIR = DATA_DIR / "raw" / "semantic_scholar"
RAW_SEMANTIC_SCHOLAR_SEARCH_DIR = RAW_SEMANTIC_SCHOLAR_DIR / "title_search"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def normalize_abstract(text):
    if not text:
        return ""
    lines = [re.sub(r"\s+", " ", unescape(line)).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_doi(value):
    if not value:
        return ""
    match = DOI_PATTERN.search(unquote(value))
    if not match:
        return ""
    return match.group(0).rstrip(").,;")


def reconstruct_abstract(inverted_index):
    if not inverted_index:
        return ""

    tokens = []
    for word, positions in inverted_index.items():
        for position in positions:
            tokens.append((position, word))
    return " ".join(word for _, word in sorted(tokens))


def normalize_title_key(title):
    if not title:
        return ""
    text = re.sub(r"<[^>]+>", " ", unescape(title))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def publisher_cache_path(url):
    parsed = urlparse(url)
    hint = parsed.netloc or "publisher"
    return cache_key_path(RAW_PUBLISHER_DIR, url, ".html", hint)


def pdf_cache_path(url):
    parsed = urlparse(url)
    hint = parsed.netloc or "paper"
    return cache_key_path(RAW_PDF_DIR, url, ".pdf", hint)


def is_pdf_url(url):
    if not url:
        return False
    return urlparse(url).path.lower().endswith(".pdf")


def normalize_source_url(url):
    if not url:
        return ""
    normalized = url.strip()
    if normalized.startswith("http://wp.internetsociety.org/ndss/wp-content/uploads/sites/25/"):
        return normalized.replace(
            "http://wp.internetsociety.org/ndss/wp-content/uploads/sites/25/",
            "https://www.ndss-symposium.org/wp-content/uploads/",
            1,
        )
    if normalized.startswith("https://wp.internetsociety.org/ndss/wp-content/uploads/sites/25/"):
        return normalized.replace(
            "https://wp.internetsociety.org/ndss/wp-content/uploads/sites/25/",
            "https://www.ndss-symposium.org/wp-content/uploads/",
            1,
        )
    return normalized


def fetch_publisher_html(url):
    if not url:
        return None
    url = normalize_source_url(url)
    return cached_get_text(url, publisher_cache_path(url))


def fetch_pdf_bytes(url):
    if not url:
        return None
    url = normalize_source_url(url)
    return cached_get_bytes(url, pdf_cache_path(url))


def load_publisher_soup(url):
    html = fetch_publisher_html(url)
    if html is None:
        return None
    return BeautifulSoup(html, 'html.parser')


def openalex_cache_path(doi):
    return cache_key_path(RAW_OPENALEX_DIR, doi, ".json", doi.replace("/", "-"))


def openalex_title_search_cache_path(title):
    return cache_key_path(RAW_OPENALEX_SEARCH_DIR, title, ".json", title)


def semantic_scholar_cache_path(identifier):
    return cache_key_path(RAW_SEMANTIC_SCHOLAR_DIR, identifier, ".json", identifier.replace("/", "-"))


def semantic_scholar_title_search_cache_path(title):
    return cache_key_path(RAW_SEMANTIC_SCHOLAR_SEARCH_DIR, title, ".json", title)


def resolve_doi_from_html(url):
    soup = load_publisher_soup(url)
    if soup is None:
        return ""

    candidates = []
    for attrs in (
        {"name": "citation_doi"},
        {"name": "dc.Identifier"},
        {"name": "dc.identifier"},
        {"property": "og:url"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            candidates.append(meta["content"])

    for anchor in soup.find_all("a", href=True):
        candidates.append(anchor["href"])

    for candidate in candidates:
        doi = extract_doi(candidate)
        if doi:
            return doi
    return ""


def resolve_doi(url):
    url = normalize_source_url(url)
    doi = extract_doi(url)
    if doi:
        return doi
    return resolve_doi_from_html(url)


def get_openalex_abstract(doi):
    if not doi:
        return ""

    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    try:
        data = cached_get_json(url, openalex_cache_path(doi))
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Failed to fetch OpenAlex abstract for DOI {doi}: {e}")
        return ""
    if not data:
        return ""
    return normalize_abstract(reconstruct_abstract(data.get("abstract_inverted_index", {})))


def get_openalex_abstract_for_title(title, authors=None):
    if not title:
        return ""

    url = requests.Request(
        "GET",
        "https://api.openalex.org/works",
        params={"search": title, "per-page": 10},
    ).prepare().url
    try:
        data = cached_get_json(url, openalex_title_search_cache_path(title))
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Failed to search OpenAlex by title for {title}: {e}")
        return ""
    if not data:
        return ""

    target_key = normalize_title_key(title)
    for result in data.get("results", []):
        if normalize_title_key(result.get("display_name")) != target_key:
            continue
        abstract = reconstruct_abstract(result.get("abstract_inverted_index", {}))
        if abstract:
            return normalize_abstract(abstract)
    return ""


def normalize_pdf_text(text):
    if not text:
        return ""
    text = text.replace("\f", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_meta_description(soup):
    if soup is None:
        return ""

    for attrs in (
        {"name": "citation_abstract"},
        {"name": "description"},
        {"property": "og:description"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if not meta or not meta.get("content"):
            continue
        content = normalize_abstract(meta["content"])
        lowered = content.casefold()
        if not content:
            continue
        if lowered.startswith("author(s):"):
            continue
        if lowered.startswith("download:"):
            continue
        if lowered.startswith("usenix is a nonprofit organization"):
            continue
        return content
    return ""


def extract_abstract_from_pdf_text(text):
    normalized = normalize_pdf_text(text)
    if not normalized:
        return ""

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    collecting = False
    collected = []

    for line in lines:
        heading_key = re.sub(r"[^a-z0-9]+", "", line.casefold())
        if not collecting:
            if "abstract" not in heading_key:
                continue
            collecting = True
            content = re.sub(r"^\s*abstract\b[\s:.\-–—]*", "", line, flags=re.IGNORECASE).strip()
            if content:
                collected.append(content)
            continue

        if heading_key in {
            "1introduction",
            "iintroduction",
            "introduction",
            "keywords",
            "indexterms",
            "categoriesandsubjectdescriptors",
        }:
            break
        if heading_key in {"1", "i"}:
            continue
        collected.append(line)

    if collected:
        return normalize_abstract(" ".join(collected))
    return ""


def extract_abstract_from_pdf_url(url):
    if not url:
        return ""
    url = normalize_source_url(url)

    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return ""

    pdf_bytes = fetch_pdf_bytes(url)
    if not pdf_bytes:
        return ""

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
            handle.write(pdf_bytes)
            temp_path = handle.name

        result = subprocess.run(
            [pdftotext, "-f", "1", "-l", "2", temp_path, "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return ""
        return extract_abstract_from_pdf_text(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def find_pdf_url_in_soup(base_url, soup):
    if soup is None:
        return ""

    candidates = []
    for attrs in (
        {"name": "citation_pdf_url"},
        {"name": "wkhealth_pdf_url"},
        {"property": "og:pdf"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            candidates.append(meta["content"])

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        label = anchor.get_text(" ", strip=True).casefold()
        if href.lower().endswith(".pdf") or label in {"pdf", "download pdf", "paper"}:
            candidates.append(href)

    for candidate in candidates:
        absolute = normalize_source_url(urljoin(base_url, candidate))
        if is_pdf_url(absolute):
            return absolute
    return ""


def extract_semantic_scholar_abstract(data):
    if not data:
        return ""
    abstract = data.get("abstract")
    if abstract:
        return normalize_abstract(abstract)
    return ""


def semantic_scholar_authors_match(result, authors):
    if not authors:
        return True

    expected = {normalize_title_key(author) for author in authors if author}
    if not expected:
        return True

    actual = {
        normalize_title_key(author.get("name"))
        for author in result.get("authors", [])
        if isinstance(author, dict) and author.get("name")
    }
    return bool(expected & actual)


def get_semantic_scholar_abstract(doi):
    if not doi:
        return ""

    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,abstract,authors,externalIds,year"
    try:
        data = cached_get_json(url, semantic_scholar_cache_path(doi))
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Failed to fetch Semantic Scholar abstract for DOI {doi}: {e}")
        return ""
    return extract_semantic_scholar_abstract(data)


def get_semantic_scholar_abstract_for_title(title, authors=None):
    if not title:
        return ""

    url = requests.Request(
        "GET",
        "https://api.semanticscholar.org/graph/v1/paper/search/match",
        params={"query": title, "fields": "title,abstract,authors,externalIds,year"},
    ).prepare().url
    try:
        data = cached_get_json(url, semantic_scholar_title_search_cache_path(title))
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Failed to search Semantic Scholar by title for {title}: {e}")
        return ""
    if not data:
        return ""

    results = data.get("data", [])
    if isinstance(results, dict):
        results = [results]

    target_key = normalize_title_key(title)
    for result in results:
        if normalize_title_key(result.get("title")) != target_key:
            continue
        if not semantic_scholar_authors_match(result, authors):
            continue
        abstract = extract_semantic_scholar_abstract(result)
        if abstract:
            return abstract
    return ""


class BasePaperAbstract(ABC):
    def get_abstract(self, paper_html, title, authors):
        try:
            publisher_url = self.get_publisher_url(paper_html)
        except Exception as e:
            logger.debug(f"Failed to obtain publisher URL. Paper: {title}")
            return ""
        return self.get_abstract_from_url(publisher_url, title, authors)

    def get_abstract_from_url(self, publisher_url, title, authors):
        publisher_url = normalize_source_url(publisher_url)
        if not publisher_url:
            abstract = get_openalex_abstract_for_title(title, authors)
            if abstract:
                return abstract
            return get_semantic_scholar_abstract_for_title(title, authors)

        if is_pdf_url(publisher_url):
            abstract = extract_abstract_from_pdf_url(publisher_url)
            if abstract:
                return abstract

        direct_doi = extract_doi(publisher_url)
        try:
            abstract = self.get_abstract_from_publisher(publisher_url, authors)
        except Exception as e:
            logger.debug(f"Failed to extract abstract from publisher URL {publisher_url}. Paper: {title}")
            abstract = ""

        if abstract:
            return normalize_abstract(abstract)

        pdf_url = ""
        try:
            pdf_url = find_pdf_url_in_soup(publisher_url, load_publisher_soup(publisher_url))
        except Exception as e:
            logger.debug(f"Failed to locate PDF from publisher URL {publisher_url}. Paper: {title}")
            pdf_url = ""
        if pdf_url:
            abstract = extract_abstract_from_pdf_url(pdf_url)
            if abstract:
                return abstract

        if direct_doi:
            abstract = get_semantic_scholar_abstract(direct_doi)
            if abstract:
                return abstract
            abstract = get_openalex_abstract_for_title(title, authors)
            if abstract:
                return abstract
            return get_semantic_scholar_abstract_for_title(title, authors)

        try:
            doi = resolve_doi(publisher_url)
        except Exception as e:
            logger.debug(f"Failed to resolve DOI from publisher URL {publisher_url}. Paper: {title}")
            doi = ""
        if doi:
            abstract = get_openalex_abstract(doi)
            if abstract:
                return abstract
            abstract = get_semantic_scholar_abstract(doi)
            if abstract:
                return abstract

        abstract = get_openalex_abstract_for_title(title, authors)
        if abstract:
            return abstract
        return get_semantic_scholar_abstract_for_title(title, authors)

    def get_publisher_url(self, paper_html):
        ee = paper_html.find('li', {'class': 'ee'})
        publisher_url = ee.find('a').get('href')
        return publisher_url

    @abstractmethod
    def get_abstract_from_publisher(self, url, authors):
        pass

class AbstractNDSS(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        logger.debug(f'URL: {url}')
        html = load_publisher_soup(url)
        if html is None:
            return ""
        paper_data = html.find('div', {'class': 'paper-data'})
        if paper_data is not None:
            first_author = authors[0] if authors else None
            abstract_paragraphs = filter(
                lambda x: x.get_text(strip=True) != '' and (first_author is None or first_author not in x.get_text()),
                paper_data.find_all('p'),
            )
            ap_list = [x.get_text(separator='\n', strip=True) for x in abstract_paragraphs]
            return '\n'.join(ap_list)
        abstract_marker = html.find(string=re.compile(r"Abstract:?", re.I))
        if abstract_marker is None:
            return extract_meta_description(html)
        abstract_paragraphs = abstract_marker.find_next(recursive=False)
        return abstract_paragraphs.get_text(separator='\n', strip=True)


class AbstractSP(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, _):
        doi = resolve_doi(url)
        if doi:
            return get_openalex_abstract(doi)

        html = load_publisher_soup(url)
        if html is None:
            return ""

        for attrs in (
            {"name": "description"},
            {"property": "og:description"},
        ):
            meta = html.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                return meta["content"]
        return ""


class AbstractUSENIX(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        logger.debug(f'URL: {url}')
        html = load_publisher_soup(url)
        if html is None:
            return ""

        abstract_div = html.find('div', {'class': 'field-name-field-paper-description'})
        if abstract_div:
            return abstract_div.get_text(separator='\n', strip=True)

        # Fallback for older page layouts
        abstract_marker = html.find(string=re.compile(r"Abstract:?", re.I))
        if abstract_marker:
            return abstract_marker.find_next(recursive=False).get_text(separator='\n', strip=True)

        return extract_meta_description(html)


class AbstractCCS(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        logger.debug(f'URL: {url}')
        doi = resolve_doi(url)
        if doi:
            abstract = get_openalex_abstract(doi)
            if abstract:
                return abstract

        html = load_publisher_soup(url)
        if html is not None:
            abstract_paragraphs = html.find('div', {'class': 'abstractInFull'})
            if abstract_paragraphs is not None:
                return abstract_paragraphs.get_text(separator='\n', strip=True)
            meta_description = extract_meta_description(html)
            if meta_description:
                return meta_description
        return ""

NDSS = AbstractNDSS()
SP = AbstractSP()
USENIX = AbstractUSENIX()
CCS = AbstractCCS()

Abstracts = {'NDSS': NDSS,
             'IEEE S&P': SP,
             'USENIX': USENIX,
             'CCS': CCS}

if __name__ == '__main__':
    logger.setLevel('DEBUG')
    print(SP.get_abstract_from_publisher('https://doi.org/10.1109/SP46215.2023.10179381', []))
    print(NDSS.get_abstract_from_publisher('https://www.ndss-symposium.org/ndss2015/i-do-not-know-what-you-visited-last-summer-protecting-users-third-party-web-tracking', []))
