# Data Model Design

## Purpose

This document defines the planned persistent data model for moving the myojou live schedule project from a static JSON export toward DB-backed live schedule management.

It is a design document for future local DB cleanup, AWS migration, AI-assisted classification, and user-facing schedule/reminder features. It does not require an immediate database migration.

## Current State

The current pipeline is:

```text
X posts / archive
-> parser
-> readiness / merger
-> SQLite state
-> public/events.json
-> GitHub Pages
```

Today, `public/events.json` is the public export consumed by the static GitHub Pages UI. It is not intended to be the long-term source of truth.

The current SQLite state stores enough local sync state and canonical event data to generate the public export, but the future system should separate raw source posts, canonical events, ticket sales, deadlines, review decisions, and public export rows more explicitly.

## Core Entities

### SourcePost

Purpose: store the original X post and raw source metadata.

Key fields:

* `id`
* `platform`
* `source_post_id`
* `author_handle`
* `text`
* `posted_at`
* `urls`
* `media_urls`
* `raw_payload`
* `fetched_at`
* `content_hash`

Relationships:

* One `SourcePost` can link to many `Event` records through `EventSource`.
* One `SourcePost` can have zero or more `ClassificationReview` rows.

Notes:

* This should be immutable or append-only where practical.
* If a post is edited or captured with additional fields later, store a new version or update only derived metadata while preserving the original raw payload.
* Raw payloads should include X entities, note_tweet text, expanded URLs, and media metadata.
* Secrets and bearer tokens must never be stored.

### Event

Purpose: represent the canonical live/event entity after parsing, readiness checks, and merging.

Key fields:

* `id`
* `canonical_title`
* `display_title`
* `event_dates`
* `venue_id`
* `open_time`
* `start_time`
* `end_time`
* `status`
* `public_ready`
* `needs_review`
* `review_reasons`
* `created_at`
* `updated_at`

Relationships:

* Many `Event` rows can reference one `Venue`.
* One `Event` can have many `TicketSale` rows.
* One `Event` can have many `Deadline` rows if deadlines are stored separately.
* One `Event` can have many `EventSource` rows.
* One `Event` can have many future `UserEventStatus` rows.

Notes:

* `canonical_title` should be normalized for matching and deduplication.
* `display_title` should preserve the best public-facing title.
* `event_dates` supports multi-day festivals. In PostgreSQL this could be an array or a related `event_occurrences` table; for stronger querying, a separate occurrence table may be better.
* `public_ready=false` rows should remain available for debugging and review but should not be exported by default.
* `needs_review=true` can still be public-safe in limited cases, but public export should normally aim to reduce review rows.

### Venue

Purpose: normalize venue names and optional location metadata.

Key fields:

* `id`
* `name`
* `normalized_name`
* `address`, optional
* `area`, optional
* `map_url`, optional

Relationships:

* One `Venue` can be referenced by many `Event` rows.

Notes:

* Venue master data is optional at first.
* `normalized_name` helps merge posts that use variants such as shorthand, spacing differences, or English/Japanese forms.
* Address and map data can be added later if the public app needs location features.

### TicketSale

Purpose: represent one ticket sale period, tier, or sales channel for an event.

Key fields:

* `id`
* `event_id`
* `label`
* `sale_type`
* `tier`
* `price`
* `url`
* `starts_at`
* `ends_at`
* `payment_deadline_at`
* `status`

Supported `sale_type` values:

* `lottery`
* `first_come`
* `general`
* `unknown`

Supported `tier` values:

* `VIP`
* `priority`
* `general`
* `same_day`
* `unknown`

Relationships:

* Many `TicketSale` rows belong to one `Event`.
* A `TicketSale` can have one or more `Deadline` rows if deadlines are stored separately.
* A `TicketSale` can reference source evidence through `EventSource` or a future direct source table.

Notes:

* Current public output already supports multiple ticket sale periods.
* Do not collapse lottery, general sale, and same-day ticket information into a single event-level deadline.
* Preserve tier-specific statuses such as sold out or sales ended.

### Deadline

Purpose: represent important dates derived from ticket sales or event workflow.

Deadlines may be stored separately or derived from `TicketSale`.

Candidate fields:

* `id`
* `event_id`
* `ticket_sale_id`
* `deadline_type`
* `deadline_at`
* `label`

Supported `deadline_type` values:

* `lottery_application`
* `first_come_application`
* `payment`
* `unknown`

Relationships:

* A `Deadline` belongs to one `Event`.
* A `Deadline` can optionally belong to one `TicketSale`.

