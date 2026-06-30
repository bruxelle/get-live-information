# Public UI Specification

This document defines the intended behavior of the public-facing myojou live schedule UI.

The purpose of this document is to prevent accidental UI behavior changes when future patches are implemented by humans or coding agents.

## Scope

This specification applies to the static public UI under `public/`.

Relevant files include:

* `public/index.html`
* `public/app.js`
* `public/styles.css`
* `public/calendar_helpers.js`
* `tests/test_cli_safety.py`
* `tests/test_public_calendar.py`

This document does not define backend parsing, readiness, merging, X archive handling, or GitHub Actions behavior.

## Core product direction

The public page is primarily used on smartphones.

The calendar is the main content of the site. The card list is a secondary browsing mode.

Therefore:

* The initial view must be the calendar view.
* The mobile layout should prioritize showing the calendar as early as possible.
* Card-list-specific filters and sorting controls must not take space while the calendar is active.

## Initial view

When the user opens the page:

* The calendar view must be shown by default.
* The card list must not be shown by default.
* The `カレンダー` view button must be active.
* The `カード` view button must be inactive.

Expected initial ARIA state:

* `カード`: `aria-pressed="false"`
* `カレンダー`: `aria-pressed="true"`

The user must still be able to switch to card view.

## View switcher

The UI must keep the following view switcher buttons:

* `カード`
* `カレンダー`

The view switcher must remain visible in both card view and calendar view.

Behavior:

* Selecting `カード` shows the card list.
* Selecting `カレンダー` shows the calendar.
* Switching between the two views must not reload the page.
* Switching views must keep the current data loaded.

## Calendar modes

The calendar must use exactly these mode buttons:

* `ライブ日`
* `抽選締切`
* `先着締切`

Do not replace these with:

* `application`
* `payment`
* `all`
* `申込`
* `申込締切`

Internal mode names should remain aligned with the existing implementation:

* `live`
* `lotteryDeadline`
* `firstComeDeadline`

## Calendar mode behavior

Calendar modes must be mutually exclusive.

### ライブ日 mode

Show only live event dates.

Do not show:

* `抽選申込締切`
* `先着申込締切`

### 抽選締切 mode

Show only lottery application deadline entries.

Show label:

* `抽選申込締切`

Do not show:

* normal live-date entries
* first-come deadline entries

### 先着締切 mode

Show only first-come/general application deadline entries.

Show label:

* `先着申込締切`

Do not show:

* normal live-date entries
* lottery deadline entries

## No mixing live dates and deadline dates

Live dates and deadline dates have different meanings.

They must not be mixed in the same calendar mode.

Correct behavior example:

An event has:

* live date: `2026-07-16`
* lottery deadline: `2026-06-29`
* first-come deadline: `2026-07-15`

Expected behavior:

* `ライブ日`: shows the event on `2026-07-16`
* `抽選締切`: shows the event on `2026-06-29`
* `先着締切`: shows the event on `2026-07-15`

Incorrect behavior:

* showing the live date while in deadline mode
* showing deadline entries while in live-date mode
* showing lottery and first-come deadlines together in one deadline mode

## Card filters

The card/list view may use these filters:

* `今日以降`
* `今週`
* `今月`
* `締切未取得`
* `すべて`

These are card-list browsing controls.

They must be visible in card view.

They must be hidden in calendar view.

## Card sort controls

The card/list view may use these sort controls:

* `ライブ日順`
* `申込締切順`

These are card-list browsing controls.

They must be visible in card view.

They must be hidden in calendar view.

## Controls visible in calendar view

When the calendar view is active, the following controls must remain visible:

* `カード`
* `カレンダー`
* `ライブ日`
* `抽選締切`
* `先着締切`
* previous month control
* next month control

The following controls must be hidden in calendar view:

* `今日以降`
* `今週`
* `今月`
* `締切未取得`
* `すべて`
* `ライブ日順`
* `申込締切順`

The `.controls-panel` wrapper may remain present for layout purposes, but card filters and sort controls inside it must not take visual space while calendar view is active.

## Missing deadline display

`締切未取得` should not be emphasized as a large filter button in calendar view.

In calendar view, missing deadline information should be shown only as a compact notice if needed.

Acceptable examples:

* `締切未取得あり`
* `締切未取得: 12件`

This notice must be compact and must not push the calendar far down the page.

## Mobile layout

The public UI is smartphone-first.

Mobile requirements:

* The calendar should be visible early after opening the page.
* The calendar grid should use as much horizontal space as possible.
* Calendar cell gaps should be minimized or removed on mobile.
* The mobile calendar must not introduce horizontal scrolling.
* Calendar day numbers and event chips must remain readable.
* Tap targets must remain usable.

