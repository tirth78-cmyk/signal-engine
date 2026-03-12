"""
Signal Scorer — Computes composite signal scores (Recency + Relevance + Authority).
Score range: 1-15 (3 dimensions x 1-5 each).
"""

from datetime import datetime, timezone, timedelta

from src.models import SignalRecord, SignalType, SourceType
from src.utils.logging import get_logger

logger = get_logger("scoring.signal")


# Authority scores by source type (higher = more authoritative)
SOURCE_AUTHORITY: dict[SourceType, int] = {
    SourceType.SEC_FILING: 5,
    SourceType.REGULATORY: 5,
    SourceType.PR_WIRE: 4,
    SourceType.NEWS_API: 3,
    SourceType.RSS_FEED: 3,
    SourceType.JOB_BOARD: 3,
    SourceType.LINKEDIN: 2,
    SourceType.CUSTOM_WEB: 2,
}

# Relevance multipliers by signal type (for pharma data/analytics GTM)
SIGNAL_RELEVANCE: dict[SignalType, float] = {
    SignalType.LEADERSHIP_CHANGE: 1.0,    # Direct buying signal
    SignalType.TECHNOLOGY_ADOPTION: 1.0,  # Direct buying signal
    SignalType.JOB_POSTING: 0.9,          # Strong intent signal
    SignalType.EXPANSION: 0.85,           # Growth = budget
    SignalType.FUNDING_EVENT: 0.85,       # Money = budget
    SignalType.PARTNERSHIP: 0.8,          # Ecosystem shift
    SignalType.MA_ACTIVITY: 0.75,         # Org change = opportunity
    SignalType.PRODUCT_LAUNCH: 0.7,       # May need data support
    SignalType.REGULATORY_CHANGE: 0.65,   # Compliance needs
    SignalType.EARNINGS_EVENT: 0.5,       # Background intel
    SignalType.EVENT_ATTENDANCE: 0.4,     # Engagement signal
    SignalType.CONTENT_ENGAGEMENT: 0.3,   # Weak signal
}

# High-value keywords that boost relevance
RELEVANCE_BOOST_KEYWORDS = [
    "databricks", "snowflake", "data platform", "data lake", "data mesh",
    "chief data officer", "vp data", "head of analytics",
    "real world evidence", "rwe", "clinical data",
    "digital transformation", "ai", "machine learning",
    "gcc", "india center", "offshore",
]


class SignalScorer:
    """
    Scores signals across 3 dimensions:
    - Recency (1-5): How recent is the signal?
    - Relevance (1-5): How relevant to our ICP/offering?
    - Authority (1-5): How authoritative is the source?

    Composite = Recency + Relevance + Authority (range 3-15)
    """

    def score_recency(self, signal: SignalRecord) -> int:
        """
        Score recency based on published/collected date.
        5 = today, 4 = this week, 3 = this month, 2 = last month, 1 = older
        """
        reference_date = signal.published_at or signal.collected_at
        if not reference_date:
            return 1

        now = datetime.now(timezone.utc)
        if reference_date.tzinfo is None:
            reference_date = reference_date.replace(tzinfo=timezone.utc)

        age = now - reference_date

        if age <= timedelta(hours=24):
            return 5
        elif age <= timedelta(days=3):
            return 4
        elif age <= timedelta(days=7):
            return 3
        elif age <= timedelta(days=30):
            return 2
        else:
            return 1

    def score_relevance(self, signal: SignalRecord) -> int:
        """
        Score relevance based on signal type + keyword analysis.
        Uses signal type base score + keyword boosting.
        """
        base_multiplier = SIGNAL_RELEVANCE.get(signal.signal_type, 0.5)
        base_score = base_multiplier * 4  # Scale to ~1-4 range

        # Keyword boost
        text = f"{signal.title} {signal.description or ''}".lower()
        keyword_hits = sum(1 for kw in RELEVANCE_BOOST_KEYWORDS if kw in text)
        boost = min(keyword_hits * 0.3, 1.5)

        # NLP confidence boost
        confidence_boost = signal.confidence * 0.5 if signal.confidence > 0.7 else 0

        final = base_score + boost + confidence_boost
        return max(1, min(5, round(final)))

    def score_authority(self, signal: SignalRecord) -> int:
        """Score authority based on source type."""
        return SOURCE_AUTHORITY.get(signal.source_type, 2)

    def score(self, signal: SignalRecord) -> SignalRecord:
        """Compute all scores for a signal record."""
        signal.recency_score = self.score_recency(signal)
        signal.relevance_score = self.score_relevance(signal)
        signal.authority_score = self.score_authority(signal)
        signal.composite_score = (
            signal.recency_score + signal.relevance_score + signal.authority_score
        )

        logger.debug(
            "signal_scored",
            title=signal.title[:50],
            recency=signal.recency_score,
            relevance=signal.relevance_score,
            authority=signal.authority_score,
            composite=signal.composite_score,
        )
        return signal

    def score_batch(self, signals: list[SignalRecord]) -> list[SignalRecord]:
        """Score a batch of signals."""
        scored = [self.score(s) for s in signals]
        # Sort by composite score descending
        scored.sort(key=lambda s: s.composite_score, reverse=True)
        logger.info("batch_scored", count=len(scored))
        return scored
