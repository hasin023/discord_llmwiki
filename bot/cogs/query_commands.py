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

# Pattern to detect Discord's raw mention format: <@USER_ID> or <@!USER_ID>
DISCORD_MENTION_RE = re.compile(r"<@!?(\d+)>")

# Pattern to detect plain @username mentions in a question
PLAIN_MENTION_RE = re.compile(r"@(\w+)", re.IGNORECASE)


class QueryCommandsCog(commands.Cog, name="Queries"):
    def __init__(self, bot):
        self.bot = bot

    def _resolve_question_mentions(
        self, question: str, guild: discord.Guild,
    ) -> tuple[str, list[discord.Member]]:
        """Detect user mentions in the question text and return a clean
        question string + list of resolved members.

        Discord sends @mentions in slash-command string params as
        ``<@USER_ID>`` or ``<@!USER_ID>``.  We resolve them to actual
        guild members by ID AND replace the raw mention tag with the
        human-readable display name so the LLM prompt reads naturally.

        Also checks plain ``@username`` and bare ``username`` references
        as a fallback.
        """
        mentioned: list[discord.Member] = []
        cleaned_question = question

        # --- Step 1: Resolve Discord <@ID> / <@!ID> mentions by user ID ---
        for match in DISCORD_MENTION_RE.finditer(question):
            user_id = int(match.group(1))
            member = guild.get_member(user_id)
            if member and not member.bot and member not in mentioned:
                mentioned.append(member)
                # Replace the raw <@ID> with the readable display name
                cleaned_question = cleaned_question.replace(
                    match.group(0), member.display_name,
                )

        # --- Step 2: Check plain @username mentions ---
        for match in PLAIN_MENTION_RE.finditer(cleaned_question):
            name = match.group(1).lower()
            for member in guild.members:
                if (member.display_name.lower() == name
                        or member.name.lower() == name):
                    if member not in mentioned and not member.bot:
                        mentioned.append(member)

        # --- Step 3: Check bare name references (no @ prefix) ---
        cleaned_lower = cleaned_question.lower()
        for member in guild.members:
            if member.bot:
                continue
            if (member.display_name.lower() in cleaned_lower
                    or member.name.lower() in cleaned_lower):
                if member not in mentioned:
                    mentioned.append(member)

        return cleaned_question, mentioned

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

            # 4. Resolve Discord mentions — convert <@USER_ID> to readable
            #    names and detect mentioned members for memory lookup.
            #    cleaned_question is used for all downstream search + LLM.
            mentioned_members = []
            cleaned_question = question
            if interaction.guild:
                cleaned_question, mentioned_members = self._resolve_question_mentions(
                    question, interaction.guild,
                )

            # 5. Hybrid search — channel-scoped semantic search + Qdrant fallback
            #    guild_id ensures defense-in-depth isolation
            facts = await self.bot.hybrid_search.query(
                cleaned_question, channel_id=search_channel_id, guild_id=guild_id,
            )

            # 6. User mention lookup — fetch mentioned users' memories
            user_facts = []
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

            # 7. Channel fallback — if semantic search + user lookup returned
            #    very few results, get recent channel memories for context
            channel_fallback = []
            if len(facts) + len(user_facts) < 3:
                channel_fallback = await self.bot.hybrid_search.get_channel_memories(
                    search_channel_id, guild_id=guild_id, limit=15,
                )
                logger.info(
                    "ask.channel_fallback",
                    channel_id=search_channel_id,
                    memories=len(channel_fallback),
                )

            # 8. Wiki search (guild-scoped) — use cleaned question
            wiki_pages = await self.bot.wiki_reader.find_relevant_pages(
                cleaned_question, max_pages=3, guild_id=guild_id,
            )

            # 9. Combine all memory sources — deduplicate by memory text
            all_facts = []
            seen_texts = set()

            for fact_list in [facts, user_facts, channel_fallback]:
                for f in fact_list:
                    text = f.get("memory", "")
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        all_facts.append(f)

            # 10. Build context for LLM
            mem0_facts = "\n".join(
                f"- {f.get('memory', '')}" for f in all_facts[:15]
            )
            wiki_context = "\n".join(
                p.body[:600] for p in wiki_pages
            ) if wiki_pages else ""

            # 11. LLM answer — use cleaned_question so the LLM sees
            #     readable names, not raw <@ID> tags
            answer = await self.bot.llm_client.answer_question(
                question=cleaned_question,
                mem0_facts=mem0_facts,
                wiki_context=wiki_context,
            )

            # 12. Store in cache (keyed on cleaned question)
            await self.bot.semantic_cache.store(cleaned_question, answer, guild_id=guild_id)

            # 13. Build response
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
