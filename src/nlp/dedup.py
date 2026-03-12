"""
Signal Deduplicator — Catches duplicate signals using content hashing + semantic similarity.
"""

import hashlib
from typing import Optional

import numpy as np
from cachetools import TTLCache

from src.models import SignalRecord
from src.utils.logging import get_logger
from config.settings import settings

logger = get_logger("nlp.dedup")


class SignalDeduplicator:
    """
    Two-phase deduplication:
    1. Exact hash match (SHA-256 of normalized title+description)
    2. Semantic similarity (cosine similarity of embeddings above threshold)
    """

    def __init__(self):
        self._model = None
        self._hash_cache: TTLCache = TTLCache(maxsize=50000, ttl=86400)  # 24h cache
        self._embedding_cache: TTLCache = TTLCache(maxsize=10000, ttl=86400)
        self._initialized = False

    async def initialize(self):
        """Load embedding model for semantic dedup."""
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(settings.nlp.embedding_model)
            self._initialized = True
            logger.info("deduplicator_initialized")
        except ImportError:
            logger.warning("sentence_transformers_not_available, hash-only dedup")
            self._initialized = True

    @staticmethod
    def compute_hash(title: str, description: str = "") -> str:
        """Compute content hash for exact matching."""
        text = f"{title} {description}".lower().strip()
        normalized = " ".join(text.split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _compute_embedding(self, text: str) -> Optional[np.ndarray]:
        """Compute embedding for semantic comparison."""
        if not self._model:
            return None
        return self._model.encode(text[:500], normalize_embeddings=True)

    def is_duplicate(self, signal: SignalRecord) -> tuple[bool, Optional[str]]:
        """
        Check if signal is a duplicate.
        Returns (is_dup, existing_cluster_id).
        """
        content_hash = self.compute_hash(signal.title, signal.description or "")

        # Phase 1: Exact hash match
        if content_hash in self._hash_cache:
            existing_id = self._hash_cache[content_hash]
            logger.debug("exact_duplicate_found", signal=signal.title[:50], match=existing_id)
            return True, existing_id

        # Phase 2: Semantic similarity
        text = f"{signal.title} {signal.description or ''}"[:500]
        embedding = self._compute_embedding(text)

        if embedding is not None:
            for cached_id, cached_embedding in self._embedding_cache.items():
                similarity = float(np.dot(embedding, cached_embedding))
                if similarity >= settings.nlp.dedup_similarity_threshold:
                    logger.debug(
                        "semantic_duplicate_found",
                        signal=signal.title[:50],
                        similarity=round(similarity, 3),
                    )
                    # Also store hash to speed up future lookups
                    self._hash_cache[content_hash] = cached_id
                    return True, cached_id

            # Not a duplicate — cache it
            self._embedding_cache[signal.id] = embedding

        # Cache hash
        self._hash_cache[content_hash] = signal.id
        return False, None

    def process_batch(self, signals: list[SignalRecord]) -> tuple[list[SignalRecord], list[SignalRecord]]:
        """
        Process a batch of signals.
        Returns (unique_signals, duplicate_signals).
        """
        unique = []
        duplicates = []

        for signal in signals:
            is_dup, cluster_id = self.is_duplicate(signal)
            if is_dup:
                signal.is_duplicate = True
                signal.dedup_cluster_id = cluster_id
                duplicates.append(signal)
            else:
                unique.append(signal)

        logger.info(
            "dedup_batch_complete",
            total=len(signals),
            unique=len(unique),
            duplicates=len(duplicates),
        )
        return unique, duplicates

    @property
    def cache_size(self) -> dict:
        """Return current cache sizes."""
        return {
            "hash_cache": len(self._hash_cache),
            "embedding_cache": len(self._embedding_cache),
        }
