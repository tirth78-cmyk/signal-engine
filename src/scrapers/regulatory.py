"""
Regulatory scrapers — SEC EDGAR filings and FDA announcements.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.models import RawSignalInput, SourceType


class SECFilingScraper(BaseScraper):
    """Scrapes SEC EDGAR for 10-K, 10-Q, 8-K filings from pharma companies."""

    name = "sec_edgar"
    source_type = SourceType.SEC_FILING

    EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
    EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt={start}&enddt={end}&forms=8-K,10-K,10-Q"

    # CIK numbers for major pharma companies
    PHARMA_CIKS = {
        "Pfizer": "0000078003",
        "Johnson & Johnson": "0000200406",
        "Merck": "0000310158",
        "AbbVie": "0001551152",
        "Eli Lilly": "0000059478",
        "Bristol-Myers Squibb": "0000014272",
        "Amgen": "0000318154",
        "Gilead Sciences": "0000882095",
        "Regeneron": "0000872589",
        "Vertex": "0000875320",
    }

    async def _search_edgar(self, client, cik: str, company: str) -> list[RawSignalInput]:
        """Search EDGAR for recent filings by CIK."""
        signals = []
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=10&search_text=&action=getcompany"

        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            rows = soup.select("table.tableFile2 tr")[1:]  # skip header

            for row in rows[:10]:
                cols = row.select("td")
                if len(cols) < 4:
                    continue

                filing_type = cols[0].get_text(strip=True)
                description = cols[2].get_text(strip=True)
                date_str = cols[3].get_text(strip=True)
                link_el = cols[1].select_one("a")
                link = f"https://www.sec.gov{link_el['href']}" if link_el and link_el.get("href") else ""

                published = None
                try:
                    published = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass

                signals.append(RawSignalInput(
                    title=f"SEC {filing_type}: {company} — {description[:200]}",
                    description=f"{company} filed {filing_type} with SEC: {description}",
                    source_url=link,
                    source_type=self.source_type,
                    source_name="SEC EDGAR",
                    company_name=company,
                    raw_content=description,
                    published_at=published,
                ))
        except Exception as e:
            self.logger.warning("sec_edgar_error", company=company, error=str(e))

        return signals

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape SEC EDGAR for pharma filings."""
        async with self._get_client() as client:
            companies = (
                {k: v for k, v in self.PHARMA_CIKS.items() if k in target_companies}
                if target_companies
                else self.PHARMA_CIKS
            )

            for company, cik in companies.items():
                results = await self._search_edgar(client, cik, company)
                for signal in results:
                    yield signal
                await asyncio.sleep(1.0)  # SEC rate limiting


class RegulatoryNewsScraper(BaseScraper):
    """Scrapes FDA and EMA regulatory announcements."""

    name = "regulatory_news"
    source_type = SourceType.REGULATORY

    FDA_SOURCES = {
        "FDA Approvals": "https://www.fda.gov/drugs/new-drugs-fda-cders-new-molecular-entities-and-new-therapeutic-biological-products/novel-drug-approvals-{year}",
        "FDA Press": "https://www.fda.gov/news-events/press-announcements",
        "FDA Drug Safety": "https://www.fda.gov/drugs/drug-safety-and-availability",
    }

    EMA_SOURCES = {
        "EMA News": "https://www.ema.europa.eu/en/news",
        "EMA Decisions": "https://www.ema.europa.eu/en/medicines/field_ema_web_categories%253Aname_field/Human/ema_group_types/ema_medicine",
    }

    async def _scrape_fda(self, client) -> list[RawSignalInput]:
        """Scrape FDA press announcements."""
        signals = []
        url = "https://www.fda.gov/news-events/press-announcements"
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            items = soup.select("li.views-row, div.view-content li, ul.list-reset li")

            for item in items[:20]:
                link_el = item.select_one("a")
                if not link_el:
                    continue

                title = link_el.get_text(strip=True)
                href = link_el.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://www.fda.gov{href}"

                date_el = item.select_one("time, span.date-display-single")
                published = None
                if date_el and date_el.get("datetime"):
                    try:
                        published = datetime.fromisoformat(date_el["datetime"])
                    except (ValueError, TypeError):
                        pass

                signals.append(RawSignalInput(
                    title=f"FDA: {title[:450]}",
                    description=title,
                    source_url=href,
                    source_type=self.source_type,
                    source_name="FDA",
                    raw_content=title,
                    published_at=published,
                ))
        except Exception as e:
            self.logger.warning("fda_scrape_error", error=str(e))

        return signals

    async def _scrape_ema(self, client) -> list[RawSignalInput]:
        """Scrape EMA news."""
        signals = []
        url = "https://www.ema.europa.eu/en/news"
        try:
            response = await self._fetch(client, url)
            soup = BeautifulSoup(response.text, "lxml")
            items = soup.select("article, div.views-row, li.ecl-content-item")

            for item in items[:20]:
                title_el = item.select_one("h2 a, h3 a, a.ecl-content-item__title")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://www.ema.europa.eu{href}"

                signals.append(RawSignalInput(
                    title=f"EMA: {title[:450]}",
                    description=title,
                    source_url=href,
                    source_type=self.source_type,
                    source_name="EMA",
                    raw_content=title,
                ))
        except Exception as e:
            self.logger.warning("ema_scrape_error", error=str(e))

        return signals

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape regulatory sources."""
        async with self._get_client() as client:
            # FDA
            for signal in await self._scrape_fda(client):
                yield signal

            await asyncio.sleep(1.0)

            # EMA
            for signal in await self._scrape_ema(client):
                yield signal
