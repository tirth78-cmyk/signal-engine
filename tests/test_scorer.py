"""Tests for the signal scoring engine."""

import pytest
from datetime import datetime, timezone, timedelta

from src.scoring.signal_scorer import SignalScorer
from src.scoring.icp_scorer import ICPScorer
from src.models import SignalRecord, SignalType, SourceType, ICPAccount


@pytest.fixture
def scorer():
    return SignalScorer()


@pytest.fixture
def icp_scorer():
    return ICPScorer()


class TestSignalScorer:

    def test_recency_today(self, scorer):
        signal = SignalRecord(
            title="Test", signal_type=SignalType.LEADERSHIP_CHANGE,
            source_type=SourceType.NEWS_API,
            published_at=datetime.now(timezone.utc),
        )
        assert scorer.score_recency(signal) == 5

    def test_recency_this_week(self, scorer):
        signal = SignalRecord(
            title="Test", signal_type=SignalType.LEADERSHIP_CHANGE,
            source_type=SourceType.NEWS_API,
            published_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        assert scorer.score_recency(signal) == 4

    def test_recency_old(self, scorer):
        signal = SignalRecord(
            title="Test", signal_type=SignalType.LEADERSHIP_CHANGE,
            source_type=SourceType.NEWS_API,
            published_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        assert scorer.score_recency(signal) == 1

    def test_authority_sec(self, scorer):
        signal = SignalRecord(
            title="Test", signal_type=SignalType.EARNINGS_EVENT,
            source_type=SourceType.SEC_FILING,
        )
        assert scorer.score_authority(signal) == 5

    def test_authority_linkedin(self, scorer):
        signal = SignalRecord(
            title="Test", signal_type=SignalType.LEADERSHIP_CHANGE,
            source_type=SourceType.LINKEDIN,
        )
        assert scorer.score_authority(signal) == 2

    def test_composite_score(self, scorer):
        signal = SignalRecord(
            title="Novartis appoints new CDO with Databricks experience",
            signal_type=SignalType.LEADERSHIP_CHANGE,
            source_type=SourceType.NEWS_API,
            confidence=0.9,
            published_at=datetime.now(timezone.utc),
        )
        scored = scorer.score(signal)
        assert scored.composite_score > 0
        assert scored.composite_score <= 15
        assert scored.recency_score >= 1
        assert scored.relevance_score >= 1
        assert scored.authority_score >= 1

    def test_batch_sorted(self, scorer):
        signals = [
            SignalRecord(
                title="Old low signal", signal_type=SignalType.CONTENT_ENGAGEMENT,
                source_type=SourceType.CUSTOM_WEB,
                published_at=datetime.now(timezone.utc) - timedelta(days=60),
            ),
            SignalRecord(
                title="New CDO appointed at Pfizer with Databricks",
                signal_type=SignalType.LEADERSHIP_CHANGE,
                source_type=SourceType.SEC_FILING, confidence=0.95,
                published_at=datetime.now(timezone.utc),
            ),
        ]
        scored = scorer.score_batch(signals)
        assert scored[0].composite_score >= scored[1].composite_score


class TestICPScorer:

    def test_pharma_industry(self, icp_scorer):
        assert icp_scorer.score_industry("Pharmaceutical") == 5

    def test_medtech_industry(self, icp_scorer):
        assert icp_scorer.score_industry("Medical Devices") == 4

    def test_large_company(self, icp_scorer):
        assert icp_scorer.score_size(50000) == 5

    def test_small_company(self, icp_scorer):
        assert icp_scorer.score_size(50) == 1

    def test_us_geography(self, icp_scorer):
        assert icp_scorer.score_geography("United States") == 5

    def test_full_icp_score(self, icp_scorer):
        account = ICPAccount(company_name="Pfizer")
        scored = icp_scorer.score_account(
            account, industry="Pharmaceutical", employee_count=80000,
            tech_stack=["Databricks", "AWS"], country="United States",
            revenue_usd=50_000_000_000,
        )
        assert scored.icp_score >= 20
        assert scored.tier == "1"
