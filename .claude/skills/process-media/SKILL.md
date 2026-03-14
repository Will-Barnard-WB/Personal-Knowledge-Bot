---
name: process-media
description: Process audio, image, and URL messages before saving them. Use when the message type is audio, image, or url.
user-invocable: false
allowed-tools: Bash(python *)
---

# Process Media

The main prompt includes a `Context JSON:` path for the current message.

## Workflow

1. Extract the media content by running:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/process_media.py" --context "<context-json-path>"
```

2. Use the script output JSON:
   - `content_file` points to extracted text saved on disk
   - `media_type` is the note media type to save
   - `suggested_topic` and `suggested_tags` are hints, not mandatory answers
   - `source_url` is present for URL messages

3. Review the extracted content conceptually and infer the final topic and tags.
4. Save the extracted content by running:

```bash
python ./.claude/skills/capture-note/scripts/capture_note.py --context "<context-json-path>" --media-type "<media_type>" --content-file "<content_file>" --topic "<topic>" --tags "<tag1>" "<tag2>"
```

If `source_url` is present, include `--source-url "<source_url>"`.

5. Reply briefly with the result.

## Notes

- Audio: save the meaningful transcription, not just a generic acknowledgement.
- Image: use the description and visible text if relevant.
- URL: preserve the important information, not the raw page dump.