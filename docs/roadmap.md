# Roadmap

This roadmap describes the path from the current static public schedule to a more complete live schedule and ticket reminder product.

The current product is a static GitHub Pages site generated from official `@info_myojou` X posts. Notion remains the detailed admin/backend database, and `public/events.json` is the public data file used by the mobile-first web UI.

## Phase 1: Current Product Stabilization

Estimated duration: 1-2 weeks.

Goal: make the existing static public schedule reliable enough to operate and review.

Focus areas:

* UI QA on mobile and desktop.
* Regression tests for the documented public UI behavior.
* Alignment with [public-ui-spec.md](public-ui-spec.md).
* Bug triage for calendar rendering, card view behavior, detail bottom sheet behavior, and public export quality.
* Manual verification checklist for each release.
* Stabilization of the current static GitHub Pages version.

Exit criteria:

* The calendar-first public UI behaves consistently on smartphone and desktop.
* Card view remains available as a secondary browsing mode.
* Public export validation passes before publishing.
* Known non-live false positives are tracked or fixed.
* The release checklist is clear enough to repeat without guesswork.

## Phase 1.5: Full UI Redesign

Estimated duration: 2-4 weeks.

Goal: redesign the public UI after stabilization and before the AWS DB migration, so the product direction is clear before deeper infrastructure work.

Focus areas:

* Define a lightweight design system for typography, spacing, colors, buttons, chips, cards, calendar cells, and bottom sheets.
* Keep mobile-first calendar as the primary experience.
* Keep card view as a secondary detailed browsing mode.
* Refine the detail bottom sheet for live info, ticket info, application/deadline info, and links.
* Avoid vibe-coding style by defining reusable components, layout rules, and interaction patterns before implementation.
* Preserve static GitHub Pages compatibility unless there is a deliberate migration decision.

Exit criteria:

* The UI has stable component and layout rules.
* The calendar, card view, and detail bottom sheet feel like one coherent service.
* Design decisions are documented before introducing larger app or backend complexity.

## Phase 2: Data Quality and Classification Improvement

Estimated duration: 2-4 weeks, then ongoing.

Goal: improve public data quality and reduce false positives, false negatives, duplicates, and low-confidence events.

Focus areas:

* Parser hardening for real X post patterns.
* Public readiness rules for non-live posts, notice-only posts, streaming-only posts, profile posts, goods posts, and benefit-only posts.
* Merger hardening for title aliases, same-date events, multi-day festivals, venue normalization, and ticket URL matching.
* False positive and false negative tracking.
* Classification case documentation.
* `needs_review` reporting and suspicious examples.
* Planning a manual correction workflow that does not depend on hand-editing `public/events.json`.

Exit criteria:

* Known recurring classification cases are represented in tests or fixtures.
* Public export excludes not-public-ready records by default.
* The review report makes missing or suspicious data easy to inspect.
* Manual corrections have a planned home before moving to a cloud database.

## Phase 3: Local Data Model and DB Preparation

Estimated duration: 2-3 weeks.

Goal: prepare the local data model for a cloud database and future app features.

Focus areas:

* Define stable entities:
  * `Post`
  * `Event`
  * `TicketSale`
  * `Deadline`
  * `Venue`
  * `ClassificationReview`
* Clean up the SQLite schema around source posts, canonical events, public occurrences, ticket sale periods, and review metadata.
* Preserve source lineage and raw X metadata for debugging.
* Produce a stable public export from the DB.
* Clarify which fields are internal, admin-only, and public.

Exit criteria:

* Local DB tables map clearly to future cloud entities.
* Public export can be regenerated from local DB state without manual patches.
* Migration risks are understood before introducing AWS storage.

## Phase 4: AWS DB and Pipeline

Estimated duration: 3-6 weeks.

Goal: move from local SQLite plus committed JSON toward a production-ready data pipeline.

Focus areas:

* Store raw X archive data in S3.
* Decide between PostgreSQL and DynamoDB for structured event data.
* Evaluate Lambda versus GitHub Actions for scheduled sync.
* Add CloudWatch/logging for sync runs, parser quality, and export validation.
* Generate public export data from the cloud pipeline.
* Keep Notion as admin/backend only if it remains useful.

Exit criteria:

* Raw posts are archived safely.
* Structured event data is queryable and reviewable.
* Scheduled sync/export can run without a local machine.
* Operational logs make failures and data quality issues visible.

## Phase 5: AI Live Classification

Estimated duration: 3-6 weeks for first evaluation, then iterative.

Goal: use AI to assist classification and extraction without making it the sole source of truth.

Focus areas:

* Use AI as an assistant first, not as the only decision maker.
* Compare AI classification against the rule-based classifier.
* Capture confidence, reasons, and risk flags.
* Route uncertain or conflicting results into a human review loop.
* Build evaluation data from real X samples and known classification cases.
* Track precision/recall for live, non-live, and needs-review decisions.

Exit criteria:

* AI output can be evaluated against known cases.
* Low-confidence AI decisions do not automatically publish.
* Human review remains possible for ambiguous posts.

## Phase 6: User-Facing Live Schedule Tool/App

Estimated duration: 6-12+ weeks after data quality and cloud pipeline are stable.

Goal: evolve from a public schedule page into a user-facing schedule and reminder tool.

Possible features:

* Favorites.
* Going/maybe status.
* Ticket application status.
* Reminder settings for application deadlines, payment deadlines, lottery results, and live dates.
* PWA support for installable mobile use.
* Future native app consideration if usage justifies it.

Exit criteria:

* Users can track their own live and ticket workflow, not only read the public schedule.
* Reminder behavior is reliable enough for deadline-sensitive use.
* Commercial architecture, privacy, and account requirements are understood.

## Guiding Principles

* Stabilize the current product before adding infrastructure.
* Do not hand-edit generated public data as the primary fix for data quality issues.
* Keep source lineage available for every public event.
* Treat AI as an assistant with reviewable reasons and confidence.
* Keep the public schedule mobile-first.
