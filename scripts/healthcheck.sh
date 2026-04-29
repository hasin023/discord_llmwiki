#!/usr/bin/env bash
# Health check script for the bot deployment
set -e

echo "=== LLMWiki Bot Health Check ==="

# Check Qdrant
echo -n "Qdrant: "
if curl -sf http://localhost:6333/readiness > /dev/null 2>&1; then
    echo "✅ Ready"
else
    echo "❌ Not responding"
    exit 1
fi

# Check bot container
echo -n "Bot container: "
if docker inspect llmwiki_bot --format='{{.State.Running}}' 2>/dev/null | grep -q true; then
    echo "✅ Running"
else
    echo "❌ Not running"
    exit 1
fi

# Check wiki directory
echo -n "Wiki directory: "
if [ -d "./wiki" ]; then
    PAGE_COUNT=$(find ./wiki -name "*.md" | wc -l)
    GUILD_COUNT=$(find ./wiki -mindepth 1 -maxdepth 1 -type d | wc -l)
    echo "✅ $PAGE_COUNT pages across $GUILD_COUNT guild(s)"
else
    echo "⚠️ Not initialized (run scripts/bootstrap_wiki.sh)"
fi

# Check data directories
echo -n "Data directories: "
for dir in data/qdrant data/sqlite data/cm_config data/cache; do
    if [ ! -d "$dir" ]; then
        echo "⚠️ Missing $dir"
        mkdir -p "$dir"
    fi
done
echo "✅ All present"

echo ""
echo "=== Health Check Complete ==="
