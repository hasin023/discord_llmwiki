"""
Ingestion pipeline v3 — Budget-aware, batched, deduplicated.

Pipeline: LocalPreFilter → ContentHashDedup → MediaEnricher → MessageBuffer → BudgetCheck → mem0.add()

Net effect: 500 msgs/day → ~65 LLM extraction calls/day (87% reduction vs naive).
"""
import asyncio
import hashlib
import re
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from budget.controller import BudgetController, BudgetDecision
from memory.schemas import MessageEvent, EnrichedMessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)

TRIVIAL_RESPONSES = {
    "ok", "lol", "thanks", "thx", "nice", "cool", "yes", "no", "sure",
    "haha", "lmao", "xd", "gg", "brb", "afk", "👍", "❤️", "😂", "😭",
    "np", "nvm", "wtf", "omg", "wow", "damn", "shit", "lgtm", "wip",
    "ty", "k", "yep", "nope", "true", "same", "rip", "oof", "yea", "bro"
}


class LocalPreFilter:
    """Zero-cost message filter. Eliminates ~65% of messages before any API call."""

    @staticmethod
    def should_ingest(event: MessageEvent) -> bool:
        content = event.content.strip()

        # Short messages with no media are noise
        if len(content) < 15 and not event.has_attachments and not event.raw_urls:
            return False

        # One-word trivial responses
        if content.lower() in TRIVIAL_RESPONSES:
            return False

        # Bot command prefixes
        if content.startswith(("/", "!", "?", ".")):
            return False

        # Pure-emoji check (no ASCII letters or digits)
        if content and not re.search(r'[a-zA-Z0-9]', content):
            return False

        return True


class ContentHashDedup:
    """Rolling dedup cache to prevent re-embedding identical/near-identical content."""

    def __init__(self, max_size: int = 500):
        self._hashes: deque[str] = deque(maxlen=max_size)
        self._hash_set: set[str] = set()

    def is_duplicate(self, content: str) -> bool:
        key = hashlib.md5(content[:200].lower().strip().encode()).hexdigest()
        if key in self._hash_set:
            return True
        # Evict oldest if at capacity
        if len(self._hashes) == self._hashes.maxlen:
            oldest = self._hashes[0]
            self._hash_set.discard(oldest)
        self._hashes.append(key)
        self._hash_set.add(key)
        return False


class MessageBuffer:
    """Collects N messages before firing a single batched mem0.add() call."""

    def __init__(self, batch_size: int = 5, flush_interval_seconds: int = 60):
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self._buffer: list[EnrichedMessageEvent] = []
        self._last_flush = datetime.now()

    def add(self, event: EnrichedMessageEvent) -> Optional[list[EnrichedMessageEvent]]:
        """Add event to buffer. Returns a batch if threshold met."""
        self._buffer.append(event)
        should_flush = (
            len(self._buffer) >= self.batch_size
            or (datetime.now() - self._last_flush) > timedelta(seconds=self.flush_interval)
        )
        if should_flush and self._buffer:
            batch = list(self._buffer)
            self._buffer.clear()
            self._last_flush = datetime.now()
            return batch
        return None

    def force_flush(self) -> Optional[list[EnrichedMessageEvent]]:
        """Force flush any buffered messages (used on shutdown)."""
        if self._buffer:
            batch = list(self._buffer)
            self._buffer.clear()
            self._last_flush = datetime.now()
            return batch
        return None


