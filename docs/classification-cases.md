# Classification Cases

This document tracks known live/non-live classification and merge cases.

It is not the source of truth for production data. Production data should come from the parser, readiness rules, merger, source archive, and public export pipeline. This file is a regression reference for parser/readiness/merger improvements and future AI classification evaluation.

| Case | Expected classification | Reason | Current status | Notes |
| --- | --- | --- | --- | --- |
| `グッズ&ナンバーくじ公開` | non-live | Goods / number lottery announcement, not a live performance schedule. | Excluded from public output | Should not be fixed by deleting generated JSON rows; parser/readiness should reject goods-only or kuji-only announcements. |
| `明夏 後日特典会` | non-live | Benefit-only / after-event-only notice, not a standalone public live schedule entry. | Excluded or needs review depending on source structure | Do not remove normal live events only because they mention `特典会`; this case is specifically after-event-only. |
| `争奪LIVE 前哨戦 緊急決起集会` | non-live | Streaming-only / not in-person live schedule for the public calendar. | Excluded from public output | If future product scope includes streams, this may become a separate content type rather than a live event. |
| `超激レア` | non-live or corrected-title case depending on source context | Ambiguous title extraction can turn a phrase into an event title when the source context is actually a notice or malformed title. | Watchlist | Use source text and surrounding structure before deciding. Do not publish if date/venue/live structure is insufficient. |
| `myojou Summer` / `myojou Summer Vol.01` | same live when date/venue/time/ticket URL match | Title aliases should merge when strong event identity fields match. | Merge regression case | Prefer richer title while preserving source lineage and useful subtitle details. |
| `IDOL INFINITE PREMIUM vol.09` | valid live | In-person live/event schedule with event structure. | Valid public event | Should remain visible unless a source-specific issue makes it not public-ready. |
| `IDOL ∞ INFINITY PREMIUM vol.12` | valid live | In-person live/event schedule with event structure. | Valid public event | Avoid over-normalizing symbols in a way that causes unsafe title loss. |

## How To Use This File

When a classification bug is found:

* Identify the source post in the X archive or real sample fixture.
* Determine whether the issue belongs in parser extraction, public readiness, merger/canonicalization, or public export filtering.
* Add or update tests using the source as a regression example.
* Regenerate public output through the normal pipeline if generated data needs to change.

Avoid:

* Hand-editing `public/events.json` as the primary fix.
* Hardcoding one generated public event ID as a deletion target.
* Removing normal live events because they contain a keyword that is also used by non-live posts.
* Treating ticket sale dates, announcement dates, goods release dates, or stream dates as live dates without live schedule structure.
