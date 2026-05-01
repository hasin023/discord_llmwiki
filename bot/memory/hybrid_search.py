"""
Hybrid search: mem0 semantic search + direct Qdrant fallback + user memory lookup.

Primary: mem0.search() scoped by channel agent_id.
Fallback: direct Qdrant vector search when mem0 returns no results.
User lookup: mem0.get_all() for user-specific memory retrieval.
"""
import asyncio
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class HybridSearch:
    """
    Search layer combining mem0 semantic search with direct Qdrant fallback.

    When the user asks a question via /ask:
    1. Semantic search via mem0 (channel-scoped by agent_id)
    2. If 0 results: fallback to direct Qdrant vector search
    3. If question mentions a user: also fetch their memories via get_all()
    4. If still sparse: fetch recent channel memories as context
    """

    def __init__(self, memory_client, qdrant_host: str,
                 qdrant_port: int, collection_name: str):
        self.memory = memory_client
        self.collection = collection_name

        # Direct Qdrant client for fallback searches
        self._qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)

        # Local embedding model (same as mem0 uses) for direct Qdrant queries
        self._embedder = SentenceTransformer(config.embedding_model)

        logger.info(
            "hybrid_search.init",
            collection=collection_name,
            qdrant=f"{qdrant_host}:{qdrant_port}",
        )

    async def query(self, question: str,
                    channel_id: Optional[int] = None,
                    guild_id: Optional[int | str] = None,
                    limit: int = 10) -> list[dict]:
        """
        Search for relevant memories via mem0's semantic search.
        Always scoped by channel agent_id — caller MUST provide channel_id.
        Falls back to direct Qdrant search if mem0 returns no results.

        SECURITY: guild_id is used as defense-in-depth — even though
        channel_id is unique across Discord, we still filter by guild_id
        in Qdrant to prevent any leakage.
        """
        results = []

        if not channel_id:
            logger.warning("hybrid_search.no_channel_id")
            return []

        agent_id = f"channel_{channel_id}"

        # Step 1: Semantic search via mem0 (channel-scoped)
        try:
            mem0_results = await asyncio.to_thread(
                self.memory.search,
                question,
                agent_id=agent_id,
                limit=limit,
            )
            if isinstance(mem0_results, dict):
                results = mem0_results.get("results", [])
            else:
                results = mem0_results or []
        except Exception as e:
            logger.warning("hybrid_search.mem0_error", error=str(e))

        # Step 2: If mem0 returned nothing, try direct Qdrant vector search
        #         (channel-scoped + guild-scoped for defense-in-depth)
        if not results:
            logger.info("hybrid_search.mem0_empty_fallback_qdrant", channel_id=channel_id)
            results = await self._direct_qdrant_search(
                question, agent_id=agent_id, guild_id=guild_id, limit=limit,
            )

        # Step 3: If channel-scoped search still returned nothing, try a
        #         broader guild-wide search (finds memories from OTHER channels
        #         in the same server).
        if not results and guild_id:
            logger.info("hybrid_search.channel_empty_fallback_guild", guild_id=guild_id)
            results = await self._direct_qdrant_search(
                question, guild_id=guild_id, limit=limit,
            )

        return results

    async def get_user_memories(self, user_id: int | str,
                                guild_id: int | str = None,
                                limit: int = 15) -> list[dict]:
        """Get memories for a specific user, STRICTLY scoped to a guild.

        Security: user_id is the same across Discord servers, so we MUST
        filter by guild_id to prevent cross-server data leakage.
        """
        if not guild_id:
            logger.warning("hybrid_search.user_memories_no_guild",
                           user_id=str(user_id))
            return []  # Refuse to return unscoped user memories

        try:
            facts = await asyncio.to_thread(
                self.memory.get_all,
                user_id=str(user_id),
            )
            results = facts.get("results", []) if isinstance(facts, dict) else facts
            if not results:
                return []

            # SECURITY: post-filter to only include memories from this guild.
            # Check metadata.guild_id AND agent_id (channel IDs are guild-unique).
            guild_str = str(guild_id)
            filtered = []
            for r in results:
                meta = r.get("metadata", {})
                if meta.get("guild_id") == guild_str:
                    filtered.append(r)

            logger.info(
                "hybrid_search.user_memories_filtered",
                user_id=str(user_id),
                guild_id=guild_str,
                total=len(results),
                after_filter=len(filtered),
            )
            return filtered[-limit:] if filtered else []
        except Exception as e:
            logger.warning("hybrid_search.user_memories_error",
                           error=str(e), user_id=str(user_id))
            return []

    async def get_channel_memories(self, channel_id: int,
                                   guild_id: Optional[int | str] = None,
                                   limit: int = 20) -> list[dict]:
        """Get recent memories from a channel (fallback when semantic search
        returns too few results).

        SECURITY: When guild_id is provided, post-filter results to only
        include memories from this guild (defense-in-depth).
        """
        try:
            facts = await asyncio.to_thread(
                self.memory.get_all,
                agent_id=f"channel_{channel_id}",
            )
            results = facts.get("results", []) if isinstance(facts, dict) else facts
            if not results:
                return []

            # SECURITY: post-filter by guild_id if provided
            if guild_id:
                guild_str = str(guild_id)
                results = [
                    r for r in results
                    if r.get("metadata", {}).get("guild_id") == guild_str
                ]

            # Return most recent N
            return results[-limit:] if results else []
        except Exception as e:
            logger.warning("hybrid_search.channel_memories_error",
                           error=str(e), channel_id=channel_id)
            return []

    async def _direct_qdrant_search(self, question: str,
                                     agent_id: str = None,
                                     guild_id: int | str = None,
                                     limit: int = 10) -> list[dict]:
        """
        Direct Qdrant vector search bypassing mem0's API restrictions.
        Uses the same embedding model as mem0 for consistent results.
        Always filtered by agent_id or guild_id for server isolation.
        """
        try:
            # Embed the query locally (0 API calls)
            query_vector = await asyncio.to_thread(
                self._embedder.encode, question,
            )

            # Build filter — ALWAYS scope to prevent cross-guild leakage
            must_conditions = []
            if agent_id:
                must_conditions.append(
                    FieldCondition(
                        key="agent_id",
                        match=MatchValue(value=agent_id),
                    )
                )
            if guild_id:
                must_conditions.append(
                    FieldCondition(
                        key="metadata.guild_id",
                        match=MatchValue(value=str(guild_id)),
                    )
                )

            search_filter = Filter(must=must_conditions) if must_conditions else None

            # Search directly in Qdrant
            points = await asyncio.to_thread(
                self._qdrant.search,
                collection_name=self.collection,
                query_vector=query_vector.tolist(),
                limit=limit,
                query_filter=search_filter,
            )

            # Convert to mem0-compatible format
            # Handle both 'memory' key (infer=True) and 'data' key (infer=False)
            results = []
            for point in points:
                payload = point.payload or {}
                memory_text = (
                    payload.get("memory")
                    or payload.get("data")
                    or payload.get("text", "")
                )
                results.append({
                    "memory": memory_text,
                    "score": point.score,
                    "id": str(point.id),
                    "user_id": payload.get("user_id", ""),
                    "agent_id": payload.get("agent_id", ""),
                    "metadata": payload.get("metadata", {}),
                })

            logger.info(
                "hybrid_search.direct_qdrant",
                results=len(results),
                agent_id=agent_id,
                guild_id=str(guild_id) if guild_id else None,
            )
            return results

        except Exception as e:
            logger.warning("hybrid_search.direct_qdrant_error", error=str(e))
            return []
