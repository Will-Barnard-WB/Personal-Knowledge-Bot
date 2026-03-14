#!/usr/bin/env python3
"""Generate an article for the current user from saved notes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent.subagents.synthesis_agent import generate_article  # noqa: E402


def _load_context(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--model", default="claude-haiku-4-5")
    args = parser.parse_args()

    ctx = _load_context(args.context)

    import asyncio

    article = asyncio.run(
        generate_article(
            user_id=ctx["user_id"],
            topic=args.topic,
            model=args.model,
        )
    )

    if not article:
        print(json.dumps({"status": "not_found", "topic": args.topic}))
        return 0

    print(json.dumps({
        "status": "ok",
        "article_id": article.id,
        "title": article.title,
        "summary": article.summary,
        "topic": article.topic,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
