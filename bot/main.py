"""
Bot entry point. Initialises all components in dependency order.

Startup sequence:
1. Config + Logging
2. Core clients (Mem0, Gemini)
3. BudgetController (free or paid tier)
4. SemanticResponseCache, HybridSearch
5. MediaEnricher, WikiReader/Writer
6. CommunityManagerAgent
7. IngestionWorker
8. Load cogs + sync slash commands
"""
import asyncio
import discord
from discord.ext import commands, tasks

from config import config
from memory.client import get_memory_client
from memory.ingestion import IngestionWorker
from memory.hybrid_search import HybridSearch
from media.enricher import MediaEnricher
from wiki.writer import WikiWriter
from wiki.reader import WikiReader
from wiki.linter import WikiLinter
from community_manager.agent import CommunityManagerAgent
from budget.controller import make_free_tier_budget_controller, make_paid_tier_budget_controller
from cache.semantic_cache import SemanticResponseCache
from llm.client import LLMClient
from utils.logging_setup import setup_logging, get_logger

setup_logging(config.log_level)
logger = get_logger("main")


class LLMWikiBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        # Store config reference for cogs
        self.config_obj = config

        # Core clients
        self.memory_client = get_memory_client()
        self.llm_client = LLMClient()

        # Budget controller — free or paid tier
        if config.budget_tier == "paid":
            self.budget = make_paid_tier_budget_controller(config)
        else:
            self.budget = make_free_tier_budget_controller(config)

        # Semantic response cache
        self.semantic_cache = SemanticResponseCache(
            gemini_client=self.llm_client.client,
            embedding_model=config.embedding_model,
            similarity_threshold=config.cache_similarity_threshold,
            max_entries=config.cache_max_entries,
            ttl_hours=config.cache_ttl_hours,
        )

        # Hybrid search (BM25 + dense)
        self.hybrid_search = HybridSearch(
            memory_client=self.memory_client,
            qdrant_host=config.qdrant_host,
            qdrant_port=config.qdrant_port,
            collection_name=config.qdrant_collection,
        )

        # Media enricher
        self.media_enricher = MediaEnricher(
            llm_client=self.llm_client,
            gemini_api_key=config.gemini_api_key,
            budget=self.budget,
        )

        # Wiki
        self.wiki_reader = WikiReader(wiki_path=config.wiki_path)
        self.wiki_writer = WikiWriter(
            llm_client=self.llm_client,
            wiki_reader=self.wiki_reader,
            budget=self.budget,
            config=config,
        )

        # Community Manager Agent
        self.cm_agent = CommunityManagerAgent(
            bot=self,
            memory_client=self.memory_client,
            wiki_reader=self.wiki_reader,
            llm_client=self.llm_client,
            budget=self.budget,
            config=config,
        )

        # Ingestion worker
        self.ingestion_worker = IngestionWorker(
            memory_client=self.memory_client,
            budget_controller=self.budget,
            media_enricher=self.media_enricher,
            wiki_buffer=self.wiki_writer.buffer,
            cm_agent=self.cm_agent,
            config=config,
        )

    async def setup_hook(self):
        logger.info("bot.loading_cogs")

        # Load all cogs
        for cog in [
            "cogs.listener",
            "cogs.query_commands",
            "cogs.wiki_commands",
            "cogs.memory_commands",
            "cogs.cm_commands",
        ]:
            try:
                await self.load_extension(cog)
                logger.info("bot.cog_loaded", cog=cog)
            except Exception as e:
                logger.error("bot.cog_error", cog=cog, error=str(e))

        # Start background tasks
        self.wiki_writer.start_background_task(self.loop)
        self.wiki_linter_task.start()
        self.cache_cleanup_task.start()

        # Sync slash commands
        guild = discord.Object(id=config.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("bot.commands_synced", guild_id=config.discord_guild_id)

    @tasks.loop(hours=24)
    async def wiki_linter_task(self):
        """Run wiki linter daily."""
        linter = WikiLinter(config.wiki_path)
        await linter.run_lint()

    @tasks.loop(hours=1)
    async def cache_cleanup_task(self):
        """Clean up expired semantic cache entries hourly."""
        self.semantic_cache.cleanup_expired()

    async def on_ready(self):
        logger.info(
            "bot.ready",
            user=str(self.user),
            guild_count=len(self.guilds),
            budget_tier=config.budget_tier,
        )


def main():
    bot = LLMWikiBot()
    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
