"""
Data models for message events and enriched content.
"""
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field


class MessageEvent(BaseModel):
    """Represents a Discord message for ingestion."""
    message_id: int
    channel_id: int
    channel_name: str
    guild_id: int
    author_id: int
    author_name: str
    author_username: str
    content: str
    timestamp: datetime
    has_attachments: bool = False
    attachment_types: list[str] = []
    raw_attachment_urls: list[str] = []
    raw_urls: list[str] = []
    reply_to_message_id: Optional[int] = None
    enriched_content: Optional[str] = None

    @property
    def date_str(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    def to_metadata_dict(self) -> dict:
        return {
            "channel_name": self.channel_name,
            "channel_id": str(self.channel_id),
            "guild_id": str(self.guild_id),
            "timestamp": self.timestamp.isoformat(),
            "message_id": str(self.message_id),
            "author_name": self.author_name,
            "has_media": bool(self.raw_attachment_urls or self.raw_urls),
        }

    def content_for_ingestion(self) -> str:
        return self.enriched_content or self.content


@dataclass
class EnrichedMessageEvent:
    """Message event enriched with media descriptions."""
    message_id: int
    channel_id: int
    channel_name: str
    guild_id: int
    author_id: int
    author_name: str
    author_username: str
    content: str
    timestamp: datetime
    has_attachments: bool = False
    raw_attachment_urls: list[str] = field(default_factory=list)
    raw_urls: list[str] = field(default_factory=list)
    reply_to_message_id: Optional[int] = None
    enriched_content: str = ""
    media_items: list[dict] = field(default_factory=list)

    @classmethod
    def from_message_event(cls, event: MessageEvent,
                           enriched_content: str = "",
                           media_items: list[dict] = None):
        return cls(
            message_id=event.message_id, channel_id=event.channel_id,
            channel_name=event.channel_name, guild_id=event.guild_id,
            author_id=event.author_id, author_name=event.author_name,
            author_username=event.author_username, content=event.content,
            timestamp=event.timestamp, has_attachments=event.has_attachments,
            raw_attachment_urls=event.raw_attachment_urls,
            raw_urls=event.raw_urls,
            reply_to_message_id=event.reply_to_message_id,
            enriched_content=enriched_content or event.content,
            media_items=media_items or [],
        )


class WikiPage(BaseModel):
    """Represents a wiki markdown page."""
    path: str
    title: str
    page_type: str = ""
    body: str = ""
    frontmatter: dict = {}
    created: Optional[str] = None
    updated: Optional[str] = None

    @field_validator("created", "updated", mode="before")
    @classmethod
    def _coerce_date(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return v
        # YAML frontmatter parses dates as datetime.date/datetime objects
        return str(v)


class QueryResult(BaseModel):
    """Result from a /ask query."""
    model_config = {"protected_namespaces": ()}  # Allow 'model_used' field name

    answer: str
    facts_used: int = 0
    wiki_pages_used: int = 0
    cache_hit: bool = False
    model_used: str = ""
