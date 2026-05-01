"""
LLM abstraction layer — Google Gemini via google-genai SDK.
All LLM interactions go through this client for consistent error handling and logging.
"""
import asyncio
from typing import Optional

from google import genai
from google.genai import types

from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class LLMClient:
    """Unified Gemini LLM client for all bot components."""

    def __init__(self):
        self.client = genai.Client(api_key=config.gemini_api_key)

    async def complete(self, prompt: str, model: Optional[str] = None) -> str:
        """Send a single-turn prompt and return the text response."""
        model = model or config.wiki_writer_model
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                ),
            )
            return response.text
        except Exception as e:
            logger.error("llm.complete_error", model=model, error=str(e))
            raise

    async def answer_question(
        self,
        question: str,
        mem0_facts: str,
        wiki_context: str,
        model: Optional[str] = None,
    ) -> str:
        """Generate a grounded answer to a user question using memory context."""
        model = model or config.query_model

        system_instruction = (
            "You are a helpful Discord server assistant. Answer questions based "
            "ONLY on the provided memory facts and wiki context. Follow these rules strictly:\n"
            "1. If you don't have enough information, say so honestly — NEVER guess or assume.\n"
            "2. When the question is about a specific user, ONLY attribute actions/interests "
            "that are EXPLICITLY linked to that user in the facts or wiki. Do NOT confuse "
            "what different users said or did.\n"
            "3. Memory Facts (from Mem0) are more reliable than Wiki Context for user-specific questions.\n"
            "4. Cite your sources (e.g., 'according to memory facts' or the wiki page title).\n"
            "5. Be concise. Format for Discord markdown."
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"## Memory Facts (from Mem0):\n{mem0_facts or 'No relevant facts found.'}\n\n"
            f"## Wiki Context:\n{wiki_context or 'No relevant wiki pages found.'}\n\n"
            "Answer:"
        )

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=model,
                contents=[types.Content(
                    role="user",
                    parts=[types.Part(text=user_prompt)]
                )],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=1500,
                ),
            )
            return response.text
        except Exception as e:
            logger.error("llm.answer_error", model=model, error=str(e))
            raise

    async def classify(self, prompt: str, model: Optional[str] = None) -> str:
        """Low-temperature classification call for CM behaviours."""
        model = model or config.extraction_model
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=500,
                ),
            )
            return response.text
        except Exception as e:
            logger.error("llm.classify_error", model=model, error=str(e))
            raise
