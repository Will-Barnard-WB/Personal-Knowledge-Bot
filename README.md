# Personal Knowledge Bot

A dual-channel AI assistant (WhatsApp + Telegram) that captures voice notes, images, links, and text — and uses an autonomous Claude agent to organise everything into a searchable knowledge base.

Built as a portfolio project demonstrating production-grade async Python, AI orchestration, and message queue architecture.

---

## How it works

Send yourself a message → the bot transcribes, analyses, or scrapes it → embeds it semantically → saves it to your knowledge base. Ask a question later and it retrieves the most relevant notes using vector similarity search.

```
Your Phone
    │  voice / image / link / text
    ▼
Node.js Gateway          (normalises payloads, downloads media)
    │  HTTP POST
    ▼
FastAPI                  (rate limit check → enqueue job → return 200 immediately)
    │  Redis queue
    ▼
ARQ Worker               (async Python — picks up job, runs AI pipeline)
    │
    ├── process-media    → Whisper transcription / Claude vision / trafilatura
    ├── capture-note     → embed (384-dim) + save to PostgreSQL
    ├── search-kb        → cosine similarity search via pgvector
    └── generate-article → parallel Claude subagents extract facts → synthesise Markdown article
    │
    ▼
PostgreSQL + pgvector    (notes + articles with vector embeddings)
    │
    ▼
Node.js Gateway /send    (delivers reply back to you)
```

---

## Key Engineering Decisions

| Pattern | Detail |
|---|---|
| **Async-first stack** | FastAPI + ARQ + asyncpg + SQLAlchemy 2.0 async — non-blocking from HTTP layer down to the DB driver |
| **Message queue decoupling** | HTTP returns 200 immediately; ARQ worker processes jobs independently via Redis. Survives restarts, retries on failure |
| **Sliding-window rate limiter** | Built from scratch using Redis sorted sets and an atomic Lua script — single round-trip, no race conditions |
| **Semantic vector search** | pgvector cosine distance over 384-dim sentence-transformer embeddings — no separate vector database needed |
| **Parallel subagent synthesis** | `asyncio.gather()` fans out N independent Claude calls (one per note) for fact extraction, then merges into a structured article |
| **Custom MCP server** | Exposes typed tools (transcription, vision, search, capture) via the Model Context Protocol — callable directly by the agent SDK |
| **Two-language architecture** | Node.js gateway tier per channel for real-time messaging; Python backend for all AI and data logic |

---

## Tech Stack

| | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, Uvicorn |
| **Task Queue** | ARQ + Redis 7 |
| **Database** | PostgreSQL 16 + pgvector |
| **AI / Agent** | Claude Agent SDK, claude-haiku-4-5 |
| **Transcription** | faster-whisper (local, ~1s/note) |
| **Embeddings** | sentence-transformers all-MiniLM-L6-v2 |
| **Link scraping** | trafilatura |
| **Gateways** | Node.js + whatsapp-web.js / Telegram Bot API |
| **Infrastructure** | Docker Compose |

---

## Quick Start

**Prerequisites:** Python 3.11+, Node.js 18+, Docker Desktop, Anthropic API key

```bash
git clone <repo>
cd PersonalKnowledgeBot
cp .env.example .env        # add your ANTHROPIC_API_KEY + TELEGRAM_BOT_TOKEN + MY_TELEGRAM_ID

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd telegram_gateway && npm install && cd ..

./start_telegram.sh         # starts Docker, FastAPI, ARQ worker, and Node gateway
```

Then message your Telegram bot. Stop everything with `./stop_telegram.sh`.

---

## Project Structure

```
├── app/
│   ├── agent/
│   │   ├── sdk_runner.py           # Claude Agent SDK orchestrator + RAG injection
│   │   └── subagents/
│   │       └── synthesis_agent.py  # Parallel fact extraction → article synthesis
│   ├── queue/
│   │   ├── tasks_telegram.py       # ARQ task — end-to-end message processing
│   │   └── worker_telegram.py      # Worker config (max_jobs, retries, lifecycle hooks)
│   ├── routers/
│   │   └── webhook_telegram.py     # FastAPI webhook — rate limit + enqueue
│   ├── mcp_server.py               # MCP server exposing multi-modal tools
│   ├── rag.py                      # Semantic context retrieval for prompt injection
│   ├── rate_limiter.py             # Redis sliding-window rate limiter (Lua)
│   ├── database.py                 # SQLAlchemy async engine + pgvector setup
│   └── embeddings.py               # sentence-transformers wrapper
│
├── .claude/skills/                 # Agent skill scripts (capture, search, media, article)
├── telegram_gateway/index.js       # Telegram Bot API bridge
├── docker-compose.yml              # PostgreSQL + Redis
└── CLAUDE.md                       # Agent behaviour instructions
```
