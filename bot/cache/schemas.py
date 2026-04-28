"""
Cache configuration schemas.
"""
from pydantic import BaseModel


class CacheStats(BaseModel):
    entries: int
    max_entries: int
    total_cache_hits: int
    ttl_hours: float
    similarity_threshold: float
