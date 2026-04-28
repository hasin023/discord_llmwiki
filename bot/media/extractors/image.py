"""
Image captioning via Gemini multimodal. This is the ONLY media extractor
that requires an LLM call — all others use free HTTP APIs.
"""
import asyncio
from typing import Optional

import httpx
from google import genai
from google.genai import types

from utils.logging_setup import get_logger

logger = get_logger(__name__)


class ImageExtractor:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    async def describe(self, image_url: str) -> Optional[str]:
        """Download image and generate a text description using Gemini multimodal."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                image_bytes = resp.content
                content_type = resp.headers.get("content-type", "image/jpeg")

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model="gemini-2.5-flash-lite",
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=content_type),
                    types.Part.from_text(
                        "Describe this image concisely in 1-3 sentences. "
                        "Focus on: what is shown, any text visible, and context "
                        "relevant if shared in a tech Discord server."
                    ),
                ],
            )
            return response.text.strip()
        except Exception as e:
            logger.warning("image.describe_failed", url=image_url[:60], error=str(e))
            return None
