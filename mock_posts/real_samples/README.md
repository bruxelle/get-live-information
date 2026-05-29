# real_samples fixture format

Use this directory for manually collected public posts from `@info_myojou`.
Do not call the real X API for these fixtures.

Each JSON object should use this shape:

```json
{
  "id": "real_sample_001",
  "text": "copied public post text",
  "created_at": "2026-05-30T03:00:00+09:00",
  "url": "https://x.com/info_myojou/status/...",
  "expected_classification": "event",
  "expected_source_kind": "initial_announcement",
  "notes": "why this label is expected"
}
```

Allowed `expected_classification` values:

```text
event
non_event
needs_review
```

Allowed `expected_source_kind` values:

```text
initial_announcement
timetable_update
day_before_reminder
same_day_reminder
ticket_update
correction
sold_out
other
```

Only include public data copied from public X posts. Never include private
messages, private account data, unpublished notes, tokens, or credentials.
