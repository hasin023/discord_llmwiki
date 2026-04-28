"""
CM configuration schemas — per-guild settings stored as JSON.
"""
from pydantic import BaseModel
from typing import Optional


class CMConfig(BaseModel):
    enabled: bool = True
    cm_model: str = "gemini-2.5-flash-lite"

    # Onboarding
    onboarding_enabled: bool = True
    welcome_channel_id: Optional[int] = None

    # FAQ responder
    faq_responder_enabled: bool = True
    faq_confidence_threshold: float = 0.85

    # Context injection
    context_injector_enabled: bool = True
    context_injector_cooldown_hours: int = 24
    context_injector_similarity_threshold: float = 0.82
    context_injector_min_prior_facts: int = 3

    # Duplicate detector
    duplicate_detector_enabled: bool = True
    duplicate_threshold: float = 0.90
    duplicate_lookback_hours: int = 2

    # Digest
    digest_enabled: bool = True
    digest_channel_id: Optional[int] = None
    digest_schedule: str = "daily"
    digest_time_utc: str = "09:00"

    # Member recognition
    recognition_enabled: bool = False
    recognition_channel_id: Optional[int] = None

    # Moderation assist
    moderation_enabled: bool = False
    mod_rules: list[str] = []
    mod_alert_channel_id: Optional[int] = None
    mod_role_id: Optional[int] = None
