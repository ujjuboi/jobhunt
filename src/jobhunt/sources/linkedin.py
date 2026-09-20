"""
LinkedIn job board adapter using Playwright.

Implements the Phase 5 plan: persisted session cookie jar (headful first
login, headless afterwards with the saved storage state), polite delays,
and ToS-aware. Intended to be feature-flagged / opt-in.
"""
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright

from ..models import Job
from ..sources import SourceAdapter

logger = logging.getLogger(__name__)

# Repo-local cache dir, anchored to the project root regardless of CWD.
CACHE_DIR = Path(__file__).resolve().parents[3] / "cache"


class LinkedInAdapter(SourceAdapter):
    """Adapter for scraping LinkedIn job listings using Playwright"""

    def __init__(self, session_file: Optional[str] = None):
        self.base_url = "https://www.linkedin.com"
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        # Persisted session (cookie jar): the user signs in once through a
        # browser; later runs reuse the saved storage state.
        self.session_file = (
            os.path.abspath(session_file)
            if session_file
            else str(CACHE_DIR / "linkedin_session.json")
        )

    def _setup_browser(self, headless: Optional[bool] = None):
        """Initialize the browser, restoring a persisted session if present."""
        if self.browser:
            return
        self.playwright = sync_playwright().start()
        has_session = os.path.exists(self.session_file)
        if headless is None:
            headless = has_session
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.context = self.browser.new_context(
            storage_state=self.session_file if has_session else None
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(60000)

    def login(self) -> bool:
        """Perform a one-time interactive LinkedIn login.

        Launches a headful browser and lets the user sign in (including any
        2FA/verification step) without storing credentials. The signed-in
        session is persisted to the local cache so later runs reuse it
        headlessly. Returns True on success and raises on failure.
        """
        try:
            self._setup_browser(headless=False)
            self.page.goto(f"{self.base_url}/login")
            # Wait for the user (and any 2FA/verify step) to finish signing in.
            self.page.wait_for_url("**/feed/**", timeout=300000)
            Path(self.session_file).parent.mkdir(parents=True, exist_ok=True)
            self.context.storage_state(path=self.session_file)
            return True
        except Exception as error:
            logger.warning(f"LinkedIn login failed: {error}")
            raise
        finally:
            self._close_browser()

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
        """Extract the job id from a LinkedIn /jobs/view/<id> href."""
        if not url:
            return ""
        match = re.search(r"/jobs/view/(\d+)", url)
        if match:
            return match.group(1)
        return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]

    def get_jobs(self, company_slug: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Get jobs from a LinkedIn company page"""
        return self._scrape_listings(
            f"{self.base_url}/company/{company_slug}/jobs/", limit, raise_errors
        )

    def search_jobs(self, query: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Search for jobs using a query"""
        return self._scrape_listings(
            f"{self.base_url}/jobs/search/?keywords={query}", limit, raise_errors
        )

    def _scrape_listings(self, url: str, limit: int, raise_errors: bool = False) -> List[Job]:
        """Open a LinkedIn listings page and normalize visible job cards."""
        try:
            self._setup_browser()
            self.page.goto(url)
            # Polite delay for the listing to render.
            self.page.wait_for_timeout(3000)

            jobs = []
            cards = self.page.query_selector_all("div.job-card-container")
            for card in cards[:limit]:
                try:
                    title_el = card.query_selector("a.job-card-container__link")
                    title = title_el.inner_text() if title_el else ""

                    company_el = card.query_selector(".artdeco-entity-lockup__subtitle")
                    company = company_el.inner_text() if company_el else ""

                    location_el = card.query_selector(".job-card-container__metadata-wrapper li")
                    location = location_el.inner_text() if location_el else ""

                    url_el = title_el
                    url = url_el.get_attribute("href") if url_el else ""
                    if url and not url.startswith("http"):
                        url = f"{self.base_url}{url}"

                    if not url:
                        continue

                    jobs.append(self.normalize_job({
                        "id": card.get_attribute("data-job-id") or self._extract_job_id(url),
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
            logger.warning(f"Error fetching jobs from LinkedIn: {error}")
            if raise_errors:
                raise
            return []
        finally:
            self._close_browser()

    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a LinkedIn job"""
        try:
            self._setup_browser()
            self.page.goto(f"{self.base_url}/jobs/view/{job_id}")
            self.page.wait_for_timeout(2000)

            title_el = self.page.query_selector("h1.jobs-unified-top-card__job-title")
            title = title_el.inner_text() if title_el else ""

            company_el = self.page.query_selector(".jobs-unified-top-card__company-name")
            company = company_el.inner_text() if company_el else ""

            location_el = self.page.query_selector(".jobs-unified-top-card__bullet")
            location = location_el.inner_text() if location_el else ""

            description_el = self.page.query_selector(".jobs-description__text")
            description = description_el.inner_text() if description_el else ""

            return self.normalize_job({
                "id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": f"{self.base_url}/jobs/view/{job_id}",
                "posted_date": None,
            })
        except Exception as error:
            logger.warning(f"Error fetching job detail from LinkedIn: {error}")
            return None
        finally:
            self._close_browser()