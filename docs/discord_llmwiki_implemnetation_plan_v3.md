# Discord LLMWiki Community Manager Bot — Complete Implementation Plan v3

> **What changed in v3:**
> (1) **Model fixes** — `gemini-2.5-flash-lite` (stable GA) replaces the preview model as default; `gemini-embedding-001` replaces `gemini-embedding-2` for Phase 1 (text-only, stable, 25% cheaper, better free limits);
> (2) **Free-tier cost architecture** — the entire ingestion pipeline is redesigned around budget-awareness: local pre-filter, Mem0 batching (5 msgs per LLM call), content hash deduplication, async token-bucket rate limiter per model;
> (3) **Semantic response cache** — LLM responses for semantically similar queries are cached locally via embedding similarity (up to 73% cost reduction in repetitive workloads);
> (4) **Hybrid Search upgrade** — `/ask` retrieval now uses Qdrant's native sparse+dense hybrid search (BM25 + vector, fused via RRF) instead of pure vector search, significantly improving retrieval accuracy;
> (5) **Mem0 NLP mode** — `mem0ai[nlp]` hybrid search with BM25 + spaCy entity extraction enabled at the Mem0 level for better memory recall;
> (6) **Deprecation fix** — all references to `gemini-2.0-flash-lite` (deprecated June 2026) removed throughout;
> (7) **New Section 4.9 – Budget Controller** — a centrally-managed async token-bucket that enforces per-model daily/minute limits, with graceful fallback paths;
> (8) **New Section 4.10 – Semantic Response Cache** — embeddings-based deduplication of LLM responses before API calls;
> (9) **New Section 9.12 – Hybrid Search** — full Qdrant sparse+dense search implementation;
> (10) **Updated extension roadmap** — Phase 2 now covers gemini-embedding-2 migration, Phase 3 adds reranking (cross-encoder), Phase 4 adds graph memory (Mem0g).

---

## Table of Contents

