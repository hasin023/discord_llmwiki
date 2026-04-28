"""
Memory commands — /memory view, /memory forget, /memory forgetall.
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.formatting import make_embed, format_facts_list
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class MemoryGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="memory", description="View and manage your memories")


class MemoryCommandsCog(commands.Cog, name="Memory"):
    def __init__(self, bot):
        self.bot = bot
        self.memory_group = MemoryGroup()
        bot.tree.add_command(self.memory_group)

        @self.memory_group.command(name="view",
                                    description="See your memory entries (ephemeral)")
        async def view(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            facts = await asyncio.to_thread(
                self.bot.memory_client.get_all,
                user_id=str(interaction.user.id),
            )
            results = facts.get("results", []) if isinstance(facts, dict) else facts
            embed = make_embed(
                "🧠 Your Memories",
                format_facts_list(results, max_facts=15),
                color=discord.Color.purple(),
                footer=f"{len(results)} memories stored",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        @self.memory_group.command(name="forget",
                                    description="Delete a specific memory")
        @app_commands.describe(memory_id="The memory ID to delete")
        async def forget(interaction: discord.Interaction, memory_id: str):
            try:
                await asyncio.to_thread(
                    self.bot.memory_client.delete, memory_id,
                )
                await interaction.response.send_message(
                    f"✅ Memory `{memory_id}` deleted.", ephemeral=True,
                )
            except Exception as e:
                await interaction.response.send_message(
                    f"❌ Failed to delete: {e}", ephemeral=True,
                )

        @self.memory_group.command(name="forgetall",
                                    description="Delete ALL your memories")
        async def forgetall(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                await asyncio.to_thread(
                    self.bot.memory_client.delete_all,
                    user_id=str(interaction.user.id),
                )
                await interaction.followup.send(
                    "✅ All your memories have been deleted.", ephemeral=True,
                )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Failed: {e}", ephemeral=True,
                )


async def setup(bot):
    await bot.add_cog(MemoryCommandsCog(bot))