class IngestionWorker:
    """Main ingestion pipeline. Processes messages through all filters before mem0."""

    def __init__(self, memory_client, budget_controller, media_enricher,
                 wiki_buffer, cm_agent, config):
        self.memory = memory_client
        self.budget = budget_controller
        self.enricher = media_enricher
        self.wiki_buffer = wiki_buffer
        self.cm_agent = cm_agent
        self.config = config

        self.prefilter = LocalPreFilter()
        self.dedup = ContentHashDedup()
        self.msg_buffer = MessageBuffer(
            batch_size=config.ingest_batch_size if config.ingest_infer_enabled else 1,
            flush_interval_seconds=config.ingest_flush_interval if config.ingest_infer_enabled else 0,
        )

    async def process(self, event: MessageEvent, discord_message) -> None:
        """Full ingestion pipeline for a single message."""
        # Step 1: Local pre-filter (0 API calls)
        if not self.prefilter.should_ingest(event):
            return

        # Step 2: Content deduplication (0 API calls)
        if self.dedup.is_duplicate(event.content):
            return

        # Step 3: Media enrichment (LLM call only for images, budgeted)
        enriched = await self.enricher.enrich(event, discord_message)
        event.enriched_content = enriched.enriched_content

        # Step 4: CM agent evaluation (uses its own pre-filter + budget check)
        try:
            await self.cm_agent.on_message(event, discord_message.channel)
        except Exception as e:
            logger.error("ingestion.cm_error", error=str(e))

        # Step 5: Buffer message
        enriched_event = EnrichedMessageEvent.from_message_event(
            event,
            enriched_content=enriched.enriched_content,
            media_items=enriched.media_items,
        )
        batch = self.msg_buffer.add(enriched_event)
        if batch is None:
            return  # Not enough messages yet

        # Step 6: Budget check before mem0 LLM call (if infer is enabled)
        infer = self.config.ingest_infer_enabled
        if infer:
            decision = await self.budget.check(
                model=self.config.extraction_model,
                tokens_estimate=2000 * len(batch),
            )
            if decision == BudgetDecision.SKIP:
                infer = False
                logger.warning("ingestion.fallback_raw", reason="budget_exhausted", count=len(batch))

        # Step 7: Single batched mem0.add() for all messages in batch
        await self._mem0_add_batch(batch, infer=infer)

        # Step 8: Wiki buffer
        for e in batch:
            self.wiki_buffer.append(e)

    async def _mem0_add_batch(self, batch: list[EnrichedMessageEvent], infer: bool = True) -> None:
        """Send a batch of messages to mem0.add(), split by author so each
        user's memories are stored with their user_id for retrieval.
        Falls back to infer=False (raw insertion) if LLM limits hit."""
        from collections import defaultdict

        # Group messages by author so each gets their own user_id
        by_author: dict[int, list[EnrichedMessageEvent]] = defaultdict(list)
        for e in batch:
            by_author[e.author_id].append(e)

        for author_id, events in by_author.items():
            combined_messages = [
                {
                    "role": "user",
                    "content": (
                        f"[{e.author_name} in #{e.channel_name} "
                        f"at {e.timestamp.strftime('%H:%M')}]: "
                        f"{e.enriched_content or e.content}"
                    ),
                }
                for e in events
            ]
            metadata = {
                "channel_name": events[0].channel_name,
                "guild_id": str(events[0].guild_id),
                "author_name": events[0].author_name,
                "batch_size": len(events),
                "timestamp": events[-1].timestamp.isoformat(),
            }

            try:
                await asyncio.to_thread(
                    self.memory.add,
                    combined_messages,
                    user_id=str(author_id),
                    agent_id=f"channel_{events[0].channel_id}",
                    infer=infer,
                    metadata=metadata,
                )
                logger.info(
                    "ingestion.mem0_batch",
                    size=len(events),
                    user_id=str(author_id),
                    author=events[0].author_name,
                    infer=infer,
                )
            except Exception as e:
                error_str = str(e)
                if "429" in error_str and infer:
                    logger.warning("ingestion.mem0_fallback", reason="429_rate_limit", user_id=str(author_id))
                    # Fallback: API quota exceeded during infer. Force raw insertion.
                    try:
                        await asyncio.to_thread(
                            self.memory.add,
                            combined_messages,
                            user_id=str(author_id),
                            agent_id=f"channel_{events[0].channel_id}",
                            infer=False,
                            metadata=metadata,
                        )
                        logger.info(
                            "ingestion.mem0_batch",
                            size=len(events),
                            user_id=str(author_id),
                            author=events[0].author_name,
                            infer=False,
                        )
                    except Exception as e2:
                        logger.error(
                            "ingestion.mem0_error_fallback",
                            error=str(e2),
                            user_id=str(author_id),
                        )
                else:
                    logger.error(
                        "ingestion.mem0_error",
                        error=error_str,
                        user_id=str(author_id),
                    )

