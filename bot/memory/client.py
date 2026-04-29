"""
Mem0 OSS client configuration.
Singleton memory client with Gemini LLM + local HuggingFace embedding + Qdrant vector store.
"""
from functools import lru_cache
from mem0 import Memory
from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


import google.generativeai as genai

# --- Runtime Patch for mem0ai Gemini function calling bug ---
_original_generate_content = genai.GenerativeModel.generate_content

def _patched_generate_content(self, contents, **kwargs):
    # If tool_config is passed but tools is empty, the API throws an error.
    # We strip tool_config if tools are absent or empty to prevent the 400 error.
    if "tool_config" in kwargs and not kwargs.get("tools"):
        del kwargs["tool_config"]
    return _original_generate_content(self, contents, **kwargs)

genai.GenerativeModel.generate_content = _patched_generate_content
# ------------------------------------------------------------

@lru_cache(maxsize=1)
def get_memory_client() -> Memory:
    """
    Create and cache a single Mem0 Memory instance.

    Configuration:
    - LLM: gemini-2.5-flash-lite (free tier) for fact extraction
    - Embedder: BAAI/bge-small-en-v1.5 (local, 384 dims, 0 API calls)
    - Vector store: Qdrant with 384-dim embeddings
    - History: SQLite for Mem0 operation logs
    """
    mem0_config = {
        "llm": {
            "provider": "gemini",
            "config": {
                "model": config.extraction_model,
                "api_key": config.gemini_api_key,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": config.embedding_model,
                "model_kwargs": {"device": "cpu"},
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": config.qdrant_host,
                "port": config.qdrant_port,
                "collection_name": config.qdrant_collection,
                "embedding_model_dims": 384,
            },
        },
        "history_db_path": config.sqlite_path,
    }

    logger.info(
        "memory.init",
        llm_model=config.extraction_model,
        embed_model=config.embedding_model,
        qdrant_host=config.qdrant_host,
    )
    return Memory.from_config(mem0_config)
