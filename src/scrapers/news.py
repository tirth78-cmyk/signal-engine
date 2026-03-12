"""
News scrapers — NewsAPI.org + RSS feeds for real-time news monitoring.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import quote_plus

import feedparser
import httpx
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.models import RawSignalInput, SourceType


class NewsAPIScraper(BaseScraper):
    """Scrapes news articles from NewsAPI.org and GNews."""

    name = "newsapi"
    source_type = SourceType.NEWS_API

    # Configurable API endpoints
    ENDPOINTS = {
        "newsapi": "https://newsapi.org/v2/everything",
        "gnews": "https://gnews.io/api/v4/search",
        "newsdata": "https://newsdata.io/api/1/news",
    }

    # Pharma/Life Sciences keywords for GTM signals
    SIGNAL_KEYWORDS = [
        "chief data officer appointed", "VP data analytics hired",
        "Databricks partnership", "Snowflake migration",
        "data platform modernization", "AI ML investment",
        "digital transformation pharma", "real world evidence",
        "clinical data management", "FDA approval",
        "pharma expansion", "new manufacturing facility",
        "biotech funding round", "pharmaceutical merger",
        "CDMO partnership", "GCC India opening",
        "Veeva migration", "IQVIA partnership",
    ]

    def __init__(self, api_keys: dict[str, str] | None = None):
        super().__init__()
        self.api_keys = api_keys or {}

    async def _search_newsapi(
        self, client: httpx.AsyncClient, query: str, page: int = 1
    ) -> list[dict]:
        """Search NewsAPI.org."""
        api_key = self.api_keys.get("newsapi", "")
        if not api_key:
            return []

        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 50,
            "page": page,
            "apiKey": api_key,
        }
        try:
            resp = await self._fetch(client, f"{self.ENDPOINTS['newsapi']}?{'&'.join(f'{k}={quote_plus(str(v))}' for k, v in params.items())}")
            data = resp.json()
            return data.get("articles", [])
        except Exception as e:
            self.logger.warning("newsapi_error", error=str(e))
            return []

    async def _search_gnews(
        self, client: httpx.AsyncClient, query: str
    ) -> list[dict]:
        """Search GNews API."""
        api_key = self.api_keys.get("gnews", "")
        if not api_key:
            return []

        params = {
            "q": query,
            "lang": "en",
            "max": 50,
            "token": api_key,
        }
        try:
            resp = await self._fetch(client, f"{self.ENDPOINTS['gnews']}?{'&'.join(f'{k}={quote_plus(str(v))}' for k, v in params.items())}")
            data = resp.json()
            return data.get("articles", [])
        except Exception as e:
            self.logger.warning("gnews_error", error=str(e))
            return []

    def _parse_article(self, article: dict, source_name: str) -> RawSignalInput:
        """Convert API article to RawSignalInput."""
        published = None
        if article.get("publishedAt"):
            try:
                published = datetime.fromisoformat(
                    article["publishedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        return RawSignalInput(
            title=article.get("title", "")[:500],
            description=article.get("description", ""),
            source_url=article.get("url", ""),
            source_type=self.source_type,
            source_name=source_name,
            raw_content=article.get("content", ""),
            published_at=published,
        )

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape news from multiple API sources."""
        queries = []
        if target_companies:
            for company in target_companies:
                for kw in self.SIGNAL_KEYWORDS[:5]:  # top keywords per company
                    queries.append(f'"{company}" {kw}')
        else:
            queries = self.SIGNAL_KEYWORDS

        async with self._get_client() as client:
            for query in queries:
                # NewsAPI
                articles = await self._search_newsapi(client, query)
                for article in articles:
                    yield self._parse_article(article, "NewsAPI")

                # GNews
                articles = await self._search_gnews(client, query)
                for article in articles:
                    yield self._parse_article(article, "GNews")

                await asyncio.sleep(0.5)  # throttle between queries


class RSSFeedScraper(BaseScraper):
    """Scrapes RSS/Atom feeds from pharma newsrooms and industry publications."""

    name = "rss_feeds"
    source_type = SourceType.RSS_FEED

    # Target RSS feeds for pharma/life sciences
    FEEDS = {
        # Company newsrooms
        "Pfizer Newsroom": "https://www.pfizer.com/news/press-releases/rss",
        "Novartis Media": "https://www.novartis.com/news/media-releases/rss",
        "Roche Media": "https://www.roche.com/media/releases/rss",
        "AstraZeneca Press": "https://www.astrazeneca.com/media-centre/press-releases.rss",
        "Sanofi Newsroom": "https://www.sanofi.com/en/media-room/press-releases/rss",
        "Amgen News": "https://www.amgen.com/newsroom/rss",
        "Gilead Press": "https://www.gilead.com/news-and-press/press-room/press-releases.rss",
        # Industry publications
        "FiercePharma": "https://www.fiercepharma.com/rss/xml",
        "BioPharma Dive": "https://www.biopharmadive.com/feeds/news/",
        "STAT News": "https://www.statnews.com/feed/",
        "Endpoints News": "https://endpts.com/feed/",
        "PharmaTimes": "https://www.pharmatimes.com/rss",
        # Technology
        "Healthcare IT News": "https://www.healthcareitnews.com/feed",
        "Drug Discovery Today": "https://www.drugdiscoverytoday.com/rss",
    }

    async def _parse_feed(self, client: httpx.AsyncClient, name: str, url: str) -> list[RawSignalInput]:
        """Parse a single RSS feed."""
        signals = []
        try:
            response = await self._fetch(client, url)
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:20]:  # last 20 entries per feed
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                description = ""
                if hasattr(entry, "summary"):
                    soup = BeautifulSoup(entry.summary, "html.parser")
                    description = soup.get_text(strip=True)[:2000]

                signals.append(RawSignalInput(
                    title=entry.get("title", "")[:500],
                    description=description,
                    source_url=entry.get("link", ""),
                    source_type=self.source_type,
                    source_name=name,
                    raw_content=description,
                    published_at=published,
                ))
        except Exception as e:
            self.logger.warning("rss_feed_error", feed=name, error=str(e))

        return signals

    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """Scrape all configured RSS feeds concurrently."""
        async with self._get_client() as client:
            tasks = [
                self._parse_feed(client, name, url)
                for name, url in self.FEEDS.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, list):
                    for signal in result:
                        yield signal