Notes:

* If deadline queries become central to the product, storing deadlines separately will make calendar and reminder queries easier.
* If the product remains a simple export, deadlines can be derived from `TicketSale`.
* Payment deadlines and lottery result dates may deserve explicit rows later.

### EventSource

Purpose: connect canonical events back to the source posts that created, updated, corrected, or confirmed them.

Key fields:

* `id`
* `event_id`
* `source_post_id`
* `source_url`
* `relation_type`
* `confidence`

Example `relation_type` values:

* `initial_announcement`
* `ticket_announcement`
* `timetable_update`
* `reminder`
* `correction`
* `inferred_duplicate_source`

Relationships:

* One `EventSource` links one `Event` to one `SourcePost`.
* One event can have many sources.
* One source post can link to multiple events when a post announces multiple lives or multi-day information.

Notes:

* This is the source lineage layer.
* Public export should usually include a primary or latest source URL, while admin views can show all sources.
* Correction and duplicate-source relationships should be preserved rather than overwritten.

### ClassificationReview

Purpose: store rule-based, future AI-assisted, and human review decisions for source posts and events.

Key fields:

* `id`
* `source_post_id`
* `event_id`, optional
* `rule_classification`
* `ai_classification`, future
* `final_classification`
* `confidence`
* `reasons`
* `risk_flags`
* `reviewed_by`
* `reviewed_at`
* `notes`

Relationships:

* A review belongs to one `SourcePost`.
* A review may link to one `Event`.

Notes:

* This is important for future AI classification and human review loops.
* AI should be an assistant first, not the only decision maker.
* Store both the machine reason and the human override reason when available.
* Known classification cases should eventually become evaluation data.

### ExportedPublicEvent

Purpose: represent the public-facing row or occurrence generated for `public/events.json`.

Key fields:

* `id`
* `event_id`
* `occurrence_date`
* `title`
* `venue`
* `open_time`
* `start_time`
* `live_summary`
* `ticket_summary`
* `application_summary`
* `ticket_url`
* `source_url`
* `public_ready`
* `needs_review`
* `generated_at`

Relationships:

* Many public occurrences can be generated from one `Event`, especially for multi-day festivals.

Notes:

* This can be a DB table, materialized view, or generated artifact.
* It should contain only public-safe fields.
* Admin-only notes, raw source payloads, and internal review details should not be exposed.

### UserEventStatus, Future

Purpose: store a user's personal relationship to an event.

Example statuses:

* `interested`
* `going`
* `maybe`
* `applied`
* `won`
* `lost`
* `paid`
* `skipped`

Relationships:

* Belongs to one future `User`.
* Belongs to one `Event`.
* May reference a `TicketSale` when the status is ticket-application-specific.

Notes:

* Out of current scope.
* Requires user accounts, privacy decisions, and auth/session design.

### UserNotification, Future

Purpose: store reminder and notification state for users.

Key fields:

* `id`
* `user_id`
* `event_id`
* `ticket_sale_id`, optional
* `deadline_id`, optional
* `notification_type`
* `scheduled_at`
* `delivered_at`
* `status`

Relationships:

* Belongs to one future `User`.
* May link to `Event`, `TicketSale`, or `Deadline`.

Notes:

* Out of current scope.
* Reminder reliability must be treated carefully because ticket deadlines are time-sensitive.

## SourcePost Detail

`SourcePost` should preserve the original X post as evidence.

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal DB identifier. |
| `platform` | Example: `x`. |
| `source_post_id` | X post ID. |
| `author_handle` | Example: `info_myojou`. |
| `text` | Full text used for parsing, preferring `note_tweet.text` when available. |
| `posted_at` | Original post timestamp. |
| `urls` | Expanded URLs from X entities. |
| `media_urls` | Media URLs and preview image URLs for future OCR/debugging. |
| `raw_payload` | Full sanitized X API payload. |
| `fetched_at` | When the sync captured the post. |
| `content_hash` | Hash of important source content for detecting changed captures. |

Design notes:

* Treat source posts as immutable evidence whenever practical.
* If a post is re-fetched with richer metadata, preserve either versions or a clear updated capture timestamp.
* Source records should not depend on public readiness.

## Event Detail

