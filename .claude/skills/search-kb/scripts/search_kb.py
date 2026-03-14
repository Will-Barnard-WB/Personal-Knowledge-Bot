#!/usr/bin/env python3
"""Search the knowledge base for the current user."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import structlog
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import get_db  # noqa: E402
from app.models.article import Article  # noqa: E402
from app.models.note import Note  # noqa: E402

log = structlog.get_logger(__name__)


async def embed_text(text: str) -> list[float]:
    def _embed_sync(t: str) -> list[float]:
        dim = 384
        values = [0.0] * dim
        tokens = t.lower().split()
        if not tokens:
            return values

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx_a = int.from_bytes(digest[0:2], "big") % dim
            idx_b = int.from_bytes(digest[2:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[idx_a] += sign
            values[idx_b] += 0.5 * sign

        norm = sum(v * v for v in values) ** 0.5
        if norm > 0:
            values = [v / norm for v in values]
        return values

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_sync, text[:8192])


async def search_knowledge_base(
    user_id: str,
    query: str,
    limit: int = 5,
    search_type: str = "both",
) -> dict:
    query_embedding = await embed_text(query)
    results = {"notes": [], "articles": [], "total": 0}

    async with get_db() as session:
        if search_type in ("notes", "both"):
            note_rows = (
                await session.execute(
                    select(
                        Note,
                        Note.embedding.cosine_distance(query_embedding).label("distance"),
                    )
                    .where(Note.user_id == user_id)
                    .where(Note.embedding.isnot(None))
                    .order_by("distance")
                    .limit(limit)
                )
            ).all()

            results["notes"] = [
                {
                    "id": row.Note.id,
                    "content_preview": row.Note.content[:300],
                    "topic": row.Note.topic,
                    "tags": row.Note.tags,
                    "score": round(1 - float(row.distance), 4),
                    "created_at": row.Note.created_at.isoformat(),
                }
                for row in note_rows
            ]

        if search_type in ("articles", "both"):
            article_rows = (
                await session.execute(
                    select(
                        Article,
                        Article.embedding.cosine_distance(query_embedding).label("distance"),
                    )
                    .where(Article.user_id == user_id)
                    .where(Article.embedding.isnot(None))
                    .order_by("distance")
                    .limit(limit)
                )
            ).all()

            results["articles"] = [
                {
                    "id": row.Article.id,
                    "title": row.Article.title,
                    "summary": row.Article.summary,
                    "topic": row.Article.topic,
                    "score": round(1 - float(row.distance), 4),
                    "created_at": row.Article.created_at.isoformat(),
                }
                for row in article_rows
            ]

    results["total"] = len(results["notes"]) + len(results["articles"])
    log.info("search_complete", query=query[:60], total=results["total"])
    return results


def _load_context(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    ctx = _load_context(args.context)

    results = asyncio.run(
        search_knowledge_base(
            user_id=ctx["user_id"],
            query=args.query,
            limit=args.limit,
            search_type="both",
        )
    )
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