Desktop/tablet layout may keep more spacing and visual separation.

## Calendar full-bleed behavior on mobile

On small screens, the calendar may use a full-bleed layout to maximize cell width.

Expected behavior:

* Calendar weekdays and grid can extend to the screen edges.
* Cell gaps may be set to `0`.
* Thin borders may be used instead of grid gaps.
* This behavior should apply only on mobile breakpoints.

Desktop layout should not be unintentionally changed by mobile full-bleed rules.

## Header and summary

The page may include:

* eyebrow / small label
* title
* subtitle
* event count
* next live summary

These should remain useful but compact.

The header must not consume so much vertical space on mobile that the calendar is pushed out of the first screen.

Prefer compact styling over deleting useful information.

## Next live summary

The next live summary must be based on actual upcoming live dates.

It must not depend on the active card sort mode.

Do not compute the next live from a list that changes according to:

* `ライブ日順`
* `申込締切順`

The next live should remain stable when the user changes card sorting.

Avoid redundant wording if the UI already labels the block as `次回`.

## Card view

Card view remains supported.

When card view is active:

* Card list must be visible.
* Calendar view may be hidden.
* Card filters should be visible.
* Card sort controls should be visible.
* Card actions should remain functional.
* Ticket links and source announcement post links should remain available when data exists.

## Card actions

Cards may show action buttons such as:

* ticket link
* `告知ポスト`

If only one action is available, it should use the available row width cleanly.

If a source announcement post URL exists, the card view should not remove access to it.

## Accessibility

The UI should keep ARIA state aligned with actual visible state.

Requirements:

* Active view button must have `aria-pressed="true"`.
* Inactive view button must have `aria-pressed="false"`.
* Calendar mode buttons should update `aria-pressed` correctly.
* Initial page load must not have mismatched button state and visible content.

Incorrect state example:

* `カレンダー` button is active, but card list is visible.

This must not happen.

## Public data

UI-only changes must not modify:

* `public/events.json`
* parser logic
* merger logic
* readiness logic
* X archive data
* GitHub Actions workflows

If a PR only changes UI behavior, `public/events.json` should normally remain unchanged.

## Tests and regression checks

UI changes should preserve or add tests for the following:

* calendar is the default initial view
* visible content matches active view button
* card filters are hidden in calendar view
* card sort controls are hidden in calendar view
* card filters and sort controls return in card view
* calendar modes remain `ライブ日 / 抽選締切 / 先着締切`
* no `application / payment / all` calendar modes are introduced
* live dates and deadline dates do not mix
* `public/events.json` is not changed by UI-only patches

Avoid brittle tests that depend on exact HTML attribute ordering or exact JavaScript formatting.

Prefer checking:

* specific attributes independently
* specific function sections
* stable class names
* stable button labels
* stable data attributes

## Manual verification checklist

Before merging UI changes, verify:

1. Opening the page shows the calendar by default.
2. The card list is not visible by default.
3. `カレンダー` is active initially.
4. `カード` is inactive initially.
5. Calendar mode buttons are exactly:

   * `ライブ日`
   * `抽選締切`
   * `先着締切`
6. Calendar view does not show:

   * `今日以降`
   * `今週`
   * `今月`
   * `締切未取得`
   * `すべて`
   * `ライブ日順`
   * `申込締切順`
7. Calendar view still shows:

   * `カード`
   * `カレンダー`
   * `ライブ日`
   * `抽選締切`
   * `先着締切`
8. Card view can be selected.
9. Card view shows filters and sort controls.
10. Calendar mode switching works.
11. Live dates do not appear in deadline modes.
12. Deadline entries do not appear in live-date mode.
13. Mobile layout has no horizontal scroll.
14. Calendar is visible early on mobile.
15. Ticket and source links still work.

## Standard check commands

Run these before merging:

```bash
node --check public/app.js
node --check public/calendar_helpers.js
.venv/bin/pytest
.venv/bin/myojou-sync validate-public --input public/events.json
```

Expected result:

* JavaScript syntax checks pass
* pytest passes
* public validation has:

  * `errors: 0`
  * `warnings: 0`
  * `not_public_ready: 0`

## PR scope rule

Keep UI PRs small.

Recommended PR types:

* default calendar view only
* hide card filters in calendar view only
* mobile calendar spacing only
* UI regression tests only
* documentation only

Avoid combining:

* UI changes
* live classification changes
* parser changes
* public data regeneration
* GitHub Actions changes

One PR should have one clear purpose.
