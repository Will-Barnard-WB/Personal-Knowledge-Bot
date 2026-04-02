"""
Light RAG context retrieval for automatic prompt injection.

Embeds the incoming query and retrieves the top-K semantically similar notes
and articles from pgvector, returning a compact markdown snippet for injection
into the orchestrator's initial prompt.

Errors are swallowed — RAG failure must never block message delivery.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select

from app.database import get_db
from app.embeddings import embed_text
from app.models.article import Article
from app.models.note import Note

log = structlog.get_logger(__name__)


async def retrieve_context(
    user_id: str,
    query: str,
    max_results: int = 2,
    min_score: float = 0.5,
) -> str:
    """
    Return a compact markdown snippet of the most relevant saved notes/articles,
    or an empty string if nothing clears the similarity threshold.

    Args:
        user_id:     WhatsApp/Telegram user ID (scopes the search).
        query:       The incoming message text used as the search query.
        max_results: Maximum number of snippets to return in total.
        min_score:   Minimum cosine similarity (0–1) required to include a result.
    """
    if not query or len(query.strip()) <= 10:
        return ""

    try:
        query_embedding = await embed_text(query)
        snippets: list[str] = []

        async with get_db() as session:
            note_rows = (
                await session.execute(
                    select(
                        Note,
                        Note.embedding.cosine_distance(query_embedding).label("distance"),
                    )
                    .where(Note.user_id == user_id)
                    .where(Note.embedding.isnot(None))
                    .order_by("distance")
                    .limit(max_results)
                )
            ).all()

            for row in note_rows:
                score = round(1 - float(row.distance), 4)
                if score >= min_score:
                    preview = row.Note.content[:300].replace("\n", " ")
                    label = row.Note.topic or row.Note.media_type
                    snippets.append(f"- [{label}] {preview}")

            article_rows = (
                await session.execute(
                    select(
                        Article,
                        Article.embedding.cosine_distance(query_embedding).label("distance"),
                    )
                    .where(Article.user_id == user_id)
                    .where(Article.embedding.isnot(None))
                    .order_by("distance")
                    .limit(max_results)
                )
            ).all()

            for row in article_rows:
                score = round(1 - float(row.distance), 4)
                if score >= min_score:
                    snippets.append(
                        f"- [article: {row.Article.title}] {row.Article.summary[:200]}"
                    )

        if not snippets:
            return ""

        snippets = list(dict.fromkeys(snippets))[:max_results]
        log.info("rag_context_found", user_id=user_id, n=len(snippets))
        return "\n".join(snippets)

    except Exception:
        log.exception("rag_retrieve_failed", user_id=user_id)
        return ""
