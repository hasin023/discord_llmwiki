"""
CommunityManagerAgent — Orchestrates all CM behaviours with budget-aware gating.

Gate 1: LocalPreFilter (0 cost) — same filter as ingestion
Gate 2: BudgetController.check(CM_MODEL) — silences proactive behaviours if depleted
Gate 3: Per-behaviour should_fire() + fire()
"""
import discord

from budget.controller import BudgetController, BudgetDecision
from memory.ingestion import LocalPreFilter
from memory.schemas import MessageEvent
from community_manager.schemas import CMConfig
from community_manager.config_store import ConfigStore
from community_manager.behaviours.faq_responder import FAQResponder
from community_manager.behaviours.moderation_assist import ModerationAssist
from community_manager.behaviours.onboarding import OnboardingFlow
from community_manager.behaviours.digest import DigestScheduler
from community_manager.behaviours.recognition import MemberRecognition
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class CommunityManagerAgent:
    """Orchestrates all community manager behaviours."""

    def __init__(self, bot, memory_client, wiki_reader, llm_client,
                 budget: BudgetController, config):
        self.bot = bot
        self.budget = budget
        self.config_store = ConfigStore(config.cm_config_path)
        self._prefilter = LocalPreFilter()

        # Event-driven behaviours (evaluated per message, priority order)
        # NOTE: ContextInjector and DuplicateDetector disabled to conserve
        #       free-tier LLM quota. They trigger mem0.search() + LLM calls
        #       on every single message. Re-enable on paid tier.
        self.behaviours = [
            FAQResponder(memory_client, wiki_reader, llm_client, config),
            # ContextInjector(memory_client, wiki_reader, llm_client, config),
            # DuplicateDetector(memory_client, llm_client, config),
            ModerationAssist(llm_client, config),
        ]

        # Standalone behaviours
        self.onboarding = OnboardingFlow(llm_client, wiki_reader, config)
        self.digest = DigestScheduler(memory_client, wiki_reader, llm_client, config)
        self.recognition = MemberRecognition(memory_client, llm_client, config)

    def _get_config(self, guild_id: int) -> CMConfig:
        return self.config_store.load(guild_id)

    async def on_message(self, event: MessageEvent, channel) -> None:
        """Evaluate a message through all CM behaviours with budget gating."""
        cm_config = self._get_config(event.guild_id)
        if not cm_config.enabled:
            return

        # Gate 1: Local pre-filter (0 cost)
        if not self._prefilter.should_ingest(event):
            return

        # Gate 2: Budget check (0 cost — just checks counters)
        decision = await self.budget.check(
            model=cm_config.cm_model,
            tokens_estimate=500,
            priority="low",
        )
        if decision == BudgetDecision.SKIP:
            return

        # Gate 3: Per-behaviour evaluation
        for behaviour in self.behaviours:
            if not behaviour.is_enabled(cm_config):
                continue
            try:
                if await behaviour.should_fire(event, cm_config):
                    await behaviour.fire(event, channel, cm_config)
                    break  # Only one behaviour fires per message
            except Exception as e:
                logger.error(
                    "cm.behaviour_error",
                    behaviour=type(behaviour).__name__,
                    error=str(e),
                )

    async def on_member_join(self, member: discord.Member) -> None:
        """Handle a new member joining the server."""
        cm_config = self._get_config(member.guild.id)
        if cm_config.onboarding_enabled:
            await self.onboarding.welcome(member, cm_config)