1. [Vision & Design Philosophy](#1-vision--design-philosophy)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Full Directory Structure](#3-full-directory-structure)
4. [Component Deep-Dives](#4-component-deep-dives)
   - 4.1 Discord Bot (discord.py v2)
   - 4.2 Memory Layer (Mem0 OSS + Qdrant)
   - 4.3 Wiki Layer (LLMWiki-inspired Markdown)
   - 4.4 Ingestion Pipeline (redesigned for free tier)
   - 4.5 Query Engine (Slash Commands)
   - 4.6 Knowledge Accumulator & Linter
   - 4.7 Community Manager Agent
   - 4.8 Rich Media Ingestion Pipeline
   - **4.9 Budget Controller** _(new)_
   - **4.10 Semantic Response Cache** _(new)_
5. [Model & Embedding Decisions](#5-model--embedding-decisions)
6. [Data Models & Schemas](#6-data-models--schemas)
7. [Docker Compose Setup](#7-docker-compose-setup)
8. [Environment Variables & Configuration](#8-environment-variables--configuration)
9. [Complete File-by-File Code Specification](#9-complete-file-by-file-code-specification)
10. [Slash Commands Reference](#10-slash-commands-reference)
11. [Deployment Guide (VPS)](#11-deployment-guide-vps)
12. [Maintenance, Linting & Retention](#12-maintenance-linting--retention)
13. [Extension Roadmap](#13-extension-roadmap)

---

## 1. Vision & Design Philosophy

### 1.1 The Core Problem

Standard Discord bots are stateless. Every interaction starts from zero context. The bot has no idea what was discussed last Tuesday, who the key people in the server are, or how a topic evolved over weeks. Even RAG-based bots re-discover knowledge from scratch on every query — they don't _build up_ understanding.

Beyond memory, a Discord server without active management drifts: duplicate conversations happen in silos, new members feel unwelcome and don't know where to start, and no one synthesises the institutional knowledge scattered across hundreds of channels.

### 1.2 The Core Question: What Does an AI Community Manager Look Like?

> **"How can we set up an agent who works like a community manager in the Discord space?"**

A human community manager does the following things that a passive RAG bot does _not_:

| Human CM Action                               | Bot Equivalent                                         |
| --------------------------------------------- | ------------------------------------------------------ |
| Welcomes new members, explains the server     | Auto-welcome DM + onboarding flow                      |
| Answers FAQ without being tagged              | Proactive FAQ responder (monitors for trigger phrases) |
| Surfaces past context when a topic re-emerges | Proactive context injection into conversations         |
| Notices duplicate discussions across channels | Cross-channel duplicate detector                       |
| Keeps the community updated with digests      | Scheduled digest poster                                |
| Recognises active contributors                | Member recognition tracker                             |
| Flags rule violations to mods                 | Moderation assist (non-punitive; escalates to humans)  |
| Knows who knows what and can connect people   | Knowledge graph of members + their expertise areas     |
| Maintains a living knowledge base             | LLMWiki layer                                          |
| Answers deep questions about server history   | `/ask` slash command                                   |

This means the Community Manager Agent is **not just a knowledgebase wrapper** — it is a set of **proactive, event-driven behaviours** layered on top of the existing memory + wiki architecture.

### 1.3 The Solution: LLMWiki + Mem0 + Community Manager Agent

**Mem0 OSS (operational memory layer):**

- Extracts structured facts from every conversation batch
- Deduplicates and conflict-resolves automatically
- Persists facts per-user and per-channel in Qdrant (vector DB)
- Supports hybrid BM25 + semantic search at query time
- Acts as the "hot" working memory — granular, searchable facts

**LLMWiki (the compiled knowledge base):**

- A directory of Markdown files maintained by the LLM
- Organized into `entities/`, `topics/`, `channels/`, `timeline/`, `synthesis/`, and `resources/`
- Acts as the "cold" long-term knowledge — synthesised, cross-referenced, interlinked

**Community Manager Agent (the proactive layer):**

- Monitors message events and runs a rule-and-intent engine on each
- Fires autonomous behaviours: welcoming, FAQ answering, context injection, duplicate detection, digests
- All behaviours are backed by the memory + wiki layers
- Is configurable per-server: each behaviour can be enabled/disabled via `/cm config`

### 1.4 Free-Tier First Design Principle _(new in v3)_

The bot is designed to run on the **Gemini API free tier** without hitting rate limits for servers up to ~200 messages/day. Every component that calls the LLM or embedding API goes through the `BudgetController` first, which enforces per-model rate limits and triggers graceful fallbacks rather than crashing. Moving to paid tier requires only changing two environment variables (`EXTRACTION_MODEL`, `EMBEDDING_MODEL`) and bumping the rate limits.

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Discord Server                             │
│  #general  #dev  #announcements  #random  ...text channels...      │
│  [Images]  [YouTube links]  [GitHub links]  [Article links]        │
└────────────────────┬────────────────────────────────────────────────┘
                     │  on_message / on_member_join events
                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         Discord Bot Service                              │
│                                                                          │
│  ┌────────────────┐  ┌─────────────────────────────────────────────┐     │
│  │  Event         │  │         Ingestion Pipeline v3               │     │
│  │  Listener      │─▶│                                             │     │
│  │  (discord.py)  │  │  1. LocalPreFilter (0 API calls)            │     │
│  └───────┬────────┘  │  2. ContentHashDedupe (0 API calls)         │     │
│          │           │  3. MediaEnricher (LLM: image caption only) │     │
│          │           │  4. MessageBuffer (collect 5 msgs)          │     │
│          │           │  5. BudgetController.check(model, rpm, rpd) │     │
│          │           │  6. mem0.add(batch_of_5)   → Qdrant         │     │
│          │           │  7. WikiBuffer.append()                     │     │
│          │           └──────────────────────────────┬──────────────┘     │
│          │                                          │                    │
│          │  also feeds                              │ batch_threshold     │
│          ▼                                          ▼                    │
│  ┌───────────────────────────┐     ┌───────────────────────────────┐     │
│  │  CommunityManagerAgent    │     │  WikiWriter (async, periodic) │     │
│  │                           │     │  - uses BudgetController      │     │
│  │  For each message:        │     │  - creates/updates md pages   │     │
│  │  1. LocalPreFilter (fast) │     │  - resource pages for media   │     │
│  │  2. BudgetCheck (CM calls)│     └───────────────────────────────┘     │
│  │  3. Behaviour dispatch    │                                           │
│  │     (FAQ, Context, etc.)  │                                           │
│  └───────────────────────────┘                                           │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │  QueryEngine (/ask, /summary, /whois)                           │     │
│  │                                                                  │     │
│  │  1. SemanticResponseCache.check(question) ← cache hit? return   │     │
│  │  2. BudgetController.check(embedding_model)                      │     │
│  │  3. HybridSearch: Qdrant sparse+dense (BM25 + vector, RRF)      │     │
│  │  4. WikiReader.find_relevant_pages()                            │     │
│  │  5. BudgetController.check(query_model)                          │     │
│  │  6. LLM.answer_question()                                        │     │
│  │  7. SemanticResponseCache.store()                                │     │
│  └─────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
            │                        │
            ▼                        ▼
┌──────────────────────┐    ┌──────────────────────────────────────┐
│   Mem0 OSS Layer     │    │          LLM API (Google Gemini)     │
│   + Qdrant           │    │                                      │
│                      │    │  LLM (free):  gemini-2.5-flash-lite  │
│  Hybrid search:      │    │  LLM (paid):  gemini-3.1-flash-lite  │
│  BM25 + dense +      │    │  Embed:       gemini-embedding-001   │
│  sparse Qdrant index │    │                                      │
│  (RRF fusion)        │    │  BudgetController wraps every call:  │
│                      │    │  - AsyncTokenBucket per model        │
│  SemanticCache:      │    │  - Graceful fallback if depleted     │
│  Redis OR in-memory  │    │  - Daily RPD counter (resets 00:00)  │
└──────────────────────┘    └──────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────┐
│               LLMWiki (Markdown files)                           │
│  wiki/                                                           │
│    entities/  topics/  channels/  timeline/  synthesis/          │
│    resources/  index.md  log.md  WIKI.md                         │
└──────────────────────────────────────────────────────────────────┘
```

**Data flow summary:**

1. Message arrives → `LocalPreFilter` (pure Python, 0 API calls) — drops 60–70% of messages
2. `ContentHashDedupe` — drops exact/near-duplicate content (0 API calls)
3. `MediaEnricher` fires if message has images/URLs → enriches via LLM (budgeted)
4. `MessageBuffer` collects 5 messages, then fires as a single batched `mem0.add()` call
5. `BudgetController` approves or defers the call based on current RPM/RPD spend
6. `CommunityManagerAgent.evaluate()` — uses local pre-filter before any LLM call
7. `WikiBuffer` collects enriched events; `WikiWriter` wakes every 10 minutes or 20 messages
8. User types `/ask` → `SemanticResponseCache` checked first → `HybridSearch` (BM25 + vector) → `LLM.answer_question()`

---

## 3. Full Directory Structure

```
discord-llmwiki-bot/
│
├── docker-compose.yml
├── .env
├── .env.example
├── .env.free-tier          ← NEW: safe free-tier defaults
├── .gitignore
├── README.md
│
├── bot/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   │
│   ├── cogs/
│   │   ├── listener.py
│   │   ├── query_commands.py
│   │   ├── wiki_commands.py
│   │   ├── memory_commands.py
│   │   └── cm_commands.py
│   │
│   ├── memory/
│   │   ├── client.py
│   │   ├── ingestion.py          ← redesigned: batching + dedup + budget-aware
│   │   ├── hybrid_search.py      ← NEW: BM25 + dense RRF search
│   │   └── schemas.py
│   │
│   ├── wiki/
│   │   ├── writer.py
│   │   ├── reader.py
│   │   └── linter.py
│   │
│   ├── media/
│   │   ├── enricher.py
│   │   └── extractors/
│   │       ├── image.py
│   │       ├── youtube.py
│   │       ├── github.py
│   │       ├── article.py
│   │       └── twitter.py
│   │
│   ├── community_manager/
│   │   ├── agent.py             ← updated: local pre-filter gates all CM LLM calls
│   │   ├── behaviours/
│   │   │   ├── onboarding.py
│   │   │   ├── faq_responder.py
│   │   │   ├── context_injector.py
│   │   │   ├── duplicate_detector.py
│   │   │   ├── digest.py
│   │   │   ├── recognition.py
│   │   │   └── moderation_assist.py
│   │   ├── config_store.py
│   │   └── schemas.py
│   │
│   ├── budget/                                        ← NEW module
│   │   ├── __init__.py
│   │   ├── controller.py        # BudgetController: async token bucket per model
│   │   └── schemas.py           # BudgetConfig, BudgetStatus
│   │
│   ├── cache/                                         ← NEW module
│   │   ├── __init__.py
│   │   ├── semantic_cache.py    # SemanticResponseCache: embedding-based
│   │   └── schemas.py
│   │
│   ├── llm/
│   │   └── client.py            # Gemini client (google-genai SDK)
│   │
│   └── utils/
│       ├── formatting.py
│       ├── rate_limiter.py      ← updated: token bucket implementation
│       └── logging_setup.py
│
├── wiki/
│   ├── WIKI.md
│   ├── index.md
│   ├── log.md
│   ├── entities/
│   ├── topics/
│   ├── channels/
│   ├── timeline/
│   ├── synthesis/
│   └── resources/
│
├── data/
│   ├── qdrant/
│   ├── sqlite/
│   ├── cm_config/
│   └── cache/                  ← NEW: semantic cache storage (in-memory or Redis)
│
└── scripts/
    ├── bootstrap_wiki.sh
    └── healthcheck.sh
```

---

## 4. Component Deep-Dives

### 4.1 Discord Bot (discord.py v2)

**Library version:** `discord.py >= 2.4.0`

**Intents required:**

- `message_content` (privileged — enable in Developer Portal)
- `guilds`, `guild_messages`, `members` (privileged — enable in Developer Portal)

**setup_hook additions in v3:** Initialises `BudgetController`, `SemanticResponseCache`, and `HybridSearch` on startup alongside existing components.

**Message filtering rules** (in `listener.py`):

1. Skip messages from bots (including self)
2. Only process messages in guild text channels
3. Apply `LocalPreFilter` before anything else — drops 60–70% of messages at zero cost
4. Apply `ContentHashDedupe` — drops near-duplicates
5. Apply per-channel `AsyncTokenBucket` rate limit
6. Remaining messages go to `IngestionQueue`

### 4.2 Memory Layer (Mem0 OSS + Qdrant) — v3 updates

**Mem0 OSS configuration (updated):**

```python
# bot/memory/client.py
from functools import lru_cache
from mem0 import Memory
from config import config

@lru_cache(maxsize=1)
def get_memory_client() -> Memory:
    mem0_config = {
        "llm": {
            "provider": "google",
            "config": {
                "model": config.extraction_model,   # gemini-2.5-flash-lite (free)
                "api_key": config.gemini_api_key,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "google",
            "config": {
                # gemini-embedding-001: stable GA, 100 RPM free, $0.15/M paid
                # Switch to gemini-embedding-2 in Phase 2 for multimodal
                "model": config.embedding_model,    # gemini-embedding-001
                "api_key": config.gemini_api_key,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": config.qdrant_host,
                "port": config.qdrant_port,
                "collection_name": config.qdrant_collection,
                # gemini-embedding-001 uses 768-dim by default
                "embedding_model_dims": 768,
            },
        },
        "history_db_path": config.sqlite_path,
    }
    return Memory.from_config(mem0_config)
```

**Why `gemini-embedding-001` over `gemini-embedding-2` for Phase 1:**

- Stable GA model → 100 RPM / 1,000 RPD on free tier vs embedding-2's ~60 RPM
- $0.15/M vs $0.20/M on paid tier (25% cheaper)
- $0.075/M with Batch API (50% off) — perfect for background ingestion
- In Phase 1, images are captioned by the LLM first (text description), so embedder only ever sees text. The multimodal advantage of embedding-2 is unused until Phase 2.
- Migrate to `gemini-embedding-2` in Phase 2 (see Section 13)

**Mem0 NLP/Hybrid mode enabled:**

Install `mem0ai[nlp]` (see requirements.txt). This enables Mem0's internal hybrid search that combines BM25 keyword matching + semantic vector search + spaCy entity extraction for memory retrieval. This improves recall significantly for queries containing exact names, project names, or specific terminology.

### 4.3 Wiki Layer (LLMWiki-inspired Markdown)

Unchanged from v2. `resources/` directory holds one page per significant external resource shared in the server. See v2 Section 4.3 for full WIKI.md format spec.

### 4.4 Ingestion Pipeline — redesigned for free tier

The v3 ingestion pipeline adds **five zero-cost layers** before any API call:

```
on_message
    │
    ├── 1. LocalPreFilter (pure Python)  ← drops ~65% of messages, 0 API calls
    │      • len < 15 chars
    │      • pure emoji
    │      • one-word ack ("ok", "lol", etc.)
    │      • starts with /, !, ?
    │
    ├── 2. ContentHashDedupe (pure Python)  ← drops repeat content, 0 API calls
    │      • MD5 of first 200 chars
    │      • rolling set of 500 hashes
    │
    ├── 3. AsyncTokenBucket (per-channel)  ← rate-gate messages per channel
    │      • 20 msgs/channel/10 min on free tier
    │
    ├── 4. MediaEnricher (optional, budgeted)
    │      • BudgetController.check(LLM_MODEL) before image caption
    │      • YouTube/GitHub extractors use httpx only (no LLM call)
    │      • Article extractor uses httpx + readability (no LLM call)
    │      • Only images require an LLM call
    │
    ├── 5. MessageBuffer (collect N messages)  ← free, reduces mem0 LLM calls
    │      • Default batch_size = 5 (free tier)
    │      • Or flush after 60s if buffer not full
    │
    ├── 6. BudgetController.check(extraction_model)  ← enforces RPM/RPD budget
    │      • Returns: APPROVED | DEFERRED | SKIP
    │      • DEFERRED: queued for next minute
    │      • SKIP: message dropped silently (last resort)
    │
    └── 7. mem0.add(batch_of_5_messages)  ← ONE LLM call for 5 messages
           └── WikiBuffer.append(batch)
```

**Net effect:** 500 messages/day → ~65 LLM extraction calls/day (vs 500 in v2) = **87% reduction**.

```python
# bot/memory/ingestion.py

import asyncio
import hashlib
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from budget.controller import BudgetController, BudgetDecision
from memory.schemas import MessageEvent, EnrichedMessageEvent
from utils.logging_setup import get_logger

logger = get_logger(__name__)

TRIVIAL_RESPONSES = {
    "ok", "lol", "thanks", "thx", "nice", "cool", "yes", "no", "sure",
    "haha", "lmao", "xd", "gg", "brb", "afk", "👍", "❤️", "😂", "😭",
    "np", "nvm", "wtf", "omg", "wow", "damn", "shit", "lgtm", "wip",
}


class LocalPreFilter:
    """Zero-cost message filter. Eliminates ~65% of messages before any API call."""

    @staticmethod
    def should_ingest(event: MessageEvent) -> bool:
        content = event.content.strip()

        if len(content) < 15 and not event.has_attachments and not event.raw_urls:
            return False

        if content.lower() in TRIVIAL_RESPONSES:
            return False

        if content.startswith(("/", "!", "?", ".")):
            return False

        # Pure-emoji check (rough heuristic: no ASCII letters)
        import re
        if content and not re.search(r'[a-zA-Z0-9]', content):
            return False

        return True


class ContentHashDedup:
    """Rolling dedup cache to prevent re-embedding identical/near-identical content."""

    def __init__(self, max_size: int = 500):
        self._hashes: deque[str] = deque(maxlen=max_size)
        self._hash_set: set[str] = set()

    def is_duplicate(self, content: str) -> bool:
        key = hashlib.md5(content[:200].lower().strip().encode()).hexdigest()
        if key in self._hash_set:
            return True
        # Evict oldest if at capacity
        if len(self._hashes) == self._hashes.maxlen:
            oldest = self._hashes[0]
            self._hash_set.discard(oldest)
        self._hashes.append(key)
        self._hash_set.add(key)
        return False


class MessageBuffer:
    """Collects N messages before firing a single batched mem0.add() call."""

    def __init__(self, batch_size: int = 5, flush_interval_seconds: int = 60):
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self._buffer: list[EnrichedMessageEvent] = []
        self._last_flush = datetime.now()

    def add(self, event: EnrichedMessageEvent) -> Optional[list[EnrichedMessageEvent]]:
        """Add event to buffer. Returns a batch to process if threshold met."""
        self._buffer.append(event)
        should_flush = (
            len(self._buffer) >= self.batch_size
            or (datetime.now() - self._last_flush) > timedelta(seconds=self.flush_interval)
        )
        if should_flush and self._buffer:
            batch = list(self._buffer)
            self._buffer.clear()
            self._last_flush = datetime.now()
            return batch
        return None


class IngestionWorker:
    """Main ingestion pipeline. Processes messages through all filters before mem0."""

    def __init__(self, memory_client, budget_controller, media_enricher,
                 wiki_buffer, cm_agent, config):
        self.memory = memory_client
        self.budget = budget_controller
        self.enricher = media_enricher
        self.wiki_buffer = wiki_buffer
        self.cm_agent = cm_agent
        self.config = config

        self.prefilter = LocalPreFilter()
        self.dedup = ContentHashDedup()
        self.msg_buffer = MessageBuffer(
            batch_size=config.ingest_batch_size,
            flush_interval_seconds=config.ingest_flush_interval,
        )

    async def process(self, event: MessageEvent, discord_message) -> None:
        # Step 1: Local pre-filter (0 API calls)
        if not self.prefilter.should_ingest(event):
            return

        # Step 2: Content deduplication (0 API calls)
        if self.dedup.is_duplicate(event.content):
            return

        # Step 3: Media enrichment (LLM call only for images, budgeted)
        enriched = await self.enricher.enrich(event, discord_message)
        event.enriched_content = enriched.enriched_content

        # Step 4: CM agent evaluation (uses its own pre-filter + budget check)
        await self.cm_agent.on_message(event, discord_message.channel)

        # Step 5: Buffer message
        batch = self.msg_buffer.add(enriched)
        if batch is None:
            return  # Not enough messages yet

        # Step 6: Budget check before mem0 LLM call
        decision = await self.budget.check(
            model=self.config.extraction_model,
            tokens_estimate=2000 * len(batch),
        )
        if decision == BudgetDecision.SKIP:
            logger.warning("ingestion.skipped", reason="budget_exhausted", count=len(batch))
            return

        # Step 7: Single batched mem0.add() for all messages in batch
        combined_messages = [
            {
                "role": "user",
                "content": (
                    f"[{e.author_name} in #{e.channel_name} at {e.timestamp.strftime('%H:%M')}]: "
                    f"{e.enriched_content or e.content}"
                ),
            }
            for e in batch
        ]

        try:
            await asyncio.to_thread(
                self.memory.add,
                combined_messages,
                agent_id=f"channel_{batch[0].channel_id}",
                metadata={
                    "channel_name": batch[0].channel_name,
                    "guild_id": str(batch[0].guild_id),
                    "batch_size": len(batch),
                    "timestamp": batch[-1].timestamp.isoformat(),
                },
            )
            logger.info("ingestion.mem0_batch", size=len(batch))
        except Exception as e:
            logger.error("ingestion.mem0_error", error=str(e))

        # Step 8: Wiki buffer
        for e in batch:
            self.wiki_buffer.append(e)
```

### 4.5 Query Engine (Slash Commands)

Updated to use `HybridSearch` (Section 9.12) and `SemanticResponseCache` (Section 4.10).

```
/ask question:[text]
    │
    ├── 1. SemanticResponseCache.check(question)
    │       → CACHE HIT: return cached answer (0 API calls!)
    │
    ├── 2. BudgetController.check(embedding_model)
    │
    ├── 3. HybridSearch.query(question)
    │       → Qdrant sparse (BM25) + dense (vector) search, RRF fusion
    │       → Returns top 10 facts (vs top 5 in v2)
    │
    ├── 4. WikiReader.find_relevant_pages(question, max_pages=3)
    │
    ├── 5. BudgetController.check(query_model)
    │
    ├── 6. LLM.answer_question(question, facts, wiki_context)
    │
    └── 7. SemanticResponseCache.store(question, answer)
```

### 4.6 Knowledge Accumulator & Linter

`WikiWriter.process_batch()` creates/updates resource pages for any new URLs in the batch. The linter runs daily at 03:00 UTC and produces a lint report in `wiki/log.md`.

### 4.7 Community Manager Agent

The CM Agent now has a mandatory two-gate system for every message before any LLM call:

**Gate 1 — LocalPreFilter (same filter as ingestion):** If the message wouldn't even be worth storing in memory, it definitely doesn't need a CM response. This alone eliminates the same 65% of messages.

**Gate 2 — BudgetController.check(CM_MODEL):** If the CM model budget is depleted for this minute, all proactive behaviours are silenced. Interactive `/ask` queries are always prioritised above proactive CM behaviours in the budget allocation.

The seven behaviours (Onboarding, FAQ Responder, Context Injector, Duplicate Detector, Digest, Recognition, Moderation Assist) are unchanged from v2. See v2 Section 4.7 for full implementation of each.

**Updated `agent.py` gate logic:**

```python
# bot/community_manager/agent.py

async def on_message(self, event: MessageEvent, channel) -> None:
    if not self.cm_config.enabled:
        return

    # Gate 1: Local pre-filter (0 cost)
    if not self._prefilter.should_ingest(event):
        return

    # Gate 2: Budget check (0 cost — just checks counters)
    decision = await self.budget.check(
        model=self.cm_config.cm_model,
        tokens_estimate=500,  # Small estimate for CM classification call
        priority="low",       # CM is lower priority than /ask queries
    )
    if decision == BudgetDecision.SKIP:
        return

    # Gate 3: Per-behaviour evaluation
    for behaviour in self.behaviours:
        if not behaviour.is_enabled:
            continue
        try:
            if await behaviour.should_fire(event):
                await behaviour.fire(event, channel)
                break
        except Exception as e:
            logger.error("cm.behaviour_error", behaviour=type(behaviour).__name__, error=str(e))
```

### 4.8 Rich Media Ingestion Pipeline

The media pipeline has one key cost-saving change in v3: **only image attachments require an LLM call**. All URL types (YouTube, GitHub, articles, Twitter/X) are enriched using free HTTP calls only — no LLM token spend.

| Media Type           | Enrichment Method                                   | LLM call?         |
| -------------------- | --------------------------------------------------- | ----------------- |
| Image attachment     | Gemini multimodal caption (`gemini-2.5-flash-lite`) | ✅ Yes (budgeted) |
| YouTube link         | oEmbed API (httpx)                                  | ❌ No             |
| GitHub repo/PR/issue | GitHub REST API (httpx)                             | ❌ No             |
| Medium/blog article  | httpx + readability-lxml                            | ❌ No             |
| Twitter/X post       | oEmbed API (httpx)                                  | ❌ No             |

This reduces media enrichment LLM calls to ~10% of messages containing attachments (vs all URL-containing messages in naive implementations).

See v2 Section 4.8 for full extractor implementations. `MediaEnricher.enrich()` now wraps the image caption call with `BudgetController.check()` before firing.

---

### 4.9 Budget Controller _(new in v3)_

The `BudgetController` is the single choke point for all Gemini API calls. Every component — `IngestionWorker`, `WikiWriter`, `CommunityManagerAgent`, `QueryEngine` — calls `budget.check()` before making an API request. This prevents runaway usage from exhausting daily free-tier limits.

```python
# bot/budget/controller.py

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Dict
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class BudgetDecision(Enum):
    APPROVED = "approved"
    DEFERRED = "deferred"   # Caller should retry in 1 minute
    SKIP = "skip"           # Budget exhausted; drop this call


@dataclass
class ModelBudget:
    """Per-model rate limits and current counters."""
    # Limits
    rpm_limit: int          # Requests per minute
    rpd_limit: int          # Requests per day (0 = no daily limit)
    # Counters
    rpm_tokens: float = field(default_factory=lambda: 0.0)
    rpm_last_refill: float = field(default_factory=time.monotonic)
    rpd_count: int = 0
    rpd_date: date = field(default_factory=date.today)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _refill_rpm(self):
        now = time.monotonic()
        elapsed = now - self.rpm_last_refill
        # Refill tokens proportionally (1 token = 1 request per minute)
        refill = elapsed * (self.rpm_limit / 60.0)
        self.rpm_tokens = min(self.rpm_limit, self.rpm_tokens + refill)
        self.rpm_last_refill = now

    def _reset_rpd_if_new_day(self):
        today = date.today()
        if today != self.rpd_date:
            self.rpd_count = 0
            self.rpd_date = today

    async def try_consume(self, priority: str = "normal") -> BudgetDecision:
        async with self.lock:
            self._refill_rpm()
            self._reset_rpd_if_new_day()

            # Check daily limit
            if self.rpd_limit > 0 and self.rpd_count >= self.rpd_limit:
                return BudgetDecision.SKIP

            # Check RPM limit
            if self.rpm_tokens < 1.0:
                if priority == "high":
                    # Wait up to 5s for high-priority requests (/ask)
                    wait_seconds = (1.0 - self.rpm_tokens) / (self.rpm_limit / 60.0)
                    if wait_seconds <= 5.0:
                        await asyncio.sleep(wait_seconds)
                        self._refill_rpm()
                    else:
                        return BudgetDecision.DEFERRED
                else:
                    return BudgetDecision.DEFERRED

            self.rpm_tokens -= 1.0
            self.rpd_count += 1
            return BudgetDecision.APPROVED


class BudgetController:
    """
    Central rate-limit enforcer for all Gemini API calls.

    Priority levels:
    - "high"   → /ask queries: will wait up to 5s for RPM slot
    - "normal" → wiki writing, CM responses
    - "low"    → background ingestion, CM classification
    """

    def __init__(self, budgets: Dict[str, ModelBudget]):
        self.budgets = budgets

    async def check(
        self,
        model: str,
        tokens_estimate: int = 1000,
        priority: str = "normal",
    ) -> BudgetDecision:
        budget = self.budgets.get(model)
        if budget is None:
            logger.warning("budget.unknown_model", model=model)
            return BudgetDecision.APPROVED  # No limit configured = allow

        decision = await budget.try_consume(priority=priority)
        if decision != BudgetDecision.APPROVED:
            logger.warning(
                "budget.limited",
                model=model,
                decision=decision.value,
                rpm_tokens=budget.rpm_tokens,
                rpd_count=budget.rpd_count,
            )
        return decision


def make_free_tier_budget_controller(config) -> BudgetController:
    """
    Free-tier limits as of Q1 2026.
    gemini-2.5-flash-lite: 15 RPM, 1000 RPD
    gemini-embedding-001:  100 RPM, 1000 RPD

    We set our limits 20% below Google's to leave headroom.
    """
    return BudgetController({
        config.extraction_model: ModelBudget(
            rpm_limit=12,    # 80% of 15 RPM
            rpd_limit=800,   # 80% of 1000 RPD
        ),
        config.query_model: ModelBudget(
            rpm_limit=12,
            rpd_limit=800,
        ),
        config.wiki_writer_model: ModelBudget(
            rpm_limit=6,     # Wiki gets half the LLM budget
            rpd_limit=200,
        ),
        config.cm_model: ModelBudget(
            rpm_limit=4,     # CM gets the smallest slice
            rpd_limit=150,
        ),
        config.embedding_model: ModelBudget(
            rpm_limit=80,    # 80% of 100 RPM
            rpd_limit=800,
        ),
    })


def make_paid_tier_budget_controller(config) -> BudgetController:
    """
    Tier 1 paid limits (~150-300 RPM per model).
    Set high — cost is the constraint, not rate limits.
    """
    return BudgetController({
        config.extraction_model: ModelBudget(rpm_limit=200, rpd_limit=0),
        config.query_model: ModelBudget(rpm_limit=200, rpd_limit=0),
        config.wiki_writer_model: ModelBudget(rpm_limit=100, rpd_limit=0),
        config.cm_model: ModelBudget(rpm_limit=100, rpd_limit=0),
        config.embedding_model: ModelBudget(rpm_limit=1000, rpd_limit=0),
    })
```

**Budget allocation by tier (free tier, 500 msg/day server, after pre-filter):**

| Component            | Budget (RPD) | Description                                            |
| -------------------- | ------------ | ------------------------------------------------------ |
| Mem0 extraction LLM  | 65           | 500 msgs × 35% pass filter ÷ 5 batch = 35, plus margin |
| Image captioning LLM | 20           | ~10% of messages have images                           |
| Wiki writing LLM     | 50           | ~25 wiki batches per day                               |
| CM behaviour LLM     | 50           | 500 msgs × 35% pass filter × 5% fire rate              |
| `/ask` query LLM     | 100          | User-triggered, prioritised                            |
| Embedding (storage)  | 70           | One embedding per Mem0 batch-add                       |
| Embedding (search)   | 100          | `/ask` + CM context search                             |
| **Total LLM**        | **~285/day** | Well within 800 RPD limit                              |
| **Total embedding**  | **~170/day** | Well within 800 RPD limit                              |

---

### 4.10 Semantic Response Cache _(new in v3)_

The semantic response cache stores recent `/ask` responses and returns them for semantically similar follow-up questions without touching the LLM. This is particularly valuable for FAQ-style questions that many members ask ("what time is the weekly call?", "how do I get the developer role?").

The cache uses embedding similarity (cosine distance) to match incoming questions against cached questions. If the similarity exceeds the threshold (default: 0.92), the cached answer is returned directly.

**Cache backend:** In-memory (Phase 1 / free tier) using a simple cosine-similarity scan over cached embeddings. Redis backend available for Phase 2 / multi-instance deployment.

```python
# bot/cache/semantic_cache.py

import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from collections import deque

from google import genai
from google.genai import types
from utils.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    question: str
    answer: str
    embedding: list[float]
    created_at: datetime
    hit_count: int = 0


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticResponseCache:
    """
    Caches LLM responses for /ask queries and returns them for semantically
    similar questions without making a new LLM call.

    Particularly effective for FAQ-style questions in Discord servers where
    many members ask the same things (meeting times, role requirements, etc.)

    Expected savings: 20-40% reduction in /ask LLM calls for active servers.
    """

    def __init__(
        self,
        gemini_client,
        embedding_model: str = "gemini-embedding-001",
        similarity_threshold: float = 0.92,
        max_entries: int = 200,
        ttl_hours: int = 24,
    ):
        self.client = gemini_client
        self.embedding_model = embedding_model
        self.threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl = timedelta(hours=ttl_hours)
        self._cache: deque[CacheEntry] = deque(maxlen=max_entries)

    async def _embed_query(self, text: str) -> list[float]:
        """Embed a query using the instruction-prefix format for retrieval."""
        query_text = f"task: search result | query: {text}"
        result = await asyncio.to_thread(
            self.client.models.embed_content,
            model=self.embedding_model,
            contents=query_text,
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return result.embeddings[0].values

    async def check(self, question: str) -> Optional[str]:
        """
        Check if a semantically similar question has been answered recently.
        Returns cached answer if found, None otherwise.
        """
        if not self._cache:
            return None

        now = datetime.now()
        question_embedding = await self._embed_query(question)

        best_score = 0.0
        best_entry: Optional[CacheEntry] = None

        for entry in self._cache:
            # Skip expired entries
            if now - entry.created_at > self.ttl:
                continue
            score = cosine_similarity(question_embedding, entry.embedding)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= self.threshold and best_entry is not None:
            best_entry.hit_count += 1
            logger.info(
                "semantic_cache.hit",
                score=round(best_score, 3),
                hit_count=best_entry.hit_count,
                question_preview=question[:60],
            )
            return best_entry.answer

        return None

    async def store(self, question: str, answer: str) -> None:
        """Store a question-answer pair in the cache."""
        try:
            embedding = await self._embed_query(question)
            entry = CacheEntry(
                question=question,
                answer=answer,
                embedding=embedding,
                created_at=datetime.now(),
            )
            self._cache.append(entry)
            logger.debug("semantic_cache.stored", question_preview=question[:60])
        except Exception as e:
            logger.warning("semantic_cache.store_error", error=str(e))

    def stats(self) -> dict:
        total = len(self._cache)
        total_hits = sum(e.hit_count for e in self._cache)
        return {"entries": total, "total_cache_hits": total_hits}
```

---

## 5. Model & Embedding Decisions

### 5.1 LLM Model Tiers

| Tier                  | Model                           | Status    | Free RPM | Free RPD     | Paid Input | Paid Output |
| --------------------- | ------------------------------- | --------- | -------- | ------------ | ---------- | ----------- |
| **Free tier default** | `gemini-2.5-flash-lite`         | GA Stable | 15       | 1,000        | $0.10/M    | $0.40/M     |
| **Paid tier upgrade** | `gemini-3.1-flash-lite-preview` | Preview   | ~5–8     | ~few hundred | $0.25/M    | $1.50/M     |
| **Reasoning tasks**   | `gemini-2.5-flash`              | GA Stable | 10       | 500          | $0.30/M    | $2.50/M     |

**Important:** `gemini-3.1-flash-lite-preview` is a **preview model** — use it on paid tier only, after billing is enabled. On free tier, use `gemini-2.5-flash-lite` (stable, better free limits, cheaper paid price).

### 5.2 Embedding Model Decision

**Phase 1 (now): `gemini-embedding-001`**

- Stable GA, 100 RPM free, $0.15/M paid, $0.075/M batch
- Text-only: sufficient because images are captioned to text first
- 768-dim, top MTEB leaderboard score (68.32)

**Phase 2 (later): migrate to `gemini-embedding-2`**

- Multimodal: embed images, audio, video natively
- $0.20/M text, 60 RPM free (currently preview)
- Enables true cross-modal search: "find the screenshot Alice shared of that API error"
- Re-embedding the corpus requires a migration script (see Section 13, Phase 2)

### 5.3 Embedding Format (Asymmetric Retrieval)

For `gemini-embedding-001`, use the explicit `task_type` parameter:

```python
# For indexing (storing messages in Qdrant):
result = client.models.embed_content(
    model="gemini-embedding-001",
    contents=document_text,
    config=types.EmbedContentConfig(
        task_type="RETRIEVAL_DOCUMENT",
        title=f"#{channel_name} - {author_name}",
    ),
)

# For querying (user's /ask question):
result = client.models.embed_content(
    model="gemini-embedding-001",
    contents=user_question,
    config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
)
```

When migrating to `gemini-embedding-2` in Phase 2, replace `task_type` with instruction-prefix format:

```python
# gemini-embedding-2 uses instruction strings instead of task_type
document_text = f"title: {title} | text: {content}"
query_text = f"task: search result | query: {question}"
```

---

## 6. Data Models & Schemas

### 6.1 MessageEvent (v3)

```python
# bot/memory/schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class MessageEvent(BaseModel):
    message_id: int
    channel_id: int
    channel_name: str
    guild_id: int
    author_id: int
    author_name: str
    author_username: str
    content: str
    timestamp: datetime
    has_attachments: bool = False
    attachment_types: list[str] = []
    raw_attachment_urls: list[str] = []
    raw_urls: list[str] = []
    reply_to_message_id: Optional[int] = None
    enriched_content: Optional[str] = None

    @property
    def date_str(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    def to_metadata_dict(self) -> dict:
        return {
            "channel_name": self.channel_name,
            "channel_id": str(self.channel_id),
            "guild_id": str(self.guild_id),
            "timestamp": self.timestamp.isoformat(),
            "message_id": str(self.message_id),
            "author_name": self.author_name,
            "has_media": bool(self.raw_attachment_urls or self.raw_urls),
        }

    def content_for_ingestion(self) -> str:
        return self.enriched_content or self.content
```

### 6.2 BudgetConfig

```python
# bot/budget/schemas.py
from pydantic import BaseModel

class ModelBudgetConfig(BaseModel):
    rpm_limit: int
    rpd_limit: int   # 0 = unlimited (paid tier)

class BudgetConfig(BaseModel):
    extraction_model: ModelBudgetConfig
    query_model: ModelBudgetConfig
    wiki_writer_model: ModelBudgetConfig
    cm_model: ModelBudgetConfig
    embedding_model: ModelBudgetConfig
    tier: str = "free"  # "free" | "paid"
```

---

## 7. Docker Compose Setup

```yaml
# docker-compose.yml
version: "3.9"

services:
  qdrant:
    image: qdrant/qdrant:v1.9.1
    container_name: llmwiki_qdrant
    restart: unless-stopped
    volumes:
      - ./data/qdrant:/qdrant/storage:z
    ports:
      - "6333:6333"
      - "6334:6334"
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/readiness"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s

  bot:
    build:
      context: ./bot
      dockerfile: Dockerfile
    container_name: llmwiki_bot
    restart: unless-stopped
    depends_on:
      qdrant:
        condition: service_healthy
    volumes:
      - ./wiki:/wiki:rw
      - ./data/sqlite:/data/sqlite:rw
      - ./data/cm_config:/data/cm_config:rw
      - ./data/cache:/data/cache:rw
    env_file:
      - .env
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
```

---

## 8. Environment Variables & Configuration

### .env.free-tier _(new — safe defaults for free tier)_

```bash
# ─── REQUIRED ────────────────────────────────────────────────────────────
DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_GUILD_ID=123456789012345678
GEMINI_API_KEY=AIza...

# ─── FREE TIER MODELS (stable GA — best free limits) ─────────────────────
# LLM: gemini-2.5-flash-lite is stable, 15 RPM / 1,000 RPD free
# DO NOT use gemini-3.1-flash-lite-preview on free tier (preview = ~5 RPM)
EXTRACTION_MODEL=gemini-2.5-flash-lite
QUERY_MODEL=gemini-2.5-flash-lite
WIKI_WRITER_MODEL=gemini-2.5-flash-lite
CM_MODEL=gemini-2.5-flash-lite

# Embedding: gemini-embedding-001 is stable, 100 RPM / 1,000 RPD free
# Switch to gemini-embedding-2 in Phase 2 (after paying tier + re-index)
EMBEDDING_MODEL=gemini-embedding-001

# ─── BUDGET CONTROLLER (free tier conservative) ───────────────────────────
BUDGET_TIER=free
# These are automatically calculated from BUDGET_TIER.
# Override only if you want custom limits:
# BUDGET_LLM_RPM=12
# BUDGET_LLM_RPD=800
# BUDGET_EMBED_RPM=80
# BUDGET_EMBED_RPD=800

# ─── INGESTION (tuned for free tier) ─────────────────────────────────────
INGEST_BATCH_SIZE=5                  # Batch 5 msgs per mem0.add() LLM call
INGEST_FLUSH_INTERVAL=60             # Force flush after 60s even if batch not full
INGEST_RATE_LIMIT_PER_CHANNEL=20     # Max 20 msgs ingested per channel per 10 min
WIKI_BATCH_SIZE=20
WIKI_BATCH_TIMEOUT_SECONDS=600

# ─── SEMANTIC CACHE ───────────────────────────────────────────────────────
CACHE_SIMILARITY_THRESHOLD=0.92
CACHE_TTL_HOURS=24
CACHE_MAX_ENTRIES=200

# ─── QDRANT ───────────────────────────────────────────────────────────────
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_COLLECTION=discord_memories

# ─── OPTIONAL ─────────────────────────────────────────────────────────────
GITHUB_TOKEN=               # Optional: GitHub API token for richer link enrichment
MEMORY_RETENTION_DAYS=180
WIKI_STALE_DAYS=30
LOG_LEVEL=INFO
WIKI_PATH=/wiki
SQLITE_PATH=/data/sqlite/mem0_history.db
CM_CONFIG_PATH=/data/cm_config
CACHE_PATH=/data/cache
```

### .env.paid-tier _(for when you add billing)_

```bash
# ─── PAID TIER MODELS ────────────────────────────────────────────────────
# Switch LLM to the newer preview model once billing is enabled
EXTRACTION_MODEL=gemini-3.1-flash-lite-preview
QUERY_MODEL=gemini-3.1-flash-lite-preview
WIKI_WRITER_MODEL=gemini-3.1-flash-lite-preview
CM_MODEL=gemini-3.1-flash-lite-preview

# Embedding stays on gemini-embedding-001 until Phase 2 re-index
EMBEDDING_MODEL=gemini-embedding-001

BUDGET_TIER=paid
# Increase batch size since we have more headroom
INGEST_BATCH_SIZE=3          # Slightly more granular on paid
INGEST_RATE_LIMIT_PER_CHANNEL=200
```

### config.py (v3)

```python
# bot/config.py
from pydantic_settings import BaseSettings
from typing import Literal

class Config(BaseSettings):
    # Discord
    discord_token: str
    discord_guild_id: int

    # Google Gemini
    gemini_api_key: str
    extraction_model: str = "gemini-2.5-flash-lite"
    query_model: str = "gemini-2.5-flash-lite"
    wiki_writer_model: str = "gemini-2.5-flash-lite"
    cm_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # Budget controller
    budget_tier: Literal["free", "paid"] = "free"

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "discord_memories"

    # Ingestion
    ingest_batch_size: int = 5
    ingest_flush_interval: int = 60
    ingest_rate_limit_per_channel: int = 20
    wiki_batch_size: int = 20
    wiki_batch_timeout_seconds: int = 600

    # Semantic cache
    cache_similarity_threshold: float = 0.92
    cache_ttl_hours: int = 24
    cache_max_entries: int = 200

    # Retention
    memory_retention_days: int = 180
    wiki_stale_days: int = 30

    # Optional
    github_token: str = ""

    # Paths
    wiki_path: str = "/wiki"
    sqlite_path: str = "/data/sqlite/mem0_history.db"
    cm_config_path: str = "/data/cm_config"
    cache_path: str = "/data/cache"

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

config = Config()
```

---

## 9. Complete File-by-File Code Specification

### 9.1–9.9: Unchanged from v2

`main.py`, `cogs/listener.py`, `cogs/query_commands.py`, `cogs/wiki_commands.py`, `cogs/memory_commands.py`, `cogs/cm_commands.py`, `wiki/writer.py`, `wiki/reader.py`, `wiki/linter.py` — see v2 for full implementations. Updates: all pass through `BudgetController` and `SemanticResponseCache` at call sites.

### 9.10 bot/llm/client.py

```python
"""
LLM abstraction layer — Google Gemini via google-genai SDK.
"""
import asyncio
from google import genai
from google.genai import types
from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class LLMClient:
    def __init__(self):
        self.client = genai.Client(api_key=config.gemini_api_key)

    async def complete(self, prompt: str, model: str = None) -> str:
        model = model or config.wiki_writer_model
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=2000,
            ),
        )
        return response.text

    async def answer_question(
        self,
        question: str,
        mem0_facts: str,
        wiki_context: str,
        model: str = None,
    ) -> str:
        model = model or config.query_model

        system_instruction = (
            "You are a helpful Discord server assistant. Answer questions based "
            "ONLY on the provided memory facts and wiki context. If you don't have "
            "enough information, say so honestly. Cite sources. Be concise. "
            "Format for Discord markdown."
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"## Memory Facts (from Mem0):\n{mem0_facts or 'No relevant facts found.'}\n\n"
            f"## Wiki Context:\n{wiki_context or 'No relevant wiki pages found.'}\n\n"
            "Answer:"
        )

        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=model,
            contents=[types.Content(
                role="user",
                parts=[types.Part.from_text(user_prompt)]
            )],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=1500,
            ),
        )
        return response.text
```

### 9.11 bot/main.py (v3 startup)

```python
"""
Bot entry point. Initialises all components in dependency order.
"""
import asyncio
import discord
from discord.ext import commands
from config import config
from memory.client import get_memory_client
from memory.ingestion import IngestionWorker
from memory.hybrid_search import HybridSearch
from media.enricher import MediaEnricher
from wiki.writer import WikiWriter
from wiki.reader import WikiReader
from wiki.linter import WikiLinter
from community_manager.agent import CommunityManagerAgent
from budget.controller import make_free_tier_budget_controller, make_paid_tier_budget_controller
from cache.semantic_cache import SemanticResponseCache
from llm.client import LLMClient
from utils.logging_setup import setup_logging

setup_logging(config.log_level)


class LLMWikiBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        # Core clients
        self.memory_client = get_memory_client()
        self.llm_client = LLMClient()

        # Budget controller — free or paid tier
        if config.budget_tier == "paid":
            self.budget = make_paid_tier_budget_controller(config)
        else:
            self.budget = make_free_tier_budget_controller(config)

        # Components
        self.semantic_cache = SemanticResponseCache(
            gemini_client=self.llm_client.client,
            embedding_model=config.embedding_model,
            similarity_threshold=config.cache_similarity_threshold,
            max_entries=config.cache_max_entries,
            ttl_hours=config.cache_ttl_hours,
        )
        self.hybrid_search = HybridSearch(
            memory_client=self.memory_client,
            qdrant_host=config.qdrant_host,
            qdrant_port=config.qdrant_port,
            collection_name=config.qdrant_collection,
        )
        self.media_enricher = MediaEnricher(
            llm_client=self.llm_client,
            gemini_api_key=config.gemini_api_key,
            budget=self.budget,
        )
        self.wiki_reader = WikiReader(wiki_path=config.wiki_path)
        self.wiki_writer = WikiWriter(
            llm_client=self.llm_client,
            wiki_reader=self.wiki_reader,
            budget=self.budget,
            config=config,
        )
        self.cm_agent = CommunityManagerAgent(
            bot=self,
            memory_client=self.memory_client,
            wiki_reader=self.wiki_reader,
            llm_client=self.llm_client,
            budget=self.budget,
            config=config,
        )
        self.ingestion_worker = IngestionWorker(
            memory_client=self.memory_client,
            budget_controller=self.budget,
            media_enricher=self.media_enricher,
            wiki_buffer=self.wiki_writer.buffer,
            cm_agent=self.cm_agent,
            config=config,
        )

    async def setup_hook(self):
        # Load all cogs
        for cog in [
            "cogs.listener",
            "cogs.query_commands",
            "cogs.wiki_commands",
            "cogs.memory_commands",
            "cogs.cm_commands",
        ]:
            await self.load_extension(cog)

        # Start background tasks
        self.wiki_writer.start_background_task(self.loop)

        # Sync slash commands
        await self.tree.sync()


bot = LLMWikiBot()
bot.run(config.discord_token)
```

### 9.12 bot/memory/hybrid_search.py _(new in v3)_

Qdrant natively supports sparse + dense (hybrid) search since v1.7. This replaces the pure dense vector search used in v2 for `/ask` queries, dramatically improving retrieval quality for exact name/term matches.

```python
"""
Hybrid search: BM25 sparse + dense vector search fused via RRF.
Uses Qdrant's native sparse vectors (FastEmbed BM25) alongside Gemini embeddings.

Why this matters:
- Pure vector search: good at semantic similarity, bad at exact matches
- BM25 alone: good at exact terms ("what did @Alice say about Qdrant?"), bad at paraphrase
- Hybrid (RRF): consistently 5-15% better recall than either alone
- Reference: BM25 outperforms dense retrieval on domain-specific terminology in financial/tech docs
"""
import asyncio
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    SparseVector, NamedSparseVector, NamedVector, QueryRequest
)
from google import genai
from google.genai import types
from config import config
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class HybridSearch:
    """
    Combines BM25 keyword search with dense vector search via Reciprocal Rank Fusion.

    Qdrant setup required:
    - Dense collection: already created by Mem0 (768-dim gemini-embedding-001)
    - Sparse collection: created by this class using FastEmbed BM25 sparse encoder

    The sparse index is populated during ingestion (see IngestionWorker integration).
    """

    SPARSE_VECTORS_NAME = "bm25"
    DENSE_VECTORS_NAME = "dense"

    def __init__(
        self,
        memory_client,
        qdrant_host: str,
        qdrant_port: int,
        collection_name: str,
    ):
        self.memory = memory_client
        self.qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self.collection = collection_name
        self.gemini = genai.Client(api_key=config.gemini_api_key)

        # FastEmbed BM25 encoder for sparse vectors (runs locally, no API call)
        try:
            from fastembed.sparse import BM25
            self.bm25_encoder = BM25()
            self._hybrid_available = True
            logger.info("hybrid_search.bm25_available")
        except ImportError:
            self._hybrid_available = False
            logger.warning(
                "hybrid_search.fastembed_not_installed",
                msg="pip install fastembed to enable hybrid search"
            )

    async def _embed_query(self, query: str) -> list[float]:
        """Embed query for dense vector search using gemini-embedding-001."""
        result = await asyncio.to_thread(
            self.gemini.models.embed_content,
            model=config.embedding_model,
            contents=query,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        return result.embeddings[0].values

    def _encode_sparse(self, query: str) -> SparseVector:
        """Generate BM25 sparse vector for keyword search."""
        if not self._hybrid_available:
            return None
        sparse_result = list(self.bm25_encoder.query_embed(query))[0]
        return SparseVector(
            indices=sparse_result.indices.tolist(),
            values=sparse_result.values.tolist(),
        )

    async def query(
        self,
        question: str,
        channel_id: Optional[int] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Hybrid search: BM25 + dense + RRF fusion.
        Falls back to pure mem0.search() if fastembed not installed.
        """
        if not self._hybrid_available:
            # Fallback: use Mem0's built-in semantic search
            filter_kwargs = {}
            if channel_id:
                filter_kwargs["agent_id"] = f"channel_{channel_id}"
            results = await asyncio.to_thread(
                self.memory.search,
                question,
                limit=limit,
                **filter_kwargs,
            )
            return results.get("results", [])

        # Full hybrid search path
        try:
            dense_embedding = await self._embed_query(question)
            sparse_vector = self._encode_sparse(question)

            # Qdrant prefetch for fusion
            from qdrant_client.models import Prefetch, FusionQuery, Fusion

            filter_condition = None
            if channel_id:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                filter_condition = Filter(
                    must=[
                        FieldCondition(
                            key="metadata.channel_id",
                            match=MatchValue(value=str(channel_id))
                        )
                    ]
                )

            results = await asyncio.to_thread(
                self.qdrant.query_points,
                collection_name=self.collection,
                prefetch=[
                    Prefetch(
                        query=dense_embedding,
                        using=self.DENSE_VECTORS_NAME,
                        limit=20,
                        filter=filter_condition,
                    ),
                    Prefetch(
                        query=sparse_vector,
                        using=self.SPARSE_VECTORS_NAME,
                        limit=20,
                        filter=filter_condition,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=limit,
            )

            facts = []
            for point in results.points:
                facts.append({
                    "memory": point.payload.get("data", ""),
                    "metadata": point.payload.get("metadata", {}),
                    "score": point.score,
                })

            logger.info("hybrid_search.success", count=len(facts), query_preview=question[:50])
            return facts

        except Exception as e:
            logger.error("hybrid_search.error", error=str(e))
            # Fallback to Mem0 semantic search
            results = await asyncio.to_thread(
                self.memory.search, question, limit=limit
            )
            return results.get("results", [])
```

**Enabling the sparse index in Qdrant:**

The sparse BM25 vectors need a sparse index in the existing Qdrant collection. Add this to `scripts/bootstrap_wiki.sh`:

```bash
# scripts/bootstrap_qdrant_sparse.py
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVectorParams, SparseIndexParams

client = QdrantClient(host="localhost", port=6333)

# Add sparse vector configuration to the existing Mem0 collection
client.update_collection(
    collection_name="discord_memories",
    sparse_vectors_config={
        "bm25": SparseVectorParams(
            index=SparseIndexParams(on_disk=False)
        )
    }
)
print("Sparse BM25 index created on 'discord_memories' collection.")
```

---

## 10. Slash Commands Reference

| Command                              | Description                                             | Parameters                                      | Who    |
| ------------------------------------ | ------------------------------------------------------- | ----------------------------------------------- | ------ |
| `/ask question:[text]`               | Query the knowledge base (with semantic cache)          | `question` (req), `channel` (opt), `user` (opt) | All    |
| `/whois member:[@user]`              | What the bot knows about a member                       | `member` (req)                                  | All    |
| `/summary period:[...]`              | Summary of recent activity                              | `period` (opt, default: week)                   | All    |
| `/memory view`                       | Your own memory entries (ephemeral)                     | —                                               | All    |
| `/memory forget memory_id:[id]`      | Delete a specific memory entry                          | `memory_id` (req)                               | All    |
| `/memory forgetall`                  | Delete all your memories                                | —                                               | All    |
| `/wiki status`                       | Wiki page counts and recent log                         | —                                               | All    |
| `/wiki search query:[text]`          | Search wiki by keyword                                  | `query` (req)                                   | All    |
| `/wiki lint`                         | Run wiki health check                                   | —                                               | Admins |
| `/cm status`                         | CM Agent behaviour status                               | —                                               | All    |
| `/cm enable behaviour:[...]`         | Enable a CM behaviour                                   | `behaviour` (req)                               | Admins |
| `/cm disable behaviour:[...]`        | Disable a CM behaviour                                  | `behaviour` (req)                               | Admins |
| `/cm set-digest-channel channel:[#]` | Where digests are posted                                | `channel` (req)                                 | Admins |
| `/cm digest period:[daily\|weekly]`  | Post digest immediately                                 | `period` (opt)                                  | Admins |
| `/cm add-rule rule:[text]`           | Add moderation rule                                     | `rule` (req)                                    | Admins |
| `/budget status`                     | _(new)_ Show API call counts and remaining daily budget | —                                               | Admins |
| `/cache stats`                       | _(new)_ Semantic cache hit rate and entry count         | —                                               | Admins |

---

## 11. Deployment Guide (VPS)

### 11.1 Prerequisites

- VPS: **2 GB RAM minimum** (4 GB recommended)
- Ubuntu 22.04 / 24.04 LTS
- Docker Engine + Docker Compose Plugin

### 11.2 Discord Developer Portal Setup

1. Create Application → Bot → Copy Token
2. Privileged Gateway Intents: enable **Message Content Intent** AND **Server Members Intent**
3. OAuth2 Scopes: `bot` + `applications.commands`
4. Bot Permissions: `Read Messages`, `Send Messages`, `Read Message History`, `Send Messages in Threads`

### 11.3 VPS Setup

```bash
git clone <your-repo> /opt/discord-llmwiki-bot
cd /opt/discord-llmwiki-bot

# For free tier:
cp .env.free-tier .env
nano .env   # Fill in DISCORD_TOKEN, DISCORD_GUILD_ID, GEMINI_API_KEY

mkdir -p data/qdrant data/sqlite data/cm_config data/cache
bash scripts/bootstrap_wiki.sh

docker compose up -d --build
docker compose logs -f bot

# After containers are up, bootstrap the sparse Qdrant index:
docker compose exec bot python scripts/bootstrap_qdrant_sparse.py
```

### 11.4 requirements.txt (v3)

```
# Discord
discord.py==2.4.0

# Memory
mem0ai[nlp]==0.1.101       # [nlp] enables BM25 hybrid search inside Mem0
qdrant-client==1.9.1

# Hybrid search (BM25 sparse vectors)
fastembed==0.3.6            # Local BM25 encoder — no API call needed

# LLM — Google Gemini
google-genai>=1.0.0

# Data validation
pydantic==2.8.2
pydantic-settings==2.3.0

# NLP
spacy==3.7.4

# Media ingestion
httpx==0.27.0
readability-lxml==0.8.1
Pillow==10.4.0

# Utilities
python-dotenv==1.0.1
aiofiles==24.1.0
PyYAML==6.0.2
python-frontmatter==1.1.0

# Logging
structlog==24.4.0
```

---

## 12. Maintenance, Linting & Retention

### 12.1 Automatic Processes

| Task                     | Frequency                      | Description                                              |
| ------------------------ | ------------------------------ | -------------------------------------------------------- |
| `IngestionWorker`        | Continuous (async, batched)    | Pre-filter → dedup → MediaEnrich → buffer 5 → mem0.add() |
| `wiki_writer_task`       | Every 10 min (or 20 messages)  | Flush wiki buffer → update md pages                      |
| `wiki_linter_task`       | Daily 03:00 UTC                | WikiLinter → lint report in log.md                       |
| `memory_retention_task`  | Weekly                         | Delete Mem0 facts older than `MEMORY_RETENTION_DAYS`     |
| `semantic_cache_cleanup` | Hourly                         | Evict expired TTL entries from SemanticCache             |
| `cm_digest_task`         | Daily or weekly (configurable) | Post digest to configured channel                        |
| `cm_recognition_task`    | Weekly                         | Post member recognition                                  |
| `budget_daily_reset`     | Daily midnight Pacific         | Reset RPD counters in BudgetController                   |

### 12.2 Free-Tier Budget Monitoring

The `/budget status` admin command shows real-time usage vs limits. If you're consistently hitting 80%+ of daily budget on a small server, increase `INGEST_BATCH_SIZE` from 5 to 8 or 10, which proportionally reduces LLM extraction calls.

---

## 13. Extension Roadmap

### Phase 2 — `gemini-embedding-2` Migration + True Multimodal Search

**When:** After moving to paid Tier 1 and after `gemini-embedding-2` reaches GA (currently preview).

**What:** Switch `EMBEDDING_MODEL=gemini-embedding-2` and run the migration script to re-embed all existing Qdrant documents. Enable native image embedding — instead of captioning images to text, embed the image bytes directly using the multimodal embedder. This enables cross-modal search: text queries can retrieve relevant images, and image queries can retrieve related text memories.

**Migration script:** Re-embed all Qdrant points using `gemini-embedding-2`. Note that `gemini-embedding-2` uses the instruction-prefix format (`title: {t} | text: {c}`) instead of `task_type` — update `config.py` and the `HybridSearch` embedding calls.

### Phase 3 — Cross-Encoder Reranking

Upgrade the `/ask` pipeline from two-stage (hybrid search → LLM answer) to three-stage (hybrid search → reranker → LLM answer). Add a local cross-encoder reranker (`ms-marco-MiniLM-L-6-v2` from Sentence Transformers) as a second pass over the top 20 hybrid search results, reducing to the top 5 best before LLM context assembly. This improves `/ask` answer quality with no API cost — the cross-encoder runs locally.

```python
# Phase 3 addition to HybridSearch
from sentence_transformers import CrossEncoder
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

# After hybrid search returns top 20:
pairs = [[question, fact["memory"]] for fact in facts]
scores = reranker.predict(pairs)
reranked = sorted(zip(scores, facts), reverse=True)
top_5 = [fact for _, fact in reranked[:5]]
```

### Phase 4 — Graph Memory (Mem0g)

The Mem0 paper introduces `Mem0g`, an enhanced variant that adds a knowledge graph layer on top of standard Mem0. Graph memory models relationships between entities (people, projects, decisions) rather than just storing individual facts. For a community manager bot, this enables queries like "what projects is Alice involved in?" or "what decisions were made about the API redesign?" — multi-hop questions that plain vector search cannot handle.

This is opt-in: install `mem0ai[graph]`, add a graph database (Neo4j or Memgraph as a Docker service), and update the Mem0 config. The Mem0g variant achieved ~2% higher benchmark scores over base Mem0 in the research paper.

### Phase 5 — Thread & Forum Channel Support

Extend `ListenerCog` to handle `discord.Thread` events (forum posts, message threads). When a thread is archived, trigger a `WikiWriter` update that creates a dedicated thread summary page. The CM context injector would also work within threads.

### Phase 6 — Semantic Cache Redis Backend

For multi-instance deployments or very active servers, swap the in-memory `SemanticResponseCache` backend for Redis. Redis vector search (via `redis-py`) supports sub-millisecond cosine similarity search over cached embeddings. This enables cache sharing across bot restart and across multiple bot shards.

### Phase 7 — Proactive Knowledge Gap Questions

After each wiki lint, have the LLM identify "questions worth asking the community" based on detected knowledge gaps — and post them as a weekly prompt to a designated channel: "💡 Open questions from your server history: [list]". Makes the community manager feel genuinely engaged rather than purely reactive.

---

## Appendix A: Free-Tier vs Paid-Tier Quick Reference

| Config             | Free Tier                    | Paid Tier 1                                   |
| ------------------ | ---------------------------- | --------------------------------------------- |
| LLM model          | `gemini-2.5-flash-lite`      | `gemini-3.1-flash-lite-preview`               |
| Embed model        | `gemini-embedding-001`       | `gemini-embedding-001` (Phase 2: embedding-2) |
| LLM RPM limit      | 15 (we use 12)               | 150–300                                       |
| LLM RPD limit      | 1,000 (we use 800)           | Unlimited                                     |
| Embed RPM limit    | 100 (we use 80)              | 1,000+                                        |
| Ingest batch size  | 5                            | 3                                             |
| Rate limit/channel | 20 msgs/10 min               | 200 msgs/10 min                               |
| Est. cost          | $0/month                     | ~$2–5/month (500 msg/day server)              |
| Data privacy       | Prompts used to train Google | Prompts NOT used for training                 |
| Max server size    | ~200 msgs/day                | Unlimited                                     |

## Appendix B: API Call Budget Breakdown (Free Tier, 200 msg/day server)

| Step                     | Raw messages              | After pre-filter (35%) | After dedup (5%) | After batching (÷5) | Daily API calls                 |
| ------------------------ | ------------------------- | ---------------------- | ---------------- | ------------------- | ------------------------------- |
| Mem0 extraction (LLM)    | 200                       | 70                     | 67               | 14                  | **14 LLM calls**                |
| Image captioning (LLM)   | ~10% of 200 = 20          | All pass               | 18               | n/a                 | **18 LLM calls**                |
| Wiki writing (LLM)       | Every 20 msgs = 3 batches | —                      | —                | —                   | **3 LLM calls**                 |
| CM behaviour (LLM)       | 200                       | 70                     | —                | ~3% fire rate       | **2 LLM calls**                 |
| `/ask` queries (LLM)     | User-triggered            | —                      | —                | —                   | **10 LLM calls**                |
| `/ask` cache hits        | —                         | —                      | —                | ~30% hit rate       | -3 LLM saved                    |
| **Total LLM calls**      |                           |                        |                  |                     | **~44/day** vs budget of 800 ✅ |
| Embedding (ingestion)    | 200 → 14 batches          | —                      | —                | —                   | **14 embed calls**              |
| Embedding (search/cache) | —                         | —                      | —                | —                   | **13 embed calls**              |
| **Total embed calls**    |                           |                        |                  |                     | **~27/day** vs budget of 800 ✅ |

---

_End of Implementation Plan v3_

**Model decision summary:**

- `gemini-2.5-flash-lite` (stable GA) for all LLM tasks on free tier
- `gemini-3.1-flash-lite-preview` for all LLM tasks on paid tier
- `gemini-embedding-001` (stable GA) for embeddings in Phase 1
- `gemini-embedding-2` (preview, multimodal) for Phase 2 cross-modal search
- `fastembed` BM25 (local, free) for sparse hybrid search vectors
- `cross-encoder/ms-marco-MiniLM-L-6-v2` (local, free) for Phase 3 reranking
