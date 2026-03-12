"""Tests for the NLP signal classifier."""

import pytest
from src.nlp.classifier import SignalClassifier
from src.models import RawSignalInput, SignalType, SourceType


@pytest.fixture
def classifier():
    clf = SignalClassifier()
    clf._initialized = True  # Skip model loading for unit tests
    return clf


class TestKeywordClassification:
    """Test keyword-based classification (no ML model needed)."""

    def test_leadership_change(self, classifier):
        signal = RawSignalInput(
            title="Novartis appoints new Chief Data Officer",
            description="Novartis has named Dr. Sarah Chen as the new CDO",
            source_type=SourceType.NEWS_API,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.LEADERSHIP_CHANGE
        assert confidence >= 0.5

    def test_job_posting(self, classifier):
        signal = RawSignalInput(
            title="Hiring: Senior Data Engineer at Pfizer",
            description="Pfizer is recruiting a Senior Data Engineer for their analytics team",
            source_type=SourceType.JOB_BOARD,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.JOB_POSTING
        assert confidence >= 0.5

    def test_technology_adoption(self, classifier):
        signal = RawSignalInput(
            title="Sanofi implements Databricks for clinical data analytics",
            description="Sanofi deploys Databricks platform to modernize their data infrastructure",
            source_type=SourceType.PR_WIRE,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.TECHNOLOGY_ADOPTION
        assert confidence >= 0.5

    def test_funding_event(self, classifier):
        signal = RawSignalInput(
            title="BioTech startup raises $50M Series B funding round",
            description="Venture capital investment in biotech data analytics company",
            source_type=SourceType.NEWS_API,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.FUNDING_EVENT
        assert confidence >= 0.5

    def test_regulatory(self, classifier):
        signal = RawSignalInput(
            title="FDA approves Pfizer's new drug for rare disease",
            description="The FDA has granted approval for Phase 3 clinical trial results",
            source_type=SourceType.REGULATORY,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.REGULATORY_CHANGE
        assert confidence >= 0.5

    def test_expansion(self, classifier):
        signal = RawSignalInput(
            title="AstraZeneca opens new GCC center in India",
            description="AstraZeneca expands with a new global capability center in Bangalore",
            source_type=SourceType.NEWS_API,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.EXPANSION
        assert confidence >= 0.5

    def test_ma_activity(self, classifier):
        signal = RawSignalInput(
            title="Merck completes acquisition of biotech firm",
            description="The merger agreement was finalized today for $2.5B buyout",
            source_type=SourceType.PR_WIRE,
        )
        signal_type, confidence = classifier.classify(signal)
        assert signal_type == SignalType.MA_ACTIVITY
        assert confidence >= 0.5

    def test_batch_classify(self, classifier):
        signals = [
            RawSignalInput(title="New CEO appointed at Roche", source_type=SourceType.NEWS_API),
            RawSignalInput(title="Hiring data scientist at Amgen", source_type=SourceType.JOB_BOARD),
            RawSignalInput(title="FDA approves new treatment", source_type=SourceType.REGULATORY),
        ]
        results = classifier.classify_batch(signals)
        assert len(results) == 3
        assert all(isinstance(r[0], SignalType) for r in results)
        assert all(isinstance(r[1], float) for r in results)
