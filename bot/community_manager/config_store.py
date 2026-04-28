"""
Per-guild CM configuration store — JSON files on disk.
"""
import json
from pathlib import Path
from community_manager.schemas import CMConfig
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class ConfigStore:
    """Manages per-guild CM configuration as JSON files."""

    def __init__(self, config_path: str):
        self.base_path = Path(config_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, guild_id: int) -> Path:
        return self.base_path / f"{guild_id}.json"

    def load(self, guild_id: int) -> CMConfig:
        path = self._path(guild_id)
        if path.exists():
            try:
                return CMConfig(**json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:
                logger.warning("cm_config.load_error", guild_id=guild_id, error=str(e))
        return CMConfig()

    def save(self, guild_id: int, cm_config: CMConfig) -> None:
        path = self._path(guild_id)
        path.write_text(cm_config.model_dump_json(indent=2), encoding="utf-8")
        logger.info("cm_config.saved", guild_id=guild_id)
