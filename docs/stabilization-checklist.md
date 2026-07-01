# Phase 1 Stabilization Checklist

This checklist defines the Phase 1 stabilization work for the current static public schedule. It should be used with [public-ui-spec.md](public-ui-spec.md).

## UI Behavior Checklist

* The initial view is the calendar view.
* The `カレンダー` view button is active on first load.
* The `カード` view button is inactive on first load.
* `aria-pressed` values match the visible view.
* Switching `カレンダー -> カード -> カレンダー` works without reload.
* Card/list filters and sort controls are hidden while calendar view is active.
* The view switcher remains visible in both views.
* No horizontal scrolling is introduced.
* No console errors appear during load, view switching, or detail sheet interaction.

## Mobile Checklist

* Calendar is visible immediately on smartphone width.
* Calendar uses the available mobile width.
* Calendar cells remain tappable.
* Calendar chips are readable enough for short event titles.
* Header and compact deadline status do not push the calendar too far down.
* Bottom sheet fits within the viewport and scrolls internally when content is long.
* Close button, overlay tap, and Escape key behavior still work where supported.
* Ticket and source buttons have comfortable tap targets.

## Desktop Checklist

* Calendar is visible immediately at desktop width.
* Calendar grid, month headings, and month load buttons are visible.
* Desktop layout remains centered and readable.
* Card view still renders in a sensible grid/list layout.
* Detail modal/sheet remains readable on wider screens.

## Calendar Mode Checklist

The only calendar mode buttons must be:

* `ライブ日`
* `抽選締切`
* `先着締切`

Internal mode values must remain:

* `live`
* `lotteryDeadline`
* `firstComeDeadline`

Behavior:

* `ライブ日` shows live dates only.
* `抽選締切` shows lottery application deadline entries only.
* `先着締切` shows first-come/general deadline entries only.
* Live-date entries do not show deadline labels.
* Deadline modes do not show normal live-date entries.
* Deadline labels use exactly:
  * `抽選申込締切`
  * `先着申込締切`
* Do not introduce `application`, `payment`, or `all` calendar modes during Phase 1 stabilization.

## Card View Checklist

Card view must remain available as a secondary browsing mode.

Filters:

* `今日以降`
* `今週`
* `今月`
* `締切未取得`
* `すべて`

Sort controls:

* `ライブ日順`
* `申込締切順`

Checks:

* Filters are visible in card view.
* Sort controls are visible in card view.
* `締切未取得` remains a card/list filter, not a large calendar-view control.
* Cards show event title, date, venue, live summary, ticket summary, application summary, ticket status, and ticket/source links when available.

## Detail Bottom Sheet Checklist

* Tapping a calendar entry opens the detail bottom sheet.
* The sheet shows the event title prominently.
* The sheet shows date, venue, open/start time, performance time, and benefit time when available.
* Ticket information remains visible.
* Application/deadline information remains visible.
* Ticket URL opens in a new tab when present.
* Source post link opens in a new tab when present.
* Missing fields are omitted rather than shown as empty labels.
* Live-date context does not show misleading deadline labels.
* Lottery deadline context shows `抽選申込締切` when appropriate.
* First-come deadline context shows `先着申込締切` when appropriate.

## Data Quality Checklist

* `public/events.json` validates successfully.
* `not_public_ready` count is `0` in public export validation.
* Known non-live posts do not appear in public output.
* Known valid live events remain visible.
* Multi-day festivals are expanded into public occurrences for each relevant date.
* Duplicate title aliases are merged where date, venue, time, and ticket URL strongly match.
* Events with missing deadline information remain visible when they are otherwise public-ready.
* `needs_review` events are still allowed only when they are safe enough for public output.

## Release Checklist

Before publishing a UI or data refresh:

* Confirm no unintended changes were made to generated or backend files.
* Run the standard commands.
* Preview locally on desktop.
* Preview locally on smartphone or responsive device mode.
* Check calendar default view.
* Check card view.
* Check detail bottom sheet.
* Check ticket/source links.
* Confirm `public/events.json` has no validation errors.
* Review any changed public data before committing.

## Standard Commands

```bash
node --check public/app.js
node --check public/calendar_helpers.js
.venv/bin/pytest
.venv/bin/myojou-sync validate-public --input public/events.json
```

Local preview:

```bash
python3 -m http.server 8766 --directory public --bind 0.0.0.0
```

Smartphone preview on the same Wi-Fi:

```bash
ipconfig getifaddr en0
```

Then open:

```text
http://<LOCAL_IP>:8766/
```
