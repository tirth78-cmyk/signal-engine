"""
Signal Classifier — NLP-based signal type classification.
Uses sentence-transformers for semantic similarity and keyword rules as fallback.
"""

import re
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from src.models import RawSignalInput, SignalType, SignalStatus, SignalRecord
from src.utils.logging import get_logger
from config.settings import settings

logger = get_logger("nlp.classifier")


# ─── Reference Descriptions for Each Signal Type ─────────────────────────────
# The classifier embeds these and compares incoming signals via cosine similarity.

SIGNAL_TYPE_DESCRIPTIONS = {
    SignalType.LEADERSHIP_CHANGE: (
        "New executive appointment, CEO hired, VP promoted, Chief Data Officer named, "
        "leadership transition, C-suite change, board member appointed, new head of department"
    ),
    SignalType.JOB_POSTING: (
        "Job opening posted, hiring for role, recruiting data engineer, career opportunity, "
        "open position, talent acquisition, seeking candidates, employment listing"
    ),
    SignalType.TECHNOLOGY_ADOPTION: (
        "Company adopts new technology platform, implements Databricks, migrates to Snowflake, "
        "deploys AWS cloud, implements Veeva CRM, digital transformation initiative, "
        "technology partnership, software implementation, platform modernization"
    ),
    SignalType.FUNDING_EVENT: (
        "Series A funding raised, IPO filed, venture capital investment, private equity deal, "
        "fundraising round closed, valuation increase, capital infusion, investor round"
    ),
    SignalType.EXPANSION: (
        "Company expands operations, opens new office, enters new market, geographic expansion, "
        "new manufacturing facility, GCC center opened, new regional headquarters, "
        "international expansion, India center launch"
    ),
    SignalType.PARTNERSHIP: (
        "Strategic partnership announced, alliance formed, collaboration agreement, "
        "joint venture, CDMO partnership, research collaboration, licensing deal, "
        "co-development agreement, technology integration partner"
    ),
    SignalType.REGULATORY_CHANGE: (
        "FDA approval granted, EMA authorization, regulatory submission, drug approved, "
        "clinical trial results, Phase 3 success, regulatory milestone, compliance update"
    ),
    SignalType.EARNINGS_EVENT: (
        "Quarterly earnings reported, revenue growth, profit increase, financial results, "
        "annual report filed, earnings beat expectations, guidance raised, SEC filing"
    ),
    SignalType.PRODUCT_LAUNCH: (
        "New product launched, drug launched commercially, product release, market launch, "
        "new indication approved, product line expansion, commercial launch"
    ),
    SignalType.MA_ACTIVITY: (
        "Merger announced, acquisition completed, company acquired, takeover bid, "
        "merger agreement, divestiture, spin-off, asset purchase, buyout"
    ),
    SignalType.CONTENT_ENGAGEMENT: (
        "Whitepaper downloaded, webinar attended, content engagement, blog interaction, "
        "demo requested, case study viewed, newsletter subscription"
    ),
    SignalType.EVENT_ATTENDANCE: (
        "Conference attendance, trade show participation, summit speaker, "
        "industry event, pharma conference, exhibition booth, keynote presentation"
    ),
}

# ─── Keyword Rules (fallback when model confidence is low) ────────────────────

KEYWORD_RULES: dict[SignalType, list[str]] = {
    SignalType.LEADERSHIP_CHANGE: [
        r"(?i)\b(appointed|hired|named|promoted|joins as|new\s+(ceo|cto|cdo|cfo|cmo|vp|svp|evp|director|head of))",
        r"(?i)\b(leadership\s+change|executive\s+appointment|c-suite|board\s+member)",
    ],
    SignalType.JOB_POSTING: [
        r"(?i)\b(hiring|job\s+posting|open\s+position|career|recruiting|seeking\s+candidates)",
        r"(?i)\b(we.re\s+hiring|join\s+our\s+team|apply\s+now)",
    ],
    SignalType.TECHNOLOGY_ADOPTION: [
        r"(?i)\b(implement|adopt|deploy|migrate|integrate|modernize|upgrade)\b.{0,30}(platform|system|technology|software|cloud|databricks|snowflake|veeva|aws|azure|gcp)",
        r"(?i)\b(digital\s+transformation|tech\s+stack|data\s+platform|cloud\s+migration)",
    ],
    SignalType.FUNDING_EVENT: [
        r"(?i)\b(series\s+[a-f]|funding\s+round|raised\s+\$|venture\s+capital|ipo|private\s+equity)",
        r"(?i)\b(investment|fundraise|valuation|capital\s+raise)",
    ],
    SignalType.EXPANSION: [
        r"(?i)\b(expand|new\s+office|new\s+facility|open.{0,10}center|gcc|enters\s+market)",
        r"(?i)\b(geographic\s+expansion|international|new\s+headquarters|india\s+center)",
    ],
    SignalType.PARTNERSHIP: [
        r"(?i)\b(partnership|alliance|collaboration|joint\s+venture|licensing\s+deal|cdmo)",
        r"(?i)\b(strategic\s+partner|co-develop|research\s+agreement)",
    ],
    SignalType.REGULATORY_CHANGE: [
        r"(?i)\b(fda\s+approv|ema\s+authoriz|regulatory\s+submission|drug\s+approv|phase\s+[123])",
        r"(?i)\b(clinical\s+trial|nda|bla|supplemental|breakthrough\s+therapy)",
    ],
    SignalType.EARNINGS_EVENT: [
        r"(?i)\b(earnings|quarterly\s+results|revenue\s+growth|annual\s+report|10-[kq]|8-k)",
        r"(?i)\b(financial\s+results|profit|guidance|sec\s+filing)",
    ],
    SignalType.PRODUCT_LAUNCH: [
        r"(?i)\b(product\s+launch|commercial\s+launch|market\s+launch|new\s+indication)",
        r"(?i)\b(new\s+product|drug\s+launch|release|rollout)",
    ],
    SignalType.MA_ACTIVITY: [
        r"(?i)\b(merger|acquisition|acquire|takeover|buyout|divestiture|spin.?off)",
        r"(?i)\b(m&a|merger\s+agreement|asset\s+purchase)",
    ],
    SignalType.CONTENT_ENGAGEMENT: [
        r"(?i)\b(whitepaper|webinar|demo\s+request|content\s+download|case\s+study)",
    ],
    SignalType.EVENT_ATTENDANCE: [
        r"(?i)\b(conference|summit|trade\s+show|exhibition|keynote|pharma\s+event)",
    ],
}


