#!/bin/bash
# Entrypoint script — runs before the bot starts.
# Creates data directories on first boot.
# Wiki guild subdirectories are created at runtime by WikiWriter/WikiReader.

set -e

WIKI_DIR="${WIKI_PATH:-/wiki}"
CM_DIR="${CM_CONFIG_PATH:-/data/cm_config}"
CACHE_DIR="${CACHE_PATH:-/data/cache}"
SQLITE_DIR="$(dirname "${SQLITE_PATH:-/data/sqlite/mem0_history.db}")"

# ── Create data directories ──────────────────────────────────────────
mkdir -p "$CM_DIR" "$CACHE_DIR" "$SQLITE_DIR"

# ── Bootstrap wiki root (guild subdirs created at runtime) ───────────
mkdir -p "$WIKI_DIR"

if [ ! -f "$WIKI_DIR/WIKI.md" ]; then
    echo "🔧 First boot — bootstrapping wiki root..."

    cat > "$WIKI_DIR/WIKI.md" << 'WIKIEOF'
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

Each guild's data is strictly isolated — the bot never reads from one guild's wiki
when serving another guild's commands.
WIKIEOF

    cat > "$WIKI_DIR/log.md" << 'LOGEOF'
# LLMWiki Operation Log

_Operations are appended automatically by the bot._
LOGEOF

    echo "✅ Wiki root initialized at $WIKI_DIR"
fi

# ── Hand off to the actual bot process ───────────────────────────────
exec python main.py
