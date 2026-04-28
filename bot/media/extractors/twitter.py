"""Twitter/X post metadata via oEmbed API. No LLM call needed."""
from typing import Optional
import httpx
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class TwitterExtractor:
    OEMBED_URL = "https://publish.twitter.com/oembed"

    async def extract(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    self.OEMBED_URL,
                    params={"url": url, "format": "json"},
                )
                resp.raise_for_status()
                data = resp.json()

            author = data.get("author_name", "")
            # The HTML contains the tweet text — extract it
            import re
            html = data.get("html", "")
            text = re.sub(r"<[^>]+>", "", html)[:300]
            return f'Tweet by @{author}: {text.strip()}' if author else None
        except Exception as e:
            logger.warning("twitter.extract_failed", url=url[:60], error=str(e))
            return None
