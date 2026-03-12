"""
Scraper Manager — Orchestrates all scrapers with concurrency control.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from src.scrapers.base import BaseScraper
from src.scrapers.news import NewsAPIScraper, RSSFeedScraper
from src.scrapers.pr_wires import PRWireScraper
from src.scrapers.job_boards import JobBoardScraper
from src.scrapers.regulatory import SECFilingScraper, RegulatoryNewsScraper
from src.scrapers.linkedin import LinkedInScraper
from src.models import RawSignalInput, ScraperStatus, ScraperRun, SourceType
from src.utils.database import get_session
from src.utils.logging import get_logger
from config.settings import settings

logger = get_logger("scraper_manager")


class ScraperManager:
    """
    Central manager for all signal scrapers.
    Handles concurrency, metrics, and orchestration.
    """

    def __init__(self, api_keys: dict[str, str] | None = None):
        self.api_keys = api_keys or {}
        self.scrapers: dict[str, BaseScraper] = {
            "newsapi": NewsAPIScraper(api_keys=self.api_keys),
            "rss_feeds": RSSFeedScraper(),
            "pr_wires": PRWireScraper(),
            "job_boards": JobBoardScraper(),
            "sec_edgar": SECFilingScraper(),
            "regulatory_news": RegulatoryNewsScraper(),
            "linkedin": LinkedInScraper(),
        }
        self._semaphore = asyncio.Semaphore(settings.scraper.max_concurrent_scrapers)
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def get_scraper_statuses(self) -> list[dict]:
        """Get status of all scrapers."""
        return [
            {
                "name": name,
                "source_type": scraper.source_type.value,
                "status": scraper.status.value,
                "last_run_at": scraper.last_run_at.isoformat() if scraper.last_run_at else None,
                "signals_found": scraper.signals_found,
                "last_duration": round(scraper.last_duration, 2),
                "errors": scraper.errors,
            }
            for name, scraper in self.scrapers.items()
        ]

    async def _run_scraper(
        self,
        scraper: BaseScraper,
        target_companies: list[str] | None = None,
    ) -> list[RawSignalInput]:
        """Run a single scraper with concurrency control."""
        async with self._semaphore:
            run_record = ScraperRun(
                scraper_name=scraper.name,
                source_type=scraper.source_type,
                status=ScraperStatus.RUNNING,
            )

            try:
                signals = await scraper.run(target_companies)
                run_record.status = ScraperStatus.SUCCESS
                run_record.signals_found = len(signals)
                run_record.completed_at = datetime.now(timezone.utc)
                run_record.duration_seconds = scraper.last_duration
                return signals

            except Exception as e:
                run_record.status = ScraperStatus.FAILED
                run_record.error_message = str(e)
                run_record.completed_at = datetime.now(timezone.utc)
                run_record.duration_seconds = scraper.last_duration
                logger.error("scraper_run_failed", scraper=scraper.name, error=str(e))
                return []

            finally:
                # Persist scraper run record
                try:
                    async with get_session() as session:
                        session.add(run_record)
                except Exception as e:
                    logger.error("scraper_run_persist_error", error=str(e))

    async def run_all(
        self,
        target_companies: list[str] | None = None,
        scraper_names: list[str] | None = None,
    ) -> list[RawSignalInput]:
        """
        Run all (or selected) scrapers concurrently.
        Returns collected raw signals.
        """
        self._running = True
        logger.info("full_scan_started", scrapers=scraper_names or list(self.scrapers.keys()))

        scrapers_to_run = (
            {k: v for k, v in self.scrapers.items() if k in scraper_names}
            if scraper_names
            else self.scrapers
        )

        tasks = [
            self._run_scraper(scraper, target_companies)
            for scraper in scrapers_to_run.values()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_signals: list[RawSignalInput] = []
        for result in results:
            if isinstance(result, list):
                all_signals.extend(result)
            elif isinstance(result, Exception):
                logger.error("scraper_task_error", error=str(result))

        self._running = False
        logger.info(
            "full_scan_completed",
            total_signals=len(all_signals),
            scrapers_run=len(scrapers_to_run),
        )
        return all_signals

    async def run_single(
        self,
        scraper_name: str,
        target_companies: list[str] | None = None,
    ) -> list[RawSignalInput]:
        """Run a specific scraper by name."""
        scraper = self.scrapers.get(scraper_name)
        if not scraper:
            raise ValueError(f"Unknown scraper: {scraper_name}")
        return await self._run_scraper(scraper, target_companies)
