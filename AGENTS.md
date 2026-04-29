# LLMWiki Discord Bot - Architecture & AI Agents Guide

This document is intended for future LLMs and developers working on this codebase. It outlines the core architecture, agent behaviors, and crucial data isolation rules of the Discord LLMWiki Community Manager Bot.

## 1. System Overview

The system is a local-first, privacy-focused Discord bot that automatically ingests conversation history, generates long-term semantic memories, and writes structured Markdown wikis. It proactively manages communities via "behaviours" while adhering strictly to free-tier API constraints.

### Core Technologies

- **LLM Provider:** Google Gemini API (`gemini-2.5-flash-lite`).
- **Embedding Model:** Local `BAAI/bge-small-en-v1.5` via `SentenceTransformers` (0 API cost).
- **Vector Store:** Local Qdrant container.
- **Memory Framework:** `mem0` (customized to run entirely locally without OpenAI).
- **Text Storage:** Local filesystem (`wiki/{guild_id}/...`) and SQLite (`history`).

## 2. Strict Data Isolation (Multi-Tenancy)

**CRITICAL RULE:** This bot operates across multiple Discord servers (Guilds). Data from one guild MUST NEVER leak into another.

- **Wiki Storage:** All wiki files must be stored under `wiki/{guild_id}/...`. The `WikiReader` and `WikiWriter` are strictly scoped to only read/write within their respective guild directories.
- **Memory Retrieval:** Direct calls to `mem0.memory_client.get_all()` are **unsafe** for user lookups because they are global. You must use `bot.hybrid_search.get_user_memories(user_id, guild_id)` to filter memories by server.
- **Qdrant Queries:** When writing custom Qdrant queries (like in `recognition.py`), you must always include a `FieldCondition` matching `key="metadata.guild_id"` to the current server.
- **Semantic Caching:** LLM answers are cached in `semantic_cache.py`. Entries are tagged with `guild_id` to prevent Server A's cached answers from being served to Server B.

## 3. The Community Manager (CM) Agent

The bot operates an event-driven agent (`bot/community_manager/agent.py`) that processes every message.

### Event-Driven Behaviours

These intercept incoming messages and can respond immediately:

- **FAQResponder:** Checks if a user's question matches a known FAQ in the Wiki.
- **ModerationAssist:** Evaluates text for toxicity/spam and flags it.
- _(Disabled for Budget)_ **ContextInjector & DuplicateDetector:** Disabled by default to conserve free-tier LLM quota, as they trigger `mem0.search()` and LLM calls on every message.

### Standalone Behaviours

These are triggered by commands or background tasks:

- **OnboardingFlow:** DMs new members a personalized welcome message summarizing the active channels in that guild based on the Wiki.
- **DigestScheduler:** Generates weekly summaries of channel activities and shared resources.
- **MemberRecognition:** Queries Qdrant directly to find the top contributors of the week for shoutouts.

### Creating a New Behaviour

1. Create a new class in `bot/community_manager/behaviours/`.
2. Implement an `async def evaluate(self, event: MessageEvent, channel) -> bool` method for event-driven behaviours.
3. Register it in the `CommunityManager.__init__` list in `bot/community_manager/agent.py`.

## 4. Ingestion & Wiki Pipeline

To prevent blocking the Discord event loop and exhausting the API, ingestion is decoupled:

1.  **Local Prefilter:** Short messages (<3 words) or spam are dropped immediately.
2.  **Async Queue:** Valid messages are pushed to an `asyncio.Queue` in `bot/ingestion/pipeline.py`.
3.  **Batch Processing:** The pipeline waits for a batch of messages (e.g., 10 messages or 180 seconds).
4.  **Local Embeddings:** The batch is embedded locally and stored in Qdrant via `mem0`.
5.  **Wiki Writing:** The batch is sent to `WikiWriter` (`bot/wiki/writer.py`), which uses the LLM to update the `channels/`, `timeline/`, and `resources/` markdown files.

## 5. Hybrid Search Layer

`bot/memory/hybrid_search.py` is the primary interface for retrieving knowledge.
It combines:

1.  **Mem0 Semantic Search:** Used for broad conceptual queries.
2.  **Qdrant Fallback:** Used when semantic search yields low scores.
3.  **Entity Resolution:** If a query mentions a specific user, it explicitly fetches their guild-scoped memories.

## 6. Budget Controller

Because the bot uses a free-tier Gemini key, `bot/budget/controller.py` tracks tokens and limits LLM calls.

- **High Priority:** User commands (`/ask`, `/summary`).
- **Low Priority:** Background tasks (Wiki writing).
  If the rate limit is approached, low-priority tasks will be skipped or queued to ensure interactive commands remain highly responsive.
