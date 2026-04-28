"""Member Recognition — Weekly top contributor shoutouts."""
import asyncio
import discord
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class MemberRecognition:
    """Tracks contributions and posts weekly recognition."""

    def __init__(self, memory_client, llm_client, config):
        self.memory = memory_client
        self.llm = llm_client
        self.config = config

    async def post_weekly_recognition(self, guild: discord.Guild,
                                       cm_config=None) -> None:
        if cm_config is None:
            from community_manager.config_store import ConfigStore
            store = ConfigStore(self.config.cm_config_path)
            cm_config = store.load(guild.id)

        channel_id = cm_config.recognition_channel_id
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            return

        # Query Mem0 for recent activity metadata
        top_contributors = await self._get_top_contributors(days=7, top_n=3)
        if not top_contributors:
            return

        members_text = []
        for user_id, count in top_contributors:
            member = guild.get_member(int(user_id))
            if member:
                members_text.append(f"{member.mention} ({count} contributions)")

        if not members_text:
            return

        await channel.send(
            f"🌟 **This week's top contributors:**\n"
            + "\n".join(f"• {m}" for m in members_text)
            + "\n\nThank you for keeping the conversation going! 🙌"
        )
        logger.info("recognition.posted", guild=guild.name)

    async def _get_top_contributors(self, days: int = 7,
                                     top_n: int = 3) -> list[tuple]:
        """Get top contributors from Mem0 history. Returns [(user_id, count)]."""
        # This queries the SQLite history DB for message counts
        # In practice, this would query mem0's internal history
        try:
            import sqlite3
            conn = sqlite3.connect(self.config.sqlite_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, COUNT(*) as cnt FROM history "
                "WHERE created_at > datetime('now', ?) "
                "GROUP BY user_id ORDER BY cnt DESC LIMIT ?",
                (f"-{days} days", top_n),
            )
            results = cursor.fetchall()
            conn.close()
            return results
        except Exception as e:
            logger.warning("recognition.query_error", error=str(e))
            return []
