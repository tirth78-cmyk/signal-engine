"""
Base scraper class — all scrapers inherit from this.
Provides rate limiting, retry logic, session management, and metrics.
"""

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import settings
from src.models import RawSignalInput, SourceType, ScraperStatus
from src.utils.logging import get_logger


class BaseScraper(ABC):
    """Abstract base for all signal scrapers."""

    name: str = "base"
    source_type: SourceType = SourceType.CUSTOM_WEB

    def __init__(self):
        self.logger = get_logger(f"scraper.{self.name}")
        self.status = ScraperStatus.IDLE
        self.signals_found = 0
        self.errors = 0
        self.last_run_at: datetime | None = None
        self.last_duration: float = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time: dict[str, float] = {}

    async def _rate_limit(self, domain: str):
        """Enforce per-domain rate limiting."""
        async with self._rate_limit_lock:
            now = time.monotonic()
            last = self._last_request_time.get(domain, 0)
            wait_time = settings.scraper.rate_limit_per_domain - (now - last)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_time[domain] = time.monotonic()

    def _get_client(self) -> httpx.AsyncClient:
        """Create a configured HTTP client."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(settings.scraper.request_timeout),
            headers={
                "User-Agent": settings.scraper.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            follow_redirects=True,
            proxy=settings.scraper.proxy_url,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def _fetch(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """Fetch a URL with retry and rate limiting."""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        await self._rate_limit(domain)
        response = await client.get(url)
        response.raise_for_status()
        return response

    @staticmethod
    def content_hash(text: str) -> str:
        """Generate SHA-256 hash for deduplication."""
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    @abstractmethod
    async def scrape(self, target_companies: list[str] | None = None) -> AsyncIterator[RawSignalInput]:
        """
        Main scrape method. Yields RawSignalInput items as they are found.
        Override in each scraper implementation.
        """
        ...

    async def run(self, target_companies: list[str] | None = None) -> list[RawSignalInput]:
        """Execute the scraper with metrics tracking."""
        self.status = ScraperStatus.RUNNING
        self.signals_found = 0
        self.errors = 0
        start = time.monotonic()
        results: list[RawSignalInput] = []

        try:
            self.logger.info("scraper_started", scraper=self.name)
            async for signal in self.scrape(target_companies):
                results.append(signal)
                self.signals_found += 1

            self.status = ScraperStatus.SUCCESS
            self.logger.info(
                "scraper_completed",
                scraper=self.name,
                signals_found=self.signals_found,
                duration=round(time.monotonic() - start, 2),
            )
        except Exception as e:
            self.status = ScraperStatus.FAILED
            self.errors += 1
            self.logger.error("scraper_failed", scraper=self.name, error=str(e))
            raise
        finally:
            self.last_run_at = datetime.now(timezone.utc)
            self.last_duration = time.monotonic() - start

        return results
