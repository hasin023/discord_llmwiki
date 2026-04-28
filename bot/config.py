"""
Bot configuration — Pydantic settings loaded from .env file.
All defaults target the Gemini free tier (gemini-2.5-flash-lite + gemini-embedding-001).
"""
from pydantic_settings import BaseSettings
from typing import Literal


class Config(BaseSettings):
    # ─── Discord ──────────────────────────────────────────────────────────
    discord_token: str
    discord_guild_id: int

    # ─── Google Gemini ────────────────────────────────────────────────────
    gemini_api_key: str
    extraction_model: str = "gemini-2.5-flash-lite"
    query_model: str = "gemini-2.5-flash-lite"
    wiki_writer_model: str = "gemini-2.5-flash-lite"
    cm_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # ─── Budget Controller ────────────────────────────────────────────────
    budget_tier: Literal["free", "paid"] = "free"

    # ─── Qdrant ───────────────────────────────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "discord_memories"

    # ─── Ingestion ────────────────────────────────────────────────────────
    ingest_batch_size: int = 5
    ingest_flush_interval: int = 60
    ingest_rate_limit_per_channel: int = 20
    wiki_batch_size: int = 20
    wiki_batch_timeout_seconds: int = 600

    # ─── Semantic Cache ───────────────────────────────────────────────────
    cache_similarity_threshold: float = 0.92
    cache_ttl_hours: int = 24
    cache_max_entries: int = 200

    # ─── Retention ────────────────────────────────────────────────────────
    memory_retention_days: int = 180
    wiki_stale_days: int = 30

    # ─── Optional ─────────────────────────────────────────────────────────
    github_token: str = ""

    # ─── Paths ────────────────────────────────────────────────────────────
    wiki_path: str = "/wiki"
    sqlite_path: str = "/data/sqlite/mem0_history.db"
    cm_config_path: str = "/data/cm_config"
    cache_path: str = "/data/cache"

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


config = Config()
