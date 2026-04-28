"""YouTube metadata via oEmbed API. No LLM call needed."""
from typing import Optional
import httpx
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class YouTubeExtractor:
    OEMBED_URL = "https://www.youtube.com/oembed"

    async def extract(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    self.OEMBED_URL,
                    params={"url": url, "format": "json"},
                )
                resp.raise_for_status()
                data = resp.json()
            title = data.get("title", "")
            author = data.get("author_name", "")
            return f'YouTube video: "{title}" by {author}' if title else None
        except Exception as e:
            logger.warning("youtube.extract_failed", url=url[:60], error=str(e))
            return None
