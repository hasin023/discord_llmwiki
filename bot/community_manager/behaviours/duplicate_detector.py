"""Duplicate Detector — Flags cross-channel duplicate discussions."""
import asyncio
from datetime import datetime, timedelta

from memory.schemas import MessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class DuplicateDetector:
    """Detects when a topic is being discussed in parallel across channels."""

    def __init__(self, memory_client, llm_client, config):
        self.memory = memory_client
        self.llm = llm_client
        self.config = config
        self._pending_other_channel: str = ""

    def is_enabled(self, cm_config) -> bool:
        return cm_config.duplicate_detector_enabled

    def _is_recent(self, timestamp_str: str, hours: int) -> bool:
        try:
            ts = datetime.fromisoformat(timestamp_str)
            return datetime.now() - ts < timedelta(hours=hours)
        except (ValueError, TypeError):
            return False

    async def should_fire(self, event: MessageEvent, cm_config) -> bool:
        if len(event.content) < 30:
            return False

        results = await asyncio.to_thread(
            self.memory.search, event.content, limit=5,
        )
        facts = results.get("results", []) if isinstance(results, dict) else results

        for fact in facts:
            score = fact.get("score", 0)
            meta = fact.get("metadata", {})
            fact_channel = meta.get("channel_name", "")
            fact_time = meta.get("timestamp", "")

            if (score >= cm_config.duplicate_threshold
                    and fact_channel
                    and fact_channel != event.channel_name):
                if fact_time and self._is_recent(fact_time, cm_config.duplicate_lookback_hours):
                    self._pending_other_channel = fact_channel
                    return True

        return False

    async def fire(self, event: MessageEvent, channel, cm_config) -> None:
        other = self._pending_other_channel
        if not other:
            return

        message_ref = channel.get_partial_message(event.message_id)
        await channel.send(
            f"👋 FYI — **#{other}** has been discussing something very similar "
            f"in the last couple of hours. Might be worth looping them in or "
            f"moving the conversation there!",
            reference=message_ref, mention_author=False,
        )
        self._pending_other_channel = ""
        logger.info("duplicate_detector.fired", channel=event.channel_name, other=other)
