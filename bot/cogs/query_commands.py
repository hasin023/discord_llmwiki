"""
Query commands — /ask, /whois, /summary slash commands.
Uses SemanticResponseCache + HybridSearch + BudgetController.
"""
import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands

from budget.controller import BudgetDecision
from utils.formatting import make_embed, truncate, format_facts_list
from utils.logging_setup import get_logger

logger = get_logger(__name__)

# Pattern to detect @username mentions in a question
# Matches both @username and plain username references
MENTION_RE = re.compile(r"@(\w+)", re.IGNORECASE)


class QueryCommandsCog(commands.Cog, name="Queries"):
    def __init__(self, bot):
        self.bot = bot

    def _extract_mentioned_members(
        self, question: str, guild: discord.Guild,
    ) -> list[discord.Member]:
        """Detect user mentions in the question text by matching against
        guild members' display names and usernames."""
        mentioned = []
        question_lower = question.lower()

        # Check explicit @mentions
        for match in MENTION_RE.finditer(question):
            name = match.group(1).lower()
            for member in guild.members:
                if (member.display_name.lower() == name
                        or member.name.lower() == name):
                    if member not in mentioned and not member.bot:
                        mentioned.append(member)

        # Also check plain name references (without @)
        for member in guild.members:
            if member.bot:
                continue
            if (member.display_name.lower() in question_lower
                    or member.name.lower() in question_lower):
                if member not in mentioned:
                    mentioned.append(member)

        return mentioned

    @app_commands.command(name="ask", description="Ask the knowledge base a question")
    @app_commands.describe(
        question="Your question",
        channel="Limit search to a specific channel",
    )
    async def ask(self, interaction: discord.Interaction, question: str,
                  channel: discord.TextChannel = None):
        await interaction.response.defer(thinking=True)

        try:
            # 0. Get guild_id for scoped queries
            guild_id = interaction.guild.id if interaction.guild else None

            # 1. Check semantic cache
            cached = await self.bot.semantic_cache.check(question, guild_id=guild_id)
            if cached:
                embed = make_embed(
                    "💬 Answer (cached)",
                    cached,
                    color=discord.Color.green(),
                    footer="From semantic cache — 0 API calls used",
                )
                await interaction.followup.send(embed=embed)
                return

            # 2. Budget check for LLM (embeddings are local now, no budget needed)
            decision = await self.bot.budget.check(
                model=self.bot.config_obj.query_model,
                priority="high",
            )
            if decision == BudgetDecision.SKIP:
                await interaction.followup.send(
                    "⚠️ LLM budget exhausted. Try again later.",
                    ephemeral=True,
                )
                return

            # 3. Determine search channel — default to current channel
            search_channel_id = channel.id if channel else interaction.channel.id

            # 4. Hybrid search — channel-scoped semantic search + Qdrant fallback
            facts = await self.bot.hybrid_search.query(
                question, channel_id=search_channel_id,
            )

            # 5. User mention detection — fetch mentioned users' memories
            user_facts = []
            mentioned_members = []
            if interaction.guild:
                mentioned_members = self._extract_mentioned_members(
                    question, interaction.guild,
                )
                for member in mentioned_members:
                    member_memories = await self.bot.hybrid_search.get_user_memories(
                        member.id, guild_id=guild_id, limit=10,
                    )
                    user_facts.extend(member_memories)
                    logger.info(
                        "ask.user_mention_fetch",
                        member=member.display_name,
                        memories=len(member_memories),
                    )

            # 6. Channel fallback — if semantic search + user lookup returned
            #    very few results, get recent channel memories for context
            channel_fallback = []
            if len(facts) + len(user_facts) < 3:
                channel_fallback = await self.bot.hybrid_search.get_channel_memories(
                    search_channel_id, limit=15,
                )
                logger.info(
                    "ask.channel_fallback",
                    channel_id=search_channel_id,
                    memories=len(channel_fallback),
                )

            # 7. Wiki search (guild-scoped)
            wiki_pages = await self.bot.wiki_reader.find_relevant_pages(
                question, max_pages=3, guild_id=guild_id,
            )

            # 8. Combine all memory sources — deduplicate by memory text
            all_facts = []
            seen_texts = set()

            for fact_list in [facts, user_facts, channel_fallback]:
                for f in fact_list:
                    text = f.get("memory", "")
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        all_facts.append(f)

            # 9. Build context for LLM
            mem0_facts = "\n".join(
                f"- {f.get('memory', '')}" for f in all_facts[:15]
            )
            wiki_context = "\n".join(
                p.body[:600] for p in wiki_pages
            ) if wiki_pages else ""

            # 10. LLM answer
            answer = await self.bot.llm_client.answer_question(
                question=question,
                mem0_facts=mem0_facts,
                wiki_context=wiki_context,
            )

            # 11. Store in cache
            await self.bot.semantic_cache.store(question, answer, guild_id=guild_id)

            # 12. Build response
            source_info = (
                f"Based on {len(all_facts)} facts + {len(wiki_pages)} wiki pages"
            )
            if mentioned_members:
                names = ", ".join(m.display_name for m in mentioned_members)
                source_info += f" | Fetched memories for: {names}"

            embed = make_embed(
                "💬 Answer",
                answer,
                footer=source_info,
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            error_msg = str(e)
            logger.error("ask.error", error=error_msg, question=question)

            # User-friendly error for rate limits
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                await interaction.followup.send(
                    "⚠️ API rate limit reached. Please wait a minute and try again.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "❌ Something went wrong while processing your question. Please try again later.",
                    ephemeral=True,
                )

    @app_commands.command(name="whois", description="See what the bot knows about a member")
    @app_commands.describe(member="The member to look up")
    async def whois(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(thinking=True)

        try:
            # Search by user_id and guild_id to get raw memories securely
            guild_id = interaction.guild.id if interaction.guild else None
            recent_results = await self.bot.hybrid_search.get_user_memories(
                member.id, guild_id=guild_id, limit=3,
            )



            # Format manually without scores
            if recent_results:
                memory_lines = [f"• {res.get('memory', '')}" for res in recent_results]
                description = "\n".join(memory_lines)
            else:
                description = "*No memories available yet.*"

            # Prepend basic Discord info
            profile_lines = [
                f"**Username:** {member.name}",
                f"**Display Name:** {member.display_name}",
                f"**Joined Server:** {member.joined_at.strftime('%B %d, %Y') if member.joined_at else 'Unknown'}",
                f"**Account Created:** {member.created_at.strftime('%B %d, %Y')}",
                f"**Roles:** {', '.join(r.name for r in member.roles[1:]) or 'None'}",
                "",
                "**📝 Memory:**",
                description,
            ]

            embed = make_embed(
                f"👤 About {member.display_name}",
                "\n".join(profile_lines),
                color=discord.Color.blue(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            error_msg = str(e)
            logger.error("whois.error", error=error_msg, member=str(member.id))

            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                await interaction.followup.send(
                    "⚠️ API rate limit reached. Please wait a minute and try again.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "❌ Failed to look up member information.",
                    ephemeral=True,
                )

    @app_commands.command(name="summary", description="Get a summary of recent activity")
    @app_commands.describe(period="Time period to summarize")
    @app_commands.choices(period=[
        app_commands.Choice(name="Last Day", value="last day"),
        app_commands.Choice(name="Last 3 Days", value="last 3 days"),
        app_commands.Choice(name="This Week", value="this week"),
        app_commands.Choice(name="Last 2 Weeks", value="last 2 weeks"),
    ])
    async def summary(self, interaction: discord.Interaction,
                      period: str = "this week"):
        await interaction.response.defer(thinking=True)

        try:
            guild_id = interaction.guild.id if interaction.guild else None
            wiki_pages = await self.bot.wiki_reader.list_pages(
                page_type="timeline", guild_id=guild_id,
            )
            if not wiki_pages:
                await interaction.followup.send("No activity data available yet.")
                return

            # Take the most recent 2 timeline pages, passing the full content
            # so the LLM has all context to filter by date
            latest = sorted(wiki_pages, key=lambda p: p.path, reverse=True)[:2]
            context = "\n\n".join(p.body for p in latest)

            from datetime import datetime
            now_str = datetime.now().strftime("%Y-%m-%d")

            answer = await self.bot.llm_client.complete(
                f"Today is {now_str}. Summarise this server activity for the past {period}. "
                f"Crucially, keep statements associated with the users who made them (e.g., '@user likes X'). "
                f"Do not assume statements from different users are contradictions. "
                f"Be concise, use bullet points, format for Discord.\n\n{context}",
            )

            embed = make_embed(
                f"📊 {period.title()} Summary",
                answer,
                color=discord.Color.purple(),
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            error_msg = str(e)
            logger.error("summary.error", error=error_msg)

            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                await interaction.followup.send(
                    "⚠️ API rate limit reached. Please wait a minute and try again.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "❌ Failed to generate summary. Please try again later.",
                    ephemeral=True,
                )


async def setup(bot):
    await bot.add_cog(QueryCommandsCog(bot))
