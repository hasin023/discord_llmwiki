# Discord LLMWiki Community Manager Bot v3

A modular, budget-aware Discord bot that builds a living knowledge base from server conversations using **Mem0 OSS**, **Qdrant**, and **Google Gemini** — plus a proactive **Community Manager Agent** with 7 autonomous behaviours.

## Key Features

### Memory Layer (Mem0 + Qdrant)

- Extracts structured facts from every conversation (batched, deduplicated)
- Hybrid BM25 + dense vector search via Qdrant for high-recall retrieval
- Per-user and per-channel memory scoping

### LLMWiki (Knowledge Base)

- LLM-maintained Markdown wiki: entities, topics, channels, timeline, resources
- Auto-generates pages from conversation patterns
- Weekly linting for quality assurance

### Community Manager Agent

| Behaviour              | Trigger               | Description                                  |
| ---------------------- | --------------------- | -------------------------------------------- |
| **Onboarding**         | `on_member_join`      | Personalised welcome DM + server guide       |
| **FAQ Responder**      | Question detected     | Auto-answers from knowledge base             |
| **Context Injector**   | Topic re-emerges      | Surfaces prior discussion context            |
| **Duplicate Detector** | Cross-channel overlap | Flags parallel discussions                   |
| **Digest**             | Scheduled             | Daily/weekly activity summaries              |
| **Recognition**        | Scheduled             | Weekly top contributor shoutouts             |
| **Moderation Assist**  | Every message         | Flags rule violations to mods (non-punitive) |

### Free-Tier First Design

- **BudgetController**: Async token-bucket rate limiter per model
- **LocalPreFilter**: Drops ~65% of messages before any API call
- **ContentHashDedup**: Rolling MD5 deduplication
- **MessageBuffer**: Batches 5 messages per `mem0.add()` call (87% reduction)
- **SemanticResponseCache**: Returns cached answers for similar questions
- Runs on Gemini free tier (~285 LLM calls/day for a 500 msg/day server)

### Rich Media Ingestion

- **Images**: Gemini multimodal captioning (budgeted LLM call)
- **YouTube**: oEmbed metadata (free)
- **GitHub**: REST API for repos/PRs/issues (free)
- **Articles**: readability-lxml extraction (free)
- **Twitter/X**: oEmbed metadata (free)

## Quick Start

### Prerequisites

- Docker + Docker Compose
- Discord bot token ([Developer Portal](https://discord.com/developers/applications))
- Google Gemini API key ([AI Studio](https://aistudio.google.com/))

### Setup

```bash
git clone https://github.com/hasin023/discord_llmwiki.git && cd discord_llmwiki
cp .env.example .env
nano .env  # Fill in DISCORD_TOKEN, DISCORD_GUILD_ID, GEMINI_API_KEY

docker compose up -d --build
docker compose logs -f bot
```

We can remove all the data and start fresh by running the following commands:

```powershell
Get-ChildItem -Path .\wiki | Remove-Item -Recurse -Force; Get-ChildItem -Path .\data\qdrant | Remove-Item -Recurse -Force; Get-ChildItem -Path .\data\sqlite | Remove-Item -Recurse -Force; Get-ChildItem -Path .\data\cache | Remove-Item -Recurse -Force; New-Item -ItemType File -Path .\wiki\.gitkeep -Force; New-Item -ItemType File -Path .\data\qdrant\.gitkeep -Force; New-Item -ItemType File -Path .\data\sqlite\.gitkeep -Force; New-Item -ItemType File -Path .\data\cache\.gitkeep -Force
```

> **Note:** All data directories and the wiki structure are created automatically on first boot — no manual setup needed beyond configuring `.env`.

### Discord Developer Portal Setup

1. Create Application → Bot → Copy Token
2. Enable **Message Content Intent** + **Server Members Intent**
3. OAuth2 Scopes: `bot` + `applications.commands`
4. Permissions: Read Messages, Send Messages, Read Message History

## Slash Commands

| Command                         | Description                   | Access |
| ------------------------------- | ----------------------------- | ------ |
| `/ask question:[text]`          | Query the knowledge base      | All    |
| `/whois member:[@user]`         | Member profile from memory    | All    |
| `/summary period:[day/week]`    | Activity summary              | All    |
| `/memory view`                  | See your memories (ephemeral) | All    |
| `/memory forget memory_id:[id]` | Delete a memory               | All    |
| `/memory forgetall`             | Delete all your memories      | All    |
| `/wiki status`                  | Wiki page counts              | All    |
| `/wiki search query:[text]`     | Search wiki                   | All    |
| `/wiki lint`                    | Run wiki health check         | Admin  |
| `/cm status`                    | CM Agent behaviour status     | All    |
| `/cm enable behaviour:[...]`    | Enable a behaviour            | Admin  |
| `/cm disable behaviour:[...]`   | Disable a behaviour           | Admin  |
| `/cm set-digest-channel`        | Set digest channel            | Admin  |
| `/cm digest period:[...]`       | Post digest now               | Admin  |
| `/cm add-rule rule:[text]`      | Add moderation rule           | Admin  |

## Architecture

```bash
Discord → Listener → LocalPreFilter → ContentHashDedup → MediaEnricher
    → MessageBuffer(5) → BudgetController → mem0.add(batch)
    → CommunityManagerAgent → WikiBuffer → WikiWriter
```

## Models (Free Tier)

| Component       | Model                   | Free Limits         |
| --------------- | ----------------------- | ------------------- |
| LLM (all tasks) | `gemini-2.5-flash-lite` | 15 RPM / 1,000 RPD  |
| Embeddings      | `gemini-embedding-001`  | 100 RPM / 1,000 RPD |

## Project Structure

```bash
bot/
├── main.py              # Entry point
├── config.py            # Pydantic settings
├── budget/              # BudgetController (rate limiting)
├── cache/               # SemanticResponseCache
├── cogs/                # Discord slash commands
├── community_manager/   # CM Agent + 7 behaviours
├── llm/                 # Gemini LLM client
├── media/               # Media enrichment extractors
├── memory/              # Mem0 client, ingestion, hybrid search
├── wiki/                # WikiWriter, Reader, Linter
└── utils/               # Logging, formatting, rate limiter
```

## License

MIT
