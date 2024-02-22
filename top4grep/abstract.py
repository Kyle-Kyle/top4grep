"""
Test: python3 -m top4grep.abstract
"""
import re
import requests
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from urllib.parse import urlparse, urlunparse

from .utils import new_logger

logger = new_logger('PaperAbstract')
logger.setLevel('WARNING')

class BasePaperAbstract(ABC):
    def get_abstract(self, paper_html, title, authors):
        # import ipdb; ipdb.set_trace()
        # logger.debug(f"abstracting {paper_html}, title: {title}")
        try:
            publisher_url = self.get_publisher_url(paper_html)
        except Exception as e:
            logger.debug(f"Failed to obtain publisher URL. Paper: {title}")
            return ""
        else:
            try:
                return self.get_abstract_from_publisher(publisher_url, authors)
            except Exception as e:
                logger.debug(f"Failed to extract abstract from publisher URL {publisher_url}.")
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
        logger.debug(f'URL: {url}')
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
    def has_abstract_sibling(self, tag):
        return any(sibling for sibling in tag.find_all_next() if sibling.get_text(strip=True) == 'Abstract')
   
    def update_url(self, url):
        parsed_url = urlparse(url)
        ieee_netloc = 'doi.ieeecomputersociety.org'
        doi_netlog = 'doi.org'
        if parsed_url.netloc != ieee_netloc and parsed_url.netloc != 'doi.org':
            modified_url = urlunparse((parsed_url.scheme, ieee_netloc, parsed_url.path,
                            parsed_url.params, parsed_url.query, parsed_url.fragment))
            return modified_url
        else:
            return url

    def _get_abstract_from_computerorg(self, url):
        # TODO: handle the case when Chrome is not available
        driver = webdriver.Chrome()
        url = self.update_url(url)
        driver.get(url)


        # Wait for the dynamic element to be present on the page
        element = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.TAG_NAME, 'article')))
        # TODO: I'm not sure if this can handle abstracts with multiple paragraphs
        abstract = element.find_element(By.CLASS_NAME, 'article-content').text
        driver.quit()
        return abstract
    
    def _get_abstract_from_ieeexplore(self, url):
        # TODO: handle the case when Chrome is not available
        driver = webdriver.Chrome()
        url = self.update_url(url)
        logger.debug(f'URL: {url}')
        driver.get(url)

        # Wait for the dynamic element to be present on the page
        element = WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CLASS_NAME, 'abstract-text')))
        temp = element.find_elements(By.CLASS_NAME, 'abstract-text-view-all')
        if len(temp) > 0:
            # If there's a view all button
            view_all = temp[0]
            driver.execute_script("arguments[0].scrollIntoView(true);", view_all)
            view_all.click()
            text = driver.find_element(By.CLASS_NAME, 'abstract-text').text
        else:
            text = element.text
        
        if text.find('Abstract:\n') >= 0:
            text = text[text.find('Abstract:\n') + len('Abstract:\n'):]
        if text.find('\n(Show Less)') >= 0:
            text = text[:text.find('\n(Show Less)')]
        
        driver.close()
        return text
    
    def get_abstract_from_publisher(self, url, _):
        # TODO: this is super slow. Maybe not Selenium?
        parsed_url = urlparse(url)
        ieee_netloc = 'doi.ieeecomputersociety.org'
        doi_netlog = 'doi.org'
        if parsed_url.netloc == ieee_netloc:  
            return self._get_abstract_from_computerorg(url)
        elif parsed_url.netloc == doi_netlog:
            return self._get_abstract_from_ieeexplore(url)
        else:
            raise NotImplementedError


class AbstractUSENIX(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        r = requests.get(url)
        logger.debug(f'URL: {url}')
        assert r.status_code == 200

        html = BeautifulSoup(r.text, 'html.parser')

        abstract_paragraphs = html.find(string=re.compile("Abstract:")).find_next(recursive=False)
        return abstract_paragraphs.get_text(separator='\n')


class AbstractCCS(BasePaperAbstract):
    def get_abstract_from_publisher(self, url, authors):
        # TODO: ACM library doesn't like me to crawl and will ban me when upset.
        logger.debug(f'URL: {url}')
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
    logger.setLevel('DEBUG')
    # SP.get_abstract_from_publisher('https://doi.ieeecomputersociety.org/10.1109/SP46215.2023.00131', [])
    # SP.get_abstract_from_publisher('https://doi.org/10.1109/SP46215.2023.10179411', [])
    # print(SP.get_abstract_from_publisher('https://doi.org/10.1109/SP46215.2023.10179381', []))
    # print(USENIX.get_abstract_from_publisher('https://www.usenix.org/conference/usenixsecurity20/presentation/cremers', []))
    # print(CCS.get_abstract_from_publisher('https://doi.org/10.1145/3576915.3616615', []))
    print(NDSS.get_abstract_from_publisher('https://www.ndss-symposium.org/ndss2015/i-do-not-know-what-you-visited-last-summer-protecting-users-third-party-web-tracking', []))
