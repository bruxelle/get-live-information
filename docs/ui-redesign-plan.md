# UI Redesign Plan

## Purpose

This document defines the future full UI redesign direction for the public myojou live schedule app.

The current UI is functional and calendar-first, but it grew through many incremental patches. This plan is meant to replace vibe-coded UI evolution with a more intentional design direction before implementation begins.

This is not an implementation plan for the current branch. It is a product/design reference for future UI redesign work.

## Current Problems

Current UI/design issues:

* The UI evolved through incremental patches.
* Header, controls, calendar, card view, and detail sheet were optimized separately.
* Some layouts still feel patched together rather than designed as one system.
* Mobile-first behavior is mostly achieved, but not fully systematized.
* Component boundaries are unclear in the current static HTML/CSS/JS implementation.
* Tests protect behavior, but not visual or design consistency.
* Future user features will be harder to add without a cleaner UI structure.
* Calendar and deadline concepts are now clearer than the original UI structure.
* The current CSS contains useful decisions, but not a complete design system.

## Product Direction

The target product is a mobile-first live schedule and ticket deadline tool.

Core direction:

* Mobile-first live schedule tool.
* Calendar-first experience.
* Deadline-aware interface.
* Quick decision support for users.
* Card/list view as secondary browsing mode.
* Future personal schedule management.
* Future reminders, saved events, and application status tracking.

The UI should help users answer practical questions quickly:

* What lives are coming up?
* What deadlines are coming up?
* Is this a lottery or first-come deadline?
* Where is the live?
* What time does it start?
* Where is the ticket link?
* What did the official source post say?

## Primary User Flows

### Flow A: Check a Live From Calendar

```text
Open app
-> see calendar
-> tap live
-> check details
-> open ticket/source link
```

Purpose: quickly understand a live schedule and take action.

### Flow B: Check Lottery Deadlines

```text
Open app
-> switch to 抽選締切
-> check upcoming application deadlines
```

Purpose: avoid missing lottery applications.

### Flow C: Check First-Come Deadlines

```text
Open app
-> switch to 先着締切
-> check general/first-come deadlines
```

Purpose: avoid missing first-come/general sales.

### Flow D: Browse With Cards

```text
Open app
-> card view
-> filter/search/browse events
```

Purpose: use a more detailed list when the calendar is not enough.

### Future Flow E: Personal Event Tracking

```text
Save event
-> mark status
-> get reminder
```

Purpose: support future personalized schedule and ticket workflow management.

## Information Architecture

Main UI regions:

* App header.
* Compact deadline/status strip.
* View switcher.
* Calendar mode switcher.
* Month navigation.
* Calendar grid.
* Detail bottom sheet.
* Card/list view.
* Empty, error, and loading states.

Suggested hierarchy:

```text
AppShell
  HeaderSummary
  DeadlineStatusStrip
  ViewSwitcher
  CalendarView
    CalendarModeSwitcher
    CalendarMonthNav
    CalendarGrid
  CardListView
  EventDetailSheet
  EmptyState / ErrorState / LoadingState
```

## Mobile-First Layout

Desired mobile layout order:

1. Compact header.
2. Compact deadline alert/status.
3. View switcher.
4. Calendar mode switcher.
5. Month navigation.
6. Calendar grid.
7. Detail bottom sheet on tap.

Rules:

* Calendar should appear early in the first viewport.
* Header copy should be short.
* Deadline status should be compact, not a large dashboard.
* Calendar should use the available screen width.
* Calendar cells should avoid horizontal scrolling.
* Tap targets must remain comfortable.
* Detail information should be available on tap, not squeezed into calendar cells.

## Desktop Layout

Desktop behavior:

* Calendar remains the default view.
* More spacing is allowed.
* Card view remains accessible.
* Avoid mobile-only assumptions.
* A future desktop side panel may replace or supplement the bottom sheet.
* A wider detail layout can show more ticket/deadline context without extra taps.

Desktop should not become a different product. It should be the same calendar-first experience with more breathing room.

## Component Model

This is a conceptual component model. It does not require React or a framework yet.

### AppShell

Owns the overall page layout, width constraints, view state, and shared loading/error states.

### HeaderSummary

Shows the service title and a concise explanation of the schedule.

### DeadlineStatusStrip

Shows compact deadline health information, such as today/tomorrow deadlines and missing deadline count.

### ViewSwitcher

Switches between:

* `カード`
* `カレンダー`

### CalendarModeSwitcher

Switches between:

* `ライブ日`
* `抽選締切`
* `先着締切`

### CalendarMonthNav

Controls visible month range, such as previous/next month loading.

### CalendarGrid

Renders month sections and week/day grids.

### CalendarCell

Represents one date cell. Shows date number and compact chips.

### CalendarChip

Represents one live or deadline entry inside a calendar cell.

### EventDetailSheet

Shows event details after tapping a calendar chip/date or card.

### EventCard

Secondary card/list representation of an event.

### TicketSaleList

Displays ticket sale periods, tiers, prices, statuses, and deadlines.

### LinkActions

Contains ticket and source announcement buttons.

### EmptyState

Shows compact no-results/no-events messaging.

### ErrorState

Shows loading or data errors without breaking the page.

## Calendar Design Rules

