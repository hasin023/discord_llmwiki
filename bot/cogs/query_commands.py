"""
Query commands — /ask, /whois, /summary slash commands.
Uses SemanticResponseCache + HybridSearch + BudgetController.
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from budget.controller import BudgetDecision
from utils.formatting import make_embed, truncate, format_facts_list
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class QueryCommandsCog(commands.Cog, name="Queries"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ask", description="Ask the knowledge base a question")
    @app_commands.describe(
        question="Your question",
        channel="Limit search to a specific channel",
    )
    async def ask(self, interaction: discord.Interaction, question: str,
                  channel: discord.TextChannel = None):
        await interaction.response.defer(thinking=True)

        try:
            # 1. Check semantic cache
            cached = await self.bot.semantic_cache.check(question)
            if cached:
                embed = make_embed(
                    "💬 Answer (cached)",
                    cached,
                    color=discord.Color.green(),
                    footer="From semantic cache — 0 API calls used",
                )
                await interaction.followup.send(embed=embed)
                return

            # 2. Budget check for embedding
            decision = await self.bot.budget.check(
                model=self.bot.config_obj.embedding_model,
                priority="high",
            )
            if decision == BudgetDecision.SKIP:
                await interaction.followup.send(
                    "⚠️ Embedding budget exhausted for today. Try again tomorrow.",
                    ephemeral=True,
                )
                return

            # 3. Hybrid search
            channel_id = channel.id if channel else None
            facts = await self.bot.hybrid_search.query(question, channel_id=channel_id)

            # 4. Wiki search
            wiki_pages = await self.bot.wiki_reader.find_relevant_pages(question, max_pages=3)

            # 5. Budget check for LLM
            decision = await self.bot.budget.check(
                model=self.bot.config_obj.query_model,
                priority="high",
            )
            if decision == BudgetDecision.SKIP:
                # Still show facts even if LLM is unavailable
                embed = make_embed(
                    "📋 Raw Facts (LLM budget depleted)",
                    format_facts_list(facts),
                    color=discord.Color.orange(),
                )
                await interaction.followup.send(embed=embed)
                return

            # 6. LLM answer
            mem0_facts = "\n".join(
                f"- {f.get('memory', '')}" for f in (facts[:8] if facts else [])
            )
            wiki_context = "\n".join(
                p.body[:600] for p in wiki_pages
            ) if wiki_pages else ""

            answer = await self.bot.llm_client.answer_question(
                question=question,
                mem0_facts=mem0_facts,
                wiki_context=wiki_context,
            )

            # 7. Store in cache
            await self.bot.semantic_cache.store(question, answer)

            embed = make_embed(
                "💬 Answer",
                answer,
                footer=f"Based on {len(facts)} facts + {len(wiki_pages)} wiki pages",
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error("ask.error", error=str(e), question=question)
            await interaction.followup.send(
                f"❌ Something went wrong while processing your question. Please try again later.",
                ephemeral=True,
            )

    @app_commands.command(name="whois", description="See what the bot knows about a member")
    @app_commands.describe(member="The member to look up")
    async def whois(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(thinking=True)

        facts = await asyncio.to_thread(
            self.bot.memory_client.search,
            f"What do we know about {member.display_name}?",
            user_id=str(member.id),
            limit=10,
        )
        results = facts.get("results", []) if isinstance(facts, dict) else facts

        embed = make_embed(
            f"👤 About {member.display_name}",
            format_facts_list(results, max_facts=10),
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="summary", description="Get a summary of recent activity")
    @app_commands.describe(period="Time period: 'day', 'week', or 'month'")
    async def summary(self, interaction: discord.Interaction,
                      period: str = "week"):
        await interaction.response.defer(thinking=True)

        wiki_pages = await self.bot.wiki_reader.list_pages(page_type="timeline")
        if not wiki_pages:
            await interaction.followup.send("No activity data available yet.")
            return

        latest = sorted(wiki_pages, key=lambda p: p.path, reverse=True)[:2]
        context = "\n\n".join(p.body[:1000] for p in latest)

        answer = await self.bot.llm_client.complete(
            f"Summarise this server activity for the past {period}. "
            f"Be concise, use bullet points, format for Discord.\n\n{context}",
        )

        embed = make_embed(
            f"📊 {period.capitalize()} Summary",
            answer,
            color=discord.Color.purple(),
        )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(QueryCommandsCog(bot))
