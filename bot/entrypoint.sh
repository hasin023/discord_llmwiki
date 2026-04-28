#!/bin/bash
# Entrypoint script — runs before the bot starts.
# Creates wiki structure and data directories on first boot.

set -e

WIKI_DIR="${WIKI_PATH:-/wiki}"
CM_DIR="${CM_CONFIG_PATH:-/data/cm_config}"
CACHE_DIR="${CACHE_PATH:-/data/cache}"
SQLITE_DIR="$(dirname "${SQLITE_PATH:-/data/sqlite/mem0_history.db}")"

# ── Create data directories ──────────────────────────────────────────
mkdir -p "$CM_DIR" "$CACHE_DIR" "$SQLITE_DIR"

# ── Bootstrap wiki if WIKI.md doesn't exist yet ──────────────────────
if [ ! -f "$WIKI_DIR/WIKI.md" ]; then
    echo "🔧 First boot — bootstrapping wiki structure..."
    mkdir -p "$WIKI_DIR"/{entities,topics,channels,timeline,synthesis,resources}

    cat > "$WIKI_DIR/WIKI.md" << 'WIKIEOF'
# LLMWiki Schema

## Purpose
This wiki is maintained by the LLMWiki bot. It serves as the compiled knowledge base
for a Discord server, synthesising conversations into structured, interlinked pages.

## Directory Structure
- entities/ — One page per notable person, tool, project, or concept
- topics/ — One page per recurring discussion topic
- channels/ — One page per active channel (auto-generated summaries)
- timeline/ — Weekly activity logs
- synthesis/ — Cross-cutting analysis and insight pages
- resources/ — One page per significant external resource shared in the server
WIKIEOF

    cat > "$WIKI_DIR/log.md" << 'LOGEOF'
# LLMWiki Operation Log

_Operations are appended automatically by the bot._
LOGEOF

    cat > "$WIKI_DIR/index.md" << 'IDXEOF'
# LLMWiki Index

_Last updated: initialization_

| Page | Type | Summary | Updated | Sources |
| ---- | ---- | ------- | ------- | ------- |
IDXEOF

    echo "✅ Wiki structure initialized at $WIKI_DIR"
fi

# ── Hand off to the actual bot process ───────────────────────────────
exec python main.py
