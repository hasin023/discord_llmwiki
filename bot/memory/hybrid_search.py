"""
Hybrid search: BM25 sparse + dense vector search fused via RRF.
Uses Qdrant's native sparse vectors (FastEmbed BM25) alongside Gemini embeddings.

Why hybrid:
- Pure vector: good at semantic similarity, bad at exact matches
- BM25 alone: good at exact terms ("@Alice", "Qdrant"), bad at paraphrase
- Hybrid (RRF): 5-15% better recall than either alone
"""
import asyncio
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector
from google import genai
from google.genai import types

from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class HybridSearch:
    """
    BM25 + dense vector search via Reciprocal Rank Fusion.
    Falls back to pure mem0.search() if fastembed not installed.
    """

    SPARSE_VECTORS_NAME = "bm25"
    DENSE_VECTORS_NAME = "dense"

    def __init__(self, memory_client, qdrant_host: str,
                 qdrant_port: int, collection_name: str):
        self.memory = memory_client
        self.qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self.collection = collection_name
        self.gemini = genai.Client(api_key=config.gemini_api_key)

        # FastEmbed BM25 encoder (runs locally, no API call)
        try:
            from fastembed.sparse import BM25
            self.bm25_encoder = BM25()
            self._hybrid_available = True
            logger.info("hybrid_search.bm25_available")
        except ImportError:
            self._hybrid_available = False
            logger.warning(
                "hybrid_search.fastembed_not_installed",
                msg="pip install fastembed to enable hybrid search"
            )

    async def _embed_query(self, query: str) -> list[float]:
        """Embed query for dense vector search."""
        result = await asyncio.to_thread(
            self.gemini.models.embed_content,
            model=config.embedding_model,
            contents=query,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        return result.embeddings[0].values

    def _encode_sparse(self, query: str) -> Optional[SparseVector]:
        """Generate BM25 sparse vector for keyword search."""
        if not self._hybrid_available:
            return None
        sparse_result = list(self.bm25_encoder.query_embed(query))[0]
        return SparseVector(
            indices=sparse_result.indices.tolist(),
            values=sparse_result.values.tolist(),
        )

    async def query(self, question: str,
                    channel_id: Optional[int] = None,
                    limit: int = 10) -> list[dict]:
        """
        Hybrid search: BM25 + dense + RRF fusion.
        Falls back to pure mem0.search() if fastembed unavailable.
        """
        if not self._hybrid_available:
            return await self._fallback_search(question, channel_id, limit)

        try:
            # Dense embedding
            dense_vector = await self._embed_query(question)
            # Sparse BM25 encoding (local, free)
            sparse_vector = self._encode_sparse(question)

            # Qdrant prefetch + RRF
            from qdrant_client.models import (
                Prefetch, FusionQuery, Fusion, Query
            )

            prefetch = []
            # Dense prefetch
            prefetch.append(Prefetch(
                query=dense_vector,
                using=self.DENSE_VECTORS_NAME,
                limit=limit * 2,
            ))
            # Sparse prefetch
            if sparse_vector:
                prefetch.append(Prefetch(
                    query=sparse_vector,
                    using=self.SPARSE_VECTORS_NAME,
                    limit=limit * 2,
                ))

            results = self.qdrant.query_points(
                collection_name=self.collection,
                prefetch=prefetch,
                query=FusionQuery(fusion=Fusion.RRF),
                limit=limit,
                with_payload=True,
            )

            # Format results to match mem0 output format
            formatted = []
            for point in results.points:
                payload = point.payload or {}
                formatted.append({
                    "memory": payload.get("data", payload.get("text", "")),
                    "score": point.score or 0.0,
                    "metadata": {
                        "channel_name": payload.get("channel_name", ""),
                        "timestamp": payload.get("timestamp", ""),
                        "author_name": payload.get("author_name", ""),
                    },
                })

            logger.info("hybrid_search.success", results=len(formatted))
            return formatted

        except Exception as e:
            logger.warning("hybrid_search.error", error=str(e))
            return await self._fallback_search(question, channel_id, limit)

    async def _fallback_search(self, question: str,
                                channel_id: Optional[int] = None,
                                limit: int = 10) -> list[dict]:
        """Fallback: use Mem0's built-in semantic search."""
        filter_kwargs = {}
        if channel_id:
            filter_kwargs["agent_id"] = f"channel_{channel_id}"

        results = await asyncio.to_thread(
            self.memory.search,
            question,
            limit=limit,
            **filter_kwargs,
        )
        return results.get("results", [])