Preserve the existing product rules.

Calendar modes are exactly:

* `ライブ日`
* `抽選締切`
* `先着締切`

Internal modes remain:

* `live`
* `lotteryDeadline`
* `firstComeDeadline`

Rules:

* Live dates and deadline dates must not mix.
* `ライブ日` shows live event dates only.
* `抽選締切` shows lottery application deadline entries only.
* `先着締切` shows first-come/general deadline entries only.
* `application`, `payment`, and `all` modes must not be introduced.
* Mobile calendar should maximize width.
* No horizontal scrolling.
* Calendar chips should stay compact.
* Calendar cells should not try to display full event details.

## Detail Sheet Design Rules

Detail sheet priorities:

1. Title.
2. Date.
3. Venue.
4. Open/start time.
5. Ticket/application/deadline information.
6. Ticket link.
7. Announcement source link.

Rules:

* Mobile should use a bottom sheet.
* Desktop may later use a side panel or centered detail panel.
* Missing fields should be omitted, not shown as empty labels.
* Live-date context should not show misleading deadline labels.
* Lottery deadline context should clearly show `抽選申込締切`.
* First-come deadline context should clearly show `先着申込締切`.
* Ticket and source links should be obvious actions.

## Visual Design Direction

The redesigned UI should feel like a clean, calm live schedule service.

Direction:

* Less clutter.
* Compact but readable.
* Consistent spacing scale.
* Consistent typography scale.
* Consistent chip/button styles.
* Clear hierarchy between title, date, venue, ticket, and deadline information.
* Accessible contrast.
* Smartphone-first tap targets.
* Avoid oversized decorative sections.
* Avoid one-off visual patches that do not map to reusable components.

Exact final colors do not need to be decided in this document. The redesign should first define spacing, hierarchy, and component behavior.

## State and Interaction Rules

Required interaction rules:

* Initial view is calendar.
* View state must match visible content.
* `aria-pressed` must match active buttons.
* Card filters/sort controls are hidden in calendar view.
* Card filters/sort controls are visible in card view.
* Calendar mode switcher remains visible in calendar view.
* Detail sheet closes through close button.
* Detail sheet closes through overlay tap when supported.
* Detail sheet closes with Escape key when supported.
* Loading state should not flash confusing empty UI.
* Error state should be readable and recoverable.

State bugs to prevent:

* Calendar button active while card list is visible.
* Calendar hidden on desktop.
* Card filters shown above calendar.
* Deadline mode accidentally mixing live-date chips.
* Calendar modes being replaced by generic application/payment/all modes.

## Future Technical Direction

Options:

* Continue vanilla JS temporarily.
* Gradually define stronger component boundaries within vanilla JS.
* Later consider a lightweight component architecture.
* Possible future React/Vite or Astro migration.

Recommendation:

Do not immediately rewrite into a framework.

First:

1. Stabilize design direction.
2. Define component boundaries.
3. Define CSS tokens and layout rules.
4. Confirm the data model and product direction.

Then decide whether a framework migration is worth it.

A framework migration should be justified by upcoming complexity, such as user accounts, saved events, reminders, richer client state, or multiple idol groups.

## Redesign Implementation Phases

### Phase UI-1: Document Redesign Plan

Create this document and align future PRs to it.

### Phase UI-2: Shared CSS Tokens

Create shared CSS tokens for:

* spacing
* typography
* color roles
* border radius
* shadows
* chip/button sizing
* z-index layers

### Phase UI-3: Header and Controls Layout

Refactor:

* compact header
* deadline/status strip
* view switcher
* calendar mode switcher

Goal: make the first viewport intentional and compact.

### Phase UI-4: Calendar Grid and Chips

Refactor:

* calendar month layout
* day cells
* live chips
* lottery deadline chips
* first-come deadline chips
* empty/busy date states

Goal: make the calendar easier to scan on mobile.

### Phase UI-5: Detail Sheet

Refactor:

* title/date/venue hierarchy
* live info section
* ticket info section
* application/deadline section
* link actions

Goal: make tapped details quick to understand.

### Phase UI-6: Card View

Refactor:

* card layout
* filters
* sort controls
* ticket sale rows
* missing deadline state

Goal: keep card view useful as secondary detailed browsing mode.

### Phase UI-7: Component Architecture or Framework Decision

Decide whether to:

* keep static vanilla JS with clearer modules
* introduce a small component architecture
* migrate to React/Vite
* migrate to Astro or another static-first framework

This decision should happen after data model and product direction are stable.

## Non-Goals

This document does not:

* Implement the redesign.
* Change the current UI.
* Introduce new calendar modes.
* Add user accounts.
* Migrate to AWS.
* Require React/Vite immediately.
* Change `public/events.json`.
* Change parser, readiness, merger, archive, or workflow logic.

## Open Questions

* Keep vanilla JS or migrate to a framework later?
* Should desktop have a side panel detail view?
* Should saved events be added before or after AWS DB migration?
* How should reminders work?
* Should the UI support multiple idol groups in the future?
* How much personalization should be added before PWA?
* Should search be part of card view before personal features?
* How should the UI show uncertain or `needs_review` data without scaring normal users?
* Should the design support both fan-facing and admin-facing modes, or keep admin in Notion/DB tooling?
