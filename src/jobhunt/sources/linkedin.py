"""
LinkedIn job board adapter using Playwright.

Implements the Phase 5 plan: persisted session cookie jar (headful first
login, headless afterwards with the saved storage state), polite delays,
and ToS-aware. Intended to be feature-flagged / opt-in.
"""
import os
import re
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright

from ..models import Job
from ..sources import SourceAdapter

# Repo-local cache dir, anchored to the project root regardless of CWD.
CACHE_DIR = Path(__file__).resolve().parents[3] / "cache"


class LinkedInAdapter(SourceAdapter):
    """Adapter for scraping LinkedIn job listings using Playwright"""

    def __init__(self, email: str, password: str, session_file: Optional[str] = None):
        self.email = email
        self.password = password
        self.base_url = "https://www.linkedin.com"
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        # Persisted session (cookie jar): credentials are only used for the
        # first headful login; later runs reuse the saved storage state.
        self.session_file = (
            os.path.abspath(session_file)
            if session_file
            else str(CACHE_DIR / "linkedin_session.json")
        )

    def _setup_browser(self):
        """Initialize the browser, restoring a persisted session if present."""
        if self.browser:
            return
        self.playwright = sync_playwright().start()
        has_session = os.path.exists(self.session_file)
        self.browser = self.playwright.chromium.launch(headless=has_session)
        self.context = self.browser.new_context(
            storage_state=self.session_file if has_session else None
        )
        self.page = self.context.new_page()
        if not has_session and self.email and self.password:
            self._login()

    def _login(self):
        """Headful login; persists the session cookie jar for later reuse."""
        self.page.goto(f"{self.base_url}/login")
        self.page.fill("#username", self.email)
        self.page.fill("#password", self.password)
        self.page.click("button[type='submit']")
        self.page.wait_for_url("**/feed/**", timeout=60000)
        Path(self.session_file).parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=self.session_file)

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

    def get_jobs(self, company_slug: str, limit: int = 50) -> List[Job]:
        """Get jobs from a LinkedIn company page"""
        return self._scrape_listings(
            f"{self.base_url}/company/{company_slug}/jobs/", limit
        )

    def search_jobs(self, query: str, limit: int = 50) -> List[Job]:
        """Search for jobs using a query"""
        return self._scrape_listings(
            f"{self.base_url}/jobs/search/?keywords={query}", limit
        )

    def _scrape_listings(self, url: str, limit: int) -> List[Job]:
        """Open a LinkedIn listings page and normalize visible job cards."""
        try:
            self._setup_browser()
            self.page.goto(url)
            # Polite delay for the listing to render.
            self.page.wait_for_timeout(3000)

            jobs = []
            cards = self.page.query_selector_all("li.job-search-results__list-item")
            for card in cards[:limit]:
                try:
                    title_el = card.query_selector(".job-card-list__title")
                    title = title_el.inner_text() if title_el else ""

                    company_el = card.query_selector(".job-card-container__company-name")
                    company = company_el.inner_text() if company_el else ""

                    location_el = card.query_selector(".job-card-container__metadata-item")
                    location = location_el.inner_text() if location_el else ""

                    url_el = card.query_selector("a.job-card-list__title")
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
        except Exception as e:
            print(f"Error fetching jobs from LinkedIn: {e}")
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
        except Exception as e:
            print(f"Error fetching job detail from LinkedIn: {e}")
            return None
        finally:
            self._close_browser()