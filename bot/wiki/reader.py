"""
WikiReader — Loads and searches wiki markdown pages.

Supports guild-scoped paths: searches within /wiki/{guild_id}/ when
guild_id is provided, falls back to searching the entire wiki root.
"""
import re
from pathlib import Path
from typing import Optional

import frontmatter

from memory.schemas import WikiPage
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class WikiReader:
    """Reads and searches the LLMWiki markdown file structure."""

    def __init__(self, wiki_path: str = "/wiki"):
        self.wiki_root = Path(wiki_path)

    def _get_search_path(self, guild_id: Optional[int | str] = None) -> Path:
        """Return the guild-scoped wiki path.

        SECURITY: When guild_id is provided, ALWAYS return the guild-specific
        path — never fall back to the wiki root. This prevents cross-server
        data leakage. The directory is created if it doesn't exist yet
        (new guild = empty wiki, not another guild's wiki).
        """
        if guild_id:
            guild_path = self.wiki_root / str(guild_id)
            guild_path.mkdir(parents=True, exist_ok=True)
            return guild_path
        # Only return wiki root when guild_id is genuinely unknown
        # (e.g. DMs, internal linter). This should NOT happen for
        # user-facing commands — all commands must pass guild_id.
        return self.wiki_root

    def _parse_page(self, path: Path, base_path: Path = None) -> WikiPage:
        """Parse a single markdown file into a WikiPage."""
        base = base_path or self.wiki_root
        try:
            post = frontmatter.load(str(path))
            # Strip code fences from body if LLM wrapped content
            body = post.content
            body_stripped = body.strip()
            if body_stripped.startswith("```"):
                first_nl = body_stripped.find("\n")
                if first_nl >= 0:
                    body = body_stripped[first_nl + 1:]
                if body.rstrip().endswith("```"):
                    body = body.rstrip()[:-3].rstrip()

            return WikiPage(
                path=str(path.relative_to(base)),
                title=post.metadata.get("title", path.stem.replace("_", " ").title()),
                page_type=post.metadata.get("type", self._infer_type(path, base)),
                body=body,
                frontmatter=dict(post.metadata),
                created=post.metadata.get("created"),
                updated=post.metadata.get("updated"),
            )
        except Exception as e:
            logger.warning("wiki.parse_error", path=str(path), error=str(e))
            return WikiPage(
                path=str(path.relative_to(base)),
                title=path.stem.replace("_", " ").title(),
                body=path.read_text(encoding="utf-8"),
            )

    def _infer_type(self, path: Path, base: Path = None) -> str:
        """Infer page type from directory."""
        base = base or self.wiki_root
        try:
            parts = path.relative_to(base).parts
        except ValueError:
            return ""
        if parts:
            type_map = {
                "entities": "entity", "topics": "topic",
                "channels": "channel", "timeline": "timeline",
                "synthesis": "synthesis", "resources": "resource",
            }
            # Check each part (skip guild_id directory)
            for part in parts:
                if part in type_map:
                    return type_map[part]
        return ""

    async def load_page(self, relative_path: str,
                        guild_id: Optional[int | str] = None) -> Optional[WikiPage]:
        """Load a single wiki page by relative path."""
        search_path = self._get_search_path(guild_id)
        full_path = search_path / relative_path
        if full_path.exists() and full_path.is_file():
            return self._parse_page(full_path, base_path=search_path)
        return None

    async def list_pages(self, page_type: str = None,
                         guild_id: Optional[int | str] = None) -> list[WikiPage]:
        """List all wiki pages, optionally filtered by type."""
        search_path = self._get_search_path(guild_id)
        pages = []
        for md_file in search_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            page = self._parse_page(md_file, base_path=search_path)
            if page_type is None or page.page_type == page_type:
                pages.append(page)
        return pages

    async def search_index(self, query: str, max_results: int = 5,
                           guild_id: Optional[int | str] = None) -> list[WikiPage]:
        """Simple keyword search across all wiki pages."""
        search_path = self._get_search_path(guild_id)
        query_lower = query.lower()
        results = []
        for md_file in search_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            try:
                content = md_file.read_text(encoding="utf-8").lower()
                if query_lower in content:
                    page = self._parse_page(md_file, base_path=search_path)
                    results.append(page)
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
        return results

    async def find_relevant_pages(self, query: str, max_pages: int = 3,
                                  guild_id: Optional[int | str] = None) -> list[WikiPage]:
        """Find wiki pages relevant to a query (keyword-based)."""
        search_path = self._get_search_path(guild_id)
        # Split query into keywords for broader matching
        keywords = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
        if not keywords:
            return []

        scored = []
        for md_file in search_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            try:
                content = md_file.read_text(encoding="utf-8").lower()
                score = sum(1 for kw in keywords if kw in content)
                if score > 0:
                    page = self._parse_page(md_file, base_path=search_path)
                    scored.append((score, page))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [page for _, page in scored[:max_pages]]

    async def get_page_count(self, guild_id: Optional[int | str] = None) -> dict:
        """Return counts of wiki pages by type."""
        search_path = self._get_search_path(guild_id)
        counts = {}
        for md_file in search_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            page_type = self._infer_type(md_file, base=search_path) or "other"
            counts[page_type] = counts.get(page_type, 0) + 1
        return counts
