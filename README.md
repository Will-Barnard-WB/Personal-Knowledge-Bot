# 🤖 WhatsApp & Telegram AI Assistant 

> A dual-channel (WhatsApp + Telegram) AI assistant that captures multi-modal content — voice notes, images, links, and text — and uses an autonomous Claude agent to organise everything into structured knowledge articles.

Built as a portfolio project to demonstrate production-grade AI engineering patterns.

---

## Architecture

Two thin Node.js gateways expose messaging-stack specifics while the Python FastAPI + ARQ backend stays identical. Start either stack (or both) depending on which network you want to use:

- **WhatsApp gateway** — powered by `whatsapp-web.js`, runs on port `3000`, and only processes self-chat messages from the owner device.
- **Telegram gateway** — powered by the official Bot API, runs on port `3001`, and only processes direct messages from the configured Telegram user ID.

Both gateways forward identical multipart payloads into the FastAPI app and receive replies through their `/send` endpoints.

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Your Phone (WhatsApp)                                                 │
 └────────────────────┬───────────────────────────────────────────────────┘
                      │  Text / Voice Note / Image / Link
                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Node.js WhatsApp Gateway  (whatsapp-web.js)          port 3000        │
 │                                                                        │
 │  • QR-scan auth, session persisted to disk                             │
 │  • Downloads media (audio/image) before forwarding                    │
 │  • Forwards all messages → POST /webhook (multipart)                  │
 │  • Exposes POST /send ← Python worker pushes replies here             │
 └────────────────────┬───────────────────────────────────────────────────┘
                      │  HTTP POST /webhook
                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  FastAPI App  (Python)                                port 8000        │
 │                                                                        │
 │  1. Redis sliding-window rate limiter (10 req/60s per user)           │
 │  2. ARQ: enqueue job → return 200 immediately                         │
 └────────────────────┬───────────────────────────────────────────────────┘
                      │  Redis (ARQ queue)
                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  ARQ Worker  (async Python)                                            │
 │                                                                        │
 │  ┌──────────────────────────────────────────────────────────────────┐ │
 │  │  Orchestrator Agent  (Claude claude-haiku-4-5, skills-first loop) │ │
 │  │                                                                  │ │
 │  │  Skills + script workflows:                                      │ │
 │  │    process-media   → Whisper / Claude vision / URL scrape        │ │
 │  │    capture-note    → embed + persist note in PostgreSQL          │ │
 │  │    search-kb       → cosine similarity over pgvector             │ │
 │  │    generate-article→ Synthesis Subagent (see below)              │ │
 │  └──────────────────────────────────────┬───────────────────────────┘ │
 │                                         │  asyncio.gather()           │
 │                 ┌───────────────────────┼──────────────────────────┐  │
 │                 ▼                       ▼                          ▼  │
 │         SubAgent-1              SubAgent-2               SubAgent-N   │
 │     (extract facts         (extract facts          (extract facts     │
 │      from note #1)          from note #2)           from note #N)     │
 │                 └───────────────────────┼──────────────────────────┘  │
 │                                         │  merged facts               │
 │                                         ▼                             │
 │                               Final synthesis call                    │
 │                               → Markdown article saved to DB          │
 └────────────────────────────────────────────────────────────────────────┘
                      │
                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  PostgreSQL + pgvector                                                 │
 │    notes      (content, embedding[384], topic, tags, media_type)      │
 │    articles   (title, content_md, summary, embedding[384], topic)     │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## Patterns Demonstrated

| Pattern | Where | Detail |
|---|---|---|
| **Agent orchestration with skills** | `app/agent/sdk_runner.py` + `CLAUDE.md` + `.claude/skills/` | Claude Agent SDK `query()` with project instructions in `CLAUDE.md` and workflow skills in `.claude/skills/` that run bundled scripts via Bash. |
| **Parallel subagents** | `app/agent/subagents/synthesis_agent.py` | `asyncio.gather()` fans out N independent Claude extraction calls — one per note — then merges into a rich article. |
| **Message queue** | `app/queue/` + ARQ + Redis | HTTP layer enqueues and returns immediately. Worker processes jobs independently. Survives restarts. |
| **Rate limiting** | `app/rate_limiter.py` | Redis sorted-set sliding window, implemented as an atomic Lua script to eliminate race conditions. |
| **Multi-modal input** | `.claude/skills/process-media/scripts/process_media.py` | Voice → Whisper; Image → Claude vision; URL → trafilatura; Text stays plain note content. |
| **Vector search** | `.claude/skills/search-kb/scripts/search_kb.py` | pgvector cosine distance over 384-dim sentence-transformers embeddings. |
| **Two-service design** | `whatsapp_gateway/`, `telegram_gateway/`, `app/` | Node.js I/O shims per channel + shared Python AI brain, connected via HTTP. |

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| AI / Agent | Anthropic `claude-haiku-4-5` | Cheapest capable Claude model ($1/MTok input). Supports tool use + vision. |
| Agent SDK | `claude-agent-sdk` Python SDK + `app/agent/sdk_runner.py` | Direct Agent SDK execution (`query`, `ClaudeAgentOptions`) with project instructions loaded from `CLAUDE.md`, skills from `.claude/skills/`, and permissions from `.claude/settings.json`. |
| WhatsApp | `whatsapp-web.js` | Browser-based WhatsApp Web automation; QR scan, no Meta approval needed. |
| Web framework | FastAPI + uvicorn | Async, fast, auto-generates OpenAPI docs at `/docs`. |
| Task queue | ARQ + Redis | asyncio-native, Redis-backed. 700 lines of source. Far simpler than Celery. |
| Rate limiting | Redis sorted sets (Lua) | Atomic sliding window; zero race conditions. |
| Database | PostgreSQL 16 + pgvector | Vector similarity search natively in SQL. |
| Embeddings | Deterministic hash embeddings (384-dim) | Lightweight, zero heavy model download, fast local vector indexing. |
| Transcription | OpenAI Whisper `base` | Runs locally on Mac Metal (~1s/note). 140MB, no API key. |
| Link scraping | trafilatura | #1 in independent benchmarks for article content extraction. |
| Infrastructure | Docker Compose | Single `docker compose up` brings up Postgres + Redis. |

---

## Quick Start

### Prerequisites

- macOS with Python 3.11+ and Node.js 18+
- Docker Desktop (for Postgres + Redis)
- [Anthropic API key](https://console.anthropic.com/)

### 1. Clone and configure

```bash
git clone <your-repo>
cd PersonalKnowledgeBot
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY
# For WhatsApp set: MY_WHATSAPP_ID, WEBHOOK_URL (optional override)
# For Telegram set: TELEGRAM_BOT_TOKEN, MY_TELEGRAM_ID, TELEGRAM_WEBHOOK_URL (optional)
```

### 2. Start infrastructure

```bash
docker compose up -d
```

### 3. Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> 🔁 **Prefer one command?** Use `./start_whatsapp.sh` or `./start_telegram.sh` to start Docker, FastAPI, the ARQ worker, and the appropriate gateway all at once. Run `./stop_<channel>.sh` to tear things down. The legacy `./start.sh` / `./stop.sh` wrappers now dispatch to these channel-specific scripts.

### 4. Start the API

```bash
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/docs
```

### 5. Start the ARQ worker

```bash
arq app.queue.worker.WorkerSettings
```

### 6. Start a gateway

**WhatsApp (websocket bridge):**

```bash
cd whatsapp_gateway
npm install
node index.js
# → Scan the QR code with your phone (WhatsApp → Linked Devices → Link a Device)
```

**Telegram (Bot API bridge):**

```bash
cd telegram_gateway
npm install
TELEGRAM_BOT_TOKEN=<token> MY_TELEGRAM_ID=<your_id> node index.js
# → Send /start to your bot from your Telegram account to confirm ownership
```

---

## Usage

### Natural language (agent mode)

Just send messages — the agent decides what to do:

| You send | Bot does |
|---|---|
| `"Interesting article about LLMs..."` | Saves as text note, extracts topic + tags |
| `https://example.com/article` | Scrapes, extracts text, saves as URL note |
| *[voice note]* | Transcribes with Whisper, saves transcription |
| *[photo]* | Analyses with Claude vision, saves description |
| `"What do I know about RAG?"` | Semantic search → returns related notes |

### Example: Article generation flow

```
You: Write me an article about Python async programming from my notes

Bot: Fetches all notes tagged "Python async programming"
     ↓
     Spawns 3 parallel Claude subagents (one per note) — extracting facts
     ↓
     Merges all facts
     ↓
     Final Claude call writes a structured Markdown article
     ↓
Bot: 📄 *Mastering Python Async Programming*

     A comprehensive guide to asyncio, coroutines...

     (Article #7 saved from 3 notes)
```

---

## Project Structure

```
PersonalKnowledgeBot/
├── whatsapp_gateway/
│   ├── index.js            # WhatsApp I/O, media download, gateway HTTP server
│   └── package.json
│
├── telegram_gateway/
│   ├── index.js            # Telegram Bot API bridge + /send endpoint
│   └── package.json
│
├── app/
│   ├── main.py             # FastAPI app, lifespan hooks, router mounting
│   ├── main_telegram.py    # Telegram-only FastAPI entrypoint
│   ├── config.py           # Pydantic settings (loads .env)
│   ├── database.py         # SQLAlchemy async engine, pgvector init
│   ├── rate_limiter.py     # Redis sliding-window rate limiter (Lua script)
│   │
│   ├── models/
│   │   ├── note.py         # Notes table (raw captured content + vector)
│   │   └── article.py      # Articles table (synthesised Markdown + vector)
│   │
│   ├── routers/
│   │   ├── webhook.py              # WhatsApp webhook
│   │   └── webhook_telegram.py     # Telegram webhook
│   │
│   ├── queue/
│   │   ├── tasks.py                # WhatsApp ARQ task
│   │   ├── tasks_telegram.py       # Telegram ARQ task
│   │   ├── worker.py               # WhatsApp worker settings
│   │   └── worker_telegram.py      # Telegram worker settings
│   │
│   └── agent/
│       ├── sdk_runner.py            # Claude Agent SDK runtime entrypoint (query + skill routing)
│       └── subagents/
│           └── synthesis_agent.py   # Parallel fact-extraction → article synthesis
│
├── docker-compose.yml      # Postgres (pgvector) + Redis
├── Dockerfile.worker       # Worker container with Whisper pre-loaded
├── requirements.txt
├── CLAUDE.md               # Primary project instructions for Claude Agent SDK
├── .claude/settings.json   # Claude project settings
├── .claude/skills/         # Focused workflow skills + Python scripts used by the agent
├── start_whatsapp.sh
├── stop_whatsapp.sh
├── start_telegram.sh
├── stop_telegram.sh
└── .env.example
```

---

## Cost estimate

For personal use (say, 50 messages/day average):

| Item | Cost/day |
|---|---|
| Claude Haiku (orchestration, ~500 tokens/msg) | ~$0.025 |
| Whisper (local) | $0 |
| Local hash embeddings | $0 |
| trafilatura (local) | $0 |
| **Total** | **~$0.75/month** |

Article generation (synthesis subagent) uses ~2,000 tokens/article-write: ~$0.002 each.
