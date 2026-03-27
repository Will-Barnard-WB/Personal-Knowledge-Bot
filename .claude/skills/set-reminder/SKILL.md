---
name: set-reminder
description: Set a one-off Telegram reminder at a specific time. Use when the user asks to be reminded about something at a given time.
user-invocable: false
allowed-tools: Bash(python *)
---

# Set Reminder

The main prompt includes a `Context JSON:` path for the current message.

## Workflow

1. Parse the user's message and extract:
   - `reminder_text`: a short, clear description of what to be reminded about
   - `when`: the trigger time — choose the format based on what the user said:
     - Absolute time ("at 3pm", "tomorrow at 9am", "Friday at 6pm") → ISO format `YYYY-MM-DDTHH:MM`
       - Use today's date (from context) for same-day times
       - Use the next calendar occurrence for day names
     - Relative time ("in 45 minutes", "in 2 hours") → shorthand `+Nm` (minutes), `+Nh` (hours), `+Nd` (days)

2. Run:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/set_reminder.py" \
  --context "<context-json-path>" \
  --reminder-text "<reminder_text>" \
  --when "<when>"
```

3. Read the returned JSON:
   - On success (`"ok": true`): confirm to the user with the reminder text and scheduled time
   - On error: report what went wrong clearly

## Examples

- "Remind me to call Mum at 6pm" → `--reminder-text "call Mum" --when "2026-03-27T18:00"`
- "Remind me about the standup in 45 minutes" → `--reminder-text "standup" --when "+45m"`
- "Remind me to take my medication tomorrow at 8am" → `--reminder-text "take medication" --when "2026-03-28T08:00"`

## Notes

- Keep `reminder_text` concise — it becomes the notification message.
- If the time is ambiguous, pick the soonest reasonable interpretation.
- If the requested time is in the past, the script will return an error — report it and ask for clarification.
