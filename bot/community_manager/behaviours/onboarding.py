"""Onboarding Flow — Welcome DM + server guide for new members."""
import discord
from typing import Optional
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class OnboardingFlow:
    def __init__(self, llm_client, wiki_reader, config):
        self.llm = llm_client
        self.wiki_reader = wiki_reader
        self.config = config

    async def _get_channel_summaries(self) -> str:
        pages = await self.wiki_reader.list_pages(page_type="channel")
        if not pages:
            return "No channel summaries available yet."
        return "\n".join(
            f"- #{p.title}: {p.body[:100]}" for p in pages[:5]
        )

    async def welcome(self, member: discord.Member, cm_config) -> None:
        channel_summaries = await self._get_channel_summaries()

        prompt = (
            f"You are a friendly community manager for a Discord server.\n"
            f"Write a warm, concise welcome DM for a new member named {member.display_name}.\n\n"
            f"Server's active channels and their purpose:\n{channel_summaries}\n\n"
            f"The message should:\n"
            f"- Be warm but not over-the-top\n"
            f"- Mention 2-3 most relevant channels to start in\n"
            f"- Tell them they can ask questions anytime\n"
            f"- Be under 200 words"
        )

        try:
            welcome_message = await self.llm.complete(prompt, model=cm_config.cm_model)
            await member.send(welcome_message)
            logger.info("onboarding.dm_sent", member=member.display_name)
        except discord.Forbidden:
            if cm_config.welcome_channel_id:
                channel = member.guild.get_channel(cm_config.welcome_channel_id)
                if channel:
                    await channel.send(
                        f"👋 Welcome to the server, {member.mention}! "
                        f"Feel free to introduce yourself!"
                    )
            logger.info("onboarding.dm_blocked", member=member.display_name)
        except Exception as e:
            logger.error("onboarding.error", error=str(e))
