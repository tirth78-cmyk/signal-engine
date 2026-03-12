"""
PR Wire scrapers — Monitor press releases from major wire services.
Covers: PR Newswire, Business Wire, GlobeNewswire.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.models import RawSignalInput, SourceType


class PRWireScraper(BaseScraper):
    """Scrapes press releases from PR wire services."""

    name = "pr_wires"
    source_type = SourceType.PR_WIRE

    # PR wire search endpoints
    SOURCES = {
        "prnewswire": {
            "base_url": "https://www.prnewswire.com/search/news/",
            "parse_method": "_parse_prnewswire",
        },
        "businesswire": {
            "base_url": "https://www.businesswire.com/portal/site/home/news/",
            "parse_method": "_parse_businesswire",
        },
        "globenewswire": {
            "base_url": "https://www.globenewswire.com/search/",
            "parse_method": "_parse_globenewswire",
        },
    }

    PHARMA_QUERIES = [
        "pharmaceutical data analytics",
        "pharma digital transformation",
        "biotech leadership appointment",
        "pharmaceutical partnership",
        "clinical data platform",
        "pharma AI machine learning",
        "drug discovery technology",
        "pharmaceutical expansion India",
        "GCC pharmaceutical",
        "Veeva Databricks pharma",
    ]

    async def _parse_prnewswire(self, client, query: str) -> list[RawSignalInput]:
        """Parse PR Newswire search results."""
        signals = []
        url = f"https://www.prnewswire.com/search/news/?keyword={query}&page=1&pagesize=25"
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            articles = soup.select("div.card, article.news-release, div.row.newsCards")

            for article in articles[:15]:
                title_el = article.select_one("h3 a, h2 a, a.newsreleaseconsolidatelink")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    link = f"https://www.prnewswire.com{link}"

                desc_el = article.select_one("p, div.description")
                description = desc_el.get_text(strip=True) if desc_el else ""

                date_el = article.select_one("small, time, span.date")
                published = None
                if date_el and date_el.get("datetime"):
                    try:
                        published = datetime.fromisoformat(date_el["datetime"])
                    except (ValueError, TypeError):
                        pass

                signals.append(RawSignalInput(
                    title=title[:500],
                    description=description[:2000],
                    source_url=link,
                    source_type=self.source_type,
                    source_name="PR Newswire",
                    raw_content=description,
                    published_at=published,
                ))
        except Exception as e:
            self.logger.warning("prnewswire_error", error=str(e))

        return signals

    async def _parse_businesswire(self, client, query: str) -> list[RawSignalInput]:
        """Parse Business Wire search results."""
        signals = []
        url = f"https://www.businesswire.com/portal/site/home/news/?searchTerm={query}"
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            articles = soup.select("div.bw-news-item, li.bwNewsItem, table.bw-release-list tr")

            for article in articles[:15]:
                title_el = article.select_one("a, h3 a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    link = f"https://www.businesswire.com{link}"

                desc_el = article.select_one("span.bw-release-description, p")
                description = desc_el.get_text(strip=True) if desc_el else ""

                signals.append(RawSignalInput(
                    title=title[:500],
                    description=description[:2000],
                    source_url=link,
                    source_type=self.source_type,
                    source_name="Business Wire",
                    raw_content=description,
                ))
        except Exception as e:
            self.logger.warning("businesswire_error", error=str(e))

        return signals

    async def _parse_globenewswire(self, client, query: str) -> list[RawSignalInput]:
        """Parse GlobeNewswire search results."""
        signals = []
        url = f"https://www.globenewswire.com/search?keyword={query}"
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            articles = soup.select("div.results-link, div.main-results-container div.pagging-list-item")

            for article in articles[:15]:
                title_el = article.select_one("a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    link = f"https://www.globenewswire.com{link}"

                signals.append(RawSignalInput(
                    title=title[:500],
                    description="",
                    source_url=link,
                    source_type=self.source_type,
                    source_name="GlobeNewswire",
                    raw_content="",
                ))
        except Exception as e:
            self.logger.warning("globenewswire_error", error=str(e))

        return signals

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape all PR wire sources."""
        queries = self.PHARMA_QUERIES.copy()
        if target_companies:
            queries.extend(target_companies)

        async with self._get_client() as client:
            for query in queries:
                # PR Newswire
                for signal in await self._parse_prnewswire(client, query):
                    yield signal

                # Business Wire
                for signal in await self._parse_businesswire(client, query):
                    yield signal

                # GlobeNewswire
                for signal in await self._parse_globenewswire(client, query):
                    yield signal

                await asyncio.sleep(1.0)
