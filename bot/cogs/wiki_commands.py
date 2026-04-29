"""
Wiki commands — /wiki status, /wiki search, /wiki lint.
"""
import re
import discord
from discord import app_commands
from discord.ext import commands

from utils.formatting import make_embed, truncate
from utils.logging_setup import get_logger

logger = get_logger(__name__)


def _extract_snippet(body: str, query: str, context_chars: int = 200) -> str:
    """Extract a relevant snippet around the query match in the body text.

    Falls back to the beginning of the body (skipping frontmatter) if no
    match is found.
    """
    # Strip YAML frontmatter if present
    clean = re.sub(r"^---\n.*?\n---\n?", "", body, flags=re.DOTALL).strip()

    # Try case-insensitive search for the query
    lower_clean = clean.lower()
    query_lower = query.lower()
    idx = lower_clean.find(query_lower)

    if idx >= 0:
        start = max(0, idx - context_chars // 2)
        end = min(len(clean), idx + len(query) + context_chars // 2)
        snippet = clean[start:end].strip()
        # Add ellipsis if we're not at the boundaries
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(clean) else ""
        return f"{prefix}{snippet}{suffix}"

    # No direct match — return beginning of body
    return truncate(clean, context_chars)


def _format_wiki_snippet(snippet: str) -> str:
    """Format a wiki snippet for clean Discord display."""
    # Collapse multiple newlines
    snippet = re.sub(r"\n{3,}", "\n\n", snippet)
    # Strip markdown headers from snippets (they look odd in embeds)
    snippet = re.sub(r"^#{1,6}\s+", "**", snippet, flags=re.MULTILINE)
    return snippet.strip()


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
                await interaction.followup.send(
                    embed=make_embed(
                        f"🔍 Wiki Search: {query}",
                        f"*No wiki pages found matching \"{query}\".*",
                        color=discord.Color.orange(),
                    )
                )
                return

            lines = []
            for p in pages:
                snippet = _extract_snippet(p.body, query, context_chars=250)
                clean_snippet = _format_wiki_snippet(snippet)
                lines.append(f"📄 **{p.title}**\n> {clean_snippet}")

            embed = make_embed(
                f"🔍 Wiki Search: {query}",
                "\n\n".join(lines),
                color=discord.Color.teal(),
                footer=f"{len(pages)} results found",
            )
            await interaction.followup.send(embed=embed)

        # Hidden command: lint
        # @self.wiki_group.command(name="lint", description="Run wiki health check (admin only)")
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
