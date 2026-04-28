"""Context Injector — Surfaces prior discussion when a topic re-emerges."""
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

from memory.schemas import MessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class ContextInjector:
    """Proactively injects prior context when a topic resurfaces."""

    def __init__(self, memory_client, wiki_reader, llm_client, config):
        self.memory = memory_client
        self.wiki_reader = wiki_reader
        self.llm = llm_client
        self.config = config
        self._cooldowns: dict[str, datetime] = {}

    def is_enabled(self, cm_config) -> bool:
        return cm_config.context_injector_enabled

    def _cooldown_key(self, channel_id: int, topic: str) -> str:
        return f"{channel_id}:{topic[:30].lower()}"

    def _is_on_cooldown(self, channel_id: int, topic: str, hours: int) -> bool:
        key = self._cooldown_key(channel_id, topic)
        if key in self._cooldowns:
            return datetime.now() - self._cooldowns[key] < timedelta(hours=hours)
        return False

    async def should_fire(self, event: MessageEvent, cm_config) -> bool:
        if len(event.content) < 20:
            return False

        if self._is_on_cooldown(
            event.channel_id, event.content,
            cm_config.context_injector_cooldown_hours,
        ):
            return False

        results = await asyncio.to_thread(
            self.memory.search, event.content,
            agent_id=f"channel_{event.channel_id}", limit=5,
        )
        prior_facts = results.get("results", []) if isinstance(results, dict) else results

        if len(prior_facts) < cm_config.context_injector_min_prior_facts:
            return False

        top_score = prior_facts[0].get("score", 0) if prior_facts else 0
        return top_score >= cm_config.context_injector_similarity_threshold

    async def fire(self, event: MessageEvent, channel, cm_config) -> None:
        results = await asyncio.to_thread(
            self.memory.search, event.content,
            agent_id=f"channel_{event.channel_id}", limit=8,
        )
        facts = results.get("results", []) if isinstance(results, dict) else results
        facts_text = "\n".join(f"- {f.get('memory', '')}" for f in facts[:6])

        summary = await self.llm.complete(
            f"Summarise these facts about a topic discussed in a Discord server "
            f"in 2-3 bullet points. Be concise and direct.\n\nFacts:\n{facts_text}\n\n"
            f"Output ONLY the 2-3 bullet points.",
            model=cm_config.cm_model,
        )

        inject_msg = (
            f"📚 **This topic has come up before!**\n"
            f"{summary}\n\n"
            f"*Use `/ask {event.content[:60]}...` for the full history.*"
        )

        message_ref = channel.get_partial_message(event.message_id)
        await channel.send(inject_msg, reference=message_ref, mention_author=False)

        key = self._cooldown_key(event.channel_id, event.content)
        self._cooldowns[key] = datetime.now()
        logger.info("context_injector.fired", channel=event.channel_name)
