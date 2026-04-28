# Discord LLMWiki Community Manager Bot — Complete Implementation Plan v2

> **What changed in v2:** (1) All LLM references updated to `gemini-3.1-flash-lite-preview`; (2) Embedding model updated to `gemini-embedding-2` (multimodal — required for image/media ingestion); (3) Proper asymmetric embedding prompt format added per Gemini Embedding 2 docs; (4) New **Section 4.7 – Community Manager Agent** (the main new architectural component); (5) New **Section 4.8 – Rich Media Ingestion Pipeline** (images, YouTube, GitHub, Twitter/X, Medium/blog articles); (6) All `openai` SDK references replaced with `google-genai`.

---

## Table of Contents

1. [Vision & Design Philosophy](#1-vision--design-philosophy)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Full Directory Structure](#3-full-directory-structure)
4. [Component Deep-Dives](#4-component-deep-dives)
   - 4.1 Discord Bot (discord.py v2)
   - 4.2 Memory Layer (Mem0 OSS + Qdrant)
   - 4.3 Wiki Layer (LLMWiki-inspired Markdown)
   - 4.4 Ingestion Pipeline
   - 4.5 Query Engine (Slash Commands)
   - 4.6 Knowledge Accumulator & Linter
   - 4.7 **Community Manager Agent** _(new)_
   - 4.8 **Rich Media Ingestion Pipeline** _(new)_
5. [Embedding Model Decision](#5-embedding-model-decision)
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

This means the Community Manager Agent is **not just a knowledgebase wrapper** — it is a set of **proactive, event-driven behaviours** layered on top of the existing memory + wiki architecture. These behaviours make the bot feel present and useful even when nobody invokes it by name.

### 1.3 The Solution: LLMWiki + Mem0 + Community Manager Agent

This bot is built around three complementary layers:

**Mem0 OSS (operational memory layer):**

- Extracts structured facts from every conversation turn (including captions for images and enriched content from URLs)
- Deduplicates and conflict-resolves automatically
- Persists facts per-user and per-channel in Qdrant (vector DB)
- Supports fast semantic search at query time (sub-100ms)
- Acts as the "hot" working memory — granular, searchable facts

**LLMWiki (the compiled knowledge base):**

- A directory of Markdown files maintained by the LLM
- Organized into `entities/`, `topics/`, `channels/`, `timeline/`, `synthesis/`, and `resources/` (new: tracks shared links and media)
- Acts as the "cold" long-term knowledge — synthesised, cross-referenced, interlinked

**Community Manager Agent (the proactive layer):**

- Monitors message events and runs a rule-and-intent engine on each
- Fires autonomous behaviours: welcoming, FAQ answering, context injection, duplicate detection, digests
- All behaviours are backed by the memory + wiki layers (it _knows_ what it knows before it speaks)
- Is configurable per-server: each behaviour can be enabled/disabled via `/cm config`

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Discord Server                             │
│  #general  #dev  #announcements  #random  ...text channels...      │
│  [Images]  [YouTube links]  [GitHub links]  [Article links]        │
└────────────────────┬────────────────────────────────────────────────┘
                     │  on_message / on_member_join events (discord.py v2)
                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         Discord Bot Service                              │
│                                                                          │
│  ┌────────────────┐  ┌─────────────────────┐  ┌──────────────────────┐  │
│  │  Event         │  │  Ingestion           │  │  Query Engine        │  │
│  │  Listener      │─▶│  Pipeline            │  │  (Slash Commands)    │  │
│  │  (discord.py)  │  │  + Media Enrichment  │  │                      │  │
│  └────────────────┘  └──────────┬───────────┘  └──────────┬──────────┘  │
│          │                      │                          │             │
│          │  also feeds          │                          │             │
│          ▼                      │                          │             │
│  ┌───────────────────────────┐  │                          │             │
│  │  Community Manager Agent  │  │                          │             │
│  │                           │  │                          │             │
│  │  • Onboarding flow        │  │                          │             │
│  │  • FAQ auto-responder     │  │                          │             │
│  │  • Context injection      │  │                          │             │
│  │  • Duplicate detector     │  │                          │             │
│  │  • Digest scheduler       │  │                          │             │
│  │  • Member recognition     │  │                          │             │
│  │  • Moderation assist      │  │                          │             │
│  └───────────────────────────┘  │                          │             │
└─────────────────────────────────┼──────────────────────────┼────────────┘
                                  │                          │
              ┌───────────────────┘               ┌──────────┘
              ▼                                   ▼
┌──────────────────────────┐    ┌──────────────────────────────────────┐
│   Mem0 OSS Layer         │    │          LLMWiki Layer               │
│                          │    │                                      │
│  mem0.add(messages,      │    │  wiki/                               │
│    user_id, agent_id)    │◀──▶│    entities/  (people, projects)     │
│  mem0.search(query, ...) │    │    topics/    (recurring themes)     │
│                          │    │    channels/  (per-channel summary)  │
│  Facts extracted:        │    │    timeline/  (chronological)        │
│  "Alex loves Python"     │    │    synthesis/ (cross-cutting)        │
│  "Project Y deadline     │    │    resources/ (links + media) ← NEW  │
│   is March 15"           │    │    index.md                          │
│  "Image: screenshot of   │    │    log.md                            │
│   API error in #dev"     │    │    WIKI.md    (schema/conventions)   │
└────────────┬─────────────┘    └──────────────────────────────────────┘
             │                                       ▲
             │ store/retrieve                        │ LLM writes
             ▼                                       │ markdown files
┌──────────────────────────┐    ┌──────────────────────────────────────┐
│   Qdrant (vector store)  │    │   Wiki Writer Service                │
│   SQLite (history)       │    │   (async, periodic)                  │
│   /qdrant_data           │    │   - Ingest messages → pages          │
│                          │    │   - Ingest media → resources/ pages  │
└──────────────────────────┘    │   - Update entity/topic pages        │
                                │   - Maintain index.md + log.md       │
                                │   - Run linter (daily)               │
                                └──────────────────────────────────────┘
                                               │
                               ┌───────────────┘
                               ▼
              ┌────────────────────────────────────────────┐
              │               LLM API                      │
              │   Google Gemini (google-genai SDK)          │
              │                                            │
              │   LLM:    gemini-3.1-flash-lite-preview    │
              │   Embed:  gemini-embedding-2 (multimodal)  │
              │                                            │
              │   Tasks:                                   │
              │   - Fact extraction (Mem0)                 │
              │   - Wiki writing (WikiWriter)              │
              │   - Query answering (/ask)                 │
              │   - Image captioning (MediaIngestion)      │
              │   - Community manager decisions            │
              └────────────────────────────────────────────┘
```

**Data flow summary:**

1. Message arrives → `EventListener` → `IngestionQueue` (async, non-blocking)
2. `MediaEnricher` fires if message has images/URLs → enriches with captions/scraped content
3. `IngestionWorker` pops from queue → calls `mem0.add()` → Qdrant stores vector + SQLite stores history
4. `CommunityManagerAgent` evaluates the message → may fire a proactive action (welcome, FAQ reply, context injection, etc.)
5. Every N messages or T minutes, `WikiWriter` wakes up → reads buffered messages → calls LLM → updates wiki markdown files
6. User types `/ask [question]` → `QueryEngine` → searches Mem0 + reads relevant wiki pages → assembles prompt → returns grounded answer

---

## 3. Full Directory Structure

```
discord-llmwiki-bot/
│
├── docker-compose.yml
├── .env
├── .env.example
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
│   │   ├── __init__.py
│   │   ├── listener.py             # on_message, on_member_join, on_message_edit
│   │   ├── query_commands.py       # /ask, /summary, /whois
│   │   ├── wiki_commands.py        # /wiki search, /wiki lint, /wiki status
│   │   ├── memory_commands.py      # /memory view, /memory forget
│   │   └── cm_commands.py          # /cm config, /cm digest, /cm status  ← NEW
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── client.py               # Mem0 Memory() singleton with Gemini config
│   │   ├── ingestion.py            # IngestionQueue + IngestionWorker
│   │   └── schemas.py              # Pydantic models for messages, facts
│   │
│   ├── wiki/
│   │   ├── __init__.py
│   │   ├── writer.py               # WikiWriter
│   │   ├── reader.py               # WikiReader
│   │   ├── linter.py               # WikiLinter
│   │   └── schemas.py
│   │
│   ├── media/                                              ← NEW
│   │   ├── __init__.py
│   │   ├── enricher.py             # MediaEnricher: images, URLs, videos
│   │   ├── extractors/
│   │   │   ├── __init__.py
│   │   │   ├── image.py            # Image captioning via Gemini multimodal
│   │   │   ├── youtube.py          # YouTube metadata via oEmbed / yt-dlp
│   │   │   ├── github.py           # GitHub API: repo/PR/issue descriptions
│   │   │   ├── article.py          # Generic article scraper (Medium, blogs)
│   │   │   └── twitter.py          # Twitter/X oEmbed or scraper
│   │   └── schemas.py              # EnrichedMedia pydantic models
│   │
│   ├── community_manager/                                  ← NEW
│   │   ├── __init__.py
│   │   ├── agent.py                # CommunityManagerAgent: orchestrator
│   │   ├── behaviours/
│   │   │   ├── __init__.py
│   │   │   ├── onboarding.py       # Welcome DM + server guide
│   │   │   ├── faq_responder.py    # Proactive FAQ answering
│   │   │   ├── context_injector.py # Proactive context when topic re-emerges
│   │   │   ├── duplicate_detector.py # Cross-channel duplicate discussion alert
│   │   │   ├── digest.py           # Scheduled daily/weekly digest
│   │   │   ├── recognition.py      # Member contribution recognition
│   │   │   └── moderation_assist.py # Flag rule violations → notify mods
│   │   ├── config_store.py         # Per-guild CM configuration (JSON on disk)
│   │   └── schemas.py              # CMConfig, CMEvent pydantic models
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py               # Gemini client (google-genai SDK)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── formatting.py
│       ├── rate_limiter.py
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
│   └── resources/                                          ← NEW
│       └── .gitkeep
│
├── data/
│   ├── qdrant/
│   ├── sqlite/
│   └── cm_config/                                          ← NEW (per-guild CM settings)
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

- `message_content` — to read message text (privileged, enable in Developer Portal)
- `guilds` — to enumerate channels
- `guild_messages` — to receive `on_message` in guild channels
- `members` — to resolve user display names AND to receive `on_member_join` (privileged)

**Key changes from v1:** The `setup_hook` now also initialises the `CommunityManagerAgent` and the `MediaEnricher`. The `on_member_join` event is wired to the CM Agent's onboarding behaviour.

**Message filtering rules** (in `listener.py`):

1. Skip messages from bots (including self): `if message.author.bot: return`
2. Only process messages in guild text channels (type `discord.TextChannel`)
3. Apply per-channel rate limiting
4. **No longer skip messages that are only a URL** — URLs are now enriched by `MediaEnricher`
5. **No longer skip messages with only attachments** — images/files are now processed by `MediaEnricher`
6. Skip only messages that are empty after stripping and have no attachments

### 4.2 Memory Layer (Mem0 OSS + Qdrant)

**Mem0 OSS configuration (updated to Gemini):**

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
                "model": config.extraction_model,   # gemini-3.1-flash-lite-preview
                "api_key": config.gemini_api_key,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "google",
            "config": {
                "model": config.embedding_model,    # gemini-embedding-2
                "api_key": config.gemini_api_key,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": config.qdrant_host,
                "port": config.qdrant_port,
                "collection_name": config.qdrant_collection,
                "embedding_model_dims": 768,  # gemini-embedding-2 at 768 dims (MRL)
            },
        },
        "history_db_path": config.sqlite_path,
    }
    return Memory.from_config(mem0_config)
```

**Memory scoping strategy:**

| Mem0 Field | Bot Usage                | Example                    |
| ---------- | ------------------------ | -------------------------- |
| `user_id`  | Discord User ID (string) | `"123456789"`              |
| `agent_id` | Channel ID (string)      | `"channel_987654321"`      |
| `run_id`   | Date + Channel           | `"2025-01-15_channel_987"` |

### 4.3 Wiki Layer (LLMWiki-inspired Markdown)

The wiki directory structure gains one new folder: `resources/`. This holds one page per significant external resource shared in the server — YouTube videos, GitHub repos, articles, etc.

**Updated WIKI.md** (additions only):

```markdown
## Directory Structure (updated)

- resources/ — One page per significant external resource shared in the server
  (YouTube videos, GitHub repos/PRs/issues, blog articles, tweets)

## Resource Page Naming

- resources/ → yt*{video_id}.md, gh*{owner}_{repo}.md, article_{slug}.md, tweet\_{id}.md

## Resource Page Format

---

title: "Video: How to implement RAG with LangChain"
type: resource
resource_type: youtube|github_repo|github_pr|article|tweet
url: https://...
shared_by: [discord_username1, discord_username2]
first_shared: YYYY-MM-DD
channels_shared: [channel_name1, channel_name2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
linked_pages: [topics/topic_rag.md, entities/person_alice.md]

---

# [Resource Title]

## Summary

[LLM-generated summary of the resource content]

## Why It Was Shared

[Context from the message(s) where it was shared]

## Reactions & Discussion

[Key points members made about it]
```

### 4.4 Ingestion Pipeline

The ingestion pipeline is extended with a **MediaEnricher** step that fires before `mem0.add()`. When a message contains an image attachment or a recognised URL pattern (YouTube, GitHub, Twitter, Medium, or generic article), the enricher fetches/generates a text description and injects it into the message content before fact extraction.

```
on_message (event loop thread)
    │
    ▼
MessageEvent (Pydantic model) — now includes raw_attachments + raw_urls
    │
    ▼
IngestionQueue (asyncio.Queue, max size 10,000)
    │
    ▼  (background asyncio task)
IngestionWorker
    │
    ├──▶ MediaEnricher.enrich(event)     ← NEW
    │    ├── Image attachment? → Gemini multimodal caption
    │    ├── YouTube URL? → oEmbed metadata + description
    │    ├── GitHub URL? → GitHub API description
    │    ├── Twitter URL? → oEmbed text
    │    └── Article URL? → httpx fetch + readability parse
    │    → Returns EnrichedMessageEvent (content augmented with descriptions)
    │
    ├──▶ mem0.add(enriched_content) → Qdrant
    │
    ├──▶ CommunityManagerAgent.evaluate(event)  ← NEW
    │    → May fire proactive Discord responses
    │
    └──▶ WikiBuffer.append(enriched_event)
              │
              ▼  (batch threshold)
         WikiWriter.process_batch()
              └──▶ Creates/updates resource pages for new links
```

### 4.5 Query Engine (Slash Commands)

Unchanged from v1. The only update is that `LLMClient` now uses the `google-genai` SDK (see Section 9.10).

### 4.6 Knowledge Accumulator & Linter

`WikiWriter.process_batch()` now has an additional step:

**Step 3b: Process shared resources.** For each enriched event that contains media:

- Check if a resource page for this URL already exists in `resources/`
- If not: create a new page using the enriched description + context from the message
- If yes: update the page with new "shared by" info and discussion context

---

### 4.7 Community Manager Agent _(new)_

This is the primary new architectural component that answers the question "how do we set up an agent who works like a community manager?"

#### Architecture Overview

The `CommunityManagerAgent` is instantiated once at bot startup and runs as a set of **event-driven + scheduled behaviours**. Each behaviour is an independent class with a single entry point: `async def should_fire(event) -> bool` and `async def fire(event, discord_channel)`.

The agent evaluates every `MessageEvent` and `MemberJoinEvent` through a lightweight intent-detection step (one cheap LLM call per message), then dispatches to the appropriate behaviour if the confidence is above a threshold.

```python
# bot/community_manager/agent.py

class CommunityManagerAgent:
    """
    Orchestrates all community manager behaviours.
    Evaluates each Discord event and fires the appropriate response.
    """

    def __init__(self, bot, memory_client, wiki_reader, llm_client, cm_config):
        self.bot = bot
        self.behaviours: list[BaseBehaviour] = [
            FAQResponder(memory_client, wiki_reader, llm_client, cm_config),
            ContextInjector(memory_client, wiki_reader, llm_client, cm_config),
            DuplicateDetector(memory_client, wiki_reader, llm_client, cm_config),
            ModerationAssist(llm_client, cm_config),
        ]
        self.onboarding = OnboardingFlow(llm_client, cm_config)
        self.digest = DigestScheduler(memory_client, wiki_reader, llm_client, cm_config)
        self.recognition = MemberRecognition(memory_client, llm_client, cm_config)

    async def on_message(self, event: MessageEvent, channel) -> None:
        """Evaluate a message event through all CM behaviours."""
        if not self.cm_config.enabled:
            return

        for behaviour in self.behaviours:
            if not behaviour.is_enabled:
                continue
            try:
                if await behaviour.should_fire(event):
                    await behaviour.fire(event, channel)
                    break  # Only one behaviour fires per message (priority order)
            except Exception as e:
                logger.error("CM behaviour error", behaviour=type(behaviour).__name__, error=str(e))

    async def on_member_join(self, member: discord.Member) -> None:
        """Handle a new member joining the server."""
        if self.cm_config.onboarding_enabled:
            await self.onboarding.welcome(member)
```

#### Behaviour 1: Onboarding Flow

**Trigger:** `on_member_join` event

**What it does:**

1. Sends a DM to the new member with a personalised welcome message based on the server's WIKI.md and channel list
2. Lists the top 3–5 most active channels and their purpose (read from the wiki's `channels/` pages)
3. Highlights any pinned "start here" resources from the wiki's `resources/` directory
4. Sends a follow-up DM after 24 hours if the member hasn't spoken yet: "Hey, we noticed you haven't introduced yourself yet — feel free to say hi in #general!"

```python
# bot/community_manager/behaviours/onboarding.py

class OnboardingFlow:
    async def welcome(self, member: discord.Member) -> None:
        # Load wiki channel summaries
        channel_summaries = await self._get_channel_summaries()

        # Generate personalised welcome via LLM
        welcome_message = await self.llm.complete(f"""
You are a friendly community manager for a Discord server.
Write a warm, concise welcome DM for a new member named {member.display_name}.

Server's active channels and their purpose:
{channel_summaries}

The message should:
- Be warm but not over-the-top
- Mention 2-3 most relevant channels to start in
- Tell them they can ask questions anytime
- Be under 200 words
""", model=self.config.cm_model)

        try:
            await member.send(welcome_message)
        except discord.Forbidden:
            # Member has DMs disabled — post in welcome channel instead
            if self.config.welcome_channel_id:
                channel = member.guild.get_channel(self.config.welcome_channel_id)
                if channel:
                    await channel.send(
                        f"👋 Welcome to the server, {member.mention}! "
                        f"Feel free to introduce yourself!"
                    )
```

#### Behaviour 2: FAQ Auto-Responder

**Trigger:** Message that looks like a common question the bot can answer from its knowledge base.

**What it does:**

1. Lightweight intent classifier: "Is this a question that can be answered from existing server knowledge?"
2. If yes AND confidence > threshold: search Mem0 + wiki for an answer
3. If a high-confidence answer is found: reply in-channel with the answer + source reference
4. If no good answer: stay silent (do not hallucinate)

**Important:** The bot only auto-responds to clear FAQ-style questions (e.g., "what time is the weekly meeting?", "where do I report a bug?"). It does NOT auto-respond to every message — that would be annoying. The classifier prompt is explicitly tuned to be conservative.

```python
# bot/community_manager/behaviours/faq_responder.py

class FAQResponder(BaseBehaviour):
    MIN_CONFIDENCE = 0.85  # Conservative threshold — stay silent if uncertain

    async def should_fire(self, event: MessageEvent) -> bool:
        if not event.content.endswith("?") and "?" not in event.content:
            return False  # Quick filter: must contain a question

        # Check if we've answered a similar question in the last hour
        # to avoid repeating ourselves
        if await self._recently_answered_similar(event.content):
            return False

        classification = await self.llm.complete(f"""
Classify this Discord message. Is it a FAQ-style question that a bot with access
to the server's conversation history could answer factually?

Message: "{event.content}"

Respond ONLY with JSON: {{"is_faq": true/false, "confidence": 0.0-1.0, "topic": "short topic"}}
Do NOT classify as FAQ if the question is: personal opinion, requires real-time data,
is addressed to a specific person, or is casual small talk.
""", model=self.config.extraction_model)

        result = json.loads(classification)
        return result.get("is_faq") and result.get("confidence", 0) >= self.MIN_CONFIDENCE

    async def fire(self, event: MessageEvent, channel) -> None:
        # Search memory and wiki for answer
        facts = await asyncio.to_thread(
            self.memory.search, event.content,
            agent_id=f"channel_{event.channel_id}", limit=8
        )
        wiki_pages = await self.wiki_reader.find_relevant_pages(event.content, max_pages=2)

        if not facts.get("results") and not wiki_pages:
            return  # Don't respond if we have nothing

        answer = await self.llm.answer_question(
            question=event.content,
            mem0_facts="\n".join(f"- {f['memory']}" for f in facts.get("results", [])[:6]),
            wiki_context="\n".join(p.body[:600] for p in wiki_pages),
            model=self.config.query_model,
        )

        # Only respond if the answer is substantive and grounded
        if len(answer) > 50 and "[no information" not in answer.lower():
            message = channel.get_partial_message(event.message_id)
            await channel.send(
                f"💡 {answer[:1800]}\n\n"
                f"*— Based on server history. Use `/ask` for more detailed queries.*",
                reference=message,
                mention_author=False,
            )
```

#### Behaviour 3: Proactive Context Injection

**Trigger:** A message that starts discussing a topic the server has significant prior history on, and this history is not likely to be known by the people currently in the conversation.

**What it does:**

1. Detects topic continuity: "Is this discussion re-treading ground covered in a previous conversation?"
2. If yes: sends a lightweight, non-intrusive note: "📚 Heads up — this was discussed in #dev 3 weeks ago. Here's a brief summary: [2–3 bullet points]. Full context: [wiki page link or /ask suggestion]"
3. Rate-limited: at most once per topic per 24 hours per channel

**This is one of the most valuable community manager behaviours** — it prevents communities from re-solving the same problems, helps new members get up to speed, and makes the server's institutional knowledge feel accessible.

```python
# bot/community_manager/behaviours/context_injector.py

class ContextInjector(BaseBehaviour):
    SIMILARITY_THRESHOLD = 0.82
    COOLDOWN_HOURS = 24  # Don't inject same topic in same channel within N hours
    MIN_PRIOR_FACTS = 3  # Only inject if we have at least N prior facts on the topic

    async def should_fire(self, event: MessageEvent) -> bool:
        # Only fire for messages with substance (>20 chars, no question mark = statement)
        if len(event.content) < 20:
            return False

        # Check cooldown for this channel/topic
        topic_key = await self._get_topic_key(event.content)
        if await self._is_on_cooldown(event.channel_id, topic_key):
            return False

        # Search for prior context
        results = await asyncio.to_thread(
            self.memory.search, event.content,
            agent_id=f"channel_{event.channel_id}", limit=5
        )
        prior_facts = results.get("results", [])

        if len(prior_facts) < self.MIN_PRIOR_FACTS:
            return False

        # Check if top result is sufficiently similar
        top_score = prior_facts[0].get("score", 0) if prior_facts else 0
        return top_score >= self.SIMILARITY_THRESHOLD

    async def fire(self, event: MessageEvent, channel) -> None:
        results = await asyncio.to_thread(
            self.memory.search, event.content,
            agent_id=f"channel_{event.channel_id}", limit=8
        )
        facts = results.get("results", [])

        # Find the earliest timestamp in facts to determine "when" this was discussed
        timestamps = [
            f.get("metadata", {}).get("timestamp", "") for f in facts
        ]
        earliest = min(t for t in timestamps if t) if timestamps else ""

        # Generate a brief summary
        facts_text = "\n".join(f"- {f['memory']}" for f in facts[:6])
        summary = await self.llm.complete(f"""
Summarise these facts about a topic discussed in a Discord server in 2-3 bullet points.
Be concise and direct. Do not include timestamps or attribution.

Facts:
{facts_text}

Output ONLY the 2-3 bullet points, nothing else.
""", model=self.config.cm_model)

        inject_msg = (
            f"📚 **This topic has come up before!**\n"
            f"{summary}\n\n"
            f"*Use `/ask {event.content[:60]}...` for the full history.*"
        )

        message_ref = channel.get_partial_message(event.message_id)
        await channel.send(inject_msg, reference=message_ref, mention_author=False)

        # Set cooldown
        await self._set_cooldown(event.channel_id, await self._get_topic_key(event.content))
```

#### Behaviour 4: Cross-Channel Duplicate Detector

**Trigger:** A message that appears to be discussing a topic already actively being discussed in another channel in the same server right now (within the last 2 hours).

**What it does:**

1. Embeds the new message and searches across ALL channels' recent Mem0 facts
2. If a very similar discussion is found in a different channel: gently notes it
3. Example output: "👋 Looks like #dev is also discussing this right now — you might want to check there or loop them in!"

This is configurable and can be turned off for servers where parallel discussions are fine.

```python
# bot/community_manager/behaviours/duplicate_detector.py

class DuplicateDetector(BaseBehaviour):
    DUPLICATE_THRESHOLD = 0.90  # High threshold — only flag very obvious duplicates
    RECENT_HOURS = 2

    async def should_fire(self, event: MessageEvent) -> bool:
        if len(event.content) < 30:
            return False

        # Search across ALL channels (no agent_id filter) for recent similar content
        results = await asyncio.to_thread(
            self.memory.search, event.content, limit=5
        )

        for fact in results.get("results", []):
            score = fact.get("score", 0)
            fact_channel = fact.get("metadata", {}).get("channel_name", "")
            fact_time = fact.get("metadata", {}).get("timestamp", "")

            if score >= self.DUPLICATE_THRESHOLD and fact_channel != event.channel_name:
                # Check if the other discussion is recent
                if fact_time and self._is_recent(fact_time, hours=self.RECENT_HOURS):
                    self._pending_other_channel = fact_channel
                    return True

        return False

    async def fire(self, event: MessageEvent, channel) -> None:
        other_channel = getattr(self, "_pending_other_channel", None)
        if not other_channel:
            return

        message_ref = channel.get_partial_message(event.message_id)
        await channel.send(
            f"👋 FYI — **#{other_channel}** has been discussing something very similar "
            f"in the last couple of hours. Might be worth looping them in or moving the "
            f"conversation there!",
            reference=message_ref,
            mention_author=False,
        )
```

#### Behaviour 5: Digest Scheduler

**Trigger:** Scheduled task (configurable: daily, weekly, or both). Posts to a designated digest channel.

**What it does:** Generates a rich digest of server activity over the past period, including: most active channels, key topics discussed, new resources shared (with summaries), notable decisions made, and new members who joined. All content is sourced from Mem0 + wiki.

```python
# bot/community_manager/behaviours/digest.py

class DigestScheduler:
    async def post_digest(self, guild: discord.Guild, period: str = "daily") -> None:
        """Generate and post a digest to the configured digest channel."""

        channel_id = self.config.digest_channel_id
        if not channel_id:
            return

        digest_channel = guild.get_channel(channel_id)
        if not digest_channel:
            return

        # Gather data for the digest period
        period_hours = 24 if period == "daily" else 168  # 7 days

        # Get recent wiki timeline page
        week_str = datetime.now().strftime("%Y_W%W")
        timeline_page = await self.wiki_reader.load_page(f"timeline/week_{week_str}.md")

        # Get recent resources from wiki
        recent_resources = await self._get_recent_resources(period_hours)

        # Generate digest via LLM
        digest_content = await self.llm.complete(f"""
Write a {period} digest post for a Discord server community manager bot.
Format it for Discord (use markdown, emojis, keep it scannable).

Timeline / recent activity:
{timeline_page.body[:2000] if timeline_page else "No timeline page yet."}

Recently shared resources:
{recent_resources[:1000]}

The digest should include:
1. 🔥 Top topics discussed today
2. 🔗 Notable resources shared (with 1-line descriptions)
3. 💡 Any decisions or conclusions reached
4. 👋 New members who joined (if any)

Keep it under 1500 characters total. Be concise and friendly.
""", model=self.config.cm_model)

        embed = discord.Embed(
            title=f"📋 {'Daily' if period == 'daily' else 'Weekly'} Digest",
            description=digest_content,
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )
        await digest_channel.send(embed=embed)
```

#### Behaviour 6: Member Recognition

**Trigger:** Scheduled weekly task. Tracks contribution metrics and posts a recognition message.

**What it does:** Counts message volume, resource shares, questions answered (via Mem0 metadata), and generates a weekly "shoutout" post. Configurable: can be turned off or restricted to specific channels.

```python
# bot/community_manager/behaviours/recognition.py

class MemberRecognition:
    async def post_weekly_recognition(self, guild: discord.Guild) -> None:
        channel_id = self.config.recognition_channel_id
        if not channel_id:
            return

        # Get all members who contributed this week
        # Query Mem0 for message counts by user_id in the last 7 days
        top_contributors = await self._get_top_contributors(days=7, top_n=3)

        if not top_contributors:
            return

        # Resolve Discord display names
        members_text = []
        for user_id, count in top_contributors:
            member = guild.get_member(int(user_id))
            if member:
                members_text.append(f"{member.mention} ({count} contributions)")

        if not members_text:
            return

        channel = guild.get_channel(channel_id)
        await channel.send(
            f"🌟 **This week's top contributors:**\n" +
            "\n".join(f"• {m}" for m in members_text) +
            "\n\nThank you for keeping the conversation going! 🙌"
        )
```

#### Behaviour 7: Moderation Assist

**Trigger:** Any message. Runs a quick content classification check.

**What it does:** Checks messages against a configurable rule set (stored in `cm_config/guild_id.json`). If a rule violation is detected above a confidence threshold: DMs the configured moderator role with a report (message content, author, channel, confidence, rule matched). Does **not** delete messages, mute users, or take any punitive action autonomously — escalation to humans only.

```python
# bot/community_manager/behaviours/moderation_assist.py

class ModerationAssist(BaseBehaviour):
    async def should_fire(self, event: MessageEvent) -> bool:
        if not self.config.moderation_enabled or not self.config.mod_rules:
            return False

        if len(event.content) < 5:
            return False

        classification = await self.llm.complete(f"""
Check this Discord message against these community rules and determine if any are violated.

Rules:
{chr(10).join(f"{i+1}. {rule}" for i, rule in enumerate(self.config.mod_rules))}

Message: "{event.content}"

Respond ONLY with JSON:
{{"violation": true/false, "confidence": 0.0-1.0, "rule_number": null_or_int, "reason": "brief reason"}}

Be conservative. Only flag clear violations, not ambiguous cases.
""", model=self.config.extraction_model)

        result = json.loads(classification)
        return result.get("violation") and result.get("confidence", 0) >= 0.85

    async def fire(self, event: MessageEvent, channel) -> None:
        if not self.config.mod_alert_channel_id:
            return

        alert_channel = channel.guild.get_channel(self.config.mod_alert_channel_id)
        if not alert_channel:
            return

        embed = discord.Embed(
            title="⚠️ Moderation Alert",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Channel", value=f"<#{event.channel_id}>", inline=True)
        embed.add_field(name="Author", value=f"<@{event.author_id}>", inline=True)
        embed.add_field(name="Message", value=event.content[:500], inline=False)
        embed.set_footer(text="No action taken — human review required.")

        await alert_channel.send(
            f"<@&{self.config.mod_role_id}>" if self.config.mod_role_id else "",
            embed=embed
        )
```

#### CM Configuration (`/cm config`)

All CM behaviours are configurable per-guild via the `/cm config` admin command. The config is stored as JSON in `data/cm_config/{guild_id}.json`.

```json
{
  "enabled": true,
  "cm_model": "gemini-3.1-flash-lite-preview",
  "onboarding_enabled": true,
  "welcome_channel_id": 123456789,
  "faq_responder_enabled": true,
  "faq_confidence_threshold": 0.85,
  "context_injector_enabled": true,
  "context_injector_cooldown_hours": 24,
  "duplicate_detector_enabled": true,
  "digest_enabled": true,
  "digest_channel_id": 987654321,
  "digest_schedule": "daily",
  "digest_time_utc": "09:00",
  "recognition_enabled": true,
  "recognition_channel_id": 987654321,
  "moderation_enabled": false,
  "mod_rules": [],
  "mod_alert_channel_id": null,
  "mod_role_id": null
}
```

---

### 4.8 Rich Media Ingestion Pipeline _(new)_

Since we are targeting text channels only (no voice channels in v1), the rich media pipeline covers:

- **Image attachments** in messages
- **YouTube video links**
- **GitHub repo, PR, and issue links**
- **Twitter/X post links**
- **Medium and generic blog article links**

All of these are converted to **text descriptions** before being passed to `mem0.add()` and the wiki writer. This means the knowledge base can answer questions like "What was the image of the API error that Alice shared in #dev last week?" or "What was the YouTube tutorial Bob linked about Qdrant?"

#### MediaEnricher

```python
# bot/media/enricher.py
import re
from dataclasses import dataclass, field
from typing import Optional

from media.extractors.image import ImageExtractor
from media.extractors.youtube import YouTubeExtractor
from media.extractors.github import GitHubExtractor
from media.extractors.article import ArticleExtractor
from memory.schemas import MessageEvent

URL_PATTERNS = {
    "youtube": re.compile(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
    ),
    "github": re.compile(
        r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/(?:pull|issues)/\d+)?)"
    ),
    "twitter": re.compile(
        r"https?://(?:twitter|x)\.com/\w+/status/(\d+)"
    ),
    "article": re.compile(
        r"https?://(?:medium\.com|dev\.to|substack\.com|hashnode\.com|[\w.-]+/blog)/\S+"
    ),
}

@dataclass
class EnrichedContent:
    original_content: str
    enriched_content: str               # Augmented with media descriptions
    media_items: list[dict] = field(default_factory=list)
    # Each item: {"type": "image"|"youtube"|"github"|..., "url": "...", "description": "..."}


class MediaEnricher:
    def __init__(self, llm_client, gemini_api_key: str):
        self.image_extractor = ImageExtractor(gemini_api_key)
        self.youtube_extractor = YouTubeExtractor()
        self.github_extractor = GitHubExtractor()
        self.article_extractor = ArticleExtractor()

    async def enrich(self, event: MessageEvent, discord_message) -> EnrichedContent:
        """Enrich a message with descriptions of its media content."""
        enriched_parts = [event.content]
        media_items = []

        # 1. Process image attachments
        for attachment in discord_message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                desc = await self.image_extractor.describe(attachment.url)
                if desc:
                    enriched_parts.append(f"[Shared image: {desc}]")
                    media_items.append({
                        "type": "image",
                        "url": attachment.url,
                        "description": desc,
                    })

        # 2. Process URLs in the message
        urls_found = set()
        for url_type, pattern in URL_PATTERNS.items():
            for match in pattern.finditer(event.content):
                url = match.group(0)
                if url in urls_found:
                    continue
                urls_found.add(url)

                desc = await self._extract_url_content(url_type, url, match)
                if desc:
                    enriched_parts.append(f"[Shared {url_type}: {desc}]")
                    media_items.append({
                        "type": url_type,
                        "url": url,
                        "description": desc,
                    })

        return EnrichedContent(
            original_content=event.content,
            enriched_content="\n".join(enriched_parts),
            media_items=media_items,
        )

    async def _extract_url_content(self, url_type: str, url: str, match) -> Optional[str]:
        extractors = {
            "youtube": self.youtube_extractor,
            "github": self.github_extractor,
            "article": self.article_extractor,
        }
        extractor = extractors.get(url_type)
        if extractor:
            return await extractor.extract(url)
        return None
```

#### Image Extractor (Gemini Multimodal)

This is where `gemini-embedding-2`'s multimodal capability becomes directly useful. We use `gemini-3.1-flash-lite-preview` (the LLM, not the embedder) to generate a text description of the image. The description is then stored in Mem0 as text — so the embedding for retrieval is a text embedding of the description. For advanced use (Phase 2), we can embed the image directly with `gemini-embedding-2` for true cross-modal search.

```python
# bot/media/extractors/image.py
import httpx
import base64
from google import genai
from google.genai import types

class ImageExtractor:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    async def describe(self, image_url: str) -> Optional[str]:
        """Download image and generate a text description using Gemini multimodal."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                image_bytes = resp.content
                content_type = resp.headers.get("content-type", "image/jpeg")

            # Use Gemini to describe the image
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model="gemini-3.1-flash-lite-preview",
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=content_type),
                    types.Part.from_text(
                        "Describe this image concisely in 1-3 sentences. "
                        "Focus on: what is shown, any text visible, and context "
                        "that would be relevant if someone shared this in a tech Discord server."
                    ),
                ]
            )
            return response.text.strip()
        except Exception as e:
            logger.warning("Image description failed", url=image_url, error=str(e))
            return None
```

#### YouTube Extractor

```python
# bot/media/extractors/youtube.py
import httpx

class YouTubeExtractor:
    OEMBED_URL = "https://www.youtube.com/oembed"

    async def extract(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    self.OEMBED_URL,
                    params={"url": url, "format": "json"}
                )
                resp.raise_for_status()
                data = resp.json()

            title = data.get("title", "")
            author = data.get("author_name", "")
            return f'YouTube video: "{title}" by {author}' if title else None
        except Exception:
            return None
```

#### GitHub Extractor

```python
# bot/media/extractors/github.py
import httpx
import re

class GitHubExtractor:
    API_BASE = "https://api.github.com"

    async def extract(self, url: str) -> Optional[str]:
        try:
            # Parse owner/repo[/pull|issues/number]
            match = re.search(
                r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
                r"(?:/(pull|issues)/(\d+))?", url
            )
            if not match:
                return None

            owner, repo = match.group(1), match.group(2)
            resource_type = match.group(3)  # "pull", "issues", or None
            number = match.group(4)

            async with httpx.AsyncClient(
                timeout=10,
                headers={"Accept": "application/vnd.github+json"}
            ) as client:
                if resource_type == "pull":
                    resp = await client.get(
                        f"{self.API_BASE}/repos/{owner}/{repo}/pulls/{number}"
                    )
                    data = resp.json()
                    return f'GitHub PR #{number} in {owner}/{repo}: "{data.get("title", "")}" — {data.get("body", "")[:200]}'

                elif resource_type == "issues":
                    resp = await client.get(
                        f"{self.API_BASE}/repos/{owner}/{repo}/issues/{number}"
                    )
                    data = resp.json()
                    return f'GitHub issue #{number} in {owner}/{repo}: "{data.get("title", "")}" — {data.get("body", "")[:200]}'

                else:
                    resp = await client.get(
                        f"{self.API_BASE}/repos/{owner}/{repo}"
                    )
                    data = resp.json()
                    desc = data.get("description", "no description")
                    stars = data.get("stargazers_count", 0)
                    lang = data.get("language", "")
                    return f'GitHub repo {owner}/{repo}: {desc} [{lang}, {stars} stars]'
        except Exception:
            return None
```

#### Article Extractor (Medium, Dev.to, Substack, generic blogs)

```python
# bot/media/extractors/article.py
import httpx
from readability import Document  # pip install readability-lxml

class ArticleExtractor:
    MAX_CONTENT_LENGTH = 800  # Characters of article body to store

    async def extract(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

            doc = Document(html)
            title = doc.title()
            # Strip HTML tags from summary
            import re
            content = re.sub(r"<[^>]+>", "", doc.summary())[:self.MAX_CONTENT_LENGTH]

            return f'Article: "{title}" — {content}...' if title else None
        except Exception:
            return None
```

---

## 5. Embedding Model Decision

### Why `gemini-embedding-2` over `gemini-embedding-001`

For this use case, `gemini-embedding-2` is the correct choice:

| Factor                 | `gemini-embedding-001`     | `gemini-embedding-2`                 |
| ---------------------- | -------------------------- | ------------------------------------ |
| **Modality**           | Text only                  | Text, images, audio, video, PDFs     |
| **Images**             | ❌ Not supported           | ✅ Up to 6 images per request        |
| **Task type API**      | `task_type` parameter      | Instruction-prefixed prompt          |
| **Dimensions**         | 768 default, MRL supported | 768/1536/3072, auto-renormalised     |
| **Cross-modal search** | ❌                         | ✅ All modalities in same space      |
| **Best for**           | Text-only RAG              | Mixed-media community knowledge base |

Since we ingest images, the `gemini-embedding-2` multimodal capability is directly relevant — in Phase 2 we can embed images directly (without needing a text description intermediary) and enable true cross-modal search: "find messages with images similar to this screenshot."

### Embedding Format (Asymmetric Retrieval)

Per the Gemini Embedding 2 documentation, text-only tasks with `gemini-embedding-2` require instruction-prefixed prompts for optimal performance. For this retrieval use case (RAG), the **asymmetric format** applies:

```python
# bot/memory/embedding_utils.py

def prepare_query_for_embedding(query: str) -> str:
    """Format a search query for gemini-embedding-2 retrieval."""
    return f"task: search result | query: {query}"

def prepare_document_for_embedding(content: str, title: str = None) -> str:
    """Format a document/message for gemini-embedding-2 indexing."""
    title_str = title if title else "none"
    return f"title: {title_str} | text: {content}"

# Example usage in mem0.add():
# The enriched message content is formatted as a document before storage:
document_text = prepare_document_for_embedding(
    content=enriched_event.enriched_content,
    title=f"#{enriched_event.channel_name} - {enriched_event.author_name}"
)

# Example usage in mem0.search():
# The user's query is formatted as a query before embedding:
query_text = prepare_query_for_embedding(user_question)
```

**Note:** Mem0 OSS calls the embedding model internally. To pass instruction-prefixed content, we need to either: (a) pre-format the content before passing to `mem0.add()`, or (b) subclass Mem0's embedder to inject the prefix. Option (a) is simpler and works by setting the `messages` content to the pre-formatted text. The Mem0 library passes `messages[].content` directly to the embedder.

### Embedding Dimensions

Use `output_dimensionality=768` (MRL truncation). This saves ~75% of storage versus 3072-dim while retaining ~99% of MTEB quality (768: 67.99 vs 3072: baseline per Google benchmarks). `gemini-embedding-2` auto-renormalises at 768, so no manual normalisation step is needed (unlike `gemini-embedding-001`).

Update the Qdrant collection config accordingly:

```python
"embedding_model_dims": 768,  # gemini-embedding-2 at 768 dims (auto-renormalised)
```

---

## 6. Data Models & Schemas

### 6.1 MessageEvent (updated)

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
    raw_attachment_urls: list[str] = []       # ← NEW: for media enrichment
    raw_urls: list[str] = []                  # ← NEW: URLs found in message text
    reply_to_message_id: Optional[int] = None
    enriched_content: Optional[str] = None   # ← NEW: set after MediaEnricher runs

    @property
    def date_str(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    def to_metadata_dict(self) -> dict:
        return {
            "channel_name": self.channel_name,
            "guild_id": str(self.guild_id),
            "timestamp": self.timestamp.isoformat(),
            "message_id": str(self.message_id),
            "has_attachments": self.has_attachments,
            "has_media": bool(self.raw_attachment_urls or self.raw_urls),
        }

    def content_for_ingestion(self) -> str:
        """Return enriched content if available, else raw content."""
        return self.enriched_content or self.content
```

### 6.2 WikiPage, QueryResult

Unchanged from v1 (see original doc Section 5.2–5.3).

### 6.3 CMConfig (new)

```python
# bot/community_manager/schemas.py
from pydantic import BaseModel
from typing import Optional

class CMConfig(BaseModel):
    enabled: bool = True
    cm_model: str = "gemini-3.1-flash-lite-preview"

    # Onboarding
    onboarding_enabled: bool = True
    welcome_channel_id: Optional[int] = None

    # FAQ responder
    faq_responder_enabled: bool = True
    faq_confidence_threshold: float = 0.85

    # Context injection
    context_injector_enabled: bool = True
    context_injector_cooldown_hours: int = 24
    context_injector_similarity_threshold: float = 0.82
    context_injector_min_prior_facts: int = 3

    # Duplicate detector
    duplicate_detector_enabled: bool = True
    duplicate_threshold: float = 0.90
    duplicate_lookback_hours: int = 2

    # Digest
    digest_enabled: bool = True
    digest_channel_id: Optional[int] = None
    digest_schedule: str = "daily"   # "daily" | "weekly" | "both"
    digest_time_utc: str = "09:00"

    # Member recognition
    recognition_enabled: bool = False
    recognition_channel_id: Optional[int] = None

    # Moderation assist
    moderation_enabled: bool = False
    mod_rules: list[str] = []
    mod_alert_channel_id: Optional[int] = None
    mod_role_id: Optional[int] = None
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
      - ./data/cm_config:/data/cm_config:rw # ← NEW
    environment:
      # Discord
      DISCORD_TOKEN: ${DISCORD_TOKEN}
      DISCORD_GUILD_ID: ${DISCORD_GUILD_ID}

      # Google Gemini (replaces OpenAI entirely)
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      EXTRACTION_MODEL: ${EXTRACTION_MODEL:-gemini-3.1-flash-lite-preview}
      QUERY_MODEL: ${QUERY_MODEL:-gemini-3.1-flash-lite-preview}
      WIKI_WRITER_MODEL: ${WIKI_WRITER_MODEL:-gemini-3.1-flash-lite-preview}
      CM_MODEL: ${CM_MODEL:-gemini-3.1-flash-lite-preview}
      EMBEDDING_MODEL: ${EMBEDDING_MODEL:-gemini-embedding-2}

      # Qdrant
      QDRANT_HOST: qdrant
      QDRANT_PORT: 6333
      QDRANT_COLLECTION: discord_memories

      # Ingestion
      INGEST_RATE_LIMIT_PER_CHANNEL: ${INGEST_RATE_LIMIT_PER_CHANNEL:-100}
      WIKI_BATCH_SIZE: ${WIKI_BATCH_SIZE:-20}
      WIKI_BATCH_TIMEOUT_SECONDS: ${WIKI_BATCH_TIMEOUT_SECONDS:-300}

      # Retention
      MEMORY_RETENTION_DAYS: ${MEMORY_RETENTION_DAYS:-180}
      WIKI_STALE_DAYS: ${WIKI_STALE_DAYS:-30}

      # GitHub token (optional, increases API rate limit for GitHub extractor)
      GITHUB_TOKEN: ${GITHUB_TOKEN:-}

      # Paths
      WIKI_PATH: /wiki
      SQLITE_PATH: /data/sqlite/mem0_history.db
      CM_CONFIG_PATH: /data/cm_config

      LOG_LEVEL: ${LOG_LEVEL:-INFO}

    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
```

### Dockerfile (updated requirements)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m spacy download en_core_web_sm

COPY . .

RUN useradd -m -u 1001 botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "main.py"]
```

### requirements.txt (updated — OpenAI removed, Gemini added, media deps added)

```
# Discord
discord.py==2.4.0

# Memory
mem0ai==0.1.101
qdrant-client==1.9.1

# LLM — Google Gemini (replaces openai entirely)
google-genai>=1.0.0

# Data validation
pydantic==2.8.2

# NLP (for Mem0 BM25 search)
spacy==3.7.4

# Media ingestion (new)
httpx==0.27.0          # async HTTP for URL fetching
readability-lxml==0.8.1  # article text extraction
Pillow==10.4.0         # image processing helpers

# Utilities
python-dotenv==1.0.1
aiofiles==24.1.0
PyYAML==6.0.2
python-frontmatter==1.1.0

# Logging
structlog==24.4.0
```

---

## 8. Environment Variables & Configuration

### .env.example (updated)

```bash
# ─── REQUIRED ────────────────────────────────────────────────────────────

DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_GUILD_ID=123456789012345678
GEMINI_API_KEY=AIza...

# ─── OPTIONAL ────────────────────────────────────────────────────────────

# All LLM tasks use gemini-3.1-flash-lite-preview by default
EXTRACTION_MODEL=gemini-3.1-flash-lite-preview   # Mem0 fact extraction
QUERY_MODEL=gemini-3.1-flash-lite-preview        # /ask command answers
WIKI_WRITER_MODEL=gemini-3.1-flash-lite-preview  # Wiki page writing
CM_MODEL=gemini-3.1-flash-lite-preview           # Community manager decisions

# Embedding: gemini-embedding-2 supports multimodal (images, etc.)
# Use gemini-embedding-001 only if you want text-only + explicit task_type API
EMBEDDING_MODEL=gemini-embedding-2

# GitHub API token (optional — increases rate limit from 60 to 5000 req/hr)
GITHUB_TOKEN=ghp_...

# Ingestion
INGEST_RATE_LIMIT_PER_CHANNEL=100
WIKI_BATCH_SIZE=20
WIKI_BATCH_TIMEOUT_SECONDS=300

# Retention
MEMORY_RETENTION_DAYS=180
WIKI_STALE_DAYS=30

# Logging
LOG_LEVEL=INFO
```

### config.py (updated)

```python
# bot/config.py
from pydantic import BaseSettings

class Config(BaseSettings):
    # Discord
    discord_token: str
    discord_guild_id: int

    # Google Gemini (no openai_api_key — removed entirely)
    gemini_api_key: str
    extraction_model: str = "gemini-3.1-flash-lite-preview"
    query_model: str = "gemini-3.1-flash-lite-preview"
    wiki_writer_model: str = "gemini-3.1-flash-lite-preview"
    cm_model: str = "gemini-3.1-flash-lite-preview"
    embedding_model: str = "gemini-embedding-2"

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "discord_memories"

    # Ingestion
    ingest_rate_limit_per_channel: int = 100
    wiki_batch_size: int = 20
    wiki_batch_timeout_seconds: int = 300

    # Retention
    memory_retention_days: int = 180
    wiki_stale_days: int = 30

    # Optional external API keys
    github_token: str = ""

    # Paths
    wiki_path: str = "/wiki"
    sqlite_path: str = "/data/sqlite/mem0_history.db"
    cm_config_path: str = "/data/cm_config"

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

config = Config()
```

---

## 9. Complete File-by-File Code Specification

Sections 9.1–9.9 are identical to the original document (listener, query_commands, wiki_commands, memory_commands, memory schemas, wiki writer/reader/linter, utils) with one exception: wherever `openai` was imported, it is replaced with `google.genai`.

### 9.10 bot/llm/client.py (updated — Gemini replaces OpenAI)

```python
"""
LLM abstraction layer — uses Google Gemini via google-genai SDK.
Replaces the previous OpenAI-based implementation entirely.
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
        """Send a single-turn prompt and return the text response."""
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
        """Generate a grounded answer to a user question using memory context."""
        model = model or config.query_model

        system_instruction = (
            "You are a helpful Discord server assistant with access to the server's "
            "conversation history. Answer questions based ONLY on the provided memory "
            "facts and wiki context. If you don't have enough information, say so honestly. "
            "Always cite which facts or wiki pages support your answer. "
            "Be specific and concise. Format answers for Discord (use markdown)."
        )

        user_prompt = f"""Question: {question}

## Memory Facts (from Mem0):
{mem0_facts or "No relevant facts found."}

## Wiki Context:
{wiki_context or "No relevant wiki pages found."}

Answer the question based on the above context."""

        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(user_prompt)]
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=1500,
            ),
        )
        return response.text
