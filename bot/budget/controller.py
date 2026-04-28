"""
BudgetController — Central rate-limit enforcer for all Gemini API calls.

Every component (IngestionWorker, WikiWriter, CommunityManagerAgent, QueryEngine)
calls budget.check() before making an API request. This prevents runaway usage
from exhausting daily free-tier limits.

Architecture:
    - One ModelBudget per model (async token bucket for RPM + daily counter for RPD)
    - Priority levels: high (/ask), normal (wiki, CM), low (ingestion, classification)
    - Returns: APPROVED | DEFERRED | SKIP
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict

from utils.logging_setup import get_logger

logger = get_logger(__name__)


class BudgetDecision(Enum):
    APPROVED = "approved"
    DEFERRED = "deferred"   # Caller should retry in 1 minute
    SKIP = "skip"           # Budget exhausted; drop this call


@dataclass
class ModelBudget:
    """Per-model rate limits and current counters."""
    # Limits
    rpm_limit: int          # Requests per minute
    rpd_limit: int          # Requests per day (0 = no daily limit)
    # Counters
    rpm_tokens: float = field(default_factory=lambda: 0.0)
    rpm_last_refill: float = field(default_factory=time.monotonic)
    rpd_count: int = 0
    rpd_date: date = field(default_factory=date.today)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        # Start with full RPM bucket
        self.rpm_tokens = float(self.rpm_limit)

    def _refill_rpm(self):
        now = time.monotonic()
        elapsed = now - self.rpm_last_refill
        # Refill tokens proportionally (1 token = 1 request per minute)
        refill = elapsed * (self.rpm_limit / 60.0)
        self.rpm_tokens = min(self.rpm_limit, self.rpm_tokens + refill)
        self.rpm_last_refill = now

    def _reset_rpd_if_new_day(self):
        today = date.today()
        if today != self.rpd_date:
            self.rpd_count = 0
            self.rpd_date = today

    async def try_consume(self, priority: str = "normal") -> BudgetDecision:
        async with self.lock:
            self._refill_rpm()
            self._reset_rpd_if_new_day()

            # Check daily limit
            if self.rpd_limit > 0 and self.rpd_count >= self.rpd_limit:
                return BudgetDecision.SKIP

            # Check RPM limit
            if self.rpm_tokens < 1.0:
                if priority == "high":
                    # Wait up to 5s for high-priority requests (/ask)
                    wait_seconds = (1.0 - self.rpm_tokens) / (self.rpm_limit / 60.0)
                    if wait_seconds <= 5.0:
                        await asyncio.sleep(wait_seconds)
                        self._refill_rpm()
                    else:
                        return BudgetDecision.DEFERRED
                else:
                    return BudgetDecision.DEFERRED

            self.rpm_tokens -= 1.0
            self.rpd_count += 1
            return BudgetDecision.APPROVED

    @property
    def status(self) -> dict:
        """Return current budget status for monitoring."""
        return {
            "rpm_remaining": round(self.rpm_tokens, 1),
            "rpm_limit": self.rpm_limit,
            "rpd_used": self.rpd_count,
            "rpd_limit": self.rpd_limit,
            "rpd_date": self.rpd_date.isoformat(),
        }


class BudgetController:
    """
    Central rate-limit enforcer for all Gemini API calls.

    Priority levels:
    - "high"   → /ask queries: will wait up to 5s for RPM slot
    - "normal" → wiki writing, CM responses
    - "low"    → background ingestion, CM classification
    """

    def __init__(self, budgets: Dict[str, ModelBudget]):
        self.budgets = budgets

    async def check(
        self,
        model: str,
        tokens_estimate: int = 1000,
        priority: str = "normal",
    ) -> BudgetDecision:
        budget = self.budgets.get(model)
        if budget is None:
            logger.warning("budget.unknown_model", model=model)
            return BudgetDecision.APPROVED  # No limit configured = allow

        decision = await budget.try_consume(priority=priority)
        if decision != BudgetDecision.APPROVED:
            logger.warning(
                "budget.limited",
                model=model,
                decision=decision.value,
                rpm_tokens=round(budget.rpm_tokens, 2),
                rpd_count=budget.rpd_count,
            )
        return decision

    def get_status(self) -> dict:
        """Return status of all model budgets for /budget status command."""
        return {
            model: budget.status
            for model, budget in self.budgets.items()
        }


def make_free_tier_budget_controller(config) -> BudgetController:
    """
    Free-tier limits (Q1 2026).
    gemini-2.5-flash-lite: 15 RPM, 1000 RPD
    gemini-embedding-001:  100 RPM, 1000 RPD

    We set our limits 20% below Google's to leave headroom.
    """
    return BudgetController({
        config.extraction_model: ModelBudget(
            rpm_limit=12,    # 80% of 15 RPM
            rpd_limit=800,   # 80% of 1000 RPD
        ),
        config.query_model: ModelBudget(
            rpm_limit=12,
            rpd_limit=800,
        ),
        config.wiki_writer_model: ModelBudget(
            rpm_limit=6,     # Wiki gets half the LLM budget
            rpd_limit=200,
        ),
        config.cm_model: ModelBudget(
            rpm_limit=4,     # CM gets the smallest slice
            rpd_limit=150,
        ),
        config.embedding_model: ModelBudget(
            rpm_limit=80,    # 80% of 100 RPM
            rpd_limit=800,
        ),
    })


def make_paid_tier_budget_controller(config) -> BudgetController:
    """
    Tier 1 paid limits (~150-300 RPM per model).
    Set high — cost is the constraint, not rate limits.
    """
    return BudgetController({
        config.extraction_model: ModelBudget(rpm_limit=200, rpd_limit=0),
        config.query_model: ModelBudget(rpm_limit=200, rpd_limit=0),
        config.wiki_writer_model: ModelBudget(rpm_limit=100, rpd_limit=0),
        config.cm_model: ModelBudget(rpm_limit=100, rpd_limit=0),
        config.embedding_model: ModelBudget(rpm_limit=1000, rpd_limit=0),
    })
