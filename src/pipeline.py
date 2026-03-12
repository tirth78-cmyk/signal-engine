"""
Signal Processing Pipeline — Orchestrates the full 4-stage pipeline:
Stage 1: Collection (Scrapers)
Stage 2: Deduplication
Stage 3: NLP Classification + Entity Extraction
Stage 4: Scoring + HubSpot Push
"""

import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select, func

from src.scrapers.manager import ScraperManager
from src.nlp.classifier import SignalClassifier
from src.nlp.dedup import SignalDeduplicator
from src.nlp.entity_extractor import EntityExtractor
from src.scoring.signal_scorer import SignalScorer
from src.connectors.hubspot import HubSpotConnector
from src.models import (
    RawSignalInput, SignalRecord, SignalStatus, PipelineMetric,
)
from src.utils.database import get_session
from src.utils.logging import get_logger
from config.settings import settings

logger = get_logger("pipeline")


class SignalPipeline:
    """
    Full signal processing pipeline.
    Processes raw signals through classification, dedup, scoring, and CRM push.
    """

    def __init__(self, api_keys: dict[str, str] | None = None):
        self.scraper_manager = ScraperManager(api_keys=api_keys)
        self.classifier = SignalClassifier()
        self.deduplicator = SignalDeduplicator()
        self.entity_extractor = EntityExtractor()
        self.scorer = SignalScorer()
        self.hubspot = HubSpotConnector()

        self._initialized = False
        self._running = False
        self._last_run_metrics: dict = {}

        # Real-time signal feed (for WebSocket broadcasting)
        self._signal_subscribers: list[asyncio.Queue] = []

    async def initialize(self):
        """Initialize all pipeline components."""
        if self._initialized:
            return

        logger.info("pipeline_initializing")
        await asyncio.gather(
            self.classifier.initialize(),
            self.deduplicator.initialize(),
            self.entity_extractor.initialize(),
        )
        self._initialized = True
        logger.info("pipeline_initialized")

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to real-time signal feed."""
        queue: asyncio.Queue = asyncio.Queue()
        self._signal_subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from signal feed."""
        if queue in self._signal_subscribers:
            self._signal_subscribers.remove(queue)

    async def _broadcast(self, signal_data: dict):
        """Broadcast signal to all subscribers."""
        for queue in self._signal_subscribers:
            try:
                queue.put_nowait(signal_data)
            except asyncio.QueueFull:
                pass  # drop if subscriber is slow

    # ─── Full Pipeline Run ───────────────────────────────────────────────────

    async def run_full_scan(
        self,
        target_companies: list[str] | None = None,
        scraper_names: list[str] | None = None,
        push_to_hubspot: bool = True,
    ) -> dict:
        """
        Execute the full 4-stage pipeline.
        Returns metrics dict.
        """
        if not self._initialized:
            await self.initialize()

        if self._running:
            return {"error": "Pipeline already running"}

        self._running = True
        start_time = time.monotonic()
        metrics = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "signals_collected": 0,
            "signals_classified": 0,
            "signals_verified": 0,
            "signals_pushed": 0,
            "duplicates_caught": 0,
            "avg_confidence": 0.0,
            "errors": 0,
        }

        try:
            # ── Stage 1: Collection ──────────────────────────────────────────
            logger.info("stage_1_collection_started")
            raw_signals = await self.scraper_manager.run_all(
                target_companies=target_companies,
                scraper_names=scraper_names,
            )
            metrics["signals_collected"] = len(raw_signals)
            logger.info("stage_1_complete", count=len(raw_signals))

            if not raw_signals:
                return metrics

            # ── Stage 2 & 3: Classify + Deduplicate ──────────────────────────
            logger.info("stage_2_3_classification_started")
            classified_records: list[SignalRecord] = []

            for raw in raw_signals:
                try:
                    # Classify
                    signal_type, confidence = self.classifier.classify(raw)

                    # Extract entities
                    text = f"{raw.title} {raw.description or ''}"
                    entities = self.entity_extractor.extract(text)
                    keywords = self.entity_extractor.extract_keywords(text)

                    # Resolve company name
                    company_name = raw.company_name or self.entity_extractor.extract_company_name(text)

                    # Create record
                    record = self.classifier.to_signal_record(raw, signal_type, confidence)
                    record.entities = entities
                    record.keywords = keywords
                    if company_name:
                        record.company_name = company_name

                    classified_records.append(record)
                except Exception as e:
                    metrics["errors"] += 1
                    logger.warning("classification_error", error=str(e))

            metrics["signals_classified"] = len(classified_records)

            # Deduplication
            unique_signals, duplicates = self.deduplicator.process_batch(classified_records)
            metrics["duplicates_caught"] = len(duplicates)
            logger.info(
                "stage_2_3_complete",
                classified=len(classified_records),
                unique=len(unique_signals),
                duplicates=len(duplicates),
            )

            # ── Stage 4: Score + Push ────────────────────────────────────────
            logger.info("stage_4_scoring_started")
            scored_signals = self.scorer.score_batch(unique_signals)

            # Compute avg confidence
            confidences = [s.confidence for s in scored_signals if s.confidence > 0]
            metrics["avg_confidence"] = (
                round(sum(confidences) / len(confidences), 3) if confidences else 0.0
            )

            # Auto-verify high-confidence signals
            for signal in scored_signals:
                if signal.confidence >= settings.nlp.classification_threshold:
                    signal.status = SignalStatus.VERIFIED
                    metrics["signals_verified"] += 1

            # Persist to database
            async with get_session() as session:
                for signal in scored_signals:
                    session.add(signal)
                # Also persist duplicates (marked as is_duplicate=True)
                for dup in duplicates:
                    session.add(dup)

            # Push to HubSpot
            if push_to_hubspot and settings.hubspot.api_key:
                verified = [s for s in scored_signals if s.status == SignalStatus.VERIFIED]
                if verified:
                    push_result = await self.hubspot.push_batch(verified)
                    metrics["signals_pushed"] = push_result["success"]

                    # Update DB after push
                    async with get_session() as session:
                        for signal in verified:
                            session.add(signal)

            # Broadcast to real-time subscribers
            for signal in scored_signals[:50]:  # cap broadcast
                await self._broadcast({
                    "id": signal.id,
                    "title": signal.title,
                    "signal_type": signal.signal_type.value,
                    "confidence": signal.confidence,
                    "composite_score": signal.composite_score,
                    "company_name": signal.company_name,
                    "source_type": signal.source_type.value,
                    "status": signal.status.value,
                })

            # Persist metrics
            pipeline_metric = PipelineMetric(
                signals_collected=metrics["signals_collected"],
                signals_classified=metrics["signals_classified"],
                signals_verified=metrics["signals_verified"],
                signals_pushed=metrics["signals_pushed"],
                duplicates_caught=metrics["duplicates_caught"],
                avg_confidence=metrics["avg_confidence"],
                avg_processing_time_ms=round((time.monotonic() - start_time) * 1000 / max(len(raw_signals), 1), 1),
                errors=metrics["errors"],
                active_scrapers=len(self.scraper_manager.scrapers),
            )
            async with get_session() as session:
                session.add(pipeline_metric)

            metrics["duration_seconds"] = round(time.monotonic() - start_time, 2)
            metrics["completed_at"] = datetime.now(timezone.utc).isoformat()
            self._last_run_metrics = metrics

            logger.info("pipeline_complete", **metrics)
            return metrics

        except Exception as e:
            metrics["errors"] += 1
            logger.error("pipeline_error", error=str(e))
            raise
        finally:
            self._running = False

    # ─── Process Single Signal ───────────────────────────────────────────────

    async def process_signal(self, raw: RawSignalInput) -> SignalRecord:
        """Process a single signal through the pipeline."""
        if not self._initialized:
            await self.initialize()

        # Classify
        signal_type, confidence = self.classifier.classify(raw)

        # Entity extraction
        text = f"{raw.title} {raw.description or ''}"
        entities = self.entity_extractor.extract(text)
        keywords = self.entity_extractor.extract_keywords(text)

        # Create record
        record = self.classifier.to_signal_record(raw, signal_type, confidence)
        record.entities = entities
        record.keywords = keywords

        # Check duplicate
        is_dup, cluster_id = self.deduplicator.is_duplicate(record)
        record.is_duplicate = is_dup
        record.dedup_cluster_id = cluster_id

        if not is_dup:
            # Score
            self.scorer.score(record)

            # Persist
            async with get_session() as session:
                session.add(record)

            # Broadcast
            await self._broadcast({
                "id": record.id,
                "title": record.title,
                "signal_type": record.signal_type.value,
                "confidence": record.confidence,
                "composite_score": record.composite_score,
                "status": record.status.value,
            })

        return record

    # ─── Metrics ─────────────────────────────────────────────────────────────

    @property
    def last_metrics(self) -> dict:
        return self._last_run_metrics

    @property
    def is_running(self) -> bool:
        return self._running
