"""Moderation Assist — Flags rule violations to moderators (non-punitive)."""
import json
import discord
from datetime import datetime

from memory.schemas import MessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class ModerationAssist:
    """Checks messages against community rules and escalates violations."""

    def __init__(self, llm_client, config):
        self.llm = llm_client
        self.config = config

    def is_enabled(self, cm_config) -> bool:
        return cm_config.moderation_enabled and bool(cm_config.mod_rules)

    async def should_fire(self, event: MessageEvent, cm_config) -> bool:
        if len(event.content) < 5:
            return False

        rules_text = "\n".join(
            f"{i+1}. {rule}" for i, rule in enumerate(cm_config.mod_rules)
        )

        prompt = (
            f"Check this Discord message against these community rules.\n\n"
            f"Rules:\n{rules_text}\n\n"
            f'Message: "{event.content}"\n\n'
            f"Respond ONLY with JSON:\n"
            f'{{"violation": true/false, "confidence": 0.0-1.0, '
            f'"rule_number": null, "reason": "brief reason"}}\n\n'
            f"Be conservative. Only flag clear violations."
        )

        try:
            result_text = await self.llm.classify(prompt, model=self.config.extraction_model)
            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(result_text)
            return result.get("violation") and result.get("confidence", 0) >= 0.85
        except Exception as e:
            logger.warning("moderation.classify_error", error=str(e))
            return False

    async def fire(self, event: MessageEvent, channel, cm_config) -> None:
        if not cm_config.mod_alert_channel_id:
            return

        alert_channel = channel.guild.get_channel(cm_config.mod_alert_channel_id)
        if not alert_channel:
            return

        embed = discord.Embed(
            title="⚠️ Moderation Alert",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Channel", value=f"<#{event.channel_id}>", inline=True)
        embed.add_field(name="Author", value=f"<@{event.author_id}>", inline=True)
        embed.add_field(name="Message", value=event.content[:500], inline=False)
        embed.set_footer(text="No action taken — human review required.")

        ping = f"<@&{cm_config.mod_role_id}>" if cm_config.mod_role_id else ""
        await alert_channel.send(ping, embed=embed)
        logger.info("moderation.alert_sent", channel=event.channel_name)
