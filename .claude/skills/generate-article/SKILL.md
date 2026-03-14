---
name: generate-article
description: Generate a synthesized write-up from saved notes. Use when the user asks for an article, guide, write-up, or combined summary from existing notes.
user-invocable: false
allowed-tools: Bash(python *)
---

# Generate Article

The main prompt includes a `Context JSON:` path for the current message.

## Workflow

1. Infer the article topic from the user's request.
2. Run:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/generate_article.py" --context "<context-json-path>" --topic "<topic>"
```

3. Read the returned JSON.
4. If the status is `not_found`, explain that there is not enough source material yet.
5. If the status is `ok`, reply with the article title and a concise summary.

## Notes

- Do not dump raw implementation details.
- Keep the chat reply short.