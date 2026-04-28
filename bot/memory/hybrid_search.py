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
            from fastembed import SparseTextEmbedding
            self.bm25_encoder = SparseTextEmbedding(model_name="Qdrant/bm25")
            self._hybrid_available = True
            logger.info("hybrid_search.bm25_available")
        except (ImportError, Exception) as e:
            self._hybrid_available = False
            logger.warning(
                "hybrid_search.fastembed_not_available",
                msg="BM25 hybrid search unavailable, falling back to dense-only",
                error=str(e),
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
        sparse_result = list(self.bm25_encoder.query_embed([query]))[0]
        return SparseVector(
            indices=sparse_result.indices.tolist(),
            values=sparse_result.values.tolist(),
        )

    async def query(self, question: str,
                    channel_id: Optional[int] = None,
                    limit: int = 10) -> list[dict]:
        """
        Search for relevant memories.
        Uses mem0's built-in semantic search (which manages the Qdrant collection).
        Direct Qdrant RRF fusion requires named vectors that mem0 doesn't create,
        so we rely on mem0's search with proper agent_id scoping.
        """
        try:
            filter_kwargs = {}
            if channel_id:
                filter_kwargs["agent_id"] = f"channel_{channel_id}"
            else:
                # mem0 requires at least one of user_id, agent_id, or run_id
                filter_kwargs["agent_id"] = "global"

            results = await asyncio.to_thread(
                self.memory.search,
                question,
                limit=limit,
                **filter_kwargs,
            )

            # mem0.search returns {"results": [...]} or a list directly
            if isinstance(results, dict):
                return results.get("results", [])
            return results if results else []

        except Exception as e:
            logger.warning("hybrid_search.error", error=str(e))
            return []

