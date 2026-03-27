"""
Synthesis subagent — generates structured knowledge articles from related notes.

Demonstrates the PARALLEL SUBAGENTS pattern:

  Orchestrator
      │
      ├─── DB query: fetch notes for topic
      │
      ├─── asyncio.gather() — N concurrent Claude calls, one per note
      │       ├── SubAgent-1: extract facts from note #1
      │       ├── SubAgent-2: extract facts from note #2
      │       └── SubAgent-N: extract facts from note #N
      │
      └─── Final Claude call: synthesise facts into Markdown article

Each sub-call is a fresh Claude message — no shared state — demonstrating
how to fan out independent LLM tasks and merge their results.
"""
import asyncio
from typing import Optional

import structlog
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

from app.database import get_db
from app.embeddings import embed_text
from app.models.note import Note
from app.models.article import Article
from sqlalchemy import select

log = structlog.get_logger(__name__)

# ─── Prompts ──────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """You are a fact-extraction sub-agent. Your job is to read one piece of raw note content and extract the key facts, concepts, and insights in a structured way.

Note content (type: {media_type}):
---
{content}
---

Respond with a JSON object:
{{
  "key_facts": ["<fact 1>", "<fact 2>", ...],
  "concepts": ["<concept 1>", ...],
  "quotes": ["<notable quote or phrase>", ...],
  "importance": "high | medium | low"
}}

JSON only, no markdown fences."""

_SYNTHESIS_PROMPT = """You are a knowledge synthesis agent. You have been given extracted facts from {n_notes} related notes on the topic "{topic}".

Your task: write a well-structured, informative Markdown article that:
1. Has a clear H1 title
2. Includes an executive summary (2–3 sentences)
3. Organises content into logical H2 sections
4. Integrates the facts naturally — no bullet-dump
5. Ends with a "Key Takeaways" section (3–5 bullets)
6. Is written in second person ("you will learn...")

Extracted facts from all notes:
---
{facts_block}
---

Write the complete Markdown article now. No preamble — start directly with the # Title."""


async def _extract_facts_from_note(
    note: Note,
    model: str,
) -> dict:
    """
    Single sub-agent call: extract structured facts from one note.
    This function is called in parallel for each note via asyncio.gather.
    """
    prompt = _EXTRACTION_PROMPT.format(
        media_type=note.media_type,
        content=note.content[:4000],  # truncate very long notes
    )

    try:
        raw = ""
        options = ClaudeAgentOptions(
            model=model,
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            max_turns=2,
        )

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage) and message.result:
                raw = message.result.strip()

        import json
        return json.loads(raw)
    except Exception as e:
        log.warning("fact_extraction_failed", note_id=note.id, error=str(e))
        # Return minimal structure on failure — synthesis continues
        return {
            "key_facts": [note.content[:300]],
            "concepts": [],
            "quotes": [],
            "importance": "medium",
        }


def _format_facts_block(facts_list: list[dict], notes: list[Note]) -> str:
    """Format all extracted facts into a single context block for the synthesis call."""
    lines = []
    for i, (facts, note) in enumerate(zip(facts_list, notes), 1):
        lines.append(f"### Source {i} ({note.media_type}, saved {note.created_at.date()})")
        for fact in facts.get("key_facts", []):
            lines.append(f"- {fact}")
        if facts.get("concepts"):
            lines.append(f"  Concepts: {', '.join(facts['concepts'])}")
        if facts.get("quotes"):
            lines.append(f"  Notable: {facts['quotes'][0]}")
        lines.append("")
    return "\n".join(lines)


async def generate_article(
    user_id: str,
    topic: str,
    model: str = "claude-haiku-4-5",
) -> Optional[Article]:
    """
    Full synthesis pipeline:
      1. Fetch all notes for the given topic from the DB
      2. Fan out: asyncio.gather() runs one Claude extraction call per note in parallel
      3. Merge extracted facts
      4. One final Claude call synthesises the Markdown article
      5. Embed the article and persist to DB

    Returns the saved Article ORM object, or None if no notes found.
    """
    # ── 1. Fetch relevant notes ──────────────────────────────────────────────
    async with get_db() as session:
        stmt = (
            select(Note)
            .where(Note.user_id == user_id)
            .where(Note.topic == topic)
            .order_by(Note.created_at.asc())
        )
        result = await session.execute(stmt)
        notes = result.scalars().all()

    if not notes:
        log.warning("synthesis_no_notes", user_id=user_id, topic=topic)
        return None

    log.info("synthesis_started", user_id=user_id, topic=topic, n_notes=len(notes))

    # ── 2. Parallel subagent extraction calls ────────────────────────────────
    # Each note gets its own independent Claude call — true parallelism via gather
    extraction_tasks = [
        _extract_facts_from_note(note, model)
        for note in notes
    ]
    facts_list = await asyncio.gather(*extraction_tasks)

    log.info(
        "synthesis_extraction_complete",
        n_notes=len(notes),
        n_facts=sum(len(f.get("key_facts", [])) for f in facts_list),
    )

    # ── 3. Merge and format facts ────────────────────────────────────────────
    facts_block = _format_facts_block(facts_list, notes)

    # ── 4. Final synthesis call ──────────────────────────────────────────────
    synthesis_prompt = _SYNTHESIS_PROMPT.format(
        n_notes=len(notes),
        topic=topic,
        facts_block=facts_block,
    )

    article_markdown = ""
    options = ClaudeAgentOptions(
        model=model,
        permission_mode="bypassPermissions",
        setting_sources=["project"],
        max_turns=3,
    )
    async for message in query(prompt=synthesis_prompt, options=options):
        if isinstance(message, ResultMessage) and message.result:
            article_markdown = message.result.strip()

    if not article_markdown:
        article_markdown = f"# {topic}\n\nNo content generated."

    # Extract title and summary from the Markdown
    lines = article_markdown.split("\n")
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("#")), topic)
    # Summary: first non-empty, non-heading paragraph
    summary = ""
    for line in lines[1:]:
        line = line.strip()
        if line and not line.startswith("#"):
            summary = line[:500]
            break

    # ── 5. Embed and persist ─────────────────────────────────────────────────
    embedding = await embed_text(f"{title}\n{summary}")

    async with get_db() as session:
        article = Article(
            user_id=user_id,
            title=title,
            summary=summary,
            content=article_markdown,
            topic=topic,
            embedding=embedding,
            source_note_ids=[n.id for n in notes],
        )
        session.add(article)
        await session.flush()
        await session.refresh(article)

    log.info(
        "synthesis_complete",
        article_id=article.id,
        title=title,
        chars=len(article_markdown),
    )
    return article
