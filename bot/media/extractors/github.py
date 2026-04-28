"""GitHub repo/PR/issue metadata via REST API. No LLM call needed."""
import re
from typing import Optional
import httpx
from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class GitHubExtractor:
    API_BASE = "https://api.github.com"

    async def extract(self, url: str) -> Optional[str]:
        try:
            match = re.search(
                r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
                r"(?:/(pull|issues)/(\d+))?", url
            )
            if not match:
                return None

            owner, repo = match.group(1), match.group(2)
            resource_type = match.group(3)
            number = match.group(4)

            headers = {"Accept": "application/vnd.github+json"}
            if config.github_token:
                headers["Authorization"] = f"Bearer {config.github_token}"

            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                if resource_type == "pull":
                    resp = await client.get(
                        f"{self.API_BASE}/repos/{owner}/{repo}/pulls/{number}"
                    )
                    data = resp.json()
                    title = data.get("title", "")
                    body = data.get("body", "")[:200]
                    return f'GitHub PR #{number} in {owner}/{repo}: "{title}" — {body}'

                elif resource_type == "issues":
                    resp = await client.get(
                        f"{self.API_BASE}/repos/{owner}/{repo}/issues/{number}"
                    )
                    data = resp.json()
                    title = data.get("title", "")
                    body = data.get("body", "")[:200]
                    return f'GitHub issue #{number} in {owner}/{repo}: "{title}" — {body}'

                else:
                    resp = await client.get(
                        f"{self.API_BASE}/repos/{owner}/{repo}"
                    )
                    data = resp.json()
                    desc = data.get("description", "no description")
                    stars = data.get("stargazers_count", 0)
                    lang = data.get("language", "")
                    return f"GitHub repo {owner}/{repo}: {desc} [{lang}, {stars} stars]"

        except Exception as e:
            logger.warning("github.extract_failed", url=url[:60], error=str(e))
            return None
