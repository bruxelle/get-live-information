# Classification Cases

This document tracks known live/non-live classification and merge cases.

It is not the source of truth for production data. Production data should come from the parser, readiness rules, merger, source archive, and public export pipeline. This file is a regression reference for parser/readiness/merger improvements and future AI classification evaluation.

| Case | Expected classification | Reason | Current status | Notes |
| --- | --- | --- | --- | --- |
| `グッズ&ナンバーくじ公開` | non-live | Goods / number lottery announcement, not a live performance schedule. | Excluded from public output | Should not be fixed by deleting generated JSON rows; parser/readiness should reject goods-only or kuji-only announcements. |
| `myojou Summer Vol.03 / 限定Tシャツ公開` | non-live | Limited T-shirt announcement with live context in the body; the subject is merchandise, not a live schedule announcement. | Parser/readiness regression case | Source post `2071494887225323698`. Future exports should not publish the merch title as a live event, but the real `myojou Summer Vol.03` live should remain valid when announced as a live. |
| `明夏 後日特典会` | non-live | Benefit-only / after-event-only notice, not a standalone public live schedule entry. | Excluded or needs review depending on source structure | Do not remove normal live events only because they mention `特典会`; this case is specifically after-event-only. |
| `争奪LIVE 前哨戦 緊急決起集会` | non-live | Streaming-only / not in-person live schedule for the public calendar. | Excluded from public output | If future product scope includes streams, this may become a separate content type rather than a live event. |
| `GIRLS GIRLS FESTIVAL 2026 / 超激レア` | valid live with corrected title | The source contains a real multi-day festival, but `超激レア` is benefit-card wording and should not become the event title. | Needs-review/corrected-title watchlist | Source post `2057721554885120196`. Preserve the festival title and dates; keep `超激レア` only as notes/benefit context. |
| `TOKYO IDOL FESTIVAL 2026` | valid live, may need review | Large multi-day festival with missing or incomplete ticket deadline information in some source posts. | Valid public event with review flag allowed | Missing ticket deadline should not remove an otherwise public-ready live occurrence. |
| `myojou Summer` / `myojou Summer Vol.01` | same live when date/venue/time/ticket URL match | Title aliases should merge when strong event identity fields match. | Merge regression case | Prefer richer title while preserving source lineage and useful subtitle details. |
| `myojou Summer Vol.01` / `myojou Summer Vol.02` / `myojou Summer Vol.03` | different lives unless date/time/ticket URL match the same occurrence | Numbered volumes in the same series can share wording and broad series posts, but different dates/venues/ticket URLs should remain separate. | Merge regression case | Do not merge unrelated numbered volumes only because the series name overlaps. |
| `IDOL INFINITE PREMIUM vol.09` | valid live | In-person live/event schedule with event structure. | Valid public event | Should remain visible unless a source-specific issue makes it not public-ready. |
| `IDOL ∞ INFINITY PREMIUM vol.12` | valid live | In-person live/event schedule with event structure. | Valid public event | Avoid over-normalizing symbols in a way that causes unsafe title loss. |
| `PreDEBUT LIVE` / `DEBUT LIVE` | valid live, may need review | Early official live rows can have sparse ticket/deadline metadata but still represent public live schedules. | Needs-review watchlist | Review flag is acceptable; do not demote solely because deadline details are incomplete. |
| `公開生放送ラジオ特番` | needs human review | Public radio/broadcast wording can be ambiguous: it may be an in-person public recording or a broadcast/content item. | Watchlist | Do not classify solely from `ラジオ`; source context should decide whether it is a public in-person schedule or non-live content. |

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
