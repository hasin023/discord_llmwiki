"""
WikiLinter — Checks wiki health and produces lint reports.
Runs daily at 03:00 UTC via background task.
"""
from datetime import datetime, timedelta
from pathlib import Path

import frontmatter

from utils.logging_setup import get_logger

logger = get_logger(__name__)


class WikiLinter:
    """Validates wiki structure and content quality."""

    def __init__(self, wiki_path: str = "/wiki"):
        self.wiki_path = Path(wiki_path)

    async def run_lint(self) -> dict:
        """Run all lint checks and return a report."""
        issues = []
        stats = {"total_pages": 0, "issues_found": 0}

        for md_file in self.wiki_path.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            stats["total_pages"] += 1
            file_issues = self._lint_page(md_file)
            if file_issues:
                issues.extend(file_issues)
                stats["issues_found"] += len(file_issues)

        report = {
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "issues": issues,
        }

        # Write lint report to log
        await self._write_lint_report(report)
        logger.info("wiki.lint_complete", **stats)
        return report

    def _lint_page(self, path: Path) -> list[dict]:
        """Lint a single wiki page."""
        issues = []
        rel_path = str(path.relative_to(self.wiki_path))

        try:
            post = frontmatter.load(str(path))

            # Check for missing frontmatter
            if not post.metadata:
                issues.append({
                    "file": rel_path,
                    "severity": "warning",
                    "message": "Missing YAML frontmatter",
                })

            # Check for missing title
            if not post.metadata.get("title"):
                issues.append({
                    "file": rel_path,
                    "severity": "warning",
                    "message": "Missing title in frontmatter",
                })

            # Check for missing type
            if not post.metadata.get("type"):
                issues.append({
                    "file": rel_path,
                    "severity": "info",
                    "message": "Missing type in frontmatter",
                })

            # Check for stale pages (not updated in 30+ days)
            updated = post.metadata.get("updated")
            if updated:
                try:
                    updated_date = datetime.strptime(str(updated), "%Y-%m-%d")
                    if datetime.now() - updated_date > timedelta(days=30):
                        issues.append({
                            "file": rel_path,
                            "severity": "info",
                            "message": f"Stale page (last updated: {updated})",
                        })
                except ValueError:
                    pass

            # Check for very short content
            if len(post.content.strip()) < 50:
                issues.append({
                    "file": rel_path,
                    "severity": "warning",
                    "message": "Very short content (<50 chars)",
                })

            # Check for broken internal links
            import re
            links = re.findall(r'\[.*?\]\(((?!http).*?\.md)\)', post.content)
            for link in links:
                link_path = path.parent / link
                if not link_path.exists():
                    issues.append({
                        "file": rel_path,
                        "severity": "error",
                        "message": f"Broken link: {link}",
                    })

        except Exception as e:
            issues.append({
                "file": rel_path,
                "severity": "error",
                "message": f"Parse error: {str(e)}",
            })

        return issues

    async def _write_lint_report(self, report: dict) -> None:
        """Append lint report to wiki/log.md."""
        log_path = self.wiki_path / "log.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        entry = (
            f"\n### Lint Report — {now}\n\n"
            f"- Total pages: {report['stats']['total_pages']}\n"
            f"- Issues found: {report['stats']['issues_found']}\n"
        )

        if report["issues"]:
            for issue in report["issues"][:10]:
                severity = issue["severity"].upper()
                entry += f"- [{severity}] `{issue['file']}`: {issue['message']}\n"
            if len(report["issues"]) > 10:
                entry += f"- ... and {len(report['issues']) - 10} more issues\n"

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass
