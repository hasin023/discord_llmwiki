"""
Mem0 OSS client configuration.
Singleton memory client with Gemini LLM + embedding + Qdrant vector store.
"""
from functools import lru_cache
from mem0 import Memory
from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_memory_client() -> Memory:
    """
    Create and cache a single Mem0 Memory instance.

    Configuration:
    - LLM: gemini-2.5-flash-lite (free tier) for fact extraction
    - Embedder: gemini-embedding-001 (stable GA, 100 RPM free)
    - Vector store: Qdrant with 768-dim embeddings
    - History: SQLite for Mem0 operation logs
    """
    mem0_config = {
        "llm": {
            "provider": "google",
            "config": {
                "model": config.extraction_model,
                "api_key": config.gemini_api_key,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "google",
            "config": {
                "model": config.embedding_model,
                "api_key": config.gemini_api_key,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": config.qdrant_host,
                "port": config.qdrant_port,
                "collection_name": config.qdrant_collection,
                "embedding_model_dims": 768,
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
