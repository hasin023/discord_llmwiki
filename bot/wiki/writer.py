"""
WikiWriter — Batch-processes ingested messages into wiki pages.
Creates/updates entity, topic, channel, timeline, and resource pages.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import frontmatter

from budget.controller import BudgetController, BudgetDecision
from memory.schemas import EnrichedMessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class WikiBuffer:
    """Collects enriched events for periodic wiki writing."""

    def __init__(self, batch_size: int = 20, timeout_seconds: int = 600):
        self.batch_size = batch_size
        self.timeout = timeout_seconds
        self._buffer: list[EnrichedMessageEvent] = []
        self._last_flush = datetime.now()

    def append(self, event) -> None:
        self._buffer.append(event)

    def should_flush(self) -> bool:
        if not self._buffer:
            return False
        elapsed = (datetime.now() - self._last_flush).total_seconds()
        return len(self._buffer) >= self.batch_size or elapsed >= self.timeout

    def flush(self) -> list[EnrichedMessageEvent]:
        batch = list(self._buffer)
        self._buffer.clear()
        self._last_flush = datetime.now()
        return batch

    @property
    def size(self) -> int:
        return len(self._buffer)


class WikiWriter:
    """Processes batches of messages into wiki markdown pages."""

    def __init__(self, llm_client, wiki_reader, budget: BudgetController, config):
        self.llm = llm_client
        self.reader = wiki_reader
        self.budget = budget
        self.config = config
        self.wiki_path = Path(config.wiki_path)
        self.buffer = WikiBuffer(
            batch_size=config.wiki_batch_size,
            timeout_seconds=config.wiki_batch_timeout_seconds,
        )

    def start_background_task(self, loop) -> None:
        """Start the periodic wiki writing task."""
        loop.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        """Background loop that flushes the wiki buffer periodically."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            if self.buffer.should_flush():
                batch = self.buffer.flush()
                if batch:
                    await self.process_batch(batch)

    async def process_batch(self, batch: list[EnrichedMessageEvent]) -> None:
        """Process a batch of enriched events into wiki pages."""
        if not batch:
            return

        # Budget check before LLM calls
        decision = await self.budget.check(
            model=self.config.wiki_writer_model,
            tokens_estimate=3000,
            priority="normal",
        )
        if decision == BudgetDecision.SKIP:
            logger.warning("wiki.batch_skipped", reason="budget_exhausted", count=len(batch))
            return

        logger.info("wiki.processing_batch", size=len(batch))

        try:
            # Step 1: Group messages by channel
            by_channel: dict[str, list] = {}
            for event in batch:
                by_channel.setdefault(event.channel_name, []).append(event)

            # Step 2: Update channel pages
            for channel_name, events in by_channel.items():
                await self._update_channel_page(channel_name, events)

            # Step 3: Update timeline page
            await self._update_timeline(batch)

            # Step 4: Process resources (URLs/media)
            for event in batch:
                if event.media_items:
                    for item in event.media_items:
                        await self._update_resource_page(item, event)

            # Step 5: Extract and update entity/topic pages
            await self._extract_entities_and_topics(batch)

            # Step 6: Log the operation
            await self._log_operation(len(batch))

        except Exception as e:
            logger.error("wiki.batch_error", error=str(e))

    async def _update_channel_page(self, channel_name: str,
                                    events: list[EnrichedMessageEvent]) -> None:
        """Create or update a channel summary page."""
        page_path = self.wiki_path / "channels" / f"channel_{channel_name}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)

        # Build conversation context
        conversation = "\n".join(
            f"- [{e.author_name} at {e.timestamp.strftime('%H:%M')}]: "
            f"{(e.enriched_content or e.content)[:200]}"
            for e in events
        )

        now = datetime.now().strftime("%Y-%m-%d")

        if page_path.exists():
            existing = page_path.read_text(encoding="utf-8")
            prompt = (
                f"Update this channel wiki page with new conversation data.\n\n"
                f"Existing page:\n{existing[:2000]}\n\n"
                f"New conversations:\n{conversation}\n\n"
                f"Return the complete updated page. Keep frontmatter. "
                f"Add new discussion points. Update the 'updated' date to {now}."
            )
        else:
            prompt = (
                f"Create a wiki page for Discord channel #{channel_name}.\n\n"
                f"Recent conversations:\n{conversation}\n\n"
                f"Format as markdown with YAML frontmatter:\n"
                f"---\ntitle: \"Channel: #{channel_name}\"\n"
                f"type: channel\ncreated: {now}\nupdated: {now}\n---\n\n"
                f"Include: purpose, key topics, active members."
            )

        try:
            content = await self.llm.complete(prompt, model=self.config.wiki_writer_model)
            page_path.write_text(content, encoding="utf-8")
            logger.info("wiki.channel_updated", channel=channel_name)
        except Exception as e:
            logger.error("wiki.channel_error", channel=channel_name, error=str(e))

    async def _update_timeline(self, batch: list[EnrichedMessageEvent]) -> None:
        """Update the weekly timeline page."""
        week_str = datetime.now().strftime("%Y_W%W")
        page_path = self.wiki_path / "timeline" / f"week_{week_str}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)

        entries = "\n".join(
            f"- {e.timestamp.strftime('%Y-%m-%d %H:%M')} #{e.channel_name}: "
            f"{(e.enriched_content or e.content)[:100]}"
            for e in batch[:20]
        )

        now = datetime.now().strftime("%Y-%m-%d")
        if page_path.exists():
            existing = page_path.read_text(encoding="utf-8")
            new_content = f"{existing}\n\n## {now}\n\n{entries}"
        else:
            new_content = (
                f"---\ntitle: \"Timeline: Week {week_str}\"\n"
                f"type: timeline\ncreated: {now}\nupdated: {now}\n---\n\n"
                f"# Week {week_str}\n\n## {now}\n\n{entries}"
            )

        page_path.write_text(new_content, encoding="utf-8")

    async def _update_resource_page(self, media_item: dict,
                                     event: EnrichedMessageEvent) -> None:
        """Create or update a resource page for a shared URL."""
        url = media_item.get("url", "")
        media_type = media_item.get("type", "unknown")
        description = media_item.get("description", "")

        # Generate safe filename from URL
        import hashlib
        slug = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"{media_type}_{slug}.md"
        page_path = self.wiki_path / "resources" / filename
        page_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now().strftime("%Y-%m-%d")

        if page_path.exists():
            # Update existing resource page
            existing = page_path.read_text(encoding="utf-8")
            if event.author_name not in existing:
                updated = existing.replace(
                    "---\n\n",
                    f"---\n\n*Also shared by {event.author_name} "
                    f"in #{event.channel_name} on {now}*\n\n",
                    1,
                )
                page_path.write_text(updated, encoding="utf-8")
        else:
            content = (
                f"---\ntitle: \"{description[:80]}\"\ntype: resource\n"
                f"resource_type: {media_type}\nurl: {url}\n"
                f"shared_by: [{event.author_name}]\n"
                f"first_shared: {now}\n"
                f"channels_shared: [{event.channel_name}]\n"
                f"created: {now}\nupdated: {now}\n---\n\n"
                f"# {description[:80]}\n\n"
                f"## Summary\n\n{description}\n\n"
                f"## Context\n\n"
                f"Shared by {event.author_name} in #{event.channel_name}.\n"
            )
            page_path.write_text(content, encoding="utf-8")
            logger.info("wiki.resource_created", url=url[:60])

    async def _extract_entities_and_topics(self,
                                            batch: list[EnrichedMessageEvent]) -> None:
        """Use LLM to extract entities and topics from a batch."""
        decision = await self.budget.check(
            model=self.config.wiki_writer_model,
            tokens_estimate=2000,
            priority="normal",
        )
        if decision != BudgetDecision.APPROVED:
            return

        conversation = "\n".join(
            f"[{e.author_name}]: {(e.enriched_content or e.content)[:150]}"
            for e in batch[:15]
        )

        prompt = (
            "Extract entities (people, tools, projects) and topics from "
            "this Discord conversation batch. Return JSON:\n"
            '{"entities": [{"name": "...", "type": "person|tool|project", '
            '"description": "..."}], "topics": [{"name": "...", '
            '"description": "..."}]}\n\n'
            f"Conversation:\n{conversation}"
        )

        try:
            import json
            result = await self.llm.complete(prompt, model=self.config.wiki_writer_model)
            # Strip markdown code fences if present
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(result)

            now = datetime.now().strftime("%Y-%m-%d")

            for entity in data.get("entities", []):
                name = entity["name"].lower().replace(" ", "_")
                etype = entity.get("type", "unknown")
                path = self.wiki_path / "entities" / f"{etype}_{name}.md"
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    content = (
                        f"---\ntitle: \"{entity['name']}\"\ntype: entity\n"
                        f"entity_type: {etype}\ncreated: {now}\n"
                        f"updated: {now}\n---\n\n"
                        f"# {entity['name']}\n\n"
                        f"{entity.get('description', '')}\n"
                    )
                    path.write_text(content, encoding="utf-8")

            for topic in data.get("topics", []):
                name = topic["name"].lower().replace(" ", "_")
                path = self.wiki_path / "topics" / f"topic_{name}.md"
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    content = (
                        f"---\ntitle: \"{topic['name']}\"\ntype: topic\n"
                        f"created: {now}\nupdated: {now}\n---\n\n"
                        f"# {topic['name']}\n\n"
                        f"{topic.get('description', '')}\n"
                    )
                    path.write_text(content, encoding="utf-8")

        except Exception as e:
            logger.warning("wiki.extract_error", error=str(e))

    async def _log_operation(self, count: int) -> None:
        """Append to wiki/log.md."""
        log_path = self.wiki_path / "log.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n- [{now}] Processed batch of {count} messages\n"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass
