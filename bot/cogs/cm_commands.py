"""
CM commands — /cm status, /cm enable, /cm disable, /cm set-digest-channel,
/cm digest, /cm add-rule.
"""
import discord
from discord import app_commands
from discord.ext import commands

from community_manager.config_store import ConfigStore
from community_manager.schemas import CMConfig
from utils.formatting import make_embed
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class CMGroup(app_commands.Group):
    def __init__(self, config_path: str):
        super().__init__(
            name="cm",
            description="Community Manager Agent settings and controls",
        )
        self.store = ConfigStore(config_path)

    @app_commands.command(name="status", description="Show CM Agent behaviour status")
    async def status(self, interaction: discord.Interaction):
        cm_config = self.store.load(interaction.guild_id)
        embed = discord.Embed(
            title="🤖 Community Manager Agent Status",
            color=discord.Color.green() if cm_config.enabled else discord.Color.red(),
        )
        embed.add_field(
            name="Overall",
            value="✅ Enabled" if cm_config.enabled else "❌ Disabled",
            inline=False,
        )
        behaviours = {
            "Onboarding": cm_config.onboarding_enabled,
            "FAQ Responder": cm_config.faq_responder_enabled,
            "Context Injector": cm_config.context_injector_enabled,
            "Duplicate Detector": cm_config.duplicate_detector_enabled,
            "Digest": cm_config.digest_enabled,
            "Member Recognition": cm_config.recognition_enabled,
            "Moderation Assist": cm_config.moderation_enabled,
        }
        lines = "\n".join(f"{'✅' if v else '❌'} {k}" for k, v in behaviours.items())
        embed.add_field(name="Behaviours", value=lines, inline=False)

        if cm_config.digest_enabled and cm_config.digest_channel_id:
            embed.add_field(
                name="Digest",
                value=(
                    f"Posts to <#{cm_config.digest_channel_id}> "
                    f"({cm_config.digest_schedule} at {cm_config.digest_time_utc} UTC)"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="enable", description="Enable a CM behaviour (admin only)")
    @app_commands.describe(behaviour="Which behaviour to enable")
    @app_commands.choices(behaviour=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Onboarding", value="onboarding"),
        app_commands.Choice(name="FAQ Responder", value="faq"),
        app_commands.Choice(name="Context Injector", value="context"),
        app_commands.Choice(name="Duplicate Detector", value="duplicate"),
        app_commands.Choice(name="Digest", value="digest"),
        app_commands.Choice(name="Recognition", value="recognition"),
        app_commands.Choice(name="Moderation Assist", value="moderation"),
    ])
    async def enable(self, interaction: discord.Interaction, behaviour: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        cm_config = self.store.load(interaction.guild_id)
        mapping = {
            "all": {"enabled": True},
            "onboarding": {"onboarding_enabled": True},
            "faq": {"faq_responder_enabled": True},
            "context": {"context_injector_enabled": True},
            "duplicate": {"duplicate_detector_enabled": True},
            "digest": {"digest_enabled": True},
            "recognition": {"recognition_enabled": True},
            "moderation": {"moderation_enabled": True},
        }
        if behaviour in mapping:
            cm_config = cm_config.model_copy(update=mapping[behaviour])
            self.store.save(interaction.guild_id, cm_config)
            await interaction.response.send_message(
                f"✅ **{behaviour}** enabled.", ephemeral=True,
            )

    @app_commands.command(name="disable", description="Disable a CM behaviour (admin only)")
    @app_commands.describe(behaviour="Which behaviour to disable")
    @app_commands.choices(behaviour=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Onboarding", value="onboarding"),
        app_commands.Choice(name="FAQ Responder", value="faq"),
        app_commands.Choice(name="Context Injector", value="context"),
        app_commands.Choice(name="Duplicate Detector", value="duplicate"),
        app_commands.Choice(name="Digest", value="digest"),
        app_commands.Choice(name="Recognition", value="recognition"),
        app_commands.Choice(name="Moderation Assist", value="moderation"),
    ])
    async def disable(self, interaction: discord.Interaction, behaviour: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        cm_config = self.store.load(interaction.guild_id)
        mapping = {
            "all": {"enabled": False},
            "onboarding": {"onboarding_enabled": False},
            "faq": {"faq_responder_enabled": False},
            "context": {"context_injector_enabled": False},
            "duplicate": {"duplicate_detector_enabled": False},
            "digest": {"digest_enabled": False},
            "recognition": {"recognition_enabled": False},
            "moderation": {"moderation_enabled": False},
        }
        if behaviour in mapping:
            cm_config = cm_config.model_copy(update=mapping[behaviour])
            self.store.save(interaction.guild_id, cm_config)
            await interaction.response.send_message(
                f"✅ **{behaviour}** disabled.", ephemeral=True,
            )

    @app_commands.command(
        name="set-digest-channel",
        description="Set the channel where digests are posted (admin only)",
    )
    @app_commands.describe(channel="The channel for digest posts")
    async def set_digest_channel(self, interaction: discord.Interaction,
                                  channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        cm_config = self.store.load(interaction.guild_id)
        cm_config = cm_config.model_copy(update={"digest_channel_id": channel.id})
        self.store.save(interaction.guild_id, cm_config)
        await interaction.response.send_message(
            f"✅ Digest channel set to {channel.mention}.", ephemeral=True,
        )

    @app_commands.command(name="digest", description="Post a digest now (admin only)")
    @app_commands.describe(period="'daily' or 'weekly'")
    async def digest(self, interaction: discord.Interaction, period: str = "daily"):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        cm_config = self.store.load(interaction.guild_id)
        await self.bot_ref.cm_agent.digest.post_digest(
            interaction.guild, period=period, cm_config=cm_config,
        )
        await interaction.followup.send("✅ Digest posted.")

    @app_commands.command(name="add-rule",
                          description="Add a moderation rule (admin only)")
    @app_commands.describe(rule="The rule text")
    async def add_rule(self, interaction: discord.Interaction, rule: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        cm_config = self.store.load(interaction.guild_id)
        rules = cm_config.mod_rules + [rule]
        cm_config = cm_config.model_copy(
            update={"mod_rules": rules, "moderation_enabled": True},
        )
        self.store.save(interaction.guild_id, cm_config)
        await interaction.response.send_message(
            f"✅ Rule added: *{rule}*\nModeration assist enabled ({len(rules)} rules).",
            ephemeral=True,
        )


class CMCommandsCog(commands.Cog, name="CommunityManager"):
    def __init__(self, bot):
        self.bot = bot
        self.cm_group = CMGroup(bot.config_obj.cm_config_path)
        self.cm_group.bot_ref = bot
        bot.tree.add_command(self.cm_group)


async def setup(bot):
    await bot.add_cog(CMCommandsCog(bot))
