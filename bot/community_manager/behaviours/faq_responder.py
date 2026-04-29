"""FAQ Auto-Responder — Proactive FAQ answering from knowledge base."""
import asyncio
import json
from datetime import datetime, timedelta
from collections import defaultdict

from memory.schemas import MessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class FAQResponder:
    """Proactively answers FAQ-style questions from memory + wiki."""

    MIN_CONFIDENCE = 0.85
    _recent_answers: dict = defaultdict(datetime.now)

    def __init__(self, memory_client, wiki_reader, llm_client, config):
        self.memory = memory_client
        self.wiki_reader = wiki_reader
        self.llm = llm_client
        self.config = config
        self._recent: dict[str, datetime] = {}

    def is_enabled(self, cm_config) -> bool:
        return cm_config.faq_responder_enabled

    async def _recently_answered_similar(self, content: str) -> bool:
        key = content[:50].lower()
        if key in self._recent:
            if datetime.now() - self._recent[key] < timedelta(hours=1):
                return True
        return False

    async def should_fire(self, event: MessageEvent, cm_config) -> bool:
        if "?" not in event.content:
            return False
        if len(event.content) < 20:
            return False
        if await self._recently_answered_similar(event.content):
            return False

        prompt = (
            f'Classify this Discord message. Is it a FAQ-style question that '
            f'a bot with server history could answer factually?\n\n'
            f'Message: "{event.content}"\n\n'
            f'Respond ONLY with JSON: {{"is_faq": true/false, "confidence": 0.0-1.0}}\n'
            f'Do NOT classify as FAQ if: personal opinion, real-time data, '
            f'addressed to a specific person, or casual small talk.'
        )

        try:
            result_text = await self.llm.classify(prompt, model=self.config.extraction_model)
            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(result_text)
            threshold = cm_config.faq_confidence_threshold
            return result.get("is_faq") and result.get("confidence", 0) >= threshold
        except Exception as e:
            logger.warning("faq.classify_error", error=str(e))
            return False

    async def fire(self, event: MessageEvent, channel, cm_config) -> None:
        facts = await asyncio.to_thread(
            self.memory.search, event.content,
            agent_id=f"channel_{event.channel_id}", limit=8,
        )
        wiki_pages = await self.wiki_reader.find_relevant_pages(
            event.content, max_pages=2, guild_id=event.guild_id,
        )

        results = facts.get("results", []) if isinstance(facts, dict) else facts
        if not results and not wiki_pages:
            return

        answer = await self.llm.answer_question(
            question=event.content,
            mem0_facts="\n".join(f"- {f.get('memory', '')}" for f in results[:6]),
            wiki_context="\n".join(p.body[:600] for p in wiki_pages),
            model=cm_config.cm_model,
        )

        if len(answer) > 50 and "[no information" not in answer.lower():
            message = channel.get_partial_message(event.message_id)
            await channel.send(
                f"💡 {answer[:1800]}\n\n"
                f"*— Based on server history. Use `/ask` for more detailed queries.*",
                reference=message, mention_author=False,
            )
            self._recent[event.content[:50].lower()] = datetime.now()
            logger.info("faq.answered", channel=event.channel_name)
