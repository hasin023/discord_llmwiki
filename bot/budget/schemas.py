"""
Budget configuration schemas for monitoring and serialization.
"""
from pydantic import BaseModel


class ModelBudgetConfig(BaseModel):
    rpm_limit: int
    rpd_limit: int   # 0 = unlimited (paid tier)


class BudgetConfig(BaseModel):
    extraction_model: ModelBudgetConfig
    query_model: ModelBudgetConfig
    wiki_writer_model: ModelBudgetConfig
    cm_model: ModelBudgetConfig
    embedding_model: ModelBudgetConfig
    tier: str = "free"  # "free" | "paid"


class BudgetStatusEntry(BaseModel):
    rpm_remaining: float
    rpm_limit: int
    rpd_used: int
    rpd_limit: int
    rpd_date: str


class BudgetStatus(BaseModel):
    models: dict[str, BudgetStatusEntry] = {}
    tier: str = "free"
