"""
LinkedIn scraper — Monitors leadership changes and company updates.
Uses public profile data only (no authentication required).
"""

import asyncio
from typing import AsyncIterator

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.models import RawSignalInput, SourceType


class LinkedInScraper(BaseScraper):
    """
    Scrapes publicly available LinkedIn data for leadership signals.
    Uses Google search index for LinkedIn posts/profiles (no auth needed).
    """

    name = "linkedin"
    source_type = SourceType.LINKEDIN

    SEARCH_QUERIES = [
        'site:linkedin.com/posts "new role" "chief data officer" pharmaceutical',
        'site:linkedin.com/posts "excited to announce" "VP" "data" pharma',
        'site:linkedin.com/posts "joined" "head of" "analytics" pharmaceutical',
        'site:linkedin.com/posts "appointed" "director" "data" biotech',
        'site:linkedin.com/posts "Databricks" "pharma" announcement',
        'site:linkedin.com/posts "digital transformation" pharmaceutical leadership',
        'site:linkedin.com/pulse pharmaceutical data analytics',
    ]

    async def _search_google_for_linkedin(self, client, query: str) -> list[RawSignalInput]:
        """Use Google search to find public LinkedIn posts."""
        signals = []
        encoded = query.replace(" ", "+")
        url = f"https://www.google.com/search?q={encoded}&tbs=qdr:w&num=20"

        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            results = soup.select("div.g, div[data-sokoban-container]")

            for result in results[:15]:
                link_el = result.select_one("a[href]")
                title_el = result.select_one("h3")
                snippet_el = result.select_one("div.VwiC3b, span.aCOpRe")

                if not link_el or not title_el:
                    continue

                href = link_el.get("href", "")
                if "linkedin.com" not in href:
                    continue

                title = title_el.get_text(strip=True)
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                signals.append(RawSignalInput(
                    title=title[:500],
                    description=snippet[:2000],
                    source_url=href,
                    source_type=self.source_type,
                    source_name="LinkedIn (via Google)",
                    raw_content=f"{title}\n{snippet}",
                ))
        except Exception as e:
            self.logger.warning("linkedin_google_error", error=str(e))

        return signals

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape LinkedIn signals via Google search."""
        queries = self.SEARCH_QUERIES.copy()

        if target_companies:
            for company in target_companies:
                queries.append(
                    f'site:linkedin.com/posts "{company}" "data" OR "analytics" OR "digital"'
                )

        async with self._get_client() as client:
            for query in queries:
                results = await self._search_google_for_linkedin(client, query)
                for signal in results:
                    yield signal
                await asyncio.sleep(3.0)  # Google rate limiting
