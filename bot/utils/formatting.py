"""
Discord message formatting helpers.
Handles truncation, embed construction, and markdown-safe output.
"""
import discord
from datetime import datetime
from typing import Optional


MAX_EMBED_DESCRIPTION = 4096
MAX_FIELD_VALUE = 1024
MAX_MESSAGE_LENGTH = 2000


def truncate(text: str, max_length: int = MAX_MESSAGE_LENGTH, suffix: str = "…") -> str:
    """Truncate text to max_length, appending suffix if truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = discord.Color.blurple(),
    footer: Optional[str] = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Create a standardised Discord embed."""
    embed = discord.Embed(
        title=title,
        description=truncate(description, MAX_EMBED_DESCRIPTION),
        color=color,
    )
    if footer:
        embed.set_footer(text=footer)
    if timestamp:
        embed.timestamp = datetime.now()
    return embed


def format_facts_list(facts: list[dict], max_facts: int = 8) -> str:
    """Format Mem0 search results as a Discord-friendly bullet list."""
    if not facts:
        return "*No relevant memories found.*"
    lines = []
    for fact in facts[:max_facts]:
        memory = fact.get("memory", "")
        score = fact.get("score", 0)
        lines.append(f"• {truncate(memory, 200)} *(score: {score:.2f})*")
    return "\n".join(lines)


def format_wiki_pages(pages: list, max_pages: int = 3) -> str:
    """Format wiki pages for embed display."""
    if not pages:
        return "*No relevant wiki pages found.*"
    lines = []
    for page in pages[:max_pages]:
        title = getattr(page, "title", "Untitled")
        summary = getattr(page, "body", "")[:150]
        lines.append(f"📄 **{title}**\n{summary}…")
    return "\n\n".join(lines)
