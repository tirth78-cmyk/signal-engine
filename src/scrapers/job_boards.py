"""
Job Board scrapers — Detect hiring signals from job postings.
Covers: LinkedIn Jobs, Indeed, Glassdoor, company career pages.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.models import RawSignalInput, SourceType


class JobBoardScraper(BaseScraper):
    """Scrapes job postings that indicate buying signals."""

    name = "job_boards"
    source_type = SourceType.JOB_BOARD

    # Job titles that signal data/analytics buying intent
    SIGNAL_JOB_TITLES = [
        "Chief Data Officer",
        "VP Data Analytics",
        "Head of Data Engineering",
        "Director Data Science",
        "Data Platform Architect",
        "Databricks Engineer",
        "Snowflake Architect",
        "Machine Learning Engineer pharma",
        "AI Lead pharmaceutical",
        "Real World Evidence Analyst",
        "Clinical Data Manager",
        "Veeva Administrator",
        "Digital Transformation Lead",
        "Head of Commercial Analytics",
        "Director RWE",
    ]

    # Company career page patterns
    CAREER_PAGES = {
        "Novartis": "https://www.novartis.com/careers/search-jobs?query={query}",
        "Pfizer": "https://careers.pfizer.com/search-jobs?query={query}",
        "Roche": "https://careers.roche.com/global/en/search-results?keywords={query}",
        "AstraZeneca": "https://careers.astrazeneca.com/search-jobs?query={query}",
        "Sanofi": "https://careers.sanofi.com/search-jobs?query={query}",
        "Amgen": "https://careers.amgen.com/search-jobs?query={query}",
        "Gilead": "https://gilead.wd1.myworkdayjobs.com/gileadExternalJobs?q={query}",
        "BMS": "https://careers.bms.com/search-jobs?query={query}",
        "Merck": "https://jobs.merck.com/search-jobs?query={query}",
        "Eli Lilly": "https://careers.lilly.com/search-jobs?query={query}",
    }

    async def _scrape_indeed(self, client, query: str) -> list[RawSignalInput]:
        """Scrape Indeed for job postings."""
        signals = []
        url = f"https://www.indeed.com/jobs?q={query}&l=&sort=date&limit=25"
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.select("div.job_seen_beacon, div.jobsearch-SerpJobCard, td.resultContent")

            for card in cards[:20]:
                title_el = card.select_one("h2 a, a.jcs-JobTitle")
                company_el = card.select_one("span[data-testid='company-name'], span.companyName")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else ""
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    link = f"https://www.indeed.com{link}"

                location_el = card.select_one("div[data-testid='text-location'], div.companyLocation")
                location = location_el.get_text(strip=True) if location_el else ""

                desc = f"{title} at {company}" + (f" — {location}" if location else "")

                signals.append(RawSignalInput(
                    title=f"Hiring: {title}",
                    description=desc[:2000],
                    source_url=link,
                    source_type=self.source_type,
                    source_name="Indeed",
                    company_name=company,
                    raw_content=desc,
                ))
        except Exception as e:
            self.logger.warning("indeed_error", query=query, error=str(e))

        return signals

    async def _scrape_career_page(
        self, client, company: str, url_template: str, query: str
    ) -> list[RawSignalInput]:
        """Scrape a company career page."""
        signals = []
        url = url_template.format(query=query)
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")

            # Generic job card selectors
            job_cards = soup.select(
                "li.job-card, div.job-listing, article.job, "
                "div[data-job-id], tr.job-row, div.search-result"
            )

            for card in job_cards[:10]:
                title_el = card.select_one("a, h2, h3, span.job-title")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    link = f"{url.split('/search')[0]}{link}"

                signals.append(RawSignalInput(
                    title=f"Hiring: {title}",
                    description=f"{company} is hiring for {title}",
                    source_url=link,
                    source_type=self.source_type,
                    source_name=f"{company} Careers",
                    company_name=company,
                    raw_content=f"{company} job posting: {title}",
                ))
        except Exception as e:
            self.logger.warning("career_page_error", company=company, error=str(e))

        return signals

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape job boards for hiring signals."""
        async with self._get_client() as client:
            # Phase 1: Indeed search for signal job titles
            for job_title in self.SIGNAL_JOB_TITLES:
                query = f'"{job_title}" pharmaceutical'
                results = await self._scrape_indeed(client, query)
                for signal in results:
                    yield signal
                await asyncio.sleep(2.0)  # Indeed rate limiting

            # Phase 2: Company career pages
            data_queries = ["data engineer", "data scientist", "Databricks", "analytics"]
            for company, url_template in self.CAREER_PAGES.items():
                if target_companies and company not in target_companies:
                    continue
                for query in data_queries:
                    results = await self._scrape_career_page(
                        client, company, url_template, query
                    )
                    for signal in results:
                        yield signal
                    await asyncio.sleep(1.5)
