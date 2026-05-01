"""
Test: python3 -m top4grep.abstract
"""
import re
import requests
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .utils import new_logger

logger = new_logger("PaperAbstract")
logger.setLevel("WARNING")

class BasePaperAbstract(ABC):
    def get_abstract(self, paper_html, title, authors):
        # import ipdb; ipdb.set_trace()
        try:
            publisher_url = self.get_publisher_url(paper_html)
        except Exception as e:
            logger.warning("Failed to obtain publisher URL for paper %r: %s", title, e)
            return ""
        else:
            try:
                return self.get_abstract_from_publisher(publisher_url, authors)
            except requests.RequestException as e:
                logger.warning("Failed to fetch abstract for paper %r from %s: %s", title, publisher_url, e)
            except Exception as e:
                logger.exception("Failed to extract abstract for paper %r from %s: %s", title, publisher_url, e)
            return ""

    def get_publisher_url(self, paper_html):
        ee = paper_html.find('li', {'class': 'ee'})
        publisher_url = ee.find('a').get('href')
        return publisher_url

    @abstractmethod
    def get_abstract_from_publisher(self, url, authors):
        pass

class AbstractNDSS(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        logger.debug("URL: %s", url)
        r = requests.get(url)
        assert r.status_code == 200

        html = BeautifulSoup(r.text, 'html.parser')
        paper_data = html.find('div', {'class': 'paper-data'})
        if paper_data is not None:
            abstract_paragraphs = filter(lambda x: x.text != '' and not authors[0] in x.text, paper_data.find_all('p'))
            ap_list = [x.text for x in abstract_paragraphs]
            return '\n'.join(ap_list)
        else:
            abstract_paragraphs = html.find(string=re.compile("Abstract:")).find_next(recursive=False)
            return abstract_paragraphs.get_text(separator='\n')


class AbstractSP(BasePaperAbstract):
    GRAPHQL_URL = "https://www.computer.org/csdl/api/v1/graphql"
    ARTICLE_FIELDS = """
        id
        abstract
        normalizedAbstract
        abstracts {
            abstractType
            content
        }
    """

    def _query_graphql(self, query, variables):
        response = requests.post(
            self.GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers={"origin": "https://www.computer.org"},
        )
        response.raise_for_status()

        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        return payload.get("data", {})

    def _get_article_by_doi(self, doi):
        query = f"""
            query ($doi: String!) {{
                article: articleByDoi(doi: $doi) {{
                    {self.ARTICLE_FIELDS}
                }}
            }}
        """
        return self._query_graphql(query, {"doi": doi}).get("article")

    def _get_article_by_id(self, article_id):
        query = f"""
            query ($articleId: String!) {{
                article: articleById(articleId: $articleId) {{
                    {self.ARTICLE_FIELDS}
                }}
            }}
        """
        return self._query_graphql(query, {"articleId": article_id}).get("article")

    def _doi_from_url(self, url):
        match = re.search(r"10\.1109/[^/?#]+", url)
        if match:
            return match.group(0)
        return None

    def _article_id_from_url(self, url):
        parsed_url = urlparse(url)
        path_parts = [part for part in parsed_url.path.split("/") if part]
        if "proceedings-article" not in path_parts:
            return None
        return path_parts[-1] if path_parts else None

    def _clean_abstract(self, abstract):
        return BeautifulSoup(abstract, "html.parser").get_text(separator=" ", strip=True)

    def _extract_abstract(self, article):
        candidates = [article.get("normalizedAbstract"), article.get("abstract")]
        abstracts = article.get("abstracts") or []
        candidates.extend(
            abstract.get("content")
            for abstract in abstracts
            if (abstract.get("abstractType") or "").lower() == "regular"
        )
        candidates.extend(abstract.get("content") for abstract in abstracts)

        for candidate in candidates:
            if candidate:
                return self._clean_abstract(candidate)
        return ""

    def get_abstract_from_publisher(self, url, _):
        logger.debug("URL: %s", url)

        article = None
        article_id = self._article_id_from_url(url)
        if article_id:
            article = self._get_article_by_id(article_id)

        doi = self._doi_from_url(url)
        if not article and doi:
            article = self._get_article_by_doi(doi)

        if not article:
            logger.warning("Failed to resolve IEEE S&P article from %s", url)
            return ""

        return self._extract_abstract(article)


class AbstractUSENIX(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        r = requests.get(url)
        logger.debug("URL: %s", url)
        assert r.status_code == 200

        html = BeautifulSoup(r.text, 'html.parser')

        abstract_paragraphs = html.find(string=re.compile("Abstract:")).find_next(recursive=False)
        return abstract_paragraphs.get_text(separator='\n')


class AbstractCCS(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        # TODO: ACM library doesn't like me to crawl and will ban me when upset.
        logger.debug("URL: %s", url)
        r = requests.get(url)
        assert r.status_code == 200

        html = BeautifulSoup(r.text, 'html.parser')
        abstract_paragraphs = html.find('div', {'class': 'abstractInFull'})
        return abstract_paragraphs.get_text(separator='\n')
        # ap_list = [x.text for x in abstract_paragraphs]
        # return '\n'.join(ap_list)

NDSS = AbstractNDSS()
SP = AbstractSP()
USENIX = AbstractUSENIX()
CCS = AbstractCCS()

Abstracts = {'NDSS': NDSS,
             'IEEE S&P': SP,
             'USENIX': USENIX,
             'CCS': CCS}

if __name__ == '__main__':
    logger.setLevel("DEBUG")
    print(SP.get_abstract_from_publisher('https://doi.org/10.1109/SP46215.2023.10179381', []))
    # print(USENIX.get_abstract_from_publisher('https://www.usenix.org/conference/usenixsecurity20/presentation/cremers', []))
    # print(CCS.get_abstract_from_publisher('https://doi.org/10.1145/3576915.3616615', []))
    # print(NDSS.get_abstract_from_publisher('https://www.ndss-symposium.org/ndss2015/i-do-not-know-what-you-visited-last-summer-protecting-users-third-party-web-tracking', []))
