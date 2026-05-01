"""
WikiWriter — Batch-processes ingested messages into wiki pages.
Creates/updates entity, topic, channel, timeline, and resource pages.

Guild-isolated: all wiki files are written under /wiki/{guild_id}/ so
multiple Discord servers sharing the same bot instance stay separated.
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
    """Collects enriched events for periodic wiki writing.

    Flush triggers:
    - Immediately when batch_size messages accumulate (event-driven)
    - After timeout_seconds if ANY new messages are waiting

    Will NOT re-flush on timer ticks if no new content has arrived.
    """

    def __init__(self, batch_size: int = 10, timeout_seconds: int = 180):
        self.batch_size = batch_size
        self.timeout = timeout_seconds
        self._buffer: list[EnrichedMessageEvent] = []
        self._last_flush = datetime.now()
        self._batch_ready = asyncio.Event()

    def append(self, event) -> None:
        self._buffer.append(event)
        # Signal immediately when batch is full
        if len(self._buffer) >= self.batch_size:
            self._batch_ready.set()

    def should_flush(self) -> bool:
        if not self._buffer:
            return False
        elapsed = (datetime.now() - self._last_flush).total_seconds()
        return len(self._buffer) >= self.batch_size or elapsed >= self.timeout

    def flush(self) -> list[EnrichedMessageEvent]:
        batch = list(self._buffer)
        self._buffer.clear()
        self._last_flush = datetime.now()
        self._batch_ready.clear()
        return batch

    @property
    def size(self) -> int:
        return len(self._buffer)


class WikiWriter:
    """Processes batches of messages into wiki markdown pages.

    Wiki files are stored under {wiki_root}/{guild_id}/ for guild isolation.
    """

    def __init__(self, llm_client, wiki_reader, budget: BudgetController, config):
        self.llm = llm_client
        self.reader = wiki_reader
        self.budget = budget
        self.config = config
        self.wiki_root = Path(config.wiki_path)
        self.buffer = WikiBuffer(
            batch_size=config.wiki_batch_size,
            timeout_seconds=config.wiki_batch_timeout_seconds,
        )

    def _guild_wiki_path(self, guild_id: int | str) -> Path:
        """Return the guild-scoped wiki directory, creating it if needed."""
        path = self.wiki_root / str(guild_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def start_background_task(self, loop) -> None:
        """Start the periodic wiki writing task."""
        loop.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        """Background loop that flushes the wiki buffer when ready.

        Wakes up immediately when batch_size is reached (via asyncio.Event),
        or checks every 30s for timeout-based flushing.
        Does NOT trigger if the buffer is empty (no wasted LLM calls).
        """
        while True:
            try:
                # Wait for batch-ready signal OR check every 30s
                await asyncio.wait_for(
                    self.buffer._batch_ready.wait(), timeout=30,
                )
                self.buffer._batch_ready.clear()
            except asyncio.TimeoutError:
                pass

            if self.buffer.should_flush():
                batch = self.buffer.flush()
                if batch:
                    await self.process_batch(batch)

    async def process_batch(self, batch: list[EnrichedMessageEvent]) -> None:
        """Process a batch of enriched events into wiki pages.

        SECURITY: Messages from different guilds may coexist in the same
        batch because the WikiBuffer is shared.  We group by guild_id
        FIRST so each guild's wiki pages are written to the correct
        guild-scoped directory — this is enforced programmatically,
        not via LLM prompts.
        """
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

        # SECURITY: Group by guild_id FIRST — never mix guilds in one wiki write.
        from collections import defaultdict
        by_guild: dict[int, list[EnrichedMessageEvent]] = defaultdict(list)
        for event in batch:
            by_guild[event.guild_id].append(event)

        for guild_id, guild_batch in by_guild.items():
            await self._process_guild_batch(guild_id, guild_batch)

    async def _process_guild_batch(self, guild_id: int,
                                    batch: list[EnrichedMessageEvent]) -> None:
        """Process a single guild's batch of events into wiki pages.

        All file writes are scoped to wiki/{guild_id}/ — guaranteed by
        _guild_wiki_path().
        """
        logger.info("wiki.processing_batch", size=len(batch), guild_id=guild_id)

        try:
            wiki_path = self._guild_wiki_path(guild_id)

            # Step 1: Group messages by channel
            by_channel: dict[str, list] = {}
            for event in batch:
                by_channel.setdefault(event.channel_name, []).append(event)

            # Step 2: Update channel pages
            for channel_name, events in by_channel.items():
                await self._update_channel_page(wiki_path, channel_name, events)

            # Step 3: Update timeline page
            await self._update_timeline(wiki_path, batch)

            # Step 4: Process resources (URLs/media)
            for event in batch:
                if event.media_items:
                    for item in event.media_items:
                        await self._update_resource_page(wiki_path, item, event)

            # Step 5: Extract and update entity/topic pages
            await self._extract_entities_and_topics(wiki_path, batch)

            # Step 6: Log the operation
            await self._log_operation(len(batch), guild_id=guild_id)

        except Exception as e:
            logger.error("wiki.batch_error", error=str(e), guild_id=guild_id)

    async def _update_channel_page(self, wiki_path: Path, channel_name: str,
                                    events: list[EnrichedMessageEvent]) -> None:
        """Create or update a channel summary page."""
        page_path = wiki_path / "channels" / f"channel_{channel_name}.md"
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
                f"Return the complete updated page in plain markdown (no code fences). "
                f"Keep frontmatter. Add new discussion points. "
                f"Update the 'updated' date to {now}."
            )
        else:
            prompt = (
                f"Create a wiki page for Discord channel #{channel_name}.\n\n"
                f"Recent conversations:\n{conversation}\n\n"
                f"Format as plain markdown (no code fences) with YAML frontmatter:\n"
                f"---\ntitle: \"Channel: #{channel_name}\"\n"
                f"type: channel\ncreated: {now}\nupdated: {now}\n---\n\n"
                f"Include: purpose, key topics, active members."
            )

        try:
            content = await self.llm.complete(prompt, model=self.config.wiki_writer_model)
            # Strip code fences if the LLM wraps the output
            content = self._strip_code_fences(content)
            page_path.write_text(content, encoding="utf-8")
            logger.info("wiki.channel_updated", channel=channel_name)
        except Exception as e:
            logger.error("wiki.channel_error", channel=channel_name, error=str(e))

    async def _update_timeline(self, wiki_path: Path,
                                batch: list[EnrichedMessageEvent]) -> None:
        """Update the weekly timeline page."""
        week_str = datetime.now().strftime("%Y_W%W")
        page_path = wiki_path / "timeline" / f"week_{week_str}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)

        entries = "\n".join(
            f"- {e.timestamp.strftime('%Y-%m-%d %H:%M')} #{e.channel_name} [@{e.author_name}]: "
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

    async def _update_resource_page(self, wiki_path: Path, media_item: dict,
                                     event: EnrichedMessageEvent) -> None:
        """Create or update a resource page for a shared URL."""
        url = media_item.get("url", "")
        media_type = media_item.get("type", "unknown")
        description = media_item.get("description", "")

        # Generate safe filename from URL
        import hashlib
        slug = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"{media_type}_{slug}.md"
        page_path = wiki_path / "resources" / filename
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

    async def _extract_entities_and_topics(self, wiki_path: Path,
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
                path = wiki_path / "entities" / f"{etype}_{name}.md"
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
                path = wiki_path / "topics" / f"topic_{name}.md"
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

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences that LLMs sometimes wrap output in."""
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (e.g. ```markdown)
            first_newline = text.find("\n")
            if first_newline >= 0:
                text = text[first_newline + 1:]
            # Remove closing fence
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()
        return text

    async def _log_operation(self, count: int, guild_id: int | str = None) -> None:
        """Append to wiki/log.md."""
        log_path = self.wiki_root / "log.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        guild_tag = f" [guild={guild_id}]" if guild_id else ""
        entry = f"\n- [{now}]{guild_tag} Processed batch of {count} messages\n"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass
