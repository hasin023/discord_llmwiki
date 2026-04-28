"""
WikiReader — Loads and searches wiki markdown pages.
"""
import os
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
        self.wiki_path = Path(wiki_path)

    def _parse_page(self, path: Path) -> WikiPage:
        """Parse a single markdown file into a WikiPage."""
        try:
            post = frontmatter.load(str(path))
            return WikiPage(
                path=str(path.relative_to(self.wiki_path)),
                title=post.metadata.get("title", path.stem.replace("_", " ").title()),
                page_type=post.metadata.get("type", self._infer_type(path)),
                body=post.content,
                frontmatter=dict(post.metadata),
                created=post.metadata.get("created"),
                updated=post.metadata.get("updated"),
            )
        except Exception as e:
            logger.warning("wiki.parse_error", path=str(path), error=str(e))
            return WikiPage(
                path=str(path.relative_to(self.wiki_path)),
                title=path.stem.replace("_", " ").title(),
                body=path.read_text(encoding="utf-8"),
            )

    def _infer_type(self, path: Path) -> str:
        """Infer page type from directory."""
        parts = path.relative_to(self.wiki_path).parts
        if parts:
            type_map = {
                "entities": "entity", "topics": "topic",
                "channels": "channel", "timeline": "timeline",
                "synthesis": "synthesis", "resources": "resource",
            }
            return type_map.get(parts[0], "")
        return ""

    async def load_page(self, relative_path: str) -> Optional[WikiPage]:
        """Load a single wiki page by relative path."""
        full_path = self.wiki_path / relative_path
        if full_path.exists() and full_path.is_file():
            return self._parse_page(full_path)
        return None

    async def list_pages(self, page_type: str = None) -> list[WikiPage]:
        """List all wiki pages, optionally filtered by type."""
        pages = []
        for md_file in self.wiki_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            page = self._parse_page(md_file)
            if page_type is None or page.page_type == page_type:
                pages.append(page)
        return pages

    async def search_index(self, query: str, max_results: int = 5) -> list[WikiPage]:
        """Simple keyword search across all wiki pages."""
        query_lower = query.lower()
        results = []
        for md_file in self.wiki_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            try:
                content = md_file.read_text(encoding="utf-8").lower()
                if query_lower in content:
                    page = self._parse_page(md_file)
                    results.append(page)
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
        return results

    async def find_relevant_pages(self, query: str, max_pages: int = 3) -> list[WikiPage]:
        """Find wiki pages relevant to a query (keyword-based)."""
        # Split query into keywords for broader matching
        keywords = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
        if not keywords:
            return []

        scored = []
        for md_file in self.wiki_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            try:
                content = md_file.read_text(encoding="utf-8").lower()
                score = sum(1 for kw in keywords if kw in content)
                if score > 0:
                    page = self._parse_page(md_file)
                    scored.append((score, page))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [page for _, page in scored[:max_pages]]

    async def get_page_count(self) -> dict:
        """Return counts of wiki pages by type."""
        counts = {}
        for md_file in self.wiki_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            page_type = self._infer_type(md_file) or "other"
            counts[page_type] = counts.get(page_type, 0) + 1
        return counts
