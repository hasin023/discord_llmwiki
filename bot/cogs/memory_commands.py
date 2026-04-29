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
            try:
                # Strictly search only this user's memories
                facts = await asyncio.to_thread(
                    self.bot.memory_client.get_all,
                    user_id=str(interaction.user.id),
                )
                results = facts.get("results", []) if isinstance(facts, dict) else facts

                if not results:
                    await interaction.followup.send(
                        "ℹ️ No memories are yet available for you.",
                        ephemeral=True,
                    )
                    return

                embed = make_embed(
                    "🧠 Your Memories",
                    format_facts_list(results, max_facts=15),
                    color=discord.Color.purple(),
                    footer=f"{len(results)} memories found",
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                logger.error("memory.view_error", error=str(e), user=str(interaction.user.id))
                await interaction.followup.send(
                    "❌ Failed to retrieve memories. Please try again later.",
                    ephemeral=True,
                )

        @self.memory_group.command(name="forget",
                                    description="Delete a specific memory")
        @app_commands.describe(memory_id="The memory to delete")
        async def forget(interaction: discord.Interaction, memory_id: str):
            try:
                await asyncio.to_thread(
                    self.bot.memory_client.delete, memory_id,
                )
                await interaction.response.send_message(
                    f"✅ Memory deleted.", ephemeral=True,
                )
            except Exception as e:
                await interaction.response.send_message(
                    f"❌ Failed to delete: {e}", ephemeral=True,
                )

        @forget.autocomplete("memory_id")
        async def forget_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            """Fetch user's memories dynamically for selection."""
            try:
                facts = await asyncio.to_thread(
                    self.bot.memory_client.get_all,
                    user_id=str(interaction.user.id),
                )
                results = facts.get("results", []) if isinstance(facts, dict) else facts
                
                choices = []
                for res in results:
                    # mem0 results are dictionaries containing 'id' and 'memory'
                    mem_id = res.get("id", "")
                    text = res.get("memory", "")
                    
                    if not text:
                        continue
                        
                    # Filter by what user typed
                    if current.lower() in text.lower():
                        # Discord allows max 100 chars for choice names
                        display_text = text[:97] + "..." if len(text) > 100 else text
                        choices.append(app_commands.Choice(name=display_text, value=str(mem_id)))
                        
                        if len(choices) >= 25:  # Discord UI limits to 25 choices max
                            break
                            
                return choices
            except Exception:
                return []

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
