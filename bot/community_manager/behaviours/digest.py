"""Digest Scheduler — Periodic server activity digests."""
import discord
from datetime import datetime

from utils.logging_setup import get_logger

logger = get_logger(__name__)


class DigestScheduler:
    """Generates and posts activity digests to a configured channel."""

    def __init__(self, memory_client, wiki_reader, llm_client, config):
        self.memory = memory_client
        self.wiki_reader = wiki_reader
        self.llm = llm_client
        self.config = config

    async def post_digest(self, guild: discord.Guild,
                          period: str = "daily", cm_config=None) -> None:
        if cm_config is None:
            from community_manager.config_store import ConfigStore
            store = ConfigStore(self.config.cm_config_path)
            cm_config = store.load(guild.id)

        channel_id = cm_config.digest_channel_id
        if not channel_id:
            return

        digest_channel = guild.get_channel(channel_id)
        if not digest_channel:
            return

        # Gather timeline data
        week_str = datetime.now().strftime("%Y_W%W")
        timeline_page = await self.wiki_reader.load_page(
            f"timeline/week_{week_str}.md", guild_id=guild.id,
        )
        recent_resources = await self._get_recent_resources(guild_id=guild.id)

        prompt = (
            f"Write a {period} digest post for a Discord server community manager bot.\n"
            f"Format for Discord (use markdown, emojis, keep it scannable).\n\n"
            f"Timeline / recent activity:\n"
            f"{timeline_page.body[:2000] if timeline_page else 'No timeline yet.'}\n\n"
            f"Recently shared resources:\n{recent_resources[:1000]}\n\n"
            f"Include:\n1. 🔥 Top topics discussed\n2. 🔗 Notable resources shared\n"
            f"3. 💡 Any decisions or conclusions reached\n4. 👋 New members\n\n"
            f"Keep it under 1500 characters total. Be concise and friendly."
        )

        digest_content = await self.llm.complete(prompt, model=cm_config.cm_model)

        embed = discord.Embed(
            title=f"📋 {'Daily' if period == 'daily' else 'Weekly'} Digest",
            description=digest_content[:4000],
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )
        await digest_channel.send(embed=embed)
        logger.info("digest.posted", period=period, guild=guild.name)

    async def _get_recent_resources(self, guild_id: int = None) -> str:
        pages = await self.wiki_reader.list_pages(page_type="resource", guild_id=guild_id)
        if not pages:
            return "No resources shared recently."
        return "\n".join(f"- {p.title}: {p.body[:100]}" for p in pages[:5])