class SignalClassifier:
    """
    Classifies raw signals into SignalType categories.

    Pipeline:
    1. Semantic similarity (sentence-transformers) — primary classifier
    2. Keyword regex rules — fallback / confidence boost
    3. Confidence thresholding — below threshold → manual review
    """

    def __init__(self):
        self._model = None
        self._type_embeddings: dict[SignalType, np.ndarray] = {}
        self._initialized = False

    async def initialize(self):
        """Load sentence-transformers model and pre-compute type embeddings."""
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info("loading_embedding_model", model=settings.nlp.embedding_model)
            self._model = SentenceTransformer(settings.nlp.embedding_model)

            # Pre-compute embeddings for signal type descriptions
            for signal_type, description in SIGNAL_TYPE_DESCRIPTIONS.items():
                embedding = self._model.encode(description, normalize_embeddings=True)
                self._type_embeddings[signal_type] = embedding

            self._initialized = True
            logger.info("classifier_initialized", types=len(self._type_embeddings))
        except ImportError:
            logger.warning("sentence_transformers_not_available, using keyword-only mode")
            self._initialized = True

    def _keyword_classify(self, text: str) -> tuple[Optional[SignalType], float]:
        """Classify using keyword regex rules. Returns (type, confidence)."""
        scores: dict[SignalType, int] = {}

        for signal_type, patterns in KEYWORD_RULES.items():
            match_count = 0
            for pattern in patterns:
                if re.search(pattern, text):
                    match_count += 1
            if match_count > 0:
                scores[signal_type] = match_count

        if not scores:
            return None, 0.0

        best_type = max(scores, key=scores.get)
        # Normalize: 2 matches → 0.8 confidence, 1 match → 0.6
        confidence = min(0.4 + scores[best_type] * 0.2, 0.85)
        return best_type, confidence

    def _embedding_classify(self, text: str) -> tuple[Optional[SignalType], float]:
        """Classify using sentence-transformer cosine similarity."""
        if not self._model or not self._type_embeddings:
            return None, 0.0

        text_embedding = self._model.encode(text, normalize_embeddings=True)

        best_type = None
        best_score = 0.0

        for signal_type, type_embedding in self._type_embeddings.items():
            similarity = cosine_similarity(
                text_embedding.reshape(1, -1),
                type_embedding.reshape(1, -1),
            )[0][0]

            if similarity > best_score:
                best_score = similarity
                best_type = signal_type

        return best_type, float(best_score)

    def classify(self, signal: RawSignalInput) -> tuple[SignalType, float]:
        """
        Classify a raw signal. Returns (signal_type, confidence).
        Combines embedding similarity + keyword rules.
        """
        text = f"{signal.title} {signal.description or ''} {signal.raw_content or ''}"
        text = text[:2000]  # cap for performance

        # Phase 1: Embedding-based classification
        emb_type, emb_confidence = self._embedding_classify(text)

        # Phase 2: Keyword-based classification
        kw_type, kw_confidence = self._keyword_classify(text)

        # Phase 3: Combine results
        if emb_type and emb_confidence >= 0.5:
            # Embedding is primary — boost if keyword agrees
            if kw_type == emb_type:
                final_confidence = min(emb_confidence * 0.7 + kw_confidence * 0.3, 0.99)
            else:
                final_confidence = emb_confidence * 0.85
            return emb_type, round(final_confidence, 3)

        elif kw_type:
            # Fall back to keywords
            return kw_type, round(kw_confidence, 3)

        else:
            # No classification possible — default
            return SignalType.CONTENT_ENGAGEMENT, 0.1

    def classify_batch(self, signals: list[RawSignalInput]) -> list[tuple[SignalType, float]]:
        """Classify a batch of signals."""
        return [self.classify(signal) for signal in signals]

    def to_signal_record(
        self,
        raw: RawSignalInput,
        signal_type: SignalType,
        confidence: float,
    ) -> SignalRecord:
        """Convert a raw signal + classification into a SignalRecord."""
        threshold = settings.nlp.classification_threshold

        return SignalRecord(
            title=raw.title,
            description=raw.description,
            signal_type=signal_type,
            status=SignalStatus.CLASSIFIED if confidence >= threshold else SignalStatus.RAW,
            source_url=raw.source_url,
            source_type=raw.source_type,
            source_name=raw.source_name,
            company_name=raw.company_name,
            company_domain=raw.company_domain,
            raw_content=raw.raw_content,
            confidence=confidence,
            content_hash=BaseScraper.content_hash(raw.title + (raw.description or "")),
            published_at=raw.published_at,
            classified_at=datetime.now(timezone.utc),
        )
