---
name: search-kb
description: Search saved notes and articles to answer questions about prior knowledge. Use when the user asks what they know about a topic or asks to find past information.
user-invocable: false
allowed-tools: Bash(python *)
---

# Search Knowledge Base

The main prompt includes a `Context JSON:` path for the current message.

## Workflow

1. Turn the user message into a good search query.
2. Run:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/search_kb.py" --context "<context-json-path>" --query "<query>"
```

3. Read the returned JSON results.
4. Answer based on those results.
5. If there are no relevant matches, say so plainly.

## Notes

- Stay grounded in retrieved material.
- Be honest about uncertainty.
- Keep the reply concise.