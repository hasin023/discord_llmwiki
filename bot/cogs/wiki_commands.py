"""
Wiki commands — /wiki status, /wiki search, /wiki lint.
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.formatting import make_embed
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class WikiGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="wiki", description="Wiki knowledge base commands")


class WikiCommandsCog(commands.Cog, name="Wiki"):
    def __init__(self, bot):
        self.bot = bot
        self.wiki_group = WikiGroup()
        bot.tree.add_command(self.wiki_group)

        # Register commands on the group
        @self.wiki_group.command(name="status", description="Show wiki page counts and health")
        async def status(interaction: discord.Interaction):
            counts = await self.bot.wiki_reader.get_page_count()
            total = sum(counts.values())
            lines = [f"**{k}**: {v} pages" for k, v in sorted(counts.items())]
            embed = make_embed(
                "📚 Wiki Status",
                f"**Total pages:** {total}\n\n" + "\n".join(lines),
                color=discord.Color.teal(),
            )
            await interaction.response.send_message(embed=embed)

        @self.wiki_group.command(name="search", description="Search wiki by keyword")
        @app_commands.describe(query="Search term")
        async def search(interaction: discord.Interaction, query: str):
            await interaction.response.defer(thinking=True)
            pages = await self.bot.wiki_reader.search_index(query, max_results=5)
            if not pages:
                await interaction.followup.send(f"No wiki pages found for: *{query}*")
                return

            lines = []
            for p in pages:
                lines.append(f"📄 **{p.title}** (`{p.path}`)\n{p.body[:150]}…")
            embed = make_embed(
                f"🔍 Wiki Search: {query}",
                "\n\n".join(lines),
                color=discord.Color.teal(),
            )
            await interaction.followup.send(embed=embed)

        @self.wiki_group.command(name="lint", description="Run wiki health check (admin only)")
        async def lint(interaction: discord.Interaction):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Admin only.", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            from wiki.linter import WikiLinter
            linter = WikiLinter(self.bot.config_obj.wiki_path)
            report = await linter.run_lint()

            stats = report["stats"]
            issues = report["issues"][:10]
            lines = [
                f"📊 **{stats['total_pages']}** pages scanned",
                f"⚠️ **{stats['issues_found']}** issues found",
                "",
            ]
            for issue in issues:
                sev = issue["severity"].upper()
                lines.append(f"[{sev}] `{issue['file']}`: {issue['message']}")

            embed = make_embed("🔧 Wiki Lint Report", "\n".join(lines),
                             color=discord.Color.orange())
            await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(WikiCommandsCog(bot))