```

### 9.11 bot/cogs/cm_commands.py (new)

```python
"""
Slash commands for Community Manager Agent configuration and management.
/cm config, /cm status, /cm digest, /cm enable, /cm disable
"""
import json
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

from config import config
from community_manager.schemas import CMConfig
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class CMGroup(app_commands.Group):
    def __init__(self):
        super().__init__(
            name="cm",
            description="Community Manager Agent settings and controls"
        )

    def _config_path(self, guild_id: int) -> Path:
        return Path(config.cm_config_path) / f"{guild_id}.json"

    def _load_config(self, guild_id: int) -> CMConfig:
        path = self._config_path(guild_id)
        if path.exists():
            return CMConfig(**json.loads(path.read_text()))
        return CMConfig()

    def _save_config(self, guild_id: int, cm_config: CMConfig) -> None:
        path = self._config_path(guild_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cm_config.model_dump_json(indent=2))

    @app_commands.command(name="status", description="Show Community Manager Agent status")
    async def status(self, interaction: discord.Interaction):
        cm_config = self._load_config(interaction.guild_id)

        embed = discord.Embed(
            title="🤖 Community Manager Agent Status",
            color=discord.Color.green() if cm_config.enabled else discord.Color.red(),
        )
        embed.add_field(
            name="Overall",
            value="✅ Enabled" if cm_config.enabled else "❌ Disabled",
            inline=False,
        )

        behaviours = {
            "Onboarding": cm_config.onboarding_enabled,
            "FAQ Responder": cm_config.faq_responder_enabled,
            "Context Injector": cm_config.context_injector_enabled,
            "Duplicate Detector": cm_config.duplicate_detector_enabled,
            "Digest": cm_config.digest_enabled,
            "Member Recognition": cm_config.recognition_enabled,
            "Moderation Assist": cm_config.moderation_enabled,
        }
        status_lines = "\n".join(
            f"{'✅' if v else '❌'} {k}" for k, v in behaviours.items()
        )
        embed.add_field(name="Behaviours", value=status_lines, inline=False)

        if cm_config.digest_enabled and cm_config.digest_channel_id:
            embed.add_field(
                name="Digest",
                value=f"Posts to <#{cm_config.digest_channel_id}> ({cm_config.digest_schedule} at {cm_config.digest_time_utc} UTC)",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="enable", description="Enable a CM behaviour (admin only)")
    @app_commands.describe(behaviour="Which behaviour to enable")
    @app_commands.choices(behaviour=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Onboarding", value="onboarding"),
        app_commands.Choice(name="FAQ Responder", value="faq"),
        app_commands.Choice(name="Context Injector", value="context"),
        app_commands.Choice(name="Duplicate Detector", value="duplicate"),
        app_commands.Choice(name="Digest", value="digest"),
        app_commands.Choice(name="Moderation Assist", value="moderation"),
    ])
    async def enable(self, interaction: discord.Interaction, behaviour: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        cm_config = self._load_config(interaction.guild_id)

        mapping = {
            "all": lambda c: c.model_copy(update={"enabled": True}),
            "onboarding": lambda c: c.model_copy(update={"onboarding_enabled": True}),
            "faq": lambda c: c.model_copy(update={"faq_responder_enabled": True}),
            "context": lambda c: c.model_copy(update={"context_injector_enabled": True}),
            "duplicate": lambda c: c.model_copy(update={"duplicate_detector_enabled": True}),
            "digest": lambda c: c.model_copy(update={"digest_enabled": True}),
            "moderation": lambda c: c.model_copy(update={"moderation_enabled": True}),
        }

        if behaviour in mapping:
            cm_config = mapping[behaviour](cm_config)
            self._save_config(interaction.guild_id, cm_config)
            await interaction.response.send_message(
                f"✅ **{behaviour}** enabled.", ephemeral=True
            )

    @app_commands.command(
        name="set-digest-channel",
        description="Set the channel where digests are posted (admin only)"
    )
    @app_commands.describe(channel="The channel for digest posts")
    async def set_digest_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        cm_config = self._load_config(interaction.guild_id)
        cm_config = cm_config.model_copy(update={"digest_channel_id": channel.id})
        self._save_config(interaction.guild_id, cm_config)

        await interaction.response.send_message(
            f"✅ Digest channel set to {channel.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="digest",
        description="Post a digest right now (admin only)"
    )
    @app_commands.describe(period="'daily' or 'weekly'")
    async def digest(
        self,
        interaction: discord.Interaction,
        period: app_commands.Choice[str] = "daily",
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        cm_agent = self.bot.cm_agent
        await cm_agent.digest.post_digest(interaction.guild, period=period)
        await interaction.followup.send("✅ Digest posted.")

    @app_commands.command(
        name="add-rule",
        description="Add a moderation rule (admin only)"
    )
    @app_commands.describe(rule="The rule text, e.g. 'No hate speech or slurs'")
    async def add_rule(self, interaction: discord.Interaction, rule: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        cm_config = self._load_config(interaction.guild_id)
        rules = cm_config.mod_rules + [rule]
        cm_config = cm_config.model_copy(update={"mod_rules": rules, "moderation_enabled": True})
        self._save_config(interaction.guild_id, cm_config)

        await interaction.response.send_message(
            f"✅ Rule added: *{rule}*\nModeration assist is now enabled ({len(rules)} rules).",
            ephemeral=True,
        )


class CMCommandsCog(commands.Cog, name="CommunityManager"):
    def __init__(self, bot):
        self.bot = bot
        self.cm_group = CMGroup()
        self.cm_group.bot = bot
        bot.tree.add_command(self.cm_group)


async def setup(bot):
    await bot.add_cog(CMCommandsCog(bot))
```

---

## 10. Slash Commands Reference

| Command                                     | Description                             | Parameters                                      | Who can use |
| ------------------------------------------- | --------------------------------------- | ----------------------------------------------- | ----------- |
| `/ask question:[text]`                      | Query the knowledge base                | `question` (req), `channel` (opt), `user` (opt) | All members |
| `/whois member:[@user]`                     | See what the bot knows about a member   | `member` (req)                                  | All members |
| `/summary period:[...]`                     | Get a summary of recent activity        | `period` (opt, default: week)                   | All members |
| `/memory view`                              | See your own memory entries (ephemeral) | —                                               | All members |
| `/memory forget memory_id:[id]`             | Delete a specific memory entry          | `memory_id` (req)                               | All members |
| `/memory forgetall`                         | Delete all your memories                | —                                               | All members |
| `/wiki status`                              | Show wiki page counts and recent log    | —                                               | All members |
| `/wiki search query:[text]`                 | Search wiki by keyword                  | `query` (req)                                   | All members |
| `/wiki lint`                                | Run wiki health check                   | —                                               | Admins only |
| `/cm status`                                | Show CM Agent behaviour status          | —                                               | All members |
| `/cm enable behaviour:[...]`                | Enable a specific CM behaviour          | `behaviour` (req, choices)                      | Admins only |
| `/cm disable behaviour:[...]`               | Disable a specific CM behaviour         | `behaviour` (req, choices)                      | Admins only |
| `/cm set-digest-channel channel:[#channel]` | Set where digests are posted            | `channel` (req)                                 | Admins only |
| `/cm digest period:[daily\|weekly]`         | Post a digest immediately               | `period` (opt)                                  | Admins only |
| `/cm add-rule rule:[text]`                  | Add a moderation rule                   | `rule` (req)                                    | Admins only |

---

## 11. Deployment Guide (VPS)

### 11.1 Prerequisites

- VPS with at least **2 GB RAM** (4 GB recommended)
- Ubuntu 22.04 or 24.04 LTS
- Docker Engine + Docker Compose Plugin

### 11.2 Discord Developer Portal Setup

1. Create Application → Bot → Copy Token → `.env` as `DISCORD_TOKEN`
2. Privileged Gateway Intents: enable **Message Content Intent** AND **Server Members Intent** (required for `on_member_join`)
3. OAuth2 Scopes: `bot` + `applications.commands`
4. Bot Permissions: `Read Messages`, `Send Messages`, `Read Message History`, `Send Messages in Threads`

### 11.3 VPS Setup Commands

```bash
git clone <your-repo> /opt/discord-llmwiki-bot
cd /opt/discord-llmwiki-bot
cp .env.example .env
nano .env   # Fill in DISCORD_TOKEN, DISCORD_GUILD_ID, GEMINI_API_KEY

mkdir -p data/qdrant data/sqlite data/cm_config
bash scripts/bootstrap_wiki.sh

docker compose up -d --build
docker compose logs -f bot
```

### 11.4 bootstrap_wiki.sh (updated)

```bash
#!/usr/bin/env bash
WIKI_DIR="./wiki"

mkdir -p "$WIKI_DIR"/{entities,topics,channels,timeline,synthesis,resources}
touch "$WIKI_DIR"/{entities,topics,channels,timeline,synthesis,resources}/.gitkeep

cat > "$WIKI_DIR/log.md" << 'EOF'
# LLMWiki Operation Log
EOF

cat > "$WIKI_DIR/index.md" << 'EOF'
# LLMWiki Index

*Last updated: initialization*

| Page | Type | Summary | Updated | Sources |
|------|------|---------|---------|---------|
EOF

echo "Wiki structure initialized at $WIKI_DIR"
```

---

## 12. Maintenance, Linting & Retention

### 12.1 Automatic Processes

| Task                    | Frequency                      | Description                                                         |
| ----------------------- | ------------------------------ | ------------------------------------------------------------------- |
| `IngestionWorker`       | Continuous (async)             | Processes queue: MediaEnrich → Mem0 add → CM evaluate → wiki buffer |
| `wiki_writer_task`      | Every 5 min (or 20 messages)   | Flushes wiki buffer → updates markdown pages + resource pages       |
| `wiki_linter_task`      | Daily at 03:00 UTC             | Runs WikiLinter, produces lint report                               |
| `memory_retention_task` | Weekly                         | Deletes Mem0 facts older than `MEMORY_RETENTION_DAYS`               |
| `cm_digest_task`        | Daily or weekly (configurable) | Posts digest to configured channel                                  |
| `cm_recognition_task`   | Weekly                         | Posts member recognition to configured channel                      |

---

## 13. Extension Roadmap

### Phase 2 — True Multimodal Search

Use `gemini-embedding-2`'s native image embedding (not just text descriptions of images) to enable cross-modal search. Store image embeddings directly in a second Qdrant collection. Enable queries like: "Find all screenshots of error messages shared in #dev this month" — where the query is embedded as text but matches against image embeddings in the same vector space.

This is one of the most compelling capabilities of `gemini-embedding-2`: text and images share the same embedding space, so text queries can retrieve relevant images and vice versa — without any text description intermediary.

### Phase 3 — Thread & Forum Support

- Extend `ListenerCog` to handle `discord.Thread` events (forum posts, message threads)
- Thread summaries: when a thread is archived, trigger a WikiWriter update that creates a dedicated thread summary page
- The CM context injector would also work within threads

### Phase 4 — Search Upgrade

Replace `WikiReader.search_index()` (keyword) with a hybrid BM25+vector search using a second Qdrant collection indexed on wiki page content. This allows semantic search over the wiki (not just Mem0 facts), which significantly improves `/ask` quality for complex multi-hop questions.

### Phase 5 — Voice Channel Digests (Post-Voice)

When voice sessions end, use Discord's audio recording feature (if enabled by users with consent) or the built-in meeting notes feature to generate a text summary and inject it into the wiki + Mem0. This is the natural extension to the current text-only scope.

### Phase 6 — Multi-Server Support

The architecture already supports per-guild CM config (`data/cm_config/{guild_id}.json`). The main additional work is ensuring Mem0 memory scoping properly isolates guilds (use `guild_id` as a filter dimension) and that wiki files are partitioned per guild.

### Phase 7 — Proactive Knowledge Gaps

After each wiki lint, have the LLM identify "questions worth asking the community" based on detected knowledge gaps — and post them as a weekly prompt to a designated channel: "💡 This week's open questions from your community history: [list]". This makes the community manager feel genuinely engaged rather than purely reactive.

---

_End of Implementation Plan v2_

**Summary of key technology decisions:**

- **discord.py v2.4** — Cog-based architecture, slash commands, `setup_hook` for initialization
- **Mem0 OSS (self-hosted)** — `Memory` class, scoped by `user_id` + `agent_id` + `run_id`, Qdrant backend
- **Qdrant v1.9.1** — separate Docker service, persistent volume
- **LLMWiki pattern** — three-layer: raw sources → LLM-maintained wiki → schema (WIKI.md); plus new `resources/` directory for media
- **Community Manager Agent** — event-driven + scheduled behaviours: onboarding, FAQ, context injection, duplicate detection, digest, recognition, moderation assist
- **Rich Media Ingestion** — images (Gemini multimodal captioning), YouTube (oEmbed), GitHub (API), articles (readability)
- **Google Gemini** — `gemini-3.1-flash-lite-preview` for all LLM tasks; `gemini-embedding-2` for embeddings (multimodal, 768-dim MRL, asymmetric retrieval format)
- **Docker Compose** — two services (`qdrant` + `bot`), bind-mount volumes, `unless-stopped` restart
