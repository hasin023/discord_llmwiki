"""
Hybrid search: delegates to mem0's built-in semantic search.

The BM25 sparse encoder is still initialised (for future direct-Qdrant RRF
when/if we create a custom collection with named vectors), but query()
currently uses mem0.search() which manages its own Qdrant collection schema.
"""
import asyncio
from typing import Optional

from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class HybridSearch:
    """
    Search layer that wraps mem0.search() with proper agent_id scoping.
    Falls back gracefully to empty results on errors.
    """

    def __init__(self, memory_client, qdrant_host: str,
                 qdrant_port: int, collection_name: str):
        self.memory = memory_client
        self.collection = collection_name

        self._hybrid_available = False

    async def query(self, question: str,
                    channel_id: Optional[int] = None,
                    limit: int = 10) -> list[dict]:
        """
        Search for relevant memories via mem0's semantic search.
        Scopes by channel agent_id when provided.
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
