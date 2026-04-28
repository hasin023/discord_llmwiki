"""Article text extraction via httpx + readability-lxml. No LLM call needed."""
import re
from typing import Optional
import httpx
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class ArticleExtractor:
    MAX_CONTENT_LENGTH = 800

    async def extract(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

            from readability import Document
            doc = Document(html)
            title = doc.title()
            content = re.sub(r"<[^>]+>", "", doc.summary())[:self.MAX_CONTENT_LENGTH]
            return f'Article: "{title}" — {content}...' if title else None
        except Exception as e:
            logger.warning("article.extract_failed", url=url[:60], error=str(e))
            return None
