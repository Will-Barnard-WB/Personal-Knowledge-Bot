---
name: capture-note
description: Save useful plain-text information as a note. Use when the user shares something that should be remembered later, even if they do not explicitly say to save it.
user-invocable: false
allowed-tools: Bash(python *)
---

# Capture Note

The main prompt includes a `Context JSON:` path for the current message.

## Workflow

1. Read the message body from the context information in the main prompt.
2. Decide whether the content is worth saving.
3. Infer:
   - a concise topic
   - 2 to 4 useful tags
4. Save the note by running:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/capture_note.py" --context "<context-json-path>" --media-type text --topic "<topic>" --tags "<tag1>" "<tag2>"
```

5. Reply briefly with what was saved.

## Notes

- If the body is not worth saving, do not force this skill.
- Keep the user reply concise and practical.