`Event` represents the canonical merged live/event after parsing.

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal event ID. |
| `canonical_title` | Normalized matching title. |
| `display_title` | Public/admin display title. |
| `event_dates` | One or more live dates. |
| `venue_id` | Optional reference to `venues`. |
| `open_time` | Local time string or time type. |
| `start_time` | Local time string or time type. |
| `end_time` | Optional. |
| `status` | Example: active, canceled, postponed, completed, unknown. |
| `public_ready` | Whether public export should include it by default. |
| `needs_review` | Whether human review is recommended. |
| `review_reasons` | Structured reasons. |
| `created_at` | DB creation timestamp. |
| `updated_at` | DB update timestamp. |

Design notes:

* Multi-day events may need an `event_occurrences` table later.
* Manual corrections should not erase source-derived values without preserving lineage.
* `display_title` can prefer richer names while `canonical_title` supports matching.

## Venue Detail

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal venue ID. |
| `name` | Display name. |
| `normalized_name` | Matching key. |
| `address` | Optional. |
| `area` | Optional, such as Shibuya or Odaiba. |
| `map_url` | Optional. |

Design notes:

* Venue master data can start simple.
* Normalize carefully; do not over-merge different venues with similar names.

## TicketSale Detail

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal sale period ID. |
| `event_id` | Parent event. |
| `label` | Display label such as `優先`, `一般販売`, or `VIPチケット`. |
| `sale_type` | `lottery`, `first_come`, `general`, or `unknown`. |
| `tier` | `VIP`, `priority`, `general`, `same_day`, or `unknown`. |
| `price` | Integer yen amount when known. |
| `url` | Ticket URL when sale-specific. |
| `starts_at` | Sale/application start. |
| `ends_at` | Sale/application deadline. |
| `payment_deadline_at` | Payment deadline if known. |
| `status` | Example: upcoming, on_sale, sold_out, ended, unknown. |

Design notes:

* Multiple ticket sales per event are first-class.
* Same-day ticket information should not overwrite lottery/general sales.
* Sold-out updates should apply to the relevant tier when identifiable.

## Deadline Detail

Deadlines can be derived from `TicketSale`, but a separate `deadlines` table may be useful for reminders and calendar queries.

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal deadline ID. |
| `event_id` | Parent event. |
| `ticket_sale_id` | Optional parent sale period. |
| `deadline_type` | `lottery_application`, `first_come_application`, `payment`, or `unknown`. |
| `deadline_at` | Timestamp. |
| `label` | Public/admin display label. |

Recommendation:

* Start by deriving deadlines from `TicketSale` in the normalized local DB.
* Add a physical `deadlines` table when user reminders or richer deadline queries become part of the product.

## EventSource Detail

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal relation ID. |
| `event_id` | Canonical event. |
| `source_post_id` | Original source post. |
| `source_url` | Public post URL. |
| `relation_type` | Source role. |
| `confidence` | Matching/extraction confidence. |

Design notes:

* Every public event should have at least one source.
* `primary_source_url`, `latest_source_url`, and `all_source_urls` can be generated from this relation table.
* Corrections and timetable updates should remain traceable.

## ClassificationReview Detail

Suggested fields:

| Field | Notes |
| --- | --- |
| `id` | Internal review ID. |
| `source_post_id` | Source post under review. |
| `event_id` | Optional linked event. |
| `rule_classification` | Rule-based result. |
| `ai_classification` | Future AI result. |
| `final_classification` | Human-approved final result. |
| `confidence` | Final or system confidence. |
| `reasons` | Explanation text or structured reason list. |
| `risk_flags` | Examples: image-dependent, title-ambiguous, non-live-likely. |
| `reviewed_by` | Optional user/admin ID. |
| `reviewed_at` | Review timestamp. |
| `notes` | Human notes. |

Design notes:

* This entity supports future AI evaluation and human review.
* Store rule and AI outputs separately so they can be compared.
* Do not let low-confidence AI output publish automatically.

## Public Export Model

`public/events.json` should be generated from DB entities.

A public event export needs:

* event title
* date
* venue
* open/start time
* ticket information
* deadlines
* source URL
* `public_ready`
* `needs_review`, which should normally be false for public export

Public export rules:

* Export only `public_ready=true` rows by default.
* Expand multi-day events into one public occurrence per relevant date.
* Include only public-safe fields.
* Keep source URL lineage visible enough for fans and debugging.
* Do not expose raw X payloads, admin-only notes, internal risk flags, or private user data.

## Future User-Specific Entities

These entities are out of current scope, but the data model should leave room for them.

### User

Purpose: represent an authenticated user if the project becomes a personalized app.

Notes:

* Requires auth, privacy, account deletion, and data retention design.
* Not needed for the current public static site.

### UserEventStatus

Purpose: track a user's personal event/ticket state.

Example statuses:

* `interested`
* `going`
* `maybe`
* `applied`
* `won`
* `lost`
* `paid`
* `skipped`

### UserFavorite

Purpose: store saved events, venues, or ticket categories.

### UserReminder

Purpose: store requested reminders for live dates, application deadlines, payment deadlines, and lottery results.

### NotificationDelivery

Purpose: track notification send attempts, delivery status, and failure reasons.

## Suggested Relational Model

Initial table outline:

```text
source_posts
events
venues
ticket_sales
deadlines
event_sources
classification_reviews
public_exports, optional
users, future
user_event_statuses, future
user_notifications, future
```

Possible supporting tables:

```text
event_occurrences
source_post_versions
ticket_sale_sources
venue_aliases
manual_corrections
classification_case_fixtures
```

Suggested relationships:

```text
venues 1 -> many events
events 1 -> many ticket_sales
events 1 -> many deadlines
ticket_sales 1 -> many deadlines
events many -> many source_posts through event_sources
source_posts 1 -> many classification_reviews
events 1 -> many classification_reviews
events 1 -> many event_occurrences
events 1 -> many future user_event_statuses
```

## AWS Mapping

### Option A: PostgreSQL/RDS

Components:

* PostgreSQL/RDS for normalized relational data.
* S3 for raw post archive and export backups.
* Lambda/EventBridge or GitHub Actions for scheduled sync.
* CloudWatch for logs and metrics.

Strengths:

* Best fit for event management, ticket sales, review workflows, joins, and future user state.
* Easier to model normalized relationships and review history.
* Easier to query deadlines and public-ready events.

Tradeoffs:

* More operational overhead than a fully serverless store.
* Requires migration and connection management.

### Option B: DynamoDB

Components:

* DynamoDB for simpler serverless event/post storage.
* S3 for raw archive and public export backups.
* Lambda/EventBridge for scheduled sync.

Strengths:

* Serverless and operationally simple.
* Good for key-value access patterns if the product remains mostly export-oriented.

Tradeoffs:

* Harder to model review workflows, many-to-many source lineage, ticket sale joins, and future user-specific queries.
* Requires careful access pattern design up front.

### Recommendation

Start with a PostgreSQL-compatible relational design if the goal includes event management, ticket sales, review workflows, and future user state.

S3 should be used regardless of DB choice for raw X archive storage and export backups.

## Migration Path

### Phase 1

Keep the current static JSON export.

Goals:

* Stabilize UI and public export.
* Continue saving raw X archives.
* Keep `public/events.json` as the GitHub Pages input.

### Phase 2

Normalize the local SQLite schema.

Goals:

* Separate source posts, events, ticket sales, event sources, and review decisions.
* Keep local development mock-based and safe.
* Preserve public export compatibility.

### Phase 3

Generate `public/events.json` from normalized DB tables.

Goals:

* Make public export a deterministic product of the normalized DB.
* Validate public-ready filtering.
* Preserve static hosting while improving internal data structure.

### Phase 4

Move raw archive and normalized DB to AWS.

Goals:

* Store raw archive in S3.
* Move structured data into PostgreSQL/RDS or DynamoDB.
* Run scheduled sync/export through Lambda/EventBridge or GitHub Actions.

### Phase 5

Add AI classification and human review workflow.

Goals:

* Compare AI output with rule-based output.
* Store confidence, reasons, and risk flags.
* Route uncertain cases to review.

### Phase 6

Add user-facing event management features.

Goals:

* Favorites.
* Going/maybe status.
* Ticket application state.
* Reminders and notification delivery.

## Non-Goals

This document does not:

* Require immediate DB migration.
* Change current `public/events.json`.
* Define UI redesign.
* Introduce AI classification yet.
* Define authentication or user account behavior.
* Replace the current static GitHub Pages deployment.

## Open Questions

* PostgreSQL vs DynamoDB: which storage model best matches the first paid/commercial product shape?
* Should `Deadline` be a separate table or derived from `TicketSale` until reminders exist?
* Should multi-day festivals use `event_dates` on `events` or a separate `event_occurrences` table?
* How should duplicate posts and correction posts be represented when they partially update event data?
* Where should manual corrections live, and how should they override parsed fields without losing source evidence?
* Should venue master data be stored now, or added only when map/location features become useful?
* How should user accounts be introduced later without overcomplicating the current public schedule?
* How long should raw X payloads and generated exports be retained?
* Which fields are public-safe, admin-only, or private-user-only?
