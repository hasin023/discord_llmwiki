"""Member Recognition — Weekly top contributor shoutouts."""
import asyncio
import discord
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class MemberRecognition:
    """Tracks contributions and posts weekly recognition."""

    def __init__(self, hybrid_search, llm_client, config):
        self.hybrid_search = hybrid_search
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

        # Query Qdrant for recent activity metadata scoped to this guild
        top_contributors = await self._get_top_contributors(guild.id, days=7, top_n=3)
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

    async def _get_top_contributors(self, guild_id: int, days: int = 7,
                                     top_n: int = 3) -> list[tuple]:
        """Get top contributors by counting memory points in Qdrant for the guild."""
        try:
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
            from collections import Counter
            from datetime import datetime, timedelta
            import asyncio
            
            cutoff = datetime.now() - timedelta(days=days)
            
            # Scroll through the guild's memory points
            qdrant = self.hybrid_search._qdrant
            collection = self.hybrid_search.collection
            
            def do_scroll():
                return qdrant.scroll(
                    collection_name=collection,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="metadata.guild_id",
                                match=MatchValue(value=str(guild_id)),
                            )
                        ]
                    ),
                    limit=10000,
                    with_payload=True,
                    with_vectors=False,
                )
                
            records, _ = await asyncio.to_thread(do_scroll)
            
            counts = Counter()
            for r in records:
                payload = r.payload or {}
                user_id = payload.get("user_id")
                if not user_id:
                    continue
                    
                meta = payload.get("metadata", {})
                timestamp_str = meta.get("timestamp")
                if timestamp_str:
                    try:
                        ts = datetime.fromisoformat(timestamp_str)
                        if ts.tzinfo is not None:
                            ts = ts.replace(tzinfo=None)
                        if ts < cutoff:
                            continue
                    except Exception:
                        pass
                
                counts[user_id] += 1
                
            return counts.most_common(top_n)
        except Exception as e:
            logger.warning("recognition.query_error", error=str(e))
            return []
