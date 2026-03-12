"""
Scheduled jobs using APScheduler.
Runs periodic scraping at configured intervals.
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from src.utils.logging import get_logger

logger = get_logger("scheduler")


class SignalScheduler:
    """Manages periodic scraping and pipeline jobs."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.scheduler = AsyncIOScheduler()
        self._setup_jobs()

    def _setup_jobs(self):
        """Configure scheduled jobs."""

        # News scraping — every 30 minutes
        self.scheduler.add_job(
            self._run_news_scrapers,
            IntervalTrigger(minutes=settings.scheduler.news_interval_minutes),
            id="news_scan",
            name="News & RSS Scan",
            replace_existing=True,
        )

        # Job board scraping — every 6 hours
        self.scheduler.add_job(
            self._run_job_scrapers,
            IntervalTrigger(minutes=settings.scheduler.jobs_interval_minutes),
            id="job_scan",
            name="Job Board Scan",
            replace_existing=True,
        )

        # Regulatory scraping — every 12 hours
        self.scheduler.add_job(
            self._run_regulatory_scrapers,
            IntervalTrigger(minutes=settings.scheduler.regulatory_interval_minutes),
            id="regulatory_scan",
            name="Regulatory Scan",
            replace_existing=True,
        )

        # Full scan — daily at 6 AM UTC
        self.scheduler.add_job(
            self._run_full_scan,
            CronTrigger.from_crontab(settings.scheduler.full_scan_cron),
            id="full_scan",
            name="Daily Full Scan",
            replace_existing=True,
        )

        logger.info("scheduled_jobs_configured", jobs=len(self.scheduler.get_jobs()))

    async def _run_news_scrapers(self):
        """Run news-related scrapers."""
        logger.info("scheduled_news_scan")
        try:
            await self.pipeline.run_full_scan(
                scraper_names=["newsapi", "rss_feeds", "pr_wires"]
            )
        except Exception as e:
            logger.error("scheduled_news_scan_failed", error=str(e))

    async def _run_job_scrapers(self):
        """Run job board scrapers."""
        logger.info("scheduled_job_scan")
        try:
            await self.pipeline.run_full_scan(
                scraper_names=["job_boards"]
            )
        except Exception as e:
            logger.error("scheduled_job_scan_failed", error=str(e))

    async def _run_regulatory_scrapers(self):
        """Run regulatory scrapers."""
        logger.info("scheduled_regulatory_scan")
        try:
            await self.pipeline.run_full_scan(
                scraper_names=["sec_edgar", "regulatory_news"]
            )
        except Exception as e:
            logger.error("scheduled_regulatory_scan_failed", error=str(e))

    async def _run_full_scan(self):
        """Run all scrapers."""
        logger.info("scheduled_full_scan")
        try:
            await self.pipeline.run_full_scan()
        except Exception as e:
            logger.error("scheduled_full_scan_failed", error=str(e))

    def start(self):
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("scheduler_started")

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("scheduler_stopped")

    def get_jobs(self) -> list[dict]:
        """Get list of scheduled jobs."""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]
