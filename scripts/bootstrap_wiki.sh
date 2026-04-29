#!/usr/bin/env bash
# Bootstrap the wiki root directory structure.
# Guild-specific subdirectories are created at runtime by the bot.
WIKI_DIR="${1:-./wiki}"

mkdir -p "$WIKI_DIR"

cat > "$WIKI_DIR/WIKI.md" << 'EOF'
# LLMWiki Schema

## Purpose
This wiki is maintained by the LLMWiki bot. It serves as the compiled knowledge base
for Discord servers, synthesising conversations into structured, interlinked pages.

## Directory Structure
Wiki pages are organised by guild (server) ID:
- {guild_id}/entities/ — One page per notable person, tool, project, or concept
- {guild_id}/topics/ — One page per recurring discussion topic
- {guild_id}/channels/ — One page per active channel (auto-generated summaries)
- {guild_id}/timeline/ — Weekly activity logs
- {guild_id}/synthesis/ — Cross-cutting analysis and insight pages
- {guild_id}/resources/ — One page per significant external resource shared in the server

## Page Format
All pages use YAML frontmatter with at minimum: title, type, created, updated.

## Resource Page Naming
- resources/ → yt_{video_id}.md, gh_{owner}_{repo}.md, article_{slug}.md, tweet_{id}.md

## Entity Page Naming
- entities/ → person_{name}.md, tool_{name}.md, project_{name}.md

## Topic Page Naming
- topics/ → topic_{slug}.md
EOF

cat > "$WIKI_DIR/log.md" << 'EOF'
# LLMWiki Operation Log

*Operations are appended automatically by the bot.*
EOF

cat > "$WIKI_DIR/index.md" << 'EOF'
# LLMWiki Index

*Last updated: initialization*

| Page | Type | Summary | Updated | Sources |
|------|------|---------|---------|---------| 
EOF

echo "✅ Wiki root initialized at $WIKI_DIR"
