"""
SemanticResponseCache — Embedding-based deduplication of /ask responses.

Caches LLM responses for /ask queries and returns them for semantically
similar questions without making a new LLM call.

Particularly effective for FAQ-style questions in Discord servers where
many members ask the same things (meeting times, role requirements, etc.)

Expected savings: 20-40% reduction in /ask LLM calls for active servers.
"""
import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from collections import deque

from google import genai
from google.genai import types

from utils.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    question: str
    answer: str
    embedding: list[float]
    created_at: datetime
    hit_count: int = 0


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticResponseCache:
    """
    In-memory semantic cache using embedding cosine similarity.

    Flow:
    1. User asks "/ask how do I get the developer role?"
    2. Cache embeds the question and scans for similar cached questions
    3. If similarity > threshold (0.92): return cached answer (0 LLM calls!)
    4. If miss: proceed to full search + LLM pipeline, then store result
    """

    def __init__(
        self,
        gemini_client,
        embedding_model: str = "gemini-embedding-001",
        similarity_threshold: float = 0.92,
        max_entries: int = 200,
        ttl_hours: int = 24,
    ):
        self.client = gemini_client
        self.embedding_model = embedding_model
        self.threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl = timedelta(hours=ttl_hours)
        self._cache: deque[CacheEntry] = deque(maxlen=max_entries)

    async def _embed_query(self, text: str) -> list[float]:
        """Embed a query using the task_type for retrieval."""
        result = await asyncio.to_thread(
            self.client.models.embed_content,
            model=self.embedding_model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        return result.embeddings[0].values

    async def check(self, question: str) -> Optional[str]:
        """
        Check if a semantically similar question has been answered recently.
        Returns cached answer if found, None otherwise.
        """
        if not self._cache:
            return None

        now = datetime.now()
        question_embedding = await self._embed_query(question)

        best_score = 0.0
        best_entry: Optional[CacheEntry] = None

        for entry in self._cache:
            # Skip expired entries
            if now - entry.created_at > self.ttl:
                continue
            score = cosine_similarity(question_embedding, entry.embedding)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= self.threshold and best_entry is not None:
            best_entry.hit_count += 1
            logger.info(
                "semantic_cache.hit",
                score=round(best_score, 3),
                hit_count=best_entry.hit_count,
                question_preview=question[:60],
            )
            return best_entry.answer

        return None

    async def store(self, question: str, answer: str) -> None:
        """Store a question-answer pair in the cache."""
        try:
            embedding = await self._embed_query(question)
            entry = CacheEntry(
                question=question,
                answer=answer,
                embedding=embedding,
                created_at=datetime.now(),
            )
            self._cache.append(entry)
            logger.debug("semantic_cache.stored", question_preview=question[:60])
        except Exception as e:
            logger.warning("semantic_cache.store_error", error=str(e))

    def cleanup_expired(self) -> int:
        """Remove expired entries. Called by hourly background task."""
        now = datetime.now()
        before = len(self._cache)
        self._cache = deque(
            (e for e in self._cache if now - e.created_at <= self.ttl),
            maxlen=self.max_entries,
        )
        removed = before - len(self._cache)
        if removed:
            logger.info("semantic_cache.cleanup", removed=removed)
        return removed

    def stats(self) -> dict:
        """Return cache statistics for /cache stats command."""
        total = len(self._cache)
        total_hits = sum(e.hit_count for e in self._cache)
        return {
            "entries": total,
            "max_entries": self.max_entries,
            "total_cache_hits": total_hits,
            "ttl_hours": self.ttl.total_seconds() / 3600,
            "similarity_threshold": self.threshold,
        }
