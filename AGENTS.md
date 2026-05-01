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

**CRITICAL RULE:** This bot operates across multiple Discord servers (Guilds). Data from one guild MUST NEVER leak into another. Every data path is enforced **programmatically** — never rely on LLM prompts for isolation.

- **Wiki Writing:** The `WikiWriter.process_batch()` groups incoming events by `guild_id` FIRST, then delegates each guild's sub-batch to `_process_guild_batch()`. This guarantees wiki files are written to the correct `wiki/{guild_id}/` directory even when the shared `WikiBuffer` contains messages from multiple guilds.
- **Wiki Reading:** The `WikiReader` methods (`find_relevant_pages`, `search_index`, `list_pages`, `get_page_count`) all require a `guild_id` parameter and ONLY search within `wiki/{guild_id}/`.
- **Memory Retrieval:** Direct calls to `mem0.memory_client.get_all()` are **unsafe** for user lookups because they are global. You must use `bot.hybrid_search.get_user_memories(user_id, guild_id)` to filter memories by server.
- **Hybrid Search:** `bot.hybrid_search.query()` accepts `guild_id` and passes it to all Qdrant fallback searches. `get_channel_memories()` also accepts and filters by `guild_id`. These are defense-in-depth filters on top of channel-scoped `agent_id` filtering.
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
5.  **Wiki Writing:** The batch is sent to `WikiWriter` (`bot/wiki/writer.py`), which **groups by guild_id** before using the LLM to update the `channels/`, `timeline/`, `entities/`, `topics/`, and `resources/` markdown files under each guild's directory.

## 5. Hybrid Search Layer

`bot/memory/hybrid_search.py` is the primary interface for retrieving knowledge.
It combines:

1.  **Mem0 Semantic Search:** Used for broad conceptual queries, scoped by `agent_id` (channel).
2.  **Qdrant Fallback (channel-scoped):** Used when semantic search yields no results. Filters by both `agent_id` AND `guild_id`.
3.  **Qdrant Fallback (guild-wide):** If channel-scoped search returns nothing, broadens to guild-wide Qdrant search using only `guild_id`.
4.  **Entity Resolution:** If a query mentions a specific user, it explicitly fetches their guild-scoped memories via `get_user_memories(user_id, guild_id)`.

### `/ask` Command Flow

The `/ask` command (`bot/cogs/query_commands.py`) resolves Discord mentions **before** any search:

1.  **Mention Resolution:** Discord `<@USER_ID>` and `<@!USER_ID>` tags are resolved to guild members by ID and replaced with human-readable display names in the question text. Plain `@username` and bare username references are also detected.
2.  **Cleaned Question:** The resolved question (e.g., `what does plum want to learn` instead of `what does <@123456> want to learn`) is used for all downstream search queries and the LLM prompt.
3.  **User Memory Fetch:** Detected members' memories are fetched via `get_user_memories()` (guild-scoped) and included as high-priority facts for the LLM.

### Anti-Hallucination Rules

The LLM system instruction in `bot/llm/client.py` enforces:
- Answer ONLY from provided facts and wiki context.
- NEVER confuse what different users said or did — attribute actions only when explicitly linked.
- Memory Facts (Mem0) take precedence over Wiki Context for user-specific questions.

## 6. Budget Controller

Because the bot uses a free-tier Gemini key, `bot/budget/controller.py` tracks tokens and limits LLM calls.

- **High Priority:** User commands (`/ask`, `/summary`).
- **Low Priority:** Background tasks (Wiki writing).
  If the rate limit is approached, low-priority tasks will be skipped or queued to ensure interactive commands remain highly responsive.
