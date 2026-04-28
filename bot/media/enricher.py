"""
MediaEnricher — Enriches messages with text descriptions of media content.
Only images require an LLM call (budgeted). All URL extractors use free HTTP calls.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from budget.controller import BudgetController, BudgetDecision
from media.extractors.image import ImageExtractor
from media.extractors.youtube import YouTubeExtractor
from media.extractors.github import GitHubExtractor
from media.extractors.article import ArticleExtractor
from media.extractors.twitter import TwitterExtractor
from memory.schemas import MessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)

URL_PATTERNS = {
    "youtube": re.compile(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
    ),
    "github": re.compile(
        r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/(?:pull|issues)/\d+)?)"
    ),
    "twitter": re.compile(
        r"https?://(?:twitter|x)\.com/\w+/status/(\d+)"
    ),
    "article": re.compile(
        r"https?://(?:medium\.com|dev\.to|substack\.com|hashnode\.com|[\w.-]+/blog)/\S+"
    ),
}


@dataclass
class EnrichedContent:
    original_content: str
    enriched_content: str
    media_items: list[dict] = field(default_factory=list)


class MediaEnricher:
    """Enriches Discord messages with text descriptions of embedded media."""

    def __init__(self, llm_client, gemini_api_key: str, budget: BudgetController):
        self.image_extractor = ImageExtractor(gemini_api_key)
        self.youtube_extractor = YouTubeExtractor()
        self.github_extractor = GitHubExtractor()
        self.article_extractor = ArticleExtractor()
        self.twitter_extractor = TwitterExtractor()
        self.budget = budget

    async def enrich(self, event: MessageEvent, discord_message) -> EnrichedContent:
        """Enrich a message with descriptions of its media content."""
        enriched_parts = [event.content]
        media_items = []

        # 1. Process image attachments (requires LLM — budgeted)
        for attachment in discord_message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                decision = await self.budget.check(
                    model="gemini-2.5-flash-lite",
                    tokens_estimate=500,
                    priority="low",
                )
                if decision == BudgetDecision.APPROVED:
                    desc = await self.image_extractor.describe(attachment.url)
                    if desc:
                        enriched_parts.append(f"[Shared image: {desc}]")
                        media_items.append({
                            "type": "image", "url": attachment.url,
                            "description": desc,
                        })

        # 2. Process URLs (all free — no LLM calls)
        urls_found = set()
        for url_type, pattern in URL_PATTERNS.items():
            for match in pattern.finditer(event.content):
                url = match.group(0)
                if url in urls_found:
                    continue
                urls_found.add(url)
                desc = await self._extract_url(url_type, url)
                if desc:
                    enriched_parts.append(f"[Shared {url_type}: {desc}]")
                    media_items.append({
                        "type": url_type, "url": url, "description": desc,
                    })

        return EnrichedContent(
            original_content=event.content,
            enriched_content="\n".join(enriched_parts),
            media_items=media_items,
        )

    async def _extract_url(self, url_type: str, url: str) -> Optional[str]:
        extractors = {
            "youtube": self.youtube_extractor,
            "github": self.github_extractor,
            "article": self.article_extractor,
            "twitter": self.twitter_extractor,
        }
        extractor = extractors.get(url_type)
        if extractor:
            try:
                return await extractor.extract(url)
            except Exception as e:
                logger.warning("media.extract_error", type=url_type, error=str(e))
        return None
