"""
ListenerCog — Handles on_message and on_member_join events.
Feeds messages through the v3 ingestion pipeline.
"""
import re
import discord
from discord.ext import commands
from datetime import datetime

from memory.schemas import MessageEvent
from utils.rate_limiter import AsyncTokenBucket
from utils.logging_setup import get_logger

logger = get_logger(__name__)

# Regex to find URLs in message text
URL_RE = re.compile(r"https?://\S+")


class ListenerCog(commands.Cog, name="Listener"):
    def __init__(self, bot):
        self.bot = bot
        self.channel_limiter = AsyncTokenBucket(
            rate=bot.config_obj.ingest_rate_limit_per_channel,
            per=600.0,  # 10 minute window
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Skip bots (including self)
        if message.author.bot:
            return

        # Only process guild text channels
        if not isinstance(message.channel, discord.TextChannel):
            return

        # Per-channel rate limit
        if not await self.channel_limiter.acquire(str(message.channel.id)):
            return

        # Build MessageEvent
        urls = URL_RE.findall(message.content)
        event = MessageEvent(
            message_id=message.id,
            channel_id=message.channel.id,
            channel_name=message.channel.name,
            guild_id=message.guild.id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            author_username=str(message.author),
            content=message.content,
            timestamp=message.created_at or datetime.now(),
            has_attachments=bool(message.attachments),
            attachment_types=[
                a.content_type or "" for a in message.attachments
            ],
            raw_attachment_urls=[a.url for a in message.attachments],
            raw_urls=urls,
            reply_to_message_id=(
                message.reference.message_id
                if message.reference else None
            ),
        )

        # Feed to ingestion pipeline
        await self.bot.ingestion_worker.process(event, message)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle new member joins — triggers CM onboarding."""
        logger.info("member.join", member=member.display_name, guild=member.guild.name)
        await self.bot.cm_agent.on_member_join(member)


async def setup(bot):
    # Store config reference for the cog
    bot.config_obj = bot.config_obj if hasattr(bot, "config_obj") else None
    await bot.add_cog(ListenerCog(bot))
