"""
Indeed job board adapter using Playwright.

ToS-aware, opt-in scraping. See plan/PLAN.md Phase 5 for the intended
feature-flag and cookie-jar/session design.
"""
import logging
import re
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright

from ..models import Job
from ..sources import SourceAdapter

logger = logging.getLogger(__name__)


class IndeedAdapter(SourceAdapter):
    """Adapter for scraping Indeed job listings using Playwright"""

    def __init__(self, proxy: str = None):
        self.base_url = "https://www.indeed.com"
        self.proxy = proxy
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None

    def _setup_browser(self):
        """Initialize the browser."""
        if self.browser:
            return
        self.playwright = sync_playwright().start()
        context_options = {}
        if self.proxy:
            context_options["proxy"] = {"server": self.proxy}
        self.browser = self.playwright.chromium.launch(headless=True, **context_options)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def _close_browser(self):
        """Close the browser and the underlying Playwright driver."""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None

    @staticmethod
    def _extract_job_id(url: str) -> str:
        """Extract the Indeed jk token from a /viewjob?jk=<jk> href."""
        if not url:
            return ""
        match = re.search(r"[?&]jk=([^&]+)", url)
        return match.group(1) if match else ""

    def get_jobs(self, company_slug: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Get jobs from an Indeed company page"""
        return self._scrape_listings(
            f"{self.base_url}/company/{company_slug}/jobs", limit, raise_errors
        )

    def search_jobs(self, query: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Search for jobs using a query"""
        return self._scrape_listings(
            f"{self.base_url}/jobs?q={query}&limit={limit}", limit, raise_errors
        )

    def _scrape_listings(self, url: str, limit: int, raise_errors: bool = False) -> List[Job]:
        """Open an Indeed results page and normalize visible job cards."""
        try:
            self._setup_browser()
            self.page.goto(url)
            # Polite delay for the results to render.
            self.page.wait_for_timeout(3000)

            jobs = []
            cards = self.page.query_selector_all("td.jobsearch-jobList-result")
            for card in cards[:limit]:
                try:
                    title_el = card.query_selector(".jobTitle")
                    title = title_el.inner_text() if title_el else ""

                    company_el = card.query_selector(".companyName")
                    company = company_el.inner_text() if company_el else ""

                    location_el = card.query_selector(".companyLocation")
                    location = location_el.inner_text() if location_el else ""

                    url_el = card.query_selector("a.jobTitle")
                    url = url_el.get_attribute("href") if url_el else ""
                    if url and not url.startswith("http"):
                        url = f"{self.base_url}{url}"

                    if not url:
                        continue

                    jobs.append(self.normalize_job({
                        "id": self._extract_job_id(url),
                        "title": title,
                        "company": company,
                        "location": location,
                        "description": "",
                        "url": url,
                        "posted_date": None,
                    }))
                except Exception:
                    # A single malformed card shouldn't abort the listing.
                    continue

            return jobs
        except Exception as error:
            logger.warning(f"Error fetching jobs from Indeed: {error}")
            if raise_errors:
                raise
            return []
        finally:
            self._close_browser()

    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about an Indeed job"""
        try:
            self._setup_browser()
            self.page.goto(f"{self.base_url}/viewjob?jk={job_id}")
            self.page.wait_for_timeout(2000)

            title_el = self.page.query_selector("h1.jobsearch-JobInfoHeader-title")
            title = title_el.inner_text() if title_el else ""

            company_el = self.page.query_selector(".jobsearch-JobInfoHeader-subheader")
            company = company_el.inner_text() if company_el else ""

            location = ""
            location_el = self.page.query_selector(".jobsearch-JobInfoHeader-subheader")
            if location_el and "·" in location_el.inner_text():
                location = location_el.inner_text().split("·")[1].strip()

            description_el = self.page.query_selector(".jobsearch-jobDescriptionText")
            description = description_el.inner_text() if description_el else ""

            return self.normalize_job({
                "id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": f"{self.base_url}/viewjob?jk={job_id}",
                "posted_date": None,
            })
        except Exception as error:
            logger.warning(f"Error fetching job detail from Indeed: {error}")
            return None
        finally:
            self._close_browser